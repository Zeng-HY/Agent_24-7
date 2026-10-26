import Foundation
#if canImport(FoundationNetworking)
import FoundationNetworking
#endif
import Observation
import TeleplyModel

/// What the computer in use offers (Android SourceInfo): the desktop apps it has, as its sidebar tree reports
/// them. [apps] nil: not known yet for [device]. [cached]: this phone's copy from an earlier visit, shown while
/// the computer is asked again. [failed]: why it could not be asked this time.
public struct SourceInfo: Equatable, Sendable {
    public var device = ""
    public var apps: [String]?
    public var loading = false
    public var failed: String?
    public var cached = false

    public init(device: String = "", apps: [String]? = nil, loading: Bool = false, failed: String? = nil, cached: Bool = false) {
        self.device = device
        self.apps = apps
        self.loading = loading
        self.failed = failed
        self.cached = cached
    }
}

/// What the app needs from the phone. The app passes the real ones; tests pass the demo service and fakes.
public struct AppServices: Sendable {
    public var store: LocalStore
    public var vault: any CookieVault
    /// Talks to whatever address a request names (URLSession on the phone).
    public var transport: any RelayTransport
    /// A fresh local demo (开发者选项 → 打开本地示例).
    public var demo: @Sendable () -> any RelayTransport
    public var pacer: any Pacer
    /// Teleply's own service (spec 4.8): used until another address is set under 开发者选项.
    public var defaultOrigin: ServiceOrigin
    public var newScope: @Sendable () -> String
    /// A send's request id (Android UUID.randomUUID()).
    public var newID: @Sendable () -> String
    /// Milliseconds, for when a send was made.
    public var now: @Sendable () -> Int64

    public init(store: LocalStore, vault: any CookieVault, transport: any RelayTransport, demo: @escaping @Sendable () -> any RelayTransport,
                pacer: any Pacer = RealPacer(), defaultOrigin: ServiceOrigin = .default,
                newScope: @escaping @Sendable () -> String = { UUID().uuidString },
                newID: @escaping @Sendable () -> String = { UUID().uuidString.lowercased() },
                now: @escaping @Sendable () -> Int64 = { Int64(Date().timeIntervalSince1970 * 1000) }) {
        self.store = store
        self.vault = vault
        self.transport = transport
        self.demo = demo
        self.pacer = pacer
        self.defaultOrigin = defaultOrigin
        self.newScope = newScope
        self.newID = newID
        self.now = now
    }
}

/// The app's pages and where it stands (Android ReaderViewModel), on the main actor. Each user action runs as one
/// operation; a newer one cancels the older, and an answer that comes back for a page no longer shown is dropped.
@Observable
public final class AppModel {
    public enum Screen: String, Sendable {
        case launch, login, devices, chats, reading
    }

    // Where the app stands
    public internal(set) var screen = Screen.launch
    public internal(set) var origin: ServiceOrigin
    /// A random id per sign-in that keeps this phone's records apart; kept across a sign-in that ran out when the
    /// same account comes back (it owns the same computer), since the relay gives no stable account id.
    public internal(set) var scope = ""
    /// The source in use: where opening a conversation reads from.
    public internal(set) var app = "codex"
    public internal(set) var theme = "system"
    public internal(set) var account: Account?
    public internal(set) var device: Computer?
    public internal(set) var serverVersion = ""
    public internal(set) var emailEnabled = false
    /// The sign-in ran out; the place is kept for after signing in again.
    public internal(set) var expired = false
    public internal(set) var busy = false
    public var error: String?
    /// A short line that comes and goes (归档、恢复…).
    public var notice: String?
    /// The local demo: nothing is saved and no real service is asked.
    public internal(set) var fixture = false

    // The list (AppModel+List)
    public internal(set) var chats: [Chat] = []
    public internal(set) var query = ""
    public internal(set) var listSource = "all"
    public internal(set) var listSort = "updated"
    public internal(set) var listStatus = "all"
    public internal(set) var listGroup = "none"
    public internal(set) var listCursor: String?
    public internal(set) var listMore = false
    public internal(set) var hidden: Set<String> = []
    /// The bar under the list after a swipe: 对话已归档 with 撤销 (AppModel+Archive).
    public internal(set) var undo: ArchiveUndo?
    public internal(set) var moreKids: [String: [Chat]] = [:]
    public internal(set) var sources = SourceInfo()
    public internal(set) var tree: JSONValue = [:]
    public internal(set) var treeError: String?

