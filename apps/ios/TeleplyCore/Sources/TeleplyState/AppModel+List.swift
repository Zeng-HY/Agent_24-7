import Foundation
import TeleplyModel

/// The conversation list, the source chips and the sidebar tree (spec 4.1, 4.2; Android ReaderViewModel).
extension AppModel {
    /// What the computer in use offers; nil while not known (never another computer's list).
    public var knownApps: [String]? {
        guard let device, sources.device == device.id else { return nil }
        return sources.apps
    }

    /// Where a new conversation starts: [wanted] when this computer has it, otherwise the first app it has.
    public func newApp(_ wanted: String) -> String {
        guard let apps = knownApps else { return wanted }
        return apps.contains(wanted) ? wanted : apps.first ?? wanted
    }

    /// The list's 草稿 for the computer in use, read from this phone once per sign-in and computer. Rows whose box
    /// was left while it read keep what the box said.
    func loadDrafts() async {
        guard let device else { return }
        let owner = scope + "\n" + device.id
        guard draftsFor != owner else { return }
        draftsFor = owner
        drafts = [:]
        draftsTouched = []
        guard !fixture else { return }
        let found = await services.store.drafts(scope: scope, device: device.id)
        guard draftsFor == owner else { return }
        for (key, words) in found where key.chat != "@new" && !isNewPage(key.chat) {
            let row = key.app + ":" + key.chat
            let line = draftPreview(words)
            if !draftsTouched.contains(row), !line.isEmpty { drafts[row] = line }
        }
    }

    /// A conversation left with [words] in its box: its row shows them after [草稿], or no longer when the box is
    /// empty (sent or cleared). A new conversation's page is no row.
    func noteDraft(_ key: ChatKey, _ words: String) {
        guard key.scope == scope, key.device == device?.id, key.chat != "@new", !isNewPage(key.chat) else { return }
        let row = key.app + ":" + key.chat
        let line = draftPreview(words)
        let next: String? = line.isEmpty ? nil : line
        draftsTouched.insert(row)
        if drafts[row] != next { drafts[row] = next }
    }

    func loadChats(_ g: Int, more: Bool = false) async throws {
        guard let device else { return }
        await loadDrafts()
        let source = listSource
        let page = try await client.chatList(device: device.id, app: source, query: query, cursor: more ? listCursor : nil, sort: listSort, status: listStatus)
        guard current(g), self.device?.id == device.id, listSource == source else { return }
        var rows = more ? chats + page.items : page.items
        var seen = Set<String>()
        rows = rows.filter { seen.insert(rowKey($0)).inserted && !hidden.contains(rowKey($0)) }
        chats = rows
        listCursor = page.cursor
        listMore = page.hasMore
        if !more { moreKids = [:] }
    }

    /// The first page again, merged into what shows (web loadList): its rows first, the rest kept below with
    /// where the next page starts.
    func mergeFirstPage(_ g: Int? = nil) async throws {
        guard let device else { return }
        let asked = (listSource, query, listSort, listStatus)
        let page = try await client.chatList(device: device.id, app: asked.0, query: asked.1, sort: asked.2, status: asked.3)
        if let g, !current(g) { return }
        guard self.device?.id == device.id, (listSource, query, listSort, listStatus) == asked else { return }
        let fresh = Set(page.items.map(rowKey))
        // 11-02: in a list of one state the first page speaks for every row up to its last. One of those it leaves out has
        // left that state (运行中: it ended). Kept, nothing would read it again: it said 运行中, its timer ticking, hours
        // after the turn ended. Rows past its last are pages read with 加载更多: taken away, the list went back to one page.
        let end = page.hasMore ? page.items.last : nil
        let kept = chats.filter { row in
            guard !fresh.contains(rowKey(row)) else { return false }
            if asked.3 == "all" { return true }
            return end.map { sortsAfter(row, $0, sort: asked.2) } ?? false
        }
        let beyond = !kept.isEmpty
        // The 10 s read mostly brings the same rows: equal values are not written again (as ChatModel.take).
        let merged = (page.items + kept).filter { !hidden.contains(rowKey($0)) }
        if merged != chats { chats = merged }
        if !beyond {
            if listCursor != page.cursor { listCursor = page.cursor }
            if listMore != page.hasMore { listMore = page.hasMore }
        }
    }

