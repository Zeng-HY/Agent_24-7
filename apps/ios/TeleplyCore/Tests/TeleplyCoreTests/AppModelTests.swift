import Foundation
import Testing
@testable import TeleplyDemo
import TeleplyModel
@testable import TeleplyState

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
}