    // Reading (AppModel+Reading)
    public internal(set) var chat: Chat?
    public internal(set) var messages: [Message] = []
    public internal(set) var cursor: String?
    public internal(set) var olderAvailable = false
    public internal(set) var newerAvailable = false
    public internal(set) var anchor: ChatRecord.Position?
    /// Goes up when the page should scroll to [anchor] (or the bottom) again.
    public internal(set) var scrollRevision = 0
    /// The page's own fields: title, folder, cwd, status and runtime.
    public internal(set) var pageMeta: JSONValue = [:]
    /// The conversation's runtime (context ring, 会话状态).
    public var runtime: JSONValue { pageMeta["runtime"] }
    public internal(set) var hits: [Message] = []
    public internal(set) var hitCursor: String?
    public internal(set) var hitMore = false
    public internal(set) var searched = false
    public internal(set) var searchQuery = ""

    // New conversations (AppModel+New)
    /// A new conversation waiting for its sheet.
    public internal(set) var pendingNew: NewTarget?
    /// The job whose 新建对话的结果 sheet is open, by request id.
    public internal(set) var jobSheet: String?
    /// A conversation just made from its job: its first message shows until the record has it.
    public internal(set) var handoff: NewHandoff?

    /// The open conversation's live connection and its composer.
    public let conversation: ChatModel
    /// What goes with the open conversation's next message (or the new conversation's first), the source's own
    /// menus and actions, and the panes.
    public let workspace: WorkspaceModel
    /// The first messages of the computer in use under way.
    public let jobs: NewChatJobs

    @ObservationIgnored let services: AppServices
    @ObservationIgnored var client: RelayClient
    /// Goes up whenever [client] is replaced, so the live connection can tell an old client from a new one.
    @ObservationIgnored var clientGeneration = 0
    @ObservationIgnored var work: Task<Void, Never>?
    @ObservationIgnored var generation = 0
    @ObservationIgnored var pendingRestore: Place?
    @ObservationIgnored var foreground = true
    @ObservationIgnored var devicePoll: Task<Void, Never>?
    @ObservationIgnored var listPoll: Task<Void, Never>?
    @ObservationIgnored var treeTask: Task<Void, Never>?
    @ObservationIgnored var treeToken = 0
    @ObservationIgnored var treeMore: [String: Int] = [:]
    @ObservationIgnored var treeAt: Date?
    @ObservationIgnored var demoPositions: [ChatKey: ChatRecord.Position] = [:]
    /// Clears the page just left once its slide-out is over.
    @ObservationIgnored var leaving: Task<Void, Never>?
    @ObservationIgnored var undoSerial = 0
    /// Whether each computer has its voice service on, as asked once.
    @ObservationIgnored var voiceOn: [String: Bool] = [:]
    /// Archives under way by row; 撤销 waits for its own to finish first.
    @ObservationIgnored var archiving: [String: Task<Bool, Never>] = [:]
    /// The new conversation's sheet being filled and opened (tests wait for it).
    @ObservationIgnored var applying: Task<Void, Never>?
    /// The restore 撤销 started (tests wait for it).
    @ObservationIgnored var restoring: Task<Void, Never>?

    public init(services: AppServices) {
        self.services = services
        origin = services.defaultOrigin
        client = RelayClient(origin: services.defaultOrigin, transport: services.transport, vault: services.vault)
        let conversation = ChatModel(pacer: services.pacer, store: services.store, newID: services.newID, now: services.now)
        let workspace = WorkspaceModel(store: services.store, newID: services.newID, now: services.now)
        conversation.extras = { try workspace.sendExtras() }
        conversation.boundSettings = { workspace.boundSettings() }
        conversation.sentExtras = { key, extras in workspace.clearSent(key, extras) }
        conversation.restoreExtras = { key, body in try workspace.restoreSent(key, body) }
        // A tap waiting on the computer holds the state polls (web claude-ui.js `choosing`).
        conversation.pollPaused = { workspace.busy || workspace.pressing || conversation.submitting }
        workspace.changed = { conversation.refreshControl() }
        workspace.stateRead = { key, raw in conversation.applyState(key, raw) }
        self.conversation = conversation
        self.workspace = workspace
        jobs = NewChatJobs(pacer: services.pacer, store: services.store, now: services.now)
        workspace.created = { [weak self] job in self?.jobCreated(job) }
        jobs.settle = { [weak self] job in
            guard let self, self.screen == .reading, self.chat?.id == job.preview else { return }
            self.finishJob(job)
        }
    }

