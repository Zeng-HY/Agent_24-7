import Foundation
import Observation
import TeleplyModel

/// Which action a pending one is, to refuse the same action twice while the first is unknown.
func actionIdentity(_ route: String, _ body: JSONValue) -> String {
    let id = ["question_id", "event_id", "call_id", "token", "tool_id", "title"].lazy.map { body[$0].string() }.first { !$0.isEmpty }
    return route + ":" + (id ?? body["kind"].string())
}

/// What goes with a conversation's next message and the source's own choices (Android WorkspaceController):
/// settings bound to the next message (Codex), the model, effort, mode and permission menus (Claude, DeepSeek)
/// with their lists kept on this phone, answers being chosen in the timeline's cards, actions posted to the
/// computer and their one-line results, Claude's timeline buttons.
@Observable
public final class WorkspaceModel {
    public internal(set) var key: ChatKey?
    public internal(set) var ready = false
    /// An action or a Claude setting is with the computer; one at a time.
    public internal(set) var busy = false
    public var error: String?
    /// The last action's one-line result (设置已绑定下一条消息…), for the composer's status line.
    public internal(set) var result = ""
    /// This conversation's saved workspace (Android "workspace" detail): settings and expected_settings bound to
    /// the next message, pending_action and action_history, the answers being chosen in its cards.
    public internal(set) var saved: JSONValue = [:]
    /// The menus' lists: source_catalog (Claude's or DeepSeek's models), permissions (DeepSeek), refreshing.
    public internal(set) var choices: JSONValue = [:]
    public internal(set) var choicesBusy = false
    public internal(set) var choicesError: String?
    /// Where each Claude timeline button stands (next-step box, task card), by card: pressing:label, done:what was
    /// done, error:why.
    public internal(set) var cards: [String: String] = [:]

    /// One Claude button at a time: its click waits for the computer's window.
    public var pressing: Bool { cards.values.contains { $0.hasPrefix("pressing:") } }

    // The panes (Android pane): "new" (新建对话), "chat" and "skill" (引用), "remote" (电脑上的文件), "files"
    // (对话文件), "file" (a file's page) and "diff" (本轮差异), with what the open one lists.
    public internal(set) var pane: String?
    public internal(set) var paneBusy = false
    public internal(set) var paneError: String?
    public internal(set) var data: JSONValue = [:]
    /// What the new-conversation sheet lists (folders, models, permissions): this phone's copy first, the
    /// computer's when it comes (spec 4.4, 8.4).
    public internal(set) var newData: JSONValue = [:]
    /// A line under the sheet: a list that did not come this time, or photos that could not follow a draft back.
    public internal(set) var newNote: String?

    /// A first message sent: it becomes a job and the sheet is free again at once (web 10-16).
    @ObservationIgnored public var created: (NewJob) -> Void = { _ in }
    @ObservationIgnored let now: @Sendable () -> Int64
    @ObservationIgnored var paneRead: Task<Void, Never>?
    @ObservationIgnored var paneGeneration = 0
    /// The sheet's lists by its workspace (kept on this phone as "new_lists").
    @ObservationIgnored var lists: [ChatKey: JSONValue] = [:]
    @ObservationIgnored var newReads: [String: Task<Void, Never>] = [:]
    /// The new conversation's request id being asked for, one per workspace.
    @ObservationIgnored var draftIDs: [ChatKey: Task<String, any Error>] = [:]

    /// After an action reached the source, so the conversation reads its state again.
    @ObservationIgnored public var changed: () -> Void = {}
    /// A state the computer sent back with an action (Claude settings), shown at once.
    @ObservationIgnored public var stateRead: (ChatKey, JSONValue) -> Void = { _, _ in }

    @ObservationIgnored let store: LocalStore?
    @ObservationIgnored let newID: @Sendable () -> String
    @ObservationIgnored var client: RelayClient?
    @ObservationIgnored var clientGeneration = -1
    @ObservationIgnored var synthetic = false
    @ObservationIgnored var generation = 0
    @ObservationIgnored var read: Task<Void, Never>?
    @ObservationIgnored var choiceRead: Task<Void, Never>?
    @ObservationIgnored var work: Task<Void, Never>?
    @ObservationIgnored var cache: [ChatKey: JSONValue] = [:]
    @ObservationIgnored var demo: [ChatKey: JSONValue] = [:]
    /// Whether each workspace belongs to the local demo (kept in memory) or a real computer (kept in the store).
    @ObservationIgnored var modes: [ChatKey: Bool] = [:]
    /// Workspace writes under way, one after another; each writes the latest value of its conversation.
    @ObservationIgnored var writing: Task<Void, Never>?
    /// Lists kept on this phone (0.8): Claude's model lists by conversation and the computer's latest; DeepSeek's.
    @ObservationIgnored var catalogs: [String: JSONValue] = [:]