    /// The list is read again every 10 s while it is in front (web loadConvs): rows merge, nothing is reset.
    /// 10-30: it is also read at once whenever it comes (back) to the front: from the background, from 设置 or 我的电脑.
    /// Rows read before going away could still say 运行中 for a turn that ended meanwhile, and their timers kept ticking
    /// for the first ten seconds (user's screenshot: 运行中 · 44 分 11 秒 on a conversation finished nine minutes
    /// earlier). Back from a conversation back() reads it itself. A read held off by work in hand is tried again a
    /// second later, not ten.
    func pollList(_ on: Bool) {
        guard on else {
            listPoll?.cancel()
            listPoll = nil
            return
        }
        guard listPoll == nil else { return }
        let first: Duration = listJustRead ? .seconds(10) : .zero
        listJustRead = false
        listPoll = Task { [weak self] in
            var wait = first
            while !Task.isCancelled {
                guard let pacer = self?.services.pacer else { return }
                if wait > .zero {
                    do { try await pacer.wait(wait) } catch { return }
                }
                guard let self else { return }
                guard self.listShown, !self.expired else {
                    wait = .seconds(10)
                    continue
                }
                if self.listPollHeld {
                    wait = .seconds(1)
                    continue
                }
                try? await self.mergeFirstPage()
                wait = .seconds(10)
            }
        }
    }

    public func searchChats(_ words: String) {
        operation(.list) { [weak self] g in
            guard let self else { return }
            self.query = words
            self.chats = []
            self.listCursor = nil
            self.listMore = false
            try await self.loadChats(g)
        }
    }

    /// 加载更多对话.
    public func moreChats() {
        operation(.list) { [weak self] g in try await self?.loadChats(g, more: true) }
    }

    /// The ⋯ 列表显示 menu: 分组, 排序, 状态, 来源.
    public func listDisplay(source: String? = nil, sort: String? = nil, status: String? = nil, group: String? = nil) {
        let source = source ?? listSource, sort = sort ?? listSort, status = status ?? listStatus
        guard source == "all" || isValidAgentId(source) else { return }
        let reload = source != listSource || sort != listSort || status != listStatus
        listSource = source
        listSort = sort
        listStatus = status
        if let group { listGroup = group }
        guard reload else { return }
        operation(.list) { [weak self] g in
            guard let self else { return }
            self.chats = []
            self.listCursor = nil
            self.listMore = false
            try await self.loadChats(g)
        }
    }

    /// 0.6.5: teleply://list?d=…&status=running, opened by the island's "还有 N 个". Selects the computer when needed and
    /// keeps the running-only filter until the user changes it.
    public func openIslandList(_ target: IslandListTarget) {
        guard let computer = account?.devices.first(where: { $0.id == target.device }) else {
            showComputers()
            return
        }
        if device?.id == computer.id {
            // 11-02: with listStatus set first this saw no change and read nothing: the rows of every state stayed.
            listDisplay(status: target.status)
        } else {
            listStatus = target.status
            select(computer)
        }
    }

    /// 清除筛选: every source, newest first, every state, no search words.
    public func clearListFilters() {
        listSource = "all"
        listSort = "updated"
        listStatus = "all"
        searchChats("")
    }

    // MARK: Which apps this computer has (0.9.1): this phone's copy first, then the computer's answer

    func sourcesKey(scope: String, device: String) -> ChatKey {
        ChatKey(scope: scope, device: device, app: "codex", chat: "@sources")
    }

    /// The apps [device] had when this phone last asked under this sign-in; nil when never asked (or the demo).
    func cachedSources(scope: String, device: String) async -> [String]? {
        guard !fixture, !scope.isEmpty else { return nil }
        let key = sourcesKey(scope: scope, device: device)
        guard let saved = await services.store.detail(scope: key.scope, device: key.device, app: key.app, chat: key.chat, kind: "sources") else { return nil }
        return saved.split(separator: ",").map(String.init).filter { isValidAgentId($0) }
    }