    // MARK: Operations

    /// Runs one user action; a newer one cancels it. Errors become the page's message; a 401 goes to 登录 with
    /// the place kept.
    func operation(_ block: @escaping (Int) async throws -> Void) {
        work?.cancel()
        generation += 1
        let g = generation
        busy = true
        error = nil
        work = Task { [weak self] in
            do {
                try await block(g)
            } catch is CancellationError {
            } catch {
                self?.fail(g, error)
            }
            guard let self, g == self.generation else { return }
            self.busy = false
            self.live()
        }
    }

    func current(_ g: Int) -> Bool {
        g == generation && !Task.isCancelled
    }

    func fail(_ g: Int, _ failure: any Error) {
        guard g == generation else { return }
        error = describe(failure)
        if (failure as? ServiceFailure)?.status == 401 {
            screen = .login
            expired = true
        }
    }

    /// Waits until the page's work (and a sidebar read it started) is done: for tests and the launch screen.
    public func settle() async {
        while let running = work {
            await running.value
            if work == running { break }
        }
        await treeTask?.value
        await leaving?.value
    }

    func cancelWork() {
        work?.cancel()
        generation += 1
        busy = false
        error = nil
    }

    func useClient(_ next: RelayClient) {
        client = next
        clientGeneration += 1
    }

    /// Back to nothing held for another account, service or the demo; the appearance and source stay.
    func clearAll() {
        account = nil
        device = nil
        expired = false
        chats = []
        query = ""
        listCursor = nil
        listMore = false
        hidden = []
        moreKids = [:]
        sources = SourceInfo()
        tree = [:]
        treeError = nil
        treeTask?.cancel()
        treeMore = [:]
        treeAt = nil
        pendingNew = nil
        jobSheet = nil
        undo = nil
        clearReading()
    }

    func clearReading() {
        chat = nil
        messages = []
        cursor = nil
        olderAvailable = false
        newerAvailable = false
        anchor = nil
        pageMeta = [:]
        hits = []
        hitCursor = nil
        hitMore = false
        searched = false
        searchQuery = ""
        handoff = nil
    }

    func persistSelection(scope: String, device: String, chat: String = "", title: String = "") async {
        guard !fixture else { return }
        await services.store.setSelection(scope: scope, device: device, chat: chat, title: title)
    }

    // MARK: Launch and sign-in (spec 4.8)

    /// As the app opens: the saved service, or the default one, with the mark shown meanwhile (web booting).
    public func start() {
        operation { [weak self] g in try await self?.begin(g) }
    }

    /// 重试 on 登录 after the service could not be reached; also leaving the demo.
    public func relaunch() {
        start()
    }

    func begin(_ g: Int) async throws {
        let place = await services.store.place()
        guard current(g) else { return }
        pendingRestore = place
        clearAll()
        fixture = false
        app = place.app.isEmpty ? "codex" : place.app
        theme = place.theme
        scope = place.scope
        origin = (try? ServiceOrigin(place.origin)) ?? services.defaultOrigin
        screen = .launch
        useClient(RelayClient(origin: origin, transport: services.transport, vault: services.vault))
        try await restore(g)
    }