    init(store: LocalStore? = nil, newID: @escaping @Sendable () -> String = { UUID().uuidString.lowercased() },
         now: @escaping @Sendable () -> Int64 = { Int64(Date().timeIntervalSince1970 * 1000) }) {
        self.store = store
        self.newID = newID
        self.now = now
    }

    /// Waits for reads and actions under way (tests).
    public func settle() async {
        await read?.value
        await choiceRead?.value
        await work?.value
        await paneRead?.value
        for list in Array(newReads.values) { await list.value }
        await writing?.value
    }

    func bind(_ next: ChatKey?, client: RelayClient, clientGeneration: Int, synthetic: Bool) {
        if next == key && clientGeneration == self.clientGeneration { return }
        read?.cancel()
        choiceRead?.cancel()
        paneRead?.cancel()
        for task in newReads.values { task.cancel() }
        newReads = [:]
        generation += 1
        paneGeneration += 1
        pane = nil
        paneBusy = false
        paneError = nil
        data = [:]
        newData = next.flatMap { lists[$0] } ?? [:]
        let g = generation
        key = next
        self.client = client
        self.clientGeneration = clientGeneration
        self.synthetic = synthetic
        ready = false
        busy = false
        error = nil
        result = ""
        saved = [:]
        choices = [:]
        choicesBusy = false
        choicesError = nil
        cards = [:]
        guard let next else { return }
        modes[next] = synthetic
        read = Task { [weak self] in
            guard let self else { return }
            var stored: JSONValue
            if synthetic {
                stored = self.demo[next] ?? [:]
            } else {
                let text = await self.store?.detail(scope: next.scope, device: next.device, app: next.app, chat: next.chat, kind: "workspace")
                stored = text.map(jsonValue) ?? [:]
            }
            // An upload the app stopped in the middle of did not finish; it says so instead of waiting forever.
            if stored["uploads"].array.contains(where: { ["uploading", "checking"].contains($0["status"].string()) }), case .object(var fields) = stored {
                fields["uploads"] = .array(stored["uploads"].array.map { row in
                    guard ["uploading", "checking"].contains(row["status"].string()), case .object(var upload) = row else { return row }
                    upload["status"] = "failed"
                    upload["error"] = "上传中断，请重新选择文件"
                    return .object(upload)
                })
                stored = .object(fields)
            }
            // The sheet's lists of last time, so it opens with them; the computer's come in behind.
            if next.chat == "@new", self.lists[next] == nil, !synthetic,
               let text = await self.store?.detail(scope: next.scope, device: next.device, app: next.app, chat: next.chat, kind: "new_lists") {
                self.lists[next] = jsonValue(text)
            }
            // Claude's model lists of last time, this conversation's and the computer's latest, for the model menu.
            if next.app == "claude" && !synthetic {
                for (name, owner) in [(self.catalogKey(next), next), (self.lastCatalogKey(next), self.lastCatalog(next))] where self.catalogs[name] == nil {
                    if let text = await self.store?.detail(scope: owner.scope, device: owner.device, app: owner.app, chat: owner.chat, kind: "claude_catalog") {
                        self.catalogs[name] = jsonValue(text)
                    }
                }
            }
            guard g == self.generation else { return }
            self.cache[next] = stored
            self.saved = stored
            self.newData = self.lists[next] ?? [:]
            self.ready = true
        }
    }

    func current(_ key: ChatKey) -> JSONValue {
        cache[key] ?? [:]
    }

    /// Keeps [value] as [key]'s workspace now and writes it after the writes under way; the last write always
    /// carries the latest value, so fast edits never land out of order.
    func keep(_ key: ChatKey, _ value: JSONValue) {
        cache[key] = value
        if self.key == key { saved = value }
        let previous = writing
        let synthetic = modes[key] ?? self.synthetic
        writing = Task { [weak self] in
            await previous?.value
            guard let self, let latest = self.cache[key] else { return }
            if synthetic {
                self.demo[key] = latest
            } else {
                await self.store?.setDetail(scope: key.scope, device: key.device, app: key.app, chat: key.chat, kind: "workspace", value: jsonText(latest))
            }
        }
    }