    /// The chips' and the sheet's 重试: ask the computer again, for its apps and for its assistant list.
    public func retrySources() {
        if let device, sources.device == device.id {
            sources.loading = true
            sources.failed = nil
        }
        loadTree(force: true)
        if let id = device?.id { refreshAgents(device: id, force: true) }
    }

    /// The computer answered with its apps: a list filter on one it does not have goes back to 全部.
    func fitSources(_ apps: [String]) {
        guard listSource != "all", !apps.contains(listSource) else { return }
        listSource = "all"
        chats = []
        listCursor = nil
        listMore = false
        if listShown { operation(.list) { [weak self] g in try await self?.loadChats(g) } }
    }

    // MARK: The assistants this computer has (handoff 3.2): its manifest list, one catalog per computer

    /// The catalog of the computer in use, kept in step with [device]: another computer's catalog shows from this
    /// phone's memory at once, then the computer is asked again. Called from live().
    func syncCatalog() {
        let id = device?.id ?? ""
        guard id != agentsFor else { return }
        agentsFor = id
        agentsTask?.cancel()
        agentsTask = nil
        catalog = id.isEmpty ? .builtin : agentCatalog.snapshot(for: id)
        AgentCatalogSnapshot.current = catalog
        shareCatalog()
        if !id.isEmpty { refreshAgents(device: id, force: false) }
    }

    /// The models that draw or act for the computer in use keep their own copy of its catalog (handoff 第三段): the
    /// process-wide snapshot stays for the view helpers and the older defaults only.
    func shareCatalog() {
        conversation.catalog = catalog
        workspace.catalog = catalog
        jobs.catalog = catalog
    }

    /// Asks the computer for its assistant list (GET /api/agents): on entering it, another computer, 重试, and when its
    /// version changed. A 404 keeps the three built-ins (an older computer); a call that failed keeps what this phone
    /// already had and asks again next time (nothing new is recorded). Never fails a page: reading the list is all
    /// this needs.
    func refreshAgents(device id: String, force: Bool) {
        agentsTask?.cancel()
        let client = client
        let known = agentCatalog.snapshotIfAny(for: id)
        agentsTask = Task { [weak self] in
            guard let self else { return }
            // Its version tells whether the list can have changed; it is recorded only once the list arrived, so a
            // failed call is asked again next time.
            let version = await self.serverVersion(id)
            guard !Task.isCancelled, self.device?.id == id else { return }
            if !force, known != nil, !version.isEmpty, version == self.agentCatalog.version(for: id) { return }
            do {
                let fetched = try await client.agents(device: id)
                guard !Task.isCancelled, self.device?.id == id else { return }
                self.applyCatalog(self.agentCatalog.store(fetched, for: id, version: version), device: id)
            } catch is CancellationError {
            } catch {
                guard !Task.isCancelled, self.device?.id == id else { return }
                // Nothing was read: the three built-ins, or the catalog this phone kept from before.
                self.applyCatalog(self.agentCatalog.snapshot(for: id), device: id)
            }
        }
    }

    /// The computer's own version (`/api/status`'s ui_version; older computers say version); "" when it cannot say.
    func serverVersion(_ id: String) async -> String {
        guard let path = try? RelayClient.devicePath(id, "/api/status"),
              let status = try? await client.json(client.get(path, deadline: 10)) else { return "" }
        let ui = status["ui_version"].string()
        return ui.isEmpty ? status["version"].string() : ui
    }

    /// One computer's catalog is now the one to draw. The chips and the sidebar keep the computer's own groups, put in
    /// the order the catalog gives them (handoff 3.2: 不认识的排最后).
    func applyCatalog(_ snapshot: AgentCatalogSnapshot, device id: String) {
        guard device?.id == id else { return }
        catalog = snapshot
        AgentCatalogSnapshot.current = snapshot
        shareCatalog()
        if sources.device == id, !tree.object.isEmpty {
            let apps = treeApps(tree, catalog: snapshot)
            if sources.apps != apps { sources.apps = apps }
        }
    }

    // MARK: What an assistant can do now (handoff 3.4)