    /// Where the app stands at launch (web account page): not signed in → 登录; signed in → the computer used last
    /// when it is online, the only computer when there is one, otherwise 我的电脑. A service out of reach stays on
    /// 登录 with why.
    func restore(_ g: Int) async throws {
        let config: AccountConfig
        do {
            config = try await client.accountConfig()
        } catch is CancellationError {
            throw CancellationError()
        } catch {
            guard current(g) else { return }
            screen = .login
            self.error = "连不上服务器，请检查网络后重试。"
            return
        }
        guard current(g) else { return }
        serverVersion = config.version
        emailEnabled = config.emailEnabled
        screen = .login
        let place = pendingRestore
        if let saved = place?.device, !saved.isEmpty { device = Computer(id: saved, label: "待核对电脑", connectable: false) }
        if let saved = place?.chat, !saved.isEmpty { chat = Chat(id: saved, title: place?.title ?? "") }
        let account: Account
        do {
            account = try await client.account()
        } catch let failure as ServiceFailure where failure.status == 401 {
            // Not signed in: 登录. Signed in before on this phone: it ran out, and the place is kept for after.
            guard current(g) else { return }
            expired = device != nil
            return
        }
        guard current(g) else { return }
        let wanted = place?.device ?? ""
        let found = account.devices.first { $0.id == wanted } ?? (wanted.isEmpty && account.devices.count == 1 ? account.devices.first : nil)
        let kept = place?.scope ?? ""
        let scope = kept.isEmpty ? services.newScope() : kept
        self.account = account
        self.scope = scope
        device = nil
        clearReading()
        screen = .devices
        expired = false
        if let found, found.connectable {
            try await client.select(device: found.id)
            guard current(g) else { return }
            let known = await cachedSources(scope: scope, device: found.id)
            device = found
            screen = .chats
            sources = SourceInfo(device: found.id, apps: known, loading: true, cached: known != nil)
            loadTree(force: true)
            if found.id == wanted, let saved = place?.chat, !saved.isEmpty {
                try await readChat(g, Chat(id: saved, title: (place?.title ?? "").isEmpty ? "对话" : place?.title ?? ""), restorePosition: true)
            } else {
                try await loadChats(g)
            }
            if found.id != wanted { await persistSelection(scope: scope, device: found.id) }
        }
        pendingRestore = nil
    }

    /// 登录 with the account name or email and the password; the password is used once and not kept.
    public func login(name: String, password: String) {
        operation { [weak self] g in try await self?.signIn(g, name: name, password: password) }
    }

    func signIn(_ g: Int, name: String, password: String) async throws {
        let name = name.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !name.isEmpty, !password.isEmpty else { throw ReadFailure("请输入账号与密码。") }
        try await client.login(name: name, password: password)
        let account = try await client.account()
        guard current(g) else { return }
        // A computer id belongs to exactly one account: the same computer means the same account came back.
        let previousDevice = device, previousChat = chat
        let sameOwner = expired && previousDevice != nil && account.devices.contains { $0.id == previousDevice?.id }
        let scope = sameOwner ? self.scope : services.newScope()
        if sameOwner, let verified = account.devices.first(where: { $0.id == previousDevice?.id }) {
            self.account = account
            device = verified
            expired = false
            screen = previousChat != nil ? .reading : .chats
            if messages.isEmpty, verified.connectable {
                try await client.select(device: verified.id)
                guard current(g) else { return }
                if sources.device != verified.id {
                    let known = await cachedSources(scope: scope, device: verified.id)
                    sources = SourceInfo(device: verified.id, apps: known, loading: true, cached: known != nil)
                }
                if knownApps == nil || sources.failed != nil { loadTree(force: true) }
                if let previousChat { try await readChat(g, previousChat, restorePosition: true) } else { try await loadChats(g) }
            }
        } else {
            clearAll()
            self.account = account
            self.scope = scope
            screen = .devices
        }
        await persistSelection(scope: scope, device: sameOwner ? previousDevice?.id ?? "" : "",
                               chat: sameOwner ? previousChat?.id ?? "" : "", title: sameOwner ? previousChat?.title ?? "" : "")
    }

    /// 退出登录 (web account menu): the service forgets the sign-in, this phone its cookie and where it was.
    public func logout() {
        operation { [weak self] g in
            guard let self else { return }
            try? await self.client.logout()
            await self.persistSelection(scope: self.scope, device: "")
            guard self.current(g) else { return }
            self.clearAll()
            self.screen = .login
        }
    }

    // MARK: 我的电脑