    /// Keeps [value] and waits until it is written.
    func persist(_ key: ChatKey, _ value: JSONValue) async {
        keep(key, value)
        await writing?.value
    }

    /// An answer being chosen in a card, or a field of the new conversation's draft: kept at once, written behind
    /// (Android edit). Refused only while an action or a create of this conversation is with the computer.
    public func edit(_ field: String, _ value: JSONValue) {
        guard let key, ready, !busy else { return }
        var next = current(key).object
        next[field] = value
        keep(key, .object(next))
    }

    // MARK: What goes with the next message

    /// A model, effort or mode picked from a Codex chip: bound to the next message, checked by Codex against
    /// [expected] (what the conversation had when it was picked).
    public func selectSettings(_ settings: JSONValue, expected: JSONValue) {
        guard let key else { return }
        var next = current(key).object
        next["settings"] = settings
        next["expected_settings"] = expected
        result = "设置已绑定下一条消息，尚未发送"
        keep(key, .object(next))
    }

    /// The model, effort and mode bound to the next message, and what they were chosen against (Codex).
    public func boundSettings() -> JSONValue {
        guard let key else { return [:] }
        let saved = current(key)
        var bound: [String: JSONValue] = [:]
        if saved["settings"].isObject { bound["settings"] = saved["settings"] }
        if saved["expected_settings"].isObject { bound["expected_settings"] = saved["expected_settings"] }
        return .object(bound)
    }

    /// What a send carries besides its words: the pictures (by their ids on the computer), the references and the
    /// other files, and the bound settings. Refuses while a file is still going up or failed (spec 8.1).
    public func sendExtras() throws -> JSONValue {
        guard let key else { throw ReadFailure("没有活动会话") }
        guard ready else { throw ReadFailure("附件和设置仍在恢复，请稍候") }
        let saved = current(key)
        let uploads = saved["uploads"].array
        let pictures = uploads.filter { $0["image"].bool() }
        guard pictures.reduce(Int64(0), { $0 + $1["meta"]["original_size"].int64() }) <= 50 * 1024 * 1024 else { throw ReadFailure("图片合计不能超过50MB") }
        guard uploads.allSatisfy({ $0["status"].string() == "ready" }) else { throw ReadFailure("存在未完成或失败的附件，请重选或移除后再发送") }
        var extras: [String: JSONValue] = [
            "attachments": .array(pictures.map { $0["meta"]["id"] }),
            "references": .array(saved["references"].array + uploads.filter { !$0["image"].bool() }.map { $0["meta"] }),
        ]
        for (name, value) in boundSettings().object { extras[name] = value }
        return .object(extras)
    }

    /// What went with a send leaves the card: its files and references, and the settings, which bound that one
    /// message only (the chips show the computer's again). Its receipt now takes the status line.
    func clearSent(_ key: ChatKey, _ extras: JSONValue) {
        let saved = current(key)
        let sent = Set(extras["attachments"].array.map { $0.string() } + extras["references"].array.map { $0["id"].string() })
        var next = saved.object
        next["uploads"] = .array(saved["uploads"].array.filter { !sent.contains($0["meta"]["id"].string()) })
        next["references"] = .array(saved["references"].array.filter { !sent.contains($0["id"].string()) })
        if extras.has("settings") {
            next["settings"] = nil
            next["expected_settings"] = nil
        }
        if self.key == key { result = "" }
        keep(key, .object(next))
    }

