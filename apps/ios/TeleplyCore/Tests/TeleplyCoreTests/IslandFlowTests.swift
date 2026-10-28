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
    var wantedValue = false
    var tokenValue: String? = String(repeating: "ab", count: 32)
    var startTokenValue: String? = String(repeating: "cd", count: 32)
    var starts: [(IslandIdentity, IslandState)] = []
    var snapshots: [IslandSnapshot] = []
    var updates = 0
    var ends = 0
    var endAlls = 0
    var handler: (@MainActor @Sendable (IslandEvent) -> Void)?

    func enabled() async -> Bool { allowed }
    var environment: String { "production" }
    func wanted() -> Bool { wantedValue }
    func setWanted(_ on: Bool) { wantedValue = on }

    func start(_ identity: IslandIdentity, _ state: IslandState) async throws -> IslandRef {
        guard allowed else { throw IslandFailure("系统里关了遥应的实时活动：到系统设置 → 遥应 里打开。") }
        starts.append((identity, state))
        let ref = IslandRef(raw: "island-\(starts.count)")
        snapshots.append(IslandSnapshot(ref: ref, identity: identity, state: state))
        return ref
    }

    func token(_ ref: IslandRef, seconds: Double) async -> String? { tokenValue }
    func startToken(seconds: Double) async -> String? { startTokenValue }
    func update(_ ref: IslandRef, _ state: IslandState) async {
        updates += 1
        if let index = snapshots.firstIndex(where: { $0.ref == ref }) { snapshots[index].state = state }
    }
    func end(_ ref: IslandRef, _ state: IslandState, dismissIn: TimeInterval) async {
        ends += 1
        snapshots.removeAll { $0.ref == ref }
    }
    func endAll() async {
        endAlls += 1
        snapshots.removeAll()
    }

    func observe(_ handler: @escaping @MainActor @Sendable (IslandEvent) -> Void) { self.handler = handler }
    func running() async -> [IslandSnapshot] { snapshots }
    func fire(_ event: IslandEvent) { handler?(event) }
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
        #expect(first["title"].string() == "" && !first.has("message"))
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

    // MARK: 阶段一：真实对话的岛

    private func signedIn(_ world: DemoWorld, island: FakeIsland, transport: WatchedTransport) async -> AppModel {
        let model = makeIslandApp(island: island, transport: transport, world: world)
        model.start()
        await model.settle()
        model.login(name: "账号", password: "密码")
        await model.settle()
        model.openNotification(PushTarget(device: DemoData.computerA, app: "codex", chat: "demo")!)
        await model.settle()
        island.wantedValue = true
        await model.islandLaunch()
        return model
    }

    @Test func aSendTheComputerTookStartsItsIslandAndRegistersTheToken() async {
        let world = DemoWorld(), watched = WatchedTransport(world: world), island = FakeIsland()
        let model = await signedIn(world, island: island, transport: watched)
        let key = ChatKey(scope: model.scope, device: DemoData.computerA, app: "codex", chat: "demo")
        let record = Submission(request: "r1", key: key, text: "跑一下", action: "send", turn: "t1", body: "{}",
                                created: Int64(Date().timeIntervalSince1970 * 1000))
        model.islandSendStarted(record)
        for _ in 0..<100 where island.starts.isEmpty { try? await Task.sleep(for: .milliseconds(20)) }
        #expect(island.starts.count == 1)
        #expect(island.starts.first?.0.chat == "demo" && island.starts.first?.0.app == "codex")
        for _ in 0..<150 where !model.island.live.values.contains(where: { $0.registered }) {
            try? await Task.sleep(for: .milliseconds(20))
        }
        #expect(model.island.live.values.contains { $0.registered })
        let paths = await watched.log.items.map(\.url.path)
        #expect(paths.contains("/account/push/activity"))
    }

    @Test func launchRegistersThePushToStartToken() async throws {
        let world = DemoWorld(), watched = WatchedTransport(world: world), island = FakeIsland()
        _ = await signedIn(world, island: island, transport: watched)
        let items = await watched.log.items
        let started = try #require(items.first { $0.url.path.hasSuffix("/start-token") })
        let body = try JSONValue.parse(started.body ?? Data())
        #expect(body["token"].string() == String(repeating: "cd", count: 32))
    }

    @Test func anIslandDismissedOnTheLockScreenIsUnregistered() async throws {
        let world = DemoWorld(), watched = WatchedTransport(world: world), island = FakeIsland()
        let model = await signedIn(world, island: island, transport: watched)
        let identity = IslandIdentity(device: DemoData.computerA, app: "claude", chat: "c9", computer: "测试电脑 A", title: "")
        let ref = IslandRef(raw: "gone-1")
        island.fire(.started(ref, identity, IslandState(status: .working, since: 1, turn: 1)))
        for _ in 0..<150 where !model.island.live.values.contains(where: { $0.registered }) {
            try? await Task.sleep(for: .milliseconds(20))
        }
        island.fire(.dismissed(ref))
        for _ in 0..<100 where model.island.live[ref.raw] != nil { try? await Task.sleep(for: .milliseconds(20)) }
        #expect(model.island.live[ref.raw] == nil)
        var bodies: [JSONValue] = []
        for _ in 0..<100 {
            let items = await watched.log.items.filter { $0.url.path.hasSuffix("/activity") }
            bodies = items.compactMap { try? JSONValue.parse($0.body ?? Data()) }
            if bodies.contains(where: { $0["op"].string() == "unregister" }) { break }
            try? await Task.sleep(for: .milliseconds(20))
        }
        #expect(bodies.contains { $0["op"].string() == "unregister" && $0["chat"].string() == "c9" })
    }

    @Test func atMostThreeIslandsAndAFinishedOneMakesWay() async {
        let world = DemoWorld(), watched = WatchedTransport(world: world), island = FakeIsland()
        let model = await signedIn(world, island: island, transport: watched)
        func record(_ chat: String) -> Submission {
            let key = ChatKey(scope: model.scope, device: DemoData.computerA, app: "codex", chat: chat)
            return Submission(request: "r-" + chat, key: key, text: "跑一下", action: "send", turn: "t",
                              body: "{}", created: Int64(Date().timeIntervalSince1970 * 1000))
        }
        for (index, chat) in ["c1", "c2", "c3"].enumerated() {
            model.islandSendStarted(record(chat))
            for _ in 0..<100 where island.starts.count < index + 1 { try? await Task.sleep(for: .milliseconds(20)) }
        }
        #expect(island.starts.count == 3)
        #expect(model.island.live.count == 3)
        model.islandSendStarted(record("c4"))  // three running: this one stays a notification
        try? await Task.sleep(for: .milliseconds(100))
        #expect(island.starts.count == 3)
        if let key = model.island.live.keys.first, var track = model.island.live[key] {
            track.state = IslandState(status: .done, since: 1, turn: 1)
            model.island.live[key] = track
        }
        model.islandSendStarted(record("c4"))  // a finished one makes way
        for _ in 0..<100 where island.starts.count < 4 { try? await Task.sleep(for: .milliseconds(20)) }
        #expect(island.starts.count == 4)
        #expect(island.ends >= 1)
    }

    @Test func aRemoteStartedIslandIsPickedUpAndItsTokenRegistered() async {
        let world = DemoWorld(), watched = WatchedTransport(world: world), island = FakeIsland()
        let model = await signedIn(world, island: island, transport: watched)
        let identity = IslandIdentity(device: DemoData.computerA, app: "claude", chat: "c9", computer: "测试电脑 A", title: "")
        island.fire(.started(IslandRef(raw: "remote-1"), identity, IslandState(status: .working, since: 1, turn: 1)))
        for _ in 0..<150 where !model.island.live.values.contains(where: { $0.registered }) {
            try? await Task.sleep(for: .milliseconds(20))
        }
        #expect(model.island.live["remote-1"] != nil)
        #expect(model.island.live.values.contains { $0.registered })
        let paths = await watched.log.items.map(\.url.path)
        #expect(paths.contains("/account/push/activity"))
    }

    @Test func turningTheSwitchOffEndsEveryIsland() async throws {
        let world = DemoWorld(), watched = WatchedTransport(world: world), island = FakeIsland()
        let model = await signedIn(world, island: island, transport: watched)
        model.island.live["one"] = IslandTrack(identity: IslandIdentity(device: DemoData.computerA, app: "codex", chat: "demo",
                                                                        computer: "测试电脑 A", title: "原生阅读示例"),
                                               state: IslandState(status: .working, since: 1, turn: 1))
        await model.islandSetWanted(false)
        #expect(island.endAlls == 1)
        #expect(model.island.live.isEmpty)
        #expect(!island.wantedValue && !model.island.wanted)
    }

    @Test func anIslandFinishedLongAgoIsEndedWhenTheAppComesBack() async {
        let world = DemoWorld(), watched = WatchedTransport(world: world), island = FakeIsland()
        let model = await signedIn(world, island: island, transport: watched)
        let identity = IslandIdentity(device: DemoData.computerA, app: "codex", chat: "demo", computer: "测试电脑 A", title: "")
        island.snapshots = [IslandSnapshot(ref: IslandRef(raw: "old"), identity: identity,
                                           state: IslandState(status: .done, since: 1, turn: 1))]
        await model.islandReconcile()
        #expect(island.ends == 1)
        #expect(model.island.live["old"] == nil)
    }
}