    /// 我的电脑, read again; the computer in use stays unless the account no longer has it.
    public func showComputers() {
        operation { [weak self] g in
            guard let self else { return }
            self.screen = .devices
            let account = try await self.client.account()
            guard self.current(g) else { return }
            if let device = self.device, !account.devices.contains(where: { $0.id == device.id }) {
                self.device = nil
                self.chats = []
                self.clearReading()
            }
            self.account = account
        }
    }

    /// 连接: routes to this computer and shows its list. Another computer starts from its own apps (this phone's
    /// copy, else unknown), never the last one's.
    public func select(_ computer: Computer) {
        operation { [weak self] g in
            guard let self else { return }
            guard computer.connectable else { throw ReadFailure("电脑已离线，请稍后刷新。") }
            let same = self.sources.device == computer.id
            let known = same ? self.sources.apps : await self.cachedSources(scope: self.scope, device: computer.id)
            guard self.current(g) else { return }
            let filter = self.listSource == "all" || known?.contains(self.listSource) == true ? self.listSource : "all"
            // Old content goes before selecting, even if the new selection fails.
            self.device = nil
            self.chats = []
            self.clearReading()
            self.query = ""
            self.listCursor = nil
            self.listMore = false
            self.tree = [:]
            self.treeError = nil
            self.listSource = filter
            self.sources = SourceInfo(device: computer.id, apps: known, loading: true, cached: known != nil && !same)
            self.treeTask?.cancel()
            self.treeMore = [:]
            self.treeAt = nil
            try await self.client.select(device: computer.id)
            guard self.current(g) else { return }
            self.device = computer
            self.screen = .chats
            self.loadTree(force: true)
            await self.persistSelection(scope: self.scope, device: computer.id)
            try await self.loadChats(g)
        }
    }

    /// 重命名 a computer; the list is read again.
    public func renameDevice(_ computer: Computer, label: String) {
        operation { [weak self] g in
            guard let self else { return }
            let label = label.trimmingCharacters(in: .whitespacesAndNewlines)
            guard !label.isEmpty else { throw ReadFailure("请输入电脑名称。") }
            try await self.client.renameDevice(computer.id, label: label)
            let account = try await self.client.account()
            guard self.current(g) else { return }
            self.account = account
            if let device = self.device { self.device = account.devices.first { $0.id == device.id } ?? device }
        }
    }

    /// 移除: the computer loses remote access (its files stay); the list is read again.
    public func removeDevice(_ computer: Computer) {
        operation { [weak self] g in
            guard let self else { return }
            try await self.client.revokeDevice(computer.id)
            let account = try await self.client.account()
            guard self.current(g) else { return }
            self.account = account
            if self.device?.id == computer.id {
                self.device = nil
                self.chats = []
            }
        }
    }

    /// 我的电脑 is read again every 15 s while it is shown (web account page), quietly.
    func pollDevices(_ on: Bool) {
        guard on else {
            devicePoll?.cancel()
            devicePoll = nil
            return
        }
        guard devicePoll == nil else { return }
        devicePoll = Task { [weak self] in
            while !Task.isCancelled {
                guard let pacer = self?.services.pacer else { return }
                do { try await pacer.wait(.seconds(15)) } catch { return }
                guard let self, !self.busy, self.screen == .devices, self.account != nil else { continue }
                let origin = self.origin
                guard let account = try? await self.client.account(), self.screen == .devices, self.origin == origin else { continue }
                self.account = account
            }
        }
    }

    // MARK: The phone, the service and the demo

    /// The app came to the front or went to the background (not a brief pull of Control Center).
    public func setForeground(_ active: Bool) {
        foreground = active
        if !active { Task { await conversation.flushDraft() } }
        live()
    }

