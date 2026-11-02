import Foundation
import Observation
import Synchronization
import Testing
@testable import TeleplyDemo
import TeleplyModel
@testable import TeleplyState

/// Whether an observed value was set (Observation's onChange runs on any thread).
final class Seen: Sendable {
    private let value = Mutex(false)

    var marked: Bool { value.withLock { $0 } }

    func mark() {
        value.withLock { $0 = true }
    }
}

/// Never lets time pass: polls and reconnects wait until the test ends.
struct IdlePacer: Pacer {
    func wait(_ duration: Duration) async throws {
        try await Task.sleep(for: .seconds(3_600))
    }
}

func temporaryFolder() -> URL {
    FileManager.default.temporaryDirectory.appendingPathComponent("teleply-app-\(UUID().uuidString)")
}

/// The app on the demo service (as if it were the real one): one store and vault per phone.
@MainActor
func makeApp(world: DemoWorld = DemoWorld(), store: LocalStore = LocalStore(folder: temporaryFolder()),
             vault: MemoryCookieVault = MemoryCookieVault()) -> AppModel {
    AppModel(services: AppServices(store: store, vault: vault, transport: DemoTransport(world: world), demo: { DemoTransport() },
                                   pacer: IdlePacer(), newScope: { "scope-1" }))
}

/// The demo computer with a list of the rows a test chose, all running: what a list brings changes from read to read.
final class ChosenListTransport: RelayTransport {
    let demo = DemoTransport()
    let rows = Mutex(["a", "b"])

