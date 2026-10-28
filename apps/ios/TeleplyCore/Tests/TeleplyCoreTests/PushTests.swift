import Foundation
import Testing
@testable import TeleplyDemo
import TeleplyModel
@testable import TeleplyState

/// The system's side of 遥应通知 as a test sets it: what it allows, what the person answers, the token it gives.
@MainActor
final class FakePush: PushPlatform {
    var allowed = PushPermission.notAsked
    var answer = true
    var registered = 0
    var on = false
    /// What iOS does when asked for a token (the test hands one to the model).
    var deliver: (() -> Void)?

    func permission() async -> PushPermission { allowed }

    func ask() async -> Bool {
        allowed = answer ? .allowed : .denied
        return answer
    }

    func register() {
        registered += 1
        deliver?()
    }

    var environment: String { "production" }
    var label: String { "iPhone" }
    var version: String { "0.5.0" }
    func wanted() -> Bool { on }
    func setWanted(_ value: Bool) { on = value }
}

@MainActor
func makePushApp(world: DemoWorld = DemoWorld(), push: FakePush) -> AppModel {
    AppModel(services: AppServices(store: LocalStore(folder: temporaryFolder()), vault: MemoryCookieVault(), transport: DemoTransport(world: world),
                                   demo: { DemoTransport() }, pacer: IdlePacer(), newScope: { "scope-1" }, push: push))
}

/// What a notification of 遥应's own carries, and how the phone asks the service about it (relay_push.py).
struct PushRequestTests {
    let device = String(repeating: "a", count: 32)
    let token = String(repeating: "ab", count: 32)

    @Test func aNotificationNamesAComputerAnAppAndAConversationOnly() {
        let info: [AnyHashable: Any] = ["aps": ["alert": ["title": "Codex · 测试电脑 A", "body": "有个对话好了"]],
                                        "teleply": ["d": device, "a": "codex", "c": "x1"]]
        #expect(PushTarget(userInfo: info) == PushTarget(device: device, app: "codex", chat: "x1"))
        #expect(PushTarget(userInfo: ["aps": ["alert": ["title": "遥应", "body": "试推一条：通知是好的"]]]) == nil)
        #expect(PushTarget(userInfo: ["teleply": ["d": "not-a-computer", "a": "codex", "c": "x1"]]) == nil)
        #expect(PushTarget(userInfo: ["teleply": ["d": device, "a": "mail", "c": "x1"]]) == nil)
        #expect(PushTarget(device: device, app: "claude", chat: "") == nil)
    }