    /// 恢复提交快照: what a send carried, back on the card: its references, its pictures (checked on the computer;
    /// one it no longer has says so and is never left out quietly), its settings.
    func restoreSent(_ key: ChatKey, _ body: JSONValue) throws {
        guard self.key == key, ready else { throw ReadFailure("当前会话已变化，未恢复附件") }
        let saved = current(key)
        guard saved["uploads"].array.isEmpty && saved["references"].array.isEmpty else { throw ReadFailure("已有新附件或引用，请先处理它们，再恢复提交快照") }
        let pictures = body["attachments"].array.map { $0.string() }
        var next = saved.object
        next["references"] = .array(body["references"].array)
        next["uploads"] = .array(pictures.map { id -> JSONValue in
            ["local": .string(newID()), "name": "恢复的图片", "image": true, "status": "checking", "meta": ["id": .string(id)]]
        })
        if body["settings"].isObject { next["settings"] = body["settings"] }
        if body["expected_settings"].isObject { next["expected_settings"] = body["expected_settings"] }
        keep(key, .object(next))
        guard !pictures.isEmpty, let client else { return }
        Task { [weak self] in
            let found = (try? await client.detail(device: key.device, route: "codex/attachments", query: [("id", key.chat), ("ids", pictures.joined(separator: ","))]))?["items"].array ?? []
            guard let self, self.key == key else { return }
            let now = self.current(key)
            var fields = now.object
            fields["uploads"] = .array(now["uploads"].array.map { row in
                guard row["status"].string() == "checking", case .object(var upload) = row else { return row }
                if let meta = found.first(where: { $0["id"].string() == row["meta"]["id"].string() }) {
                    upload["status"] = "ready"
                    upload["meta"] = meta
                    upload["name"] = meta["name"]
                } else {
                    upload["status"] = "failed"
                    upload["error"] = "原图片无法恢复，请重选或移除；不会省略附件发送"
                }
                return .object(upload)
            })
            self.keep(key, .object(fields))
        }
    }

    // MARK: The chips' lists (spec 8.4, B17)

    func catalogKey(_ key: ChatKey) -> String { "claude|\(key.scope)|\(key.device)|\(key.chat)" }
    func lastCatalogKey(_ key: ChatKey) -> String { "claude-last|\(key.scope)|\(key.device)" }
    func lastCatalog(_ key: ChatKey) -> ChatKey { ChatKey(scope: key.scope, device: key.device, app: "@catalog", chat: "claude") }

    /// What the menus showed last (web savedCatalog): this conversation's list, or the latest on the same model
    /// with its picks unknown; DeepSeek's models and permissions as read last.
    func remembered(_ key: ChatKey, model: String) -> [String: JSONValue] {
        var shown: [String: JSONValue] = [:]
        if key.app == "claude" {
            if let own = catalogs[catalogKey(key)] {
                shown["source_catalog"] = own
            } else if !model.isEmpty, let last = catalogs[lastCatalogKey(key)], last["model_id"].string() == model {
                var borrowed = last.object
                borrowed["fast"] = .array(last["fast"].array.map { row in
                    var fields = row.object
                    fields["selected"] = .null
                    return .object(fields)
                })
                borrowed["effort"] = .array(last["effort"].array.map { row in
                    var fields = row.object
                    fields["selected"] = false
                    if fields["range"]?.isObject == true, case .object(var range)? = fields["range"] {
                        range["value"] = .null
                        fields["range"] = .object(range)
                    }
                    return .object(fields)
                })
                borrowed["borrowed"] = true
                shown["source_catalog"] = .object(borrowed)
            }
        }
        if key.app == "deepseek" {
            if let models = catalogs["deepseek-models|\(key.device)"] { shown["source_catalog"] = models }
            if let permissions = catalogs["deepseek-permissions|\(key.device)|\(key.chat)"] { shown["permissions"] = permissions }
        }
        return shown
    }

    func keepCatalog(_ key: ChatKey, _ catalog: JSONValue) async {
        var own = catalog.object
        own["borrowed"] = nil
        own["cached"] = nil
        let value = JSONValue.object(own)
        catalogs[catalogKey(key)] = value
        catalogs[lastCatalogKey(key)] = value
        guard !synthetic else { return }
        let last = lastCatalog(key)
        await store?.setDetail(scope: key.scope, device: key.device, app: key.app, chat: key.chat, kind: "claude_catalog", value: jsonText(value))
        await store?.setDetail(scope: last.scope, device: last.device, app: last.app, chat: last.chat, kind: "claude_catalog", value: jsonText(value))
    }

