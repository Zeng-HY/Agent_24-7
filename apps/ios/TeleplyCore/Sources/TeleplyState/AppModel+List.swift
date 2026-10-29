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
        let beyond = chats.contains { !fresh.contains(rowKey($0)) }
        // The 10 s read mostly brings the same rows: equal values are not written again (as ChatModel.take).
        let merged = (page.items + chats.filter { !fresh.contains(rowKey($0)) }).filter { !hidden.contains(rowKey($0)) }
        if merged != chats { chats = merged }
        if !beyond {
            if listCursor != page.cursor { listCursor = page.cursor }
            if listMore != page.hasMore { listMore = page.hasMore }
        }
    }

    /// The list is read again every 10 s while it is in front (web loadConvs): rows merge, nothing is reset.
    func pollList(_ on: Bool) {
        guard on else {
            listPoll?.cancel()
            listPoll = nil
            return
        }
        guard listPoll == nil else { return }
        listPoll = Task { [weak self] in
            while !Task.isCancelled {
                guard let pacer = self?.services.pacer else { return }
                do { try await pacer.wait(.seconds(10)) } catch { return }
                guard let self, !self.busy, self.screen == .chats, !self.expired else { continue }
                try? await self.mergeFirstPage()
            }
        }
    }

    public func searchChats(_ words: String) {
        operation { [weak self] g in
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
        operation { [weak self] g in try await self?.loadChats(g, more: true) }
    }

    /// The ⋯ 列表显示 menu: 分组, 排序, 状态, 来源.
    public func listDisplay(source: String? = nil, sort: String? = nil, status: String? = nil, group: String? = nil) {
        let source = source ?? listSource, sort = sort ?? listSort, status = status ?? listStatus
        guard source == "all" || sourceOrder.contains(source) else { return }
        let reload = source != listSource || sort != listSort || status != listStatus
        listSource = source
        listSort = sort
        listStatus = status
        if let group { listGroup = group }
        guard reload else { return }
        operation { [weak self] g in
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
        listStatus = target.status
        if device?.id == computer.id {
            listDisplay(status: target.status)
        } else {
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
        return saved.split(separator: ",").map(String.init).filter { sourceOrder.contains($0) }
    }

    /// The chips' and the sheet's 重试: ask the computer again.
    public func retrySources() {
        if let device, sources.device == device.id {
            sources.loading = true
            sources.failed = nil
        }
        loadTree(force: true)
    }

    /// The computer answered with its apps: a list filter on one it does not have goes back to 全部.
    func fitSources(_ apps: [String]) {
        guard listSource != "all", !apps.contains(listSource) else { return }
        listSource = "all"
        chats = []
        listCursor = nil
        listMore = false
        if screen == .chats { operation { [weak self] g in try await self?.loadChats(g) } }
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
                let apps = treeApps(tree)
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