    @Test func theTokenTravelsInPostBodiesNeverInAnAddress() async throws {
        let transport = RecordingTransport { request in
            request.url.path.hasSuffix("/state") ? .json(#"{"available":true,"registered":true,"phones":2}"#)
                : .json(#"{"ok":true,"text":"刚推了一条，看看通知"}"#)
        }
        let client = RelayClient(origin: .default, transport: transport)
        #expect(try await client.pushState(token: token) == PushStatus(available: true, registered: true, phones: 2))
        try await client.pushRegister(token: token, environment: "production", label: "iPhone", version: "0.5.0")
        try await client.pushUnregister(token: token)
        #expect(try await client.pushTest(token: token) == "刚推了一条，看看通知")
        let sent = await transport.log.items
        #expect(sent.map(\.url.path) == ["/account/push/state", "/account/push/register", "/account/push/unregister", "/account/push/test"])
        #expect(sent.allSatisfy { $0.method == .post && $0.headers["Origin"] != nil && !$0.url.absoluteString.contains(token) })
        let register = try JSONValue.parse(sent[1].body ?? Data())
        #expect(register["token"].string() == token && register["platform"].string() == "ios" && register["environment"].string() == "production")
    }
}

/// 设置 → 手机通知 → 遥应通知 and a tapped notification, on the demo service.
@MainActor
struct PushFlowTests {
    let token = String(repeating: "ab", count: 32)

    func signedIn(_ world: DemoWorld = DemoWorld(), push: FakePush) async -> AppModel {
        let model = makePushApp(world: world, push: push)
        model.start()
        await model.settle()
        model.login(name: "账号", password: "密码")
        await model.settle()
        return model
    }

    func tokens(_ world: DemoWorld) -> Set<String> {
        world.state.withLock { $0.pushTokens }
    }

    /// The switch (0.5.6): on asks the system and has the service keep the phone; off has it forget the phone. Neither
    /// leaves words behind when it works.
    @Test func turnedOnTheSystemAsksAndTheServiceKeepsThePhoneUntilTurnedOff() async {
        let world = DemoWorld(), push = FakePush()
        let model = await signedIn(world, push: push)
        push.deliver = { [token] in model.pushToken(token) }
        await model.pushRefresh()
        #expect(model.push.phase == .off)
        await model.pushTurnOn()
        #expect(push.registered == 1 && push.on)
        #expect(model.push.phase == .on && model.push.note == nil)
        #expect(tokens(world) == [token])
        await model.pushRefresh()
        #expect(model.push.phase == .on)
        await model.pushTurnOff()
        #expect(model.push.phase == .off && !push.on)
        #expect(model.push.note == nil)
        #expect(tokens(world).isEmpty)
    }

    @Test func refusedInTheSystemItStaysOffAndSaysWhere() async {
        let push = FakePush()
        push.answer = false
        let model = await signedIn(push: push)
        await model.pushTurnOn()
        #expect(model.push.phase == .denied && !push.on && push.registered == 0)
        #expect(model.push.note?.contains("系统设置") == true)
        await model.pushRefresh()
        #expect(model.push.phase == .denied)
    }

    @Test func aServiceWithoutAKeySaysSo() async {
        let world = DemoWorld()
        world.state.withLock { $0.pushAvailable = false }
        let push = FakePush()
        let model = await signedIn(world, push: push)
        push.deliver = { [token] in model.pushToken(token) }
        await model.pushRefresh()
        #expect(model.push.phase == .unavailable)
        await model.pushTurnOn()
        #expect(model.push.phase == .unavailable)
        #expect(model.push.note == "服务器还没开通遥应通知")
    }

    @Test func noTokenFromIOSIsSaid() async {
        let push = FakePush()
        let model = await signedIn(push: push)
        push.deliver = { model.pushTokenFailed("没有网络") }
        await model.pushTurnOn()
        #expect(model.push.note == "没拿到这部 iPhone 的推送令牌：没有网络")
        #expect(model.push.phase != .on)
    }

    @Test func signingOutForgetsThePhoneAndSigningInAgainDoesNotBringItBack() async {
        let world = DemoWorld(), push = FakePush()
        let model = await signedIn(world, push: push)
        push.deliver = { [token] in model.pushToken(token) }
        await model.pushTurnOn()
        #expect(tokens(world) == [token])
        model.logout()
        await model.settle()
        #expect(tokens(world).isEmpty && !push.on)
        model.login(name: "账号", password: "密码")
        await model.settle()
        model.pushSync()
        try? await Task.sleep(for: .milliseconds(100))
        #expect(tokens(world).isEmpty)
    }

    @Test func aTokenAtLaunchIsKeptForTheAccountWhileWanted() async {
        let world = DemoWorld(), push = FakePush()
        push.on = true
        push.allowed = .allowed
        let model = await signedIn(world, push: push)
        model.pushToken(token)  // iOS answers the launch's request
        for _ in 0..<100 where tokens(world).isEmpty { try? await Task.sleep(for: .milliseconds(20)) }
        #expect(tokens(world) == [token])
        #expect(model.push.phase == .on)
    }

    @Test func aTappedNotificationOpensItsConversationOnItsComputer() async throws {
        let model = await signedIn(push: FakePush())
        #expect(model.screen == .devices)
        let target = try #require(PushTarget(device: DemoData.computerA, app: "codex", chat: "demo"))
        model.openNotification(target)
        await model.settle()
        #expect(model.screen == .reading && model.device?.id == DemoData.computerA && model.app == "codex")
        #expect(model.chat?.id == "demo" && model.chat?.title == "原生阅读示例")
        #expect(!model.messages.isEmpty && model.error == nil)
        #expect(model.isShowing(target))
        model.setForeground(false)
        #expect(!model.isShowing(target))
        model.setForeground(true)
        #expect(!model.isShowing(try #require(PushTarget(device: DemoData.computerA, app: "codex", chat: "other"))))
        let elsewhere = try #require(PushTarget(device: DemoData.computerB, app: "claude", chat: "demo"))
        model.openNotification(elsewhere)  // another computer of the account: it is used now
        await model.settle()
        #expect(model.device?.id == DemoData.computerB && model.app == "claude" && model.chat?.id == "demo")
    }

    @Test func oneTappedWhileTheAppOpensWaitsForTheLaunch() async throws {
        let world = DemoWorld(), store = LocalStore(folder: temporaryFolder()), vault = MemoryCookieVault()
        let services = AppServices(store: store, vault: vault, transport: DemoTransport(world: world), demo: { DemoTransport() },
                                   pacer: IdlePacer(), newScope: { "scope-1" }, push: FakePush())
        let first = AppModel(services: services)
        first.start()
        await first.settle()
        first.login(name: "账号", password: "密码")
        await first.settle()
        // the app is opened again by the tap: the launch restores the sign-in meanwhile
        let model = AppModel(services: services)
        let target = try #require(PushTarget(device: DemoData.computerA, app: "codex", chat: "demo"))
        model.start()
        model.openNotification(target)
        #expect(model.push.waiting == target)
        await model.settle()
        model.resumeNotification()  // RootView, once the launch is done
        await model.settle()
        #expect(model.push.waiting == nil)
        #expect(model.screen == .reading && model.chat?.id == "demo")
    }

    @Test func anotherAccountsComputerOrAnOfflineOneIsSaidAndNothingOpens() async throws {
        let model = await signedIn(push: FakePush())
        model.openNotification(try #require(PushTarget(device: String(repeating: "9", count: 32), app: "codex", chat: "x")))
        await model.settle()
        #expect(model.error == "这条通知来自别的账号的电脑，或者这台电脑已经移除。")
        #expect(model.screen == .devices && model.chat == nil)
        model.openNotification(try #require(PushTarget(device: DemoData.offline, app: "codex", chat: "x")))
        await model.settle()
        #expect(model.error == "电脑已离线，请稍后刷新。")
        #expect(model.chat == nil)
    }

    @Test func signedOutTheTapWaitsForTheSignIn() async throws {
        let model = makePushApp(push: FakePush())
        model.start()
        await model.settle()
        #expect(model.screen == .login)
        let target = try #require(PushTarget(device: DemoData.computerA, app: "codex", chat: "demo"))
        model.openNotification(target)
        #expect(model.push.waiting == target)
        model.login(name: "账号", password: "密码")
        await model.settle()
        model.resumeNotification()
        await model.settle()
        #expect(model.chat?.id == "demo" && model.push.waiting == nil)
    }
}