    /// Binds what should be running to what is shown: the open conversation's live connection, the list's 10 s
    /// read and 我的电脑's 15 s read, the new conversations' looks, all only in the foreground. Off a conversation,
    /// the workspace holds the new conversation's draft ("@new"). A new conversation's page has no state yet:
    /// drafts only.
    public func live() {
        var key: ChatKey?
        if screen == .reading, !expired, let device, let chat { key = ChatKey(scope: scope, device: device.id, app: app, chat: chat.id) }
        let newPage = isNewPage(key?.chat)
        pollList(foreground && screen == .chats && device != nil && !expired)
        pollDevices(foreground && screen == .devices && account != nil && !fixture)
        conversation.bind(key, client: client, clientGeneration: clientGeneration, active: foreground && !newPage, synthetic: fixture) { [weak self] frame, key in
            self?.apply(frame, for: key)
        }
        let draft = device.flatMap { device in expired ? nil : ChatKey(scope: scope, device: device.id, app: app, chat: key?.chat ?? "@new") }
        workspace.bind(draft, client: client, clientGeneration: clientGeneration, synthetic: fixture)
        jobs.bind(scope: scope, device: expired ? nil : device?.id, client: client, synthetic: fixture)
        jobs.setForeground(foreground)
        jobs.onScreen = newPage ? key?.chat : nil
    }

    /// 外观: 跟随系统 / 浅色 / 深色.
    public func setAppearance(_ value: String) {
        theme = value
        guard !fixture else { return }
        Task { await services.store.setTheme(value) }
    }

    /// 连接这个服务 (开发者选项 → 服务地址): only a service that answers replaces the one in use, and the app then
    /// starts on it as at launch. One out of reach keeps the page with why.
    public func connect(_ address: String) {
        operation { [weak self] g in
            guard let self else { return }
            let next = try ServiceOrigin(address)
            let probe = RelayClient(origin: next, transport: self.services.transport, vault: self.services.vault)
            do {
                _ = try await probe.accountConfig()
            } catch is CancellationError {
                throw CancellationError()
            } catch {
                throw ReadFailure("连不上这个服务，请检查地址和网络后重试。")
            }
            let saved = (try? ServiceOrigin(await self.services.store.place().origin)) ?? self.services.defaultOrigin
            if saved != next { await self.services.store.setOrigin(next.header) }
            try await self.begin(g)
        }
    }

    /// 打开本地示例 (开发者选项): fixed data, no real service, nothing saved; 登录 accepts anything.
    public func openDemo() {
        cancelWork()
        clearAll()
        fixture = true
        scope = "fixture"
        serverVersion = "fixture"
        emailEnabled = false
        demoPositions = [:]
        useClient(RelayClient(origin: services.defaultOrigin, transport: services.demo(), vault: MemoryCookieVault()))
        screen = .login
        live()
    }

    /// The system back (or the page's own 返回).
    public func back() {
        switch screen {
        case .login where fixture:
            relaunch()
        case .reading:
            // The navigation stack pops at once, so the screen changes now; the page keeps what it showed until its
            // slide-out is over, unless it is opened again meanwhile.
            screen = .chats
            live()
            leaving?.cancel()
            leaving = Task { [weak self] in
                try? await Task.sleep(for: .milliseconds(450))
                guard let self, !Task.isCancelled, self.screen != .reading else { return }
                self.clearReading()
            }
            operation { [weak self] g in
                guard let self else { return }
                await self.persistSelection(scope: self.scope, device: self.device?.id ?? "")
                // Back in the list it is read again (web closeConv → loadConvs): a conversation made meanwhile shows.
                if self.chats.isEmpty { try await self.loadChats(g) } else { try? await self.mergeFirstPage(g) }
            }
        case .devices where device != nil:
            cancelWork()
            screen = .chats
            live()
        default:
            break
        }
    }

    /// 测一下连接 (开发者选项 → 诊断测速): one status read of the computer in use, as the web words the outcome.
    public func checkStatus() async -> String {
        guard let device else { return "没有选择电脑" }
        do {
            _ = try await client.json(client.get(RelayClient.devicePath(device.id, "/api/status"), deadline: 10))
            return "成功"
        } catch let failure as ServiceFailure {
            return "HTTP \(failure.status)"
        } catch let failure as URLError where failure.code == .timedOut {
            return "超过10秒"
        } catch {
            return "网络失败"
        }
    }

    /// The page's 重试.
    public func retry() {
        switch screen {
        case .devices: showComputers()
        case .chats: searchChats(query)
        case .reading: if let chat { open(chat) }
        case .login, .launch: if account == nil && !fixture { relaunch() }
        }
    }
}