    /// The model and mode menus' lists: shown at once as last read, then asked of the computer, which answers
    /// from the list it keeps. [fresh] (刷新电脑上的列表) has it open Claude's menus on the desktop again. Codex
    /// needs none: its catalog comes with the conversation state.
    public func loadChoices(fresh: Bool = false, model: String = "") {
        guard let key, let client, key.app != "codex" else { return }
        choiceRead?.cancel()
        var shown = remembered(key, model: model)
        if fresh { shown["refreshing"] = true }
        choices = .object(shown)
        choicesBusy = true
        choicesError = nil
        choiceRead = Task { [weak self] in
            var data = shown
            data["refreshing"] = nil
            do {
                if key.app == "claude" {
                    let catalog = try await client.detail(device: key.device, route: "claude/catalog", body: ["id": .string(key.chat), "fresh": .bool(fresh)])
                    await self?.keepCatalog(key, catalog)
                    data["source_catalog"] = catalog
                }
                if key.app == "deepseek" {
                    let models = try await client.detail(device: key.device, route: "deepseek/models")
                    self?.catalogs["deepseek-models|\(key.device)"] = models
                    let permissions = try await client.detail(device: key.device, route: "deepseek/permissions", query: [("app", key.app), ("id", key.chat)])
                    self?.catalogs["deepseek-permissions|\(key.device)|\(key.chat)"] = permissions
                    data["source_catalog"] = models
                    data["permissions"] = permissions
                }
                guard let self, self.key == key, !Task.isCancelled else { return }
                self.choices = .object(data)
                self.choicesBusy = false
            } catch is CancellationError {
            } catch {
                guard let self, self.key == key else { return }
                self.choicesError = describe(error)
                self.choicesBusy = false
            }
        }
    }

    /// A model, effort, speed or mode picked from a Claude chip (web claude-ui.js change): applied on the computer,
    /// which sends back the state and mostly the updated list; only without a list is the desktop read again.
    public func claudeSetting(kind: String, name: String, value: JSONValue = .null, expected: String = "") {
        guard let key, let client, key.app == "claude", !busy else { return }
        busy = true
        error = nil
        result = ""
        work = Task { [weak self] in
            var again = false
            do {
                var body: [String: JSONValue] = ["id": .string(key.chat), "kind": .string(kind), "name": .string(name), "value": value]
                if !expected.isEmpty { body["expected_model"] = .string(expected) }
                let reply = try await client.detail(device: key.device, route: "claude/setting", body: .object(body))
                guard let self else { return }
                if reply["state"].isObject { self.stateRead(key, reply["state"]) } else { self.changed() }
                if reply["catalog"].isObject {
                    await self.keepCatalog(key, reply["catalog"])
                    if self.key == key {
                        var choices = self.choices.object
                        choices["source_catalog"] = reply["catalog"]
                        self.choices = .object(choices)
                    }
                } else {
                    again = kind != "mode"
                }
                let text = reply["text"].string()
                if self.key == key { self.result = text.isEmpty ? (kind == "mode" ? "已切换到「\(name)」" : "已应用到这个 Claude 对话") : text }
            } catch {
                if self?.key == key { self?.error = describe(error) }
            }
            if self?.key == key { self?.busy = false }
            if again { self?.loadChoices(fresh: true) }
        }
    }

    /// Leaves no menu open on the computer once the phone's model menu closed (web claude-ui.js closeMenu).
    public func closeClaudeMenu() {
        guard let key, let client, key.app == "claude" else { return }
        Task { _ = try? await client.detail(device: key.device, route: "claude/close-menu", body: ["id": .string(key.chat)]) }
    }

    // MARK: Actions on the computer

    /// An answer, approval, desktop choice or setting, posted at once as the web does (spec 8.4): the computer checks
    /// it still applies and turns a stale one away. Only a reply lost on the way stays to be checked; it is never
    /// sent again by itself.
    public func action(_ route: String, _ body: JSONValue) {
        guard let key, let client, !busy else { return }
        busy = true
        error = nil
        result = ""
        work = Task { [weak self] in
            guard let self else { return }
            var posted = false
            do {
                guard route != "claude/choose" || !body["token"].string().isEmpty else { throw ReadFailure("桌面选项已变化，请刷新") }
                guard self.key == key else { throw ReadFailure("来源或会话已切换，未提交") }
                var payload = body.object
                payload["id"] = .string(key.chat)
                payload["request_id"] = .string(self.newID())
                let previous = self.current(key)["pending_action"]
                if previous.isObject && previous["status"].string() != "done"
                    && actionIdentity(previous["route"].string(), previous["body"]) == actionIdentity(route, .object(payload)) {
                    throw ReadFailure("上次操作结果仍待核对，请刷新来源状态后处理")
                }
                var next = self.current(key).object
                if previous.isObject { next["action_history"] = .array(self.current(key)["action_history"].array + [previous]) }
                next["pending_action"] = ["route": .string(route), "body": .object(payload), "status": "unknown"]
                await self.persist(key, .object(next))
                posted = true
                let reply = route == "codex/answer"
                    ? try await client.command(device: key.device, app: key.app, route: "answer", body: .object(payload))
                    : try await client.detail(device: key.device, route: route, body: .object(payload))
                var done = self.current(key).object
                done["pending_action"] = ["route": .string(route), "body": .object(payload), "status": "done"]
                await self.persist(key, .object(done))
                let text = reply["text"].string()
                if self.key == key { self.result = text.isEmpty ? "操作已返回，请刷新核对实际状态" : text }
                self.changed()
            } catch {
                // Turned away by the computer (4xx: answered elsewhere, expired, changed): nothing happened there, so
                // it is not left to be checked.
                let refused = (error as? ServiceFailure).map { (400..<500).contains($0.status) } ?? false
                if posted && refused {
                    var next = self.current(key).object
                    next["pending_action"] = nil
                    await self.persist(key, .object(next))
                }
                if self.key == key { self.error = describe(error) }
                if posted && refused { self.changed() }
            }
            if self.key == key { self.busy = false }
        }
    }

