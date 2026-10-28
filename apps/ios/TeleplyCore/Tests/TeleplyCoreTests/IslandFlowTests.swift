import Foundation
import Testing
import TeleplyIsland
@testable import TeleplyDemo
import TeleplyModel
@testable import TeleplyState

/// The phone's side of the island as a test sets it: whether the system allows one, the token Apple gives, and
/// what the app asked of it.
@MainActor
final class FakeIsland: IslandPlatform {
    var allowed = true
    var tokenValue: String? = String(repeating: "ab", count: 32)
    var starts: [(IslandIdentity, IslandState)] = []
    var updates = 0
    var ends = 0

    func enabled() async -> Bool { allowed }
    var environment: String { "production" }

    func start(_ identity: IslandIdentity, _ state: IslandState) async throws -> IslandRef {
        guard allowed else { throw IslandFailure("系统里关了遥应的实时活动：到系统设置 → 遥应 里打开。") }
        starts.append((identity, state))
        return IslandRef(raw: "island-\(starts.count)")
    }

    func token(_ ref: IslandRef, seconds: Double) async -> String? { tokenValue }
    func update(_ ref: IslandRef, _ state: IslandState) async { updates += 1 }
    func end(_ ref: IslandRef, _ state: IslandState, dismissIn: TimeInterval) async { ends += 1 }
    func endAll() async {}
}

@MainActor
func makeIslandApp(island: FakeIsland, transport: any RelayTransport = DemoTransport(), world: DemoWorld = DemoWorld()) -> AppModel {
    AppModel(services: AppServices(store: LocalStore(folder: temporaryFolder()), vault: MemoryCookieVault(), transport: transport,
                                   demo: { DemoTransport(world: world) }, pacer: IdlePacer(), newScope: { "scope-1" },
                                   push: FakePush(), island: island))
}

/// 开发者选项's 试一下灵动岛 and 让中转改一下 (handoff 阶段零), and the requests behind them.
@MainActor
struct IslandFlowTests {
    let token = String(repeating: "ab", count: 32)

    @Test func theIslandRequestsCarryTheIdsAndTheStateOnly() async throws {
        let transport = RecordingTransport { _ in .json(#"{"ok":true,"text":"中转推了一条，看看岛"}"#) }
        let client = RelayClient(origin: .default, transport: transport)
        let device = String(repeating: "a", count: 32), chat = "chat-1"
        let registration = IslandRegistration(token: token, device: device, app: "claude", chat: chat,
                                              environment: "production", state: "working", since: 1761629940, turn: 1761629940)
        try await client.islandRegister(registration)
        try await client.islandRegister(.unregister(token: token, device: device, app: "claude", chat: chat,
                                                    environment: "production"))
        try await client.islandStartToken(IslandStartToken(token: token, environment: "production"))
        #expect(try await client.islandTest(device: device, app: "claude", chat: chat) == "中转推了一条，看看岛")
        let sent = await transport.log.items
        #expect(sent.map(\.url.path) == ["/account/push/activity", "/account/push/activity", "/account/push/start-token",
                                         "/account/push/island-test"])
        let first = try JSONValue.parse(sent[0].body ?? Data())
        #expect(first["op"].string() == "register" && first["token"].string() == token)
        #expect(first["device"].string() == device && first["app"].string() == "claude" && first["chat"].string() == chat)
        #expect(first["state"].string() == "working" && first["since"].int64() == 1761629940 && first["turn"].int64() == 1761629940)
        #expect(!first.has("title") && !first.has("message"))
        let second = try JSONValue.parse(sent[1].body ?? Data())
        #expect(second["op"].string() == "unregister" && !second.has("state") && !second.has("since"))
        let test = try JSONValue.parse(sent[3].body ?? Data())
        #expect(test["device"].string() == device && !test.has("token"))
    }

    @Test func tappingTheIslandOpensOnlyItsOwnAddress() throws {
        let device = String(repeating: "a", count: 32)
        let url = try #require(IslandURL.open(device: device, app: "claude", chat: "x 1"))
        #expect(PushTarget(url: url) == PushTarget(device: device, app: "claude", chat: "x 1"))
        #expect(PushTarget(url: URL(string: "https://example.com/open?d=\(device)&a=claude&c=x")!) == nil)
        #expect(PushTarget(url: URL(string: "teleply://list?d=\(device)")!) == nil)
        #expect(PushTarget(url: URL(string: "teleply://open?d=bad&a=claude&c=x")!) == nil)
        #expect(PushTarget(url: URL(string: "teleply://open?d=\(device)&a=mail&c=x")!) == nil)
    }

    @Test func theDemoStartsAnIslandOnThisPhoneOnly() async {
        let island = FakeIsland()
        let model = makeIslandApp(island: island)
        model.start()
        await model.settle()
        await model.islandDemo()
        #expect(island.starts.count == 1)
        #expect(island.starts.first?.0.chat == AppModel.islandDemoChat)
        #expect(island.starts.first?.0.title == "试一下灵动岛")
        #expect(island.starts.first?.1.status == .working)
        #expect(model.island.demo != nil)
        #expect(model.island.note?.contains("岛开了") == true)
        await model.islandDemoEnd()
        #expect(island.ends == 1 && model.island.demo == nil)
    }

    @Test func withLiveActivitiesOffTheDemoSaysWhereToTurnThemOn() async {
        let island = FakeIsland()
        island.allowed = false
        let model = makeIslandApp(island: island)
        model.start()
        await model.settle()
        await model.islandDemo()
        #expect(island.starts.isEmpty)
        #expect(model.island.note?.contains("系统设置") == true)
    }

    @Test func theRelayTestStartsTheIslandRegistersItsTokenAndAsksTheRelay() async throws {
        let world = DemoWorld(), watched = WatchedTransport(world: world), island = FakeIsland()
        let model = makeIslandApp(island: island, transport: watched, world: world)
        model.start()
        await model.settle()
        model.login(name: "账号", password: "密码")
        await model.settle()
        // open a conversation on that computer: the island names its computer
        model.openNotification(try #require(PushTarget(device: DemoData.computerA, app: "codex", chat: "demo")))
        await model.settle()
        await model.islandRelayTest()
        let items = await watched.log.items
        let paths = items.map(\.url.path)
        #expect(paths.contains("/account/push/activity"))
        #expect(paths.contains("/account/push/island-test"))
        #expect(model.island.note?.contains("中转推了一条") == true)
        let registration = try #require(items.first { $0.url.path.hasSuffix("/activity") })
        let body = try JSONValue.parse(registration.body ?? Data())
        #expect(body["device"].string() == DemoData.computerA)
        #expect(body["chat"].string() == AppModel.islandDemoChat)
        #expect(body["token"].string() == token)
    }

    @Test func withoutAComputerTheRelayTestSaysWhatToDo() async {
        let island = FakeIsland()
        let model = makeIslandApp(island: island)
        model.start()
        await model.settle()
        await model.islandRelayTest()
        #expect(island.starts.isEmpty)
        #expect(model.island.note?.contains("电脑") == true)
    }
}