    /// One assistant's capabilities as they apply now: the manifest's, narrowed by the open conversation's
    /// `capabilities_now` when it is this assistant's conversation (docs §八). An older computer sends no such state,
    /// so the manifest's own values stand, exactly as before.
    public func capabilities(_ app: String? = nil) -> AgentCapabilities {
        let id = app ?? self.app
        let base = catalog.caps(id)
        guard id == self.app, conversation.key?.app == id else { return base }
        return conversation.control.narrowed(base)
    }

    /// Whether [capability] can be used now by this assistant (or [app]).
    public func can(_ capability: String, app: String? = nil) -> Bool {
        capabilities(app).flag(capability) ?? false
    }

    /// Why [capability] cannot be used now, in the computer's words; "" when it gave none.
    public func capabilityNote(_ capability: String, app: String? = nil) -> String {
        let id = app ?? self.app
        guard id == self.app, conversation.key?.app == id else { return "" }
        return conversation.control.note(capability)
    }

    /// Whether this assistant (or [app]) draws the generic panel and cards: every layout but the three's own.
    public func isGeneric(_ app: String? = nil) -> Bool {
        !catalog.info(app ?? self.app).legacy
    }

    /// The layout its cards and panel follow (`generic.v1` for a new assistant).
    public func cardLayout(_ app: String? = nil) -> String {
        catalog.info(app ?? self.app).ui.cardLayout
    }

    /// What the composer says while a new assistant cannot take a message now (its app closed, say); nil when it can.
    public func sendBlockedNote(_ app: String? = nil) -> String? {
        let id = app ?? self.app
        guard isGeneric(id), capabilities(id).sendModes.isEmpty else { return nil }
        let note = capabilityNote("send", app: id)
        return note.isEmpty ? "这个对话现在不能从手机发消息，请在电脑上处理" : note
    }

    // The buttons of the three old assistants never changed (handoff 0 and 3.4): their expressions are exactly the
    // ones they had before any capability was read. Only an assistant whose layout is not one of the three's goes by
    // what its manifest (and its conversation's `capabilities_now`) allows.

    /// 停止这一轮: the three always had it; a new assistant needs `stop` now.
    public func offersStop(_ app: String? = nil) -> Bool {
        let id = app ?? self.app
        return isGeneric(id) ? can("stop", app: id) : true
    }

    /// The composer's queue tray / 发送并排队: the three always had the state say (`queue_available`); a new one
    /// needs `queue` in its send modes now.
    public func offersQueue(_ app: String? = nil) -> Bool {
        let id = app ?? self.app
        return isGeneric(id) ? can("queue", app: id) : true
    }

    /// Whether the composer may send at all: a new assistant needs a send mode now; the three never asked.
    public func offersSend(_ app: String? = nil) -> Bool {
        let id = app ?? self.app
        return isGeneric(id) ? !capabilities(id).sendModes.isEmpty : true
    }

    /// ＋ and its menu: the three always had it; a new one needs `attachments`.
    public func offersAttachments(_ app: String? = nil) -> Bool {
        let id = app ?? self.app
        return isGeneric(id) ? can("attachments", app: id) : true
    }

    /// 电脑上打开, in the ⋯ menu and the away chip: the three always had it; a new one needs `open`.
    public func offersOpenOnComputer(_ app: String? = nil) -> Bool {
        let id = app ?? self.app
        return isGeneric(id) ? can("open", app: id) : true
    }

    /// The ⋯ menu's 用量: the three had it but DeepSeek's (11-17: it has no plan limits). A new assistant shows none in
    /// 0.9.0 even when its computer offers `usage` (dev.54 opens Antigravity's): its usage section comes with the next
    /// version, so the row would open a page listing only Codex's and Claude's.
    public func showsUsage(_ app: String? = nil) -> Bool {
        let id = app ?? self.app
        if isGeneric(id) { return false }
        return id != "deepseek"
    }

    /// The composer's `/` list: the three always offered it; a new one needs `slash_commands`.
    public func allowsCommands(_ app: String? = nil) -> Bool {
        let id = app ?? self.app
        return isGeneric(id) ? can("slash_commands", app: id) : true
    }