    /// A button of Claude's next-step box or of a task card, pressed on the computer as if clicked there (web
    /// pressNext, pressTask). The computer checks the box or card still waits with that very button, so a press
    /// that comes too late is refused there instead of landing elsewhere; a refusal leaves the buttons for another
    /// try.
    public func claudeButton(card: String, route: String, body: JSONValue, label: String) {
        guard let key, let client, key.app == "claude", ["claude/next", "claude/task"].contains(route), !pressing else { return }
        cards[card] = "pressing:" + label
        error = nil
        work = Task { [weak self] in
            do {
                var payload = body.object
                payload["id"] = .string(key.chat)
                let reply = try await client.detail(device: key.device, route: route, body: .object(payload))
                guard let self, self.key == key else { return }
                let text = reply["text"].string()
                self.cards[card] = "done:" + (text.isEmpty ? "已在电脑上点了「\(label)」" : text)
                self.changed()
            } catch {
                guard let self, self.key == key else { return }
                self.cards[card] = "error:" + describe(error)
            }
        }
    }

    /// 核对上次操作: reads back whether an action whose reply was lost took effect; never sends it again.
    public func checkAction() {
        guard let key, let client, !busy else { return }
        let pending = current(key)["pending_action"]
        guard pending.isObject else { return }
        work = Task { [weak self] in
            do {
                let route = pending["route"].string()
                let body = pending["body"]
                var confirmed = false
                var line: String
                if route == "codex/answer" {
                    let receipt = try await client.receipt(device: key.device, app: key.app, chat: key.chat, request: body["request_id"].string())
                    confirmed = ["accepted", "rejected"].contains(receipt["state"].string())
                    line = "回答回执：" + receipt["state"].string()
                } else {
                    let actual = try await client.control(device: key.device, app: key.app, chat: key.chat).raw
                    switch route {
                    case "deepseek/permission":
                        confirmed = actual["permission"].string() == body["preset"].string()
                    case "deepseek/model":
                        confirmed = body["settings"].isObject && body["settings"].object.allSatisfy { actual["settings"][$0.key] == $0.value }
                    default:
                        confirmed = false
                    }
                    line = confirmed ? "已读回所选设置" : "此来源没有独立动作回执，请核对刷新后的实际状态；不会自动重试。"
                }
                guard let self else { return }
                if confirmed {
                    var next = self.current(key).object
                    var done = pending.object
                    done["status"] = "done"
                    next["pending_action"] = .object(done)
                    await self.persist(key, .object(next))
                }
                if self.key == key { self.result = line }
            } catch {
                if self?.key == key { self?.error = describe(error) }
            }
        }
    }

    /// 电脑上打开: the computer shows this conversation in its desktop app. Not a message; nothing is sent.
    public func openOnComputer() {
        guard let key, let client, !busy else { return }
        busy = true
        error = nil
        result = ""
        work = Task { [weak self] in
            do {
                let reply = try await client.detail(device: key.device, route: "chat/open", body: ["app": .string(key.app), "id": .string(key.chat)])
                let text = reply["text"].string()
                if self?.key == key { self?.result = text.isEmpty ? "已在电脑上打开" : text }
            } catch {
                if self?.key == key { self?.error = describe(error) }
            }
            if self?.key == key { self?.busy = false }
        }
    }

    /// The composer showed the one-line result; it goes.
    public func clearResult() {
        result = ""
    }
}
