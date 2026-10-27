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