    func send(_ request: RelayRequest) async throws -> RelayResponse {
        guard request.url.path.hasSuffix("/api/chats") else { return try await demo.send(request) }
        let items = rows.withLock { $0 }.map { #"{"id":"\#($0)","title":"\#($0)","app":"codex","status":"running"}"# }
        return .json(#"{"items":[\#(items.joined(separator: ","))],"has_more":false}"#)
    }
}

/// The demo computer with a list a test chose, answered as chat_history.py does: only the asked state, in its order, two
/// rows at a time, each page starting after the end of the one before (the cursor here is that row's id).
final class PagedListTransport: RelayTransport {
    struct Row: Sendable {
        var id: String
        var status: String
        var updated: Int64
        var created: Int64 = 0
    }

    let demo = DemoTransport()
    let rows: Mutex<[Row]>

    /// A row for each letter, newest first.
    init(_ names: String, status: String = "running") {
        rows = Mutex(names.enumerated().map { Row(id: String($1), status: status, updated: 1_000 - Int64($0)) })
    }

    init(rows: [Row]) {
        self.rows = Mutex(rows)
    }

    func end(_ names: String) {
        rows.withLock { list in
            for index in list.indices where names.contains(list[index].id) { list[index].status = "idle" }
        }
    }

    func send(_ request: RelayRequest) async throws -> RelayResponse {
        guard request.url.path.hasSuffix("/api/chats") else { return try await demo.send(request) }
        let query = URLComponents(url: request.url, resolvingAgainstBaseURL: false)?.queryItems ?? []
        let value = { (name: String) in query.first { $0.name == name }?.value }
        let byCreated = value("sort") == "created", status = value("status") ?? "all", cursor = value("cursor")
        let order = { (row: Row) in byCreated ? row.created : row.updated }
        let all = rows.withLock { $0 }
        var rest = all.filter { status == "all" || $0.status == status }.sorted { (order($0), $1.id) > (order($1), $0.id) }
        if let end = all.first(where: { $0.id == cursor }) { rest = rest.filter { (order($0), end.id) < (order(end), $0.id) } }
        let items = rest.prefix(2).map { #"{"id":"\#($0.id)","title":"\#($0.id)","app":"codex","status":"\#($0.status)","updated":\#($0.updated),"created":\#($0.created)}"# }
        let next = rest.count > 2 ? #""\#(rest[1].id)""# : "null"
        return .json(#"{"items":[\#(items.joined(separator: ","))],"next_cursor":\#(next),"has_more":\#(rest.count > 2)}"#)
    }
}

/// The demo computer, with every conversation opening on a message cut short the way the computer cuts one over 6000
/// characters (chat_history.public_message; the user's prompt of 7545, 10-27).
struct CutMessageTransport: RelayTransport {
    let demo = DemoTransport()

    func send(_ request: RelayRequest) async throws -> RelayResponse {
        let path = request.url.path
        if path.hasSuffix("/api/chat/message") { return .json(#"{"id":"long","role":"user","text":"前半后半","length":4}"#) }
        guard path.hasSuffix("/api/chat") else { return try await demo.send(request) }
        let query = URLComponents(url: request.url, resolvingAgainstBaseURL: false)?.queryItems ?? []
        let value = { (name: String) in query.first { $0.name == name }?.value ?? "" }
        return .json(#"{"app":"\#(value("app"))","id":"\#(value("id"))","messages":[{"id":"long","role":"user","text":"前半","truncated":true,"length":4}]}"#)
    }
}

@MainActor
struct AppModelTests {
    let a = String(repeating: "a", count: 32)
    let b = String(repeating: "b", count: 32)

    func signedInOnA(_ model: AppModel) async {
        model.start()
        await model.settle()
        model.login(name: "账号", password: "密码")
        await model.settle()
        if let computer = model.account?.devices.first(where: { $0.id == a }) { model.select(computer) }
        await model.settle()
    }

    @Test func theFirstLaunchAsksToSignIn() async {
        let model = makeApp()
        model.start()
        await model.settle()
        #expect(model.screen == .login)
        #expect(model.serverVersion == "fixture" && !model.expired && model.error == nil)
    }

    @Test func signingInListsTheComputersAndEnteringOneShowsItsList() async {
        let model = makeApp()
        model.start()
        await model.settle()
        model.login(name: "账号", password: "密码")
        await model.settle()
        #expect(model.screen == .devices)
        #expect(model.account?.devices.map(\.label) == ["测试电脑 A", "测试电脑 B", "离线电脑"])
        model.select(model.account!.devices[0])
        await model.settle()
        #expect(model.screen == .chats && model.device?.id == a)
        #expect(model.chats.first?.title == "原生阅读示例" && model.listCursor == "page2")
        #expect(model.knownApps == ["codex", "claude", "deepseek"])
    }

    @Test func aComputerWithoutClaudeDropsAClaudeFilter() async {
        let model = makeApp()
        await signedInOnA(model)
        model.listDisplay(source: "claude")
        await model.settle()
        #expect(model.chats.allSatisfy { $0.app == "claude" })
        model.select(model.account!.devices[1])
        await model.settle()
        #expect(model.knownApps == ["codex", "deepseek"])
        #expect(model.listSource == "all")
        #expect(!model.chats.contains { $0.app == "claude" })
    }

    @Test func openingAConversationReadsItAndRemembersThePlace() async {
        let store = LocalStore(folder: temporaryFolder())
        let model = makeApp(store: store)
        await signedInOnA(model)
        model.open(model.chats.first { $0.id == "demo" }!)
        await model.settle()
        #expect(model.screen == .reading && model.chat?.title == "原生阅读示例")
        #expect(model.messages.map(\.id) == ["m1", "m1b", "m1c", "m2", "m3"])
        #expect(model.runtime["percent"].int() == 46)
        let place = await store.place()
        #expect(place.device == a && place.chat == "demo" && place.scope == "scope-1")
    }

    @Test func relaunchingReturnsToTheSameConversation() async {
        let store = LocalStore(folder: temporaryFolder())
        let vault = MemoryCookieVault()
        let world = DemoWorld()
        let first = makeApp(world: world, store: store, vault: vault)
        await signedInOnA(first)
        first.open(first.chats.first { $0.id == "claude-demo" }!)
        await first.settle()
        let again = makeApp(world: world, store: store, vault: vault)
        again.start()
        await again.settle()
        #expect(again.screen == .reading && again.app == "claude" && again.chat?.id == "claude-demo")
        #expect(again.messages.first?.id == "c1")
    }

    @Test func anExpiredSignInKeepsThePlaceUntilTheSameAccountComesBack() async {
        let store = LocalStore(folder: temporaryFolder())
        let world = DemoWorld()
        let first = makeApp(world: world, store: store)
        await signedInOnA(first)
        first.open(first.chats.first { $0.id == "demo" }!)
        await first.settle()
        world.state.withLock { $0.signedIn = false }
        let again = makeApp(world: world, store: store, vault: MemoryCookieVault())
        again.start()
        await again.settle()
        #expect(again.screen == .login && again.expired)
        again.login(name: "账号", password: "密码")
        await again.settle()
        #expect(again.screen == .reading && again.chat?.id == "demo" && again.scope == "scope-1")
    }

    @Test func anOfflineComputerIsRefusedWithItsReason() async {
        let model = makeApp()
        await signedInOnA(model)
        model.select(model.account!.devices[2])
        await model.settle()
        #expect(model.error == "电脑已离线，请稍后刷新。")
    }

    @Test func goingBackFromAConversationReadsTheListAgain() async {
        let store = LocalStore(folder: temporaryFolder())
        let model = makeApp(store: store)
        await signedInOnA(model)
        model.open(model.chats[0])
        await model.settle()
        model.back()
        await model.settle()
        #expect(model.screen == .chats && model.chat == nil && !model.chats.isEmpty)
        #expect(await store.place().chat == "")
    }

    @Test func olderMessagesComeBeforeAndSearchFindsAndJumps() async {
        let model = makeApp()
        await signedInOnA(model)
        model.open(model.chats[0])
        await model.settle()
        model.older()
        await model.settle()
        #expect(model.messages.first?.id == "m0")
        model.searchHistory("原生")
        await model.settle()
        #expect(model.hits.map(\.id) == ["m2"] && model.searched)
        model.jump(to: model.hits[0])
        await model.settle()
        #expect(model.anchor?.message == "m2" && model.hits.isEmpty)
    }

    /// Every conversation opens at its latest messages (user 10-27: "保持每次点开对话都在最新的地方"): from the list, after
    /// a found message, after a relaunch and from a notification. A place an older build kept is not read.
    @Test func everyOpeningReadsTheLatestPageFromTheBottom() async throws {
        let world = DemoWorld()
        let store = LocalStore(folder: temporaryFolder())
        let vault = MemoryCookieVault()
        let transport = WatchedTransport(world: world)
        func app() -> AppModel {
            AppModel(services: AppServices(store: store, vault: vault, transport: transport, demo: { DemoTransport() }, pacer: IdlePacer(),
                                           newScope: { "scope-1" }))
        }
        let model = app()
        await signedInOnA(model)
        await store.update(scope: "scope-1", device: a, app: "codex", chat: "demo") { $0.position = .init(message: "m2", offset: 0) }
        model.open(model.chats.first { $0.id == "demo" }!)
        await model.settle()
        #expect(model.anchor == nil && model.messages.last?.id == "m3")
        model.searchHistory("原生")
        await model.settle()
        model.jump(to: model.hits[0])
        await model.settle()
        #expect(model.anchor?.message == "m2")
        model.back()
        await model.settle()
        model.open(model.chats.first { $0.id == "demo" }!)
        await model.settle()
        #expect(model.anchor == nil)
        // Opened again after the app was closed, then from a notification.
        let again = app()
        again.start()
        await again.settle()
        #expect(again.screen == .reading && again.chat?.id == "demo" && again.anchor == nil)
        again.openNotification(try #require(PushTarget(device: a, app: "codex", chat: "demo")))
        await again.settle()
        #expect(again.screen == .reading && again.anchor == nil)
        let reads = await transport.log.items.filter { $0.url.path.hasSuffix("/api/chat") }
        #expect(reads.map { queryValue($0, "around") } == [nil, "m2", nil, nil, nil])
        // Nothing was written over the old place either; it is simply not read.
        #expect(await store.record(scope: "scope-1", device: a, app: "codex", chat: "demo").position == .init(message: "m2", offset: 0))
    }

    /// A poll that brings nothing new tells no page anything: a long conversation's page is costly to redraw (10-27).
    @Test func pollsThatBringNothingNewLeaveThePagesAlone() async throws {
        let model = makeApp()
        model.openDemo()
        model.login(name: "x", password: "y")
        await model.settle()
        model.select(model.account!.devices[0])
        await model.settle()
        let list = Seen()
        withObservationTracking {
            _ = model.chats
            _ = model.listCursor
            _ = model.listMore
        } onChange: { list.mark() }
        try await model.mergeFirstPage()
        #expect(!list.marked)
        model.open(model.chats.first { $0.title == "DeepSeek 批准示例" }!)
        await model.settle()
        await model.conversation.settle()
        let state = Seen()
        withObservationTracking {
            _ = model.conversation.control
            _ = model.conversation.connection
        } onChange: { state.mark() }
        model.conversation.refreshControl()
        await model.conversation.settle()
        #expect(!state.marked)
        // A state that did change is still shown.
        model.workspace.action("deepseek/approval", ["event_id": "e-approval-1", "choice": "allowed-once"])
        await model.workspace.settle()
        await model.conversation.settle()
        #expect(state.marked && model.conversation.control.running)
    }

    /// 10-30: back in front (from the background, 设置 or 我的电脑) the list is read at once, so a turn that ended
    /// meanwhile no longer shows 运行中 with a ticking timer for ten seconds; back from a conversation it is read once
    /// (by back()), not twice.
    @Test func theListIsReadAtOnceWhenItComesBackToTheFront() async throws {
        let transport = WatchedTransport(world: DemoWorld())
        let model = AppModel(services: AppServices(store: LocalStore(folder: temporaryFolder()), vault: MemoryCookieVault(),
                                                   transport: transport, demo: { DemoTransport() }, pacer: IdlePacer(),
                                                   newScope: { "scope-1" }))
        await signedInOnA(model)
        func reads() async -> Int { await transport.log.items.filter { $0.url.path.hasSuffix("/api/chats") }.count }
        // Lets a read that is due happen, then waits until no more come.
        func quiet() async throws {
            var last = -1
            while true {
                let now = await reads()
                if now == last { return }
                last = now
                try await Task.sleep(for: .milliseconds(100))
            }
        }
        try await quiet()
        let start = await reads()
        model.setForeground(false)
        model.setForeground(true)
        try await quiet()
        #expect(await reads() == start + 1)
        model.open(model.chats.first { $0.id == "demo" }!)
        await model.settle()
        model.back()
        await model.settle()
        try await quiet()
        #expect(await reads() == start + 2)
    }

    /// 11-02: the island's 还有 N 个 set the state first, so the list saw no change and kept every row. The polls then
    /// brought the running ones alone and nothing read the others again.
    @Test func theIslandsListOpensOnTheRunningRowsAlone() async throws {
        let model = makeApp()
        await signedInOnA(model)
        #expect(model.chats.contains { $0.status != "running" })
        model.openIslandList(try #require(IslandListTarget(url: URL(string: "teleply://list?d=\(model.device!.id)&status=running")!)))
        await model.settle()
        #expect(model.listStatus == "running")
        #expect(model.chats.allSatisfy { $0.status == "running" })
    }

    /// 11-02: a conversation that ended is not in a running-only list any more; kept, it said 运行中 for hours.
    @Test func aRowThatEndedLeavesAListOfOneStateAndStaysInTheWholeList() async throws {
        let transport = ChosenListTransport()
        let model = AppModel(services: AppServices(store: LocalStore(folder: temporaryFolder()), vault: MemoryCookieVault(),
                                                   transport: transport, demo: { DemoTransport() }, pacer: IdlePacer(),
                                                   newScope: { "scope-1" }))
        await signedInOnA(model)
        #expect(model.chats.map(\.id) == ["a", "b"])
        // The whole list: the first page leaving a row out says nothing about it (it may be on a later page).
        transport.rows.withLock { $0 = ["a"] }
        try await model.mergeFirstPage()
        #expect(model.chats.map(\.id) == ["a", "b"])
        transport.rows.withLock { $0 = ["a", "b"] }
        model.listDisplay(status: "running")
        await model.settle()
        #expect(model.chats.map(\.id) == ["a", "b"])
        transport.rows.withLock { $0 = ["a"] }
        try await model.mergeFirstPage()
        #expect(model.chats.map(\.id) == ["a"])
        #expect(!model.listMore)
    }

    /// Signed in on a computer whose list is [transport]'s, showing the rows of [status], [sort] first.
    func onPagedList(_ transport: PagedListTransport, status: String, sort: String = "updated") async -> AppModel {
        let model = AppModel(services: AppServices(store: LocalStore(folder: temporaryFolder()), vault: MemoryCookieVault(),
                                                   transport: transport, demo: { DemoTransport() }, pacer: IdlePacer(),
                                                   newScope: { "scope-1" }))
        await signedInOnA(model)
        model.listDisplay(sort: sort, status: status)
        await model.settle()
        return model
    }

    func more(_ model: AppModel) async {
        model.moreChats()
        await model.settle()
    }

    func shown(_ model: AppModel) -> String { model.chats.map(\.id).joined() }

    /// 11-02: 加载更多 is not taken back at the next read: 已结束 could not be read past its first page.
    @Test func thePagesReadPastTheFirstStayInAListOfOneState() async throws {
        let transport = PagedListTransport("abcde", status: "idle")
        let model = await onPagedList(transport, status: "idle")
        await more(model)
        #expect(shown(model) == "abcd")
        try await model.mergeFirstPage()
        #expect(shown(model) == "abcd")
        #expect(model.listCursor == "d")
        #expect(model.listMore)
        await more(model)
        #expect(shown(model) == "abcde")
    }

    @Test func aRowThatLeftItsStateGoesEvenWithLaterPagesRead() async throws {
        let transport = PagedListTransport("abcdef")
        let model = await onPagedList(transport, status: "running")
        await more(model)
        #expect(shown(model) == "abcd")
        transport.end("b")
        try await model.mergeFirstPage()
        #expect(shown(model) == "acd")
        #expect(model.listCursor == "d")
        await more(model)
        #expect(shown(model) == "acdef")
    }

    /// A newer row takes the first page's place: the last one there has not left its state, it is on the next page.
    @Test func aRowPushedOffTheFirstPageStays() async throws {
        let transport = PagedListTransport("abcde")
        let model = await onPagedList(transport, status: "running")
        #expect(shown(model) == "ab")
        transport.rows.withLock { $0.insert(PagedListTransport.Row(id: "n", status: "running", updated: 2_000), at: 0) }
        try await model.mergeFirstPage()
        #expect(shown(model) == "nab")
        #expect(model.listCursor == "b")
        await more(model)
        #expect(shown(model) == "nabcd")
    }

    @Test func rowsPastTheFirstPageGoOnceTheListFitsOnIt() async throws {
        let transport = PagedListTransport("abcde")
        let model = await onPagedList(transport, status: "running")
        await more(model)
        #expect(shown(model) == "abcd")
        transport.end("cde")
        try await model.mergeFirstPage()
        #expect(shown(model) == "ab")
        #expect(model.listCursor == nil)
        #expect(!model.listMore)
    }

    /// Sorted by 创建时间, that order says which rows come after the first page: here newly active ones still do.
    @Test func sortedByCreationThatOrderDecidesWhatStays() async throws {
        let rows = [(50, 1), (40, 2), (30, 99), (20, 98), (10, 3)].enumerated().map { index, dates in
            PagedListTransport.Row(id: String(Array("abcde")[index]), status: "idle", updated: Int64(dates.1), created: Int64(dates.0))
        }
        let model = await onPagedList(PagedListTransport(rows: rows), status: "idle", sort: "created")
        await more(model)
        #expect(shown(model) == "abcd")
        try await model.mergeFirstPage()
        #expect(shown(model) == "abcd")
    }

    /// The whole list as before: a row the first page leaves out may be on a later page, and where the next page starts stays.
    @Test func theWholeListKeepsThePagesReadPastTheFirst() async throws {
        let transport = PagedListTransport("abcde")
        let model = await onPagedList(transport, status: "all")
        await more(model)
        #expect(shown(model) == "abcd")
        transport.rows.withLock { $0.insert(PagedListTransport.Row(id: "n", status: "running", updated: 2_000), at: 0) }
        try await model.mergeFirstPage()
        #expect(shown(model) == "nabcd")
        #expect(model.listCursor == "d")
        #expect(model.listMore)
    }

    /// The demo's second page is its one finished row: another state's list has none to promise.
    @Test func onlyTheDemosEndedListHasASecondPage() async {
        let model = makeApp()
        await signedInOnA(model)
        model.listDisplay(status: "idle")
        await model.settle()
        #expect(model.listMore)
        model.listDisplay(status: "running")
        await model.settle()
        #expect(!model.listMore)
    }

    @Test func theLiveConnectionReadsStateFreshOnEntering() async {
        let world = DemoWorld()
        let model = makeApp(world: world)
        await signedInOnA(model)
        model.open(model.chats[0])
        await model.settle()
        #expect(model.conversation.key?.chat == "demo")
        // The fresh read comes first; the stream is not available on this fake service, so it waits to reconnect.
        for _ in 0..<50 where world.stateReads.isEmpty { await Task.yield() }
        #expect(world.stateReads.first?.fresh == true)
    }

    @Test func theDemoSavesNothingAndHasNoLiveStream() async {
        let store = LocalStore(folder: temporaryFolder())
        let model = makeApp(store: store)
        model.openDemo()
        #expect(model.screen == .login && model.fixture)
        model.login(name: "x", password: "y")
        await model.settle()
        model.select(model.account!.devices[0])
        await model.settle()
        model.open(model.chats[0])
        await model.settle()
        await model.conversation.settle()
        #expect(model.conversation.connection == "本地固定场景")
        #expect(await store.place() == Place())
    }

    @Test func leavingTheDemoStartsOnTheSavedService() async {
        let model = makeApp()
        model.openDemo()
        model.back()
        await model.settle()
        #expect(!model.fixture && model.screen == .login && model.scope.isEmpty)
    }

    @Test func aLongMessageCopiesWholeAndStaysWholeOnceOpened() async {
        let model = AppModel(services: AppServices(store: LocalStore(folder: temporaryFolder()), vault: MemoryCookieVault(),
                                                   transport: CutMessageTransport(), demo: { DemoTransport() }, pacer: IdlePacer(),
                                                   newScope: { "scope-1" }))
        await signedInOnA(model)
        model.open(model.chats.first { $0.id == "demo" }!)
        await model.settle()
        let cut = model.messages.first { $0.id == "long" }!
        #expect(cut.truncated && cut.length == 4 && cut.text == "前半")
        // 复制 reads the whole words and leaves the bubble as it was.
        var copied: String?
        model.whole(cut) { copied = $0.text }
        await model.settle()
        #expect(copied == "前半后半")
        #expect(model.messages.first { $0.id == "long" }?.truncated == true)
        // 展开全文 opens it, and reading the page again keeps it open.
        model.expand(cut)
        await model.settle()
        #expect(model.messages.first { $0.id == "long" }?.text == "前半后半")
        model.latest()
        await model.settle()
        let again = model.messages.first { $0.id == "long" }
        #expect(again?.text == "前半后半" && again?.truncated == false)
    }
}