    /// The composer's `$` list and 引用技能: the three never had it only for DeepSeek; a new one needs its skills.
    public func allowsSkills(_ app: String? = nil) -> Bool {
        let id = app ?? self.app
        return isGeneric(id) ? skillsAvailable(capabilities(id), layout: cardLayout(id)) : id != "deepseek"
    }

    // MARK: The sidebar tree (spec 4.2)

    /// Read when the drawer opens and at most every 15 s, and on entering a computer: its groups are the apps that
    /// computer has. Runs beside the page's own work; a read under way is not started again unless forced.
    public func loadTree(force: Bool = false) {
        guard let device else { return }
        let recent = treeAt.map { Date().timeIntervalSince($0) < 15 } ?? false
        if !force, treeTask != nil || (recent && !tree.object.isEmpty) { return }
        treeTask?.cancel()
        treeToken += 1
        let token = treeToken
        let owner = (origin, scope, device.id)
        let client = client
        let more = treeMore.map { key, count -> JSONValue in
            let parts = key.split(separator: "\u{1F}", maxSplits: 1).map(String.init)
            return [.string(parts.first ?? ""), .string(parts.count > 1 ? parts[1] : ""), .number(Double(count))]
        }
        treeTask = Task { [weak self] in
            defer { if let self, self.treeToken == token { self.treeTask = nil } }
            do {
                let encoded = String(decoding: try JSONValue.array(more).encoded(), as: UTF8.self)
                let request = try client.get(RelayClient.devicePath(device.id, "/api/chat/projects"), query: [("more", more.isEmpty ? nil : encoded)])
                let tree = try await client.json(request)
                guard let self, !Task.isCancelled, (self.origin, self.scope, self.device?.id ?? "") == owner else { return }
                let apps = treeApps(tree, catalog: self.catalog)
                self.treeAt = Date()
                self.tree = tree
                self.treeError = nil
                self.sources = SourceInfo(device: device.id, apps: apps)
                self.fitSources(apps)
                if !self.fixture {
                    let key = self.sourcesKey(scope: owner.1, device: device.id)
                    await self.services.store.setDetail(scope: key.scope, device: key.device, app: key.app, chat: key.chat, kind: "sources",
                                                        value: apps.joined(separator: ","))
                }
            } catch is CancellationError {
            } catch {
                guard let self, (self.origin, self.scope, self.device?.id ?? "") == owner else { return }
                let why = (error as? ServiceFailure)?.message ?? "暂时读不到电脑上的分组，可稍后再打开侧栏。"
                self.treeError = why
                if self.sources.device == device.id {
                    self.sources.loading = false
                    self.sources.failed = why
                }
            }
        }
    }

    /// 显示更多: 30 more rows of one project.
    public func moreTree(app: String, project: String) {
        let key = app + "\u{1F}" + project
        treeMore[key] = (treeMore[key] ?? 10) + 30
        loadTree(force: true)
    }

    /// 再显示 N 个: the next children of a row, past the ones it carries.
    public func moreChildren(_ parent: Chat) {
        guard let device else { return }
        let key = rowKey(parent)
        let have = parent.children.count + (moreKids[key]?.count ?? 0)
        let client = client
        Task { [weak self] in
            do {
                let page = try await client.json(client.get(RelayClient.devicePath(device.id, "/api/chats/children"),
                                                            query: [("app", parent.app), ("id", parent.id), ("offset", String(have)), ("limit", "50")]))
                let items = try page["items"].array.map(parseChat)
                guard let self else { return }
                var seen = Set<String>()
                self.moreKids[key] = ((self.moreKids[key] ?? []) + items).filter { seen.insert($0.id).inserted }
            } catch {
                self?.notice = describe(error)
            }
        }
    }

    /// A subagent's own record is not readable here: its row opens the conversation that shows its card.
    public func openChild(_ child: Chat, parent: Chat?) {
        if child.kind != "subagent" {
            open(child)
        } else {
            var fallback = Chat(id: child.parent, title: child.parentTitle.isEmpty ? "对话" : child.parentTitle)
            fallback.app = child.app
            open(parent ?? fallback)
        }
    }
}
