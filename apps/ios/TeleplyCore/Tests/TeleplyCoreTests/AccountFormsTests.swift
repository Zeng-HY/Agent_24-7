import Foundation
import Synchronization
import Testing
@testable import TeleplyDemo
import TeleplyIsland
@testable import TeleplyModel
@testable import TeleplyState

/// The relay's email and deletion routes as relay_service.py answers them, around the demo service (which has none):
/// a sign-up or a reset waits for the code 246810, a right one signs in; [State.wait] makes every mail and the deletion
/// answer 429 with retry_after. Every request is kept.
final class MailRelay: RelayTransport, Sendable {
    struct State {
        /// Sign-ups waiting for their code: email → password.
        var signups: [String: String] = [:]
        var resets: Set<String> = []
        var email = "fixture@example.invalid"
        var password = "fixture-password"
        /// Seconds to wait before the next mail or deletion; 0 lets them through.
        var wait = 0
    }

    static let code = "246810"
    let world: DemoWorld
    let demo: DemoTransport
    let log = RequestLog()
    let state = Mutex(State())

    init(world: DemoWorld = DemoWorld()) {
        self.world = world
        demo = DemoTransport(world: world)
    }

    func send(_ request: RelayRequest) async throws -> RelayResponse {
        await log.add(request)
        let body = request.body.flatMap { try? JSONValue.parse($0) } ?? [:]
        let field = { (name: String) in body[name].string() }
        let path = request.url.path
        let limited = ["/account/register", "/account/resend", "/account/forgot", "/account/delete"].contains(path)
        if limited, let wait = state.withLock({ $0.wait > 0 ? $0.wait : nil }) {
            return .json(#"{"error":"请在 \#(wait) 秒后重试","code":"rate_limited","retry_after":\#(wait)}"#, status: 429)
        }
        switch path {
        case "/account/config":
            return .json(#"{"version":"fixture","email_enabled":true}"#)
        case "/account/register":
            guard (12...256).contains(field("password").unicodeScalars.count) else { return Self.refused("密码须为 12 至 256 个字符") }
            state.withLock { $0.signups[field("email").lowercased()] = field("password") }
            return .json(#"{"ok":true,"message":"请查收邮件"}"#)
        case "/account/resend":
            return .json(#"{"ok":true,"message":"请查收邮件"}"#)
        case "/account/verify":
            let email = field("email").lowercased()
            guard let password = state.withLock({ $0.signups[email] }) else { return Self.refused("验证码已失效，请重新发送") }
            guard field("pin") == Self.code else { return Self.refused("验证码不对") }
            state.withLock {
                $0.signups[email] = nil
                $0.email = email
                $0.password = password
            }
            return signedIn()
        case "/account/forgot":
            let email = field("email").lowercased()
            state.withLock { if $0.email == email { $0.resets.insert(email) } }
            return .json(#"{"ok":true,"message":"请查收邮件"}"#)
        case "/account/reset":
            let email = field("email").lowercased()
            guard state.withLock({ $0.resets.contains(email) }) else { return Self.refused("验证码已失效，请重新发送") }
            guard field("pin") == Self.code else { return Self.refused("验证码不对") }
            state.withLock {
                $0.resets.remove(email)
                $0.password = field("password")
            }
            return signedIn()
        case "/account/delete":
            guard world.state.withLock({ $0.signedIn }) else { return .json("{}", status: 401) }
            guard field("password") == state.withLock({ $0.password }) else { return Self.refused("当前密码错误") }
            world.state.withLock {
                $0.signedIn = false
                $0.devices = []
                $0.pushTokens = []
            }
            return RelayResponse(status: 200, headers: ["content-type": "application/json",
                                                        "set-cookie": "__Host-ar_account=; Path=/; Secure; HttpOnly; SameSite=Strict; Max-Age=0"],
                                 body: Data(#"{"ok":true}"#.utf8))
        default:
            return try await demo.send(request)
        }
    }

    private func signedIn() -> RelayResponse {
        world.state.withLock { $0.signedIn = true }
        return RelayResponse(status: 200, headers: ["content-type": "application/json",
                                                    "set-cookie": "__Host-ar_account=mailed; Path=/; Secure; HttpOnly; SameSite=Strict; Max-Age=604800"],
                             body: Data(#"{"ok":true}"#.utf8))
    }

    private static func refused(_ words: String) -> RelayResponse {
        .json(#"{"error":"\#(words)"}"#, status: 400)
    }

    func paths() async -> [String] {
        await log.items.map(\.url.path)
    }
}

extension TestClock {
    var date: Date { Date(timeIntervalSince1970: Double(now) / 1000) }
}

/// 创建账号, 忘记密码 and 删除账号 as requests (relay_service.py account; web relay_account.js).
struct AccountRequestTests {
    @Test func eachFormPostsStringsWithTheOriginOfTheAddressItGoesTo() async throws {
        for origin in [ServiceOrigin.default, .formerDefault] {
            let vault = MemoryCookieVault()
            let transport = RecordingTransport { request in
                guard ["/account/verify", "/account/reset"].contains(request.url.path) else { return .json(#"{"ok":true}"#) }
                return RelayResponse(status: 200, headers: ["set-cookie": "__Host-ar_account=fresh; Path=/; Secure; HttpOnly; Max-Age=604800"],
                                     body: Data(#"{"ok":true}"#.utf8))
            }
            let client = RelayClient(origin: origin, transport: transport, vault: vault)
            try await client.register(email: "new@example.invalid", password: "twelve-chars")
            try await client.resendSignup(email: "new@example.invalid")
            try await client.verify(email: "new@example.invalid", pin: "012345")
            #expect(try vault.read(origin.key)?.value == "fresh")
            try await client.forgot(email: "new@example.invalid")
            try vault.write(origin.key, nil)
            try await client.reset(email: "new@example.invalid", pin: "000111", password: "another-password")
            #expect(try vault.read(origin.key)?.value == "fresh")
            try await client.deleteAccount(password: "another-password")
            #expect(try vault.read(origin.key) == nil)
            let sent = await transport.log.items
            #expect(sent.map(\.url.path) == ["/account/register", "/account/resend", "/account/verify", "/account/forgot", "/account/reset", "/account/delete"])
            for request in sent {
                #expect(request.method == .post && request.url.host == String(origin.header.dropFirst("https://".count)))
                #expect(request.headers["Origin"] == origin.header && request.headers["Content-Type"] == "application/json; charset=utf-8")
                let body = try JSONValue.parse(try #require(request.body))
                #expect(body.isObject && body.object.values.allSatisfy { if case .string = $0 { true } else { false } })
            }
            #expect(sent.map { request in (try? JSONValue.parse(request.body ?? Data()))?.object.keys.sorted() ?? [] } == [
                ["email", "password"], ["email"], ["email", "pin"], ["email"], ["email", "password", "pin"], ["password"],
            ])
            // The code goes as text, its leading zero kept.
            #expect(try JSONValue.parse(try #require(sent[2].body))["pin"] == "012345")
            // The sign-in that went with 验证 is sent back on the next request.
            #expect(sent[3].headers["Cookie"] == "__Host-ar_account=fresh")
        }
    }

    @Test func aRefusalKeepsTheRelaysWordsAndALimitItsWait() async {
        let refused = RelayClient(origin: .default, transport: RecordingTransport { _ in .json(#"{"error":"当前密码错误"}"#, status: 400) })
        await #expect(throws: ServiceFailure(status: 400, detail: "当前密码错误")) { try await refused.deleteAccount(password: "x") }
        #expect(ServiceFailure(status: 400, detail: "当前密码错误").message == "当前密码错误")
        let limited = RelayClient(origin: .default, transport: RecordingTransport { _ in
            .json(#"{"error":"请在 42 秒后重试","code":"rate_limited","retry_after":42}"#, status: 429)
        })
        do {
            try await limited.resendSignup(email: "new@example.invalid")
            Issue.record("a limited resend should fail")
        } catch let failure as ServiceFailure {
            #expect(failure.status == 429 && failure.retryAfter == 42 && failure.code == "rate_limited")
            #expect(failure.message == "请在 42 秒后重试")
        } catch {
            Issue.record("unexpected \(error)")
        }
        #expect(ServiceFailure(status: 409, body: Data(#"{"code":"device_offline"}"#.utf8)).retryAfter == 0)
    }

    @Test func aDeletionTheRelayRefusesKeepsTheSignIn() async throws {
        let vault = MemoryCookieVault()
        try vault.write(ServiceOrigin.default.key, SessionCookie(value: "kept", expires: nil))
        let client = RelayClient(origin: .default, transport: RecordingTransport { _ in .json(#"{"error":"当前密码错误"}"#, status: 400) }, vault: vault)
        _ = try? await client.deleteAccount(password: "wrong")
        #expect(try vault.read(ServiceOrigin.default.key)?.value == "kept")
    }

    @Test func aBodyTheRelayWouldRefuseIsNotSent() async {
        let transport = RecordingTransport { _ in .json(#"{"ok":true}"#) }
        let client = RelayClient(origin: .default, transport: transport)
        await #expect(throws: ReadFailure("填的内容太长了，请检查后重试。")) {
            try await client.deleteAccount(password: String(repeating: "x", count: 9_000))
        }
        #expect(await transport.log.items.isEmpty)
    }

    @Test func theRelaysOwnChecksComeFirst() throws {
        #expect(try AccountInput.email("  New@Example.invalid ") == "New@Example.invalid")
        #expect(try AccountInput.email("a@b.c") == "a@b.c")
        #expect(try AccountInput.email("a@b..c") == "a@b..c")
        for bad in ["", "plain", "a@b", "a@.c", "a@b.", "@b.c", "a@@b.c", "a b@c.d", "a@b c.d", "<a>@b.c", "a@b.c@d.e",
                    String(repeating: "a", count: 250) + "@b.cd"] {
            #expect(throws: ReadFailure("请输入有效的邮箱地址")) { try AccountInput.email(bad) }
        }
        #expect(throws: ReadFailure("密码须为 12 至 256 个字符")) { try AccountInput.newPassword(String(repeating: "x", count: 11)) }
        try AccountInput.newPassword(String(repeating: "x", count: 12))
        try AccountInput.newPassword(String(repeating: "x", count: 256))
        #expect(throws: ReadFailure("密码须为 12 至 256 个字符")) { try AccountInput.newPassword(String(repeating: "x", count: 257)) }
        // Counted as the relay counts (Python len): six two-scalar flags are twelve.
        try AccountInput.newPassword(String(repeating: "🇨🇳", count: 6))
        #expect(AccountInput.code("12 34-5678") == "123456")
        #expect(AccountInput.code("你的验证码是 246810。") == "246810")
        #expect(AccountInput.code("１２３") == "")
        #expect(AccountInput.code("") == "")
    }

    @Test func theRelaysWaitIsReadFromItsWords() {
        #expect(Hints.wait("请在 30 秒后重试") == 30)
        #expect(Hints.wait("请在 1 秒后重试") == 1)
        #expect(Hints.wait("请在 秒后重试") == nil)
        #expect(Hints.wait("当前密码错误") == nil)
    }
}

/// The same on 登录 and 设置 → 账号, with the relay's answers (MailRelay) around the demo service.
@MainActor
struct AccountFlowTests {
    let clock = TestClock()

    func app(_ relay: MailRelay, vault: MemoryCookieVault = MemoryCookieVault(), store: LocalStore = LocalStore(folder: temporaryFolder()),
             push: any PushPlatform = NoPush(), island: any IslandPlatform = NoIsland()) -> AppModel {
        let clock = clock
        return AppModel(services: AppServices(store: store, vault: vault, transport: relay, demo: { DemoTransport() }, pacer: IdlePacer(),
                                              newScope: { "scope-1" }, now: { clock.now }, push: push, island: island))
    }

    /// Waits for 重新发送, which runs beside the page's own work.
    func resent(_ model: AppModel) async {
        for _ in 0..<500 where model.forms.resending { try? await Task.sleep(for: .milliseconds(10)) }
    }

    @Test func signingUpTakesTheMailedCodeAndSignsIn() async throws {
        let relay = MailRelay(), vault = MemoryCookieVault()
        let model = app(relay, vault: vault)
        model.start()
        await model.settle()
        #expect(model.screen == .login && model.emailEnabled && model.forms.mode == .login)
        model.showForm(.register)
        model.register(email: " new@example.invalid ", password: "twelve-chars")
        await model.settle()
        #expect(model.forms.mode == .verify && model.forms.email == "new@example.invalid")
        #expect(model.forms.said == "验证码已发送" && model.error == nil && model.screen == .login)
        // Digits only, six at most; the sixth sends the code by itself.
        model.enterCode("24 68")
        #expect(model.forms.code == "2468" && !model.busy)
        model.enterCode("2468101")
        await model.settle()
        #expect(model.screen == .devices && model.account?.devices.count == 3)
        #expect(model.forms.mode == .login && model.forms.code.isEmpty && model.forms.said == nil)
        #expect(try vault.read(ServiceOrigin.default.key)?.value == "mailed")
        #expect(await relay.paths() == ["/account/config", "/account/state", "/account/register", "/account/verify", "/account/state"])
        let sent = await relay.log.items
        #expect(try JSONValue.parse(try #require(sent[2].body)) == ["email": "new@example.invalid", "password": "twelve-chars"])
        #expect(try JSONValue.parse(try #require(sent[3].body)) == ["email": "new@example.invalid", "pin": "246810"])
    }

    @Test func aWrongCodeIsSaidAndClearedForTheNextTry() async {
        let relay = MailRelay()
        let model = app(relay)
        model.start()
        await model.settle()
        model.showForm(.register)
        model.register(email: "new@example.invalid", password: "twelve-chars")
        await model.settle()
        model.enterCode("111111")
        await model.settle()
        #expect(model.error == "验证码不对" && model.forms.code.isEmpty)
        #expect(model.forms.mode == .verify && model.screen == .login && model.account == nil)
        model.enterCode(MailRelay.code)
        await model.settle()
        #expect(model.screen == .devices && model.error == nil)
    }

    @Test func theFormsCheckFirstAndSpendNoMail() async {
        let relay = MailRelay()
        let model = app(relay)
        model.start()
        await model.settle()
        model.showForm(.register)
        model.register(email: "not-an-address", password: "twelve-chars")
        await model.settle()
        #expect(model.error == "请输入有效的邮箱地址" && model.forms.mode == .register)
        model.register(email: "new@example.invalid", password: "short")
        await model.settle()
        #expect(model.error == "密码须为 12 至 256 个字符" && model.forms.mode == .register)
        model.showForm(.forgot)
        model.forgot(email: "")
        await model.settle()
        #expect(model.error == "请输入有效的邮箱地址")
        #expect(await relay.paths() == ["/account/config", "/account/state"])
    }

    @Test func resendCountsDownWhileTheRelaySaysToWait() async {
        let relay = MailRelay()
        let model = app(relay)
        model.start()
        await model.settle()
        model.showForm(.register)
        model.register(email: "new@example.invalid", password: "twelve-chars")
        await model.settle()
        relay.state.withLock { $0.wait = 30 }
        model.resend()
        await resent(model)
        #expect(model.error == "请在 30 秒后重试" && model.forms.said == nil)
        #expect(model.forms.resendWait(at: clock.date) == 30)
        #expect(model.forms.resendWait(at: clock.date.addingTimeInterval(29.5)) == 1)
        // Pressed again while it counts: nothing goes out.
        model.resend()
        #expect(!model.forms.resending)
        #expect(await relay.paths().filter { $0 == "/account/resend" }.count == 1)
        clock.advance(30_000)
        relay.state.withLock { $0.wait = 0 }
        #expect(model.forms.resendWait(at: clock.date) == 0)
        model.enterCode("12")
        model.resend()
        await resent(model)
        #expect(model.forms.said == "已重新发送" && model.error == nil && model.forms.code.isEmpty)
        #expect(await relay.paths().filter { $0 == "/account/resend" }.count == 2)
        // The relay's wait is kept to 15 minutes at most, as on the web.
        relay.state.withLock { $0.wait = 86_400 }
        model.resend()
        await resent(model)
        #expect(model.forms.resendWait(at: clock.date) == 900)
    }

    @Test func aForgottenPasswordIsResetWithTheCodeAndSaysSo() async throws {
        let relay = MailRelay(), vault = MemoryCookieVault()
        let model = app(relay, vault: vault)
        model.start()
        await model.settle()
        model.showForm(.forgot)
        model.forgot(email: "Fixture@example.invalid")
        await model.settle()
        #expect(model.forms.mode == .reset && model.forms.said == "请查收邮件")
        // Six digits do not send themselves here: the new password is still to come.
        model.enterCode(MailRelay.code)
        await model.settle()
        #expect(!(await relay.paths()).contains("/account/reset"))
        model.resetPassword(password: "short")
        await model.settle()
        #expect(model.error == "密码须为 12 至 256 个字符" && model.forms.code == MailRelay.code)
        #expect(!(await relay.paths()).contains("/account/reset"))
        // 重新发送 here asks for the code again the way 发送验证码 did.
        model.resend()
        await resent(model)
        #expect(await relay.paths().filter { $0 == "/account/forgot" }.count == 2 && model.forms.said == "已重新发送")
        model.enterCode(MailRelay.code)
        model.resetPassword(password: "a-new-long-password")
        await model.settle()
        #expect(model.screen == .devices && model.forms.said == "密码已更新" && model.error == nil)
        #expect(try vault.read(ServiceOrigin.default.key)?.value == "mailed")
        #expect(relay.state.withLock { $0.password } == "a-new-long-password")
        // The next thing done on 我的电脑 takes the line away.
        model.showComputers()
        await model.settle()
        #expect(model.forms.said == nil)
    }

    @Test func anotherFormClearsWhatWasSaidAndTheCode() async {
        let model = app(MailRelay())
        model.start()
        await model.settle()
        model.showForm(.register)
        model.register(email: "new@example.invalid", password: "twelve-chars")
        await model.settle()
        model.enterCode("12")
        model.showForm(.login)
        #expect(model.forms.mode == .login && model.forms.said == nil && model.forms.code.isEmpty && model.error == nil)
        model.showForm(.forgot)
        #expect(model.forms.mode == .forgot)
    }

    @Test func deletingTheAccountAsksForThePasswordThenSignsOutHere() async throws {
        let relay = MailRelay(), vault = MemoryCookieVault(), push = FakePush(), island = FakeIsland()
        let folder = temporaryFolder()
        let store = LocalStore(folder: folder)
        push.on = true
        let model = app(relay, vault: vault, store: store, push: push, island: island)
        model.start()
        await model.settle()
        model.login(name: "账号", password: "密码")
        await model.settle()
        #expect(model.screen == .devices && model.scope == "scope-1")
        // What this phone keeps for the sign-in, and for another one; an island it shows for the account.
        let mine = ChatKey(scope: "scope-1", device: DemoData.computerA, app: "codex", chat: "demo")
        let other = ChatKey(scope: "scope-other", device: DemoData.computerA, app: "codex", chat: "demo")
        // A send takes the draft with it (LocalStore.begin), so the draft typed after it comes second.
        await store.begin(Submission(request: "r1", key: mine, text: "发过的", action: "send", turn: "t1", body: "{}", created: 1))
        await store.setDraft(mine, "还没发的话")
        await store.setDetail(scope: "scope-1", device: DemoData.computerA, app: "codex", chat: "@sources", kind: "sources", value: "codex")
        await store.setDraft(other, "别的登录的")
        let identity = IslandIdentity(device: DemoData.computerA, app: "", chat: "", computer: "测试电脑 A", title: "")
        let shown = IslandState(status: .working, since: 1, turn: 1)
        model.island.live["one"] = IslandTrack(identity: identity, state: shown, token: String(repeating: "ab", count: 32), registered: true)
        island.snapshots = [IslandSnapshot(ref: IslandRef(raw: "one"), identity: identity, state: shown)]
        #expect(await model.deleteAccount(password: "wrong") == false)
        #expect(model.forms.deleteError == "当前密码错误" && !model.forms.deleting)
        #expect(model.screen == .devices && model.account != nil && push.on && island.endAlls == 0)
        #expect(try vault.read(ServiceOrigin.default.key) != nil)
        let draftBefore = await store.draft(mine), sendsBefore = await store.submissions(mine)
        #expect(draftBefore == "还没发的话" && sendsBefore.count == 1)
        relay.state.withLock { $0.wait = 60 }
        #expect(await model.deleteAccount(password: "fixture-password") == false)
        #expect(model.forms.deleteError == "请在 60 秒后重试")
        relay.state.withLock { $0.wait = 0 }
        let before = await relay.log.items.count
        #expect(await model.deleteAccount(password: "fixture-password"))
        #expect(model.screen == .login && model.account == nil && model.device == nil && !model.expired && model.scope.isEmpty)
        #expect(model.forms.said == "账号已删除" && model.forms.deleteError == nil && model.error == nil)
        #expect(try vault.read(ServiceOrigin.default.key) == nil)
        // Signed out here as 退出登录 does, with nothing more asked of the relay: it deleted the phones and islands itself.
        #expect(!push.on && model.push.phase == .off)
        #expect(await relay.paths().dropFirst(before) == ["/account/delete"])
        // Unlike 退出登录, every island ends and nothing of the sign-in stays on the phone; another sign-in's records do.
        #expect(island.endAlls == 1 && island.snapshots.isEmpty && model.island.live.isEmpty)
        let reopened = LocalStore(folder: folder)
        let draft = await reopened.draft(mine), sends = await reopened.submissions(mine)
        #expect(draft.isEmpty && sends.isEmpty)
        #expect(await reopened.detail(scope: "scope-1", device: DemoData.computerA, app: "codex", chat: "@sources", kind: "sources") == nil)
        #expect(await reopened.draft(other) == "别的登录的")
        let place = await reopened.place()
        #expect(place.scope.isEmpty && place.device.isEmpty && place.chat.isEmpty)
        // A write for it that comes late is dropped.
        await store.setDraft(mine, "迟到的")
        #expect(await LocalStore(folder: folder).draft(mine).isEmpty)
        // 登录 again starts afresh.
        model.showForm(.register)
        #expect(model.forms.said == nil)
    }

    /// 退出登录 stays as it was: islands are left to their switch, and the sign-in's records stay on the phone.
    @Test func signingOutKeepsTheRecordsAndLeavesTheIslands() async {
        let relay = MailRelay(), island = FakeIsland()
        let folder = temporaryFolder()
        let store = LocalStore(folder: folder)
        let model = app(relay, store: store, island: island)
        model.start()
        await model.settle()
        model.login(name: "账号", password: "密码")
        await model.settle()
        let mine = ChatKey(scope: "scope-1", device: DemoData.computerA, app: "codex", chat: "demo")
        await store.setDraft(mine, "还没发的话")
        model.logout()
        await model.settle()
        #expect(model.screen == .login && island.endAlls == 0)
        #expect(await LocalStore(folder: folder).draft(mine) == "还没发的话")
    }

    @Test func aSignInThatRanOutMeanwhileGoesToLogin() async {
        let relay = MailRelay()
        let model = app(relay)
        model.start()
        await model.settle()
        model.login(name: "账号", password: "密码")
        await model.settle()
        relay.world.state.withLock { $0.signedIn = false }
        #expect(await model.deleteAccount(password: "fixture-password") == false)
        #expect(model.forms.deleteError == "登录已失效，请重新登录；当前阅读位置已保留。")
        #expect(model.screen == .login && model.expired)
    }
}
