import Foundation
import TeleplyModel

/// 创建账号, 忘记密码 and 删除账号 inside the app (web relay_account.js; App Review 4 and 5.1.1(v)), each one screen with
/// the relay's own requests: 注册 → 输入验证码 → signed in; 发送验证码 → 重置密码 → signed in with 密码已更新. When the relay
/// refuses, its words say why. 登录 offers the first two only while the service sends email (AccountConfig).
extension AppModel {
    /// 创建账号, 忘记密码 or 返回登录 (web setMode): another form of 登录. The email typed stays in its field; what was
    /// said and the code go.
    public func showForm(_ mode: AccountForms.Mode) {
        forms.mode = mode
        forms.code = ""
        forms.said = nil
        error = nil
    }

    /// 注册 (web register): the address and password are checked here in the relay's words, then the relay mails six
    /// digits and 输入验证码 comes next.
    public func register(email: String, password: String) {
        operation { [weak self] g in
            guard let self else { return }
            let email = try AccountInput.email(email)
            try AccountInput.newPassword(password)
            try await self.client.register(email: email, password: password)
            guard self.current(g) else { return }
            self.codeSent(to: email, next: .verify, said: "验证码已发送")
        }
    }

    /// 发送验证码 (web forgot): the relay mails six digits when the address has an account, and answers the same when it
    /// has none; 重置密码 comes next either way.
    public func forgot(email: String) {
        operation { [weak self] g in
            guard let self else { return }
            let email = try AccountInput.email(email)
            try await self.client.forgot(email: email)
            guard self.current(g) else { return }
            self.codeSent(to: email, next: .reset, said: "请查收邮件")
        }
    }

    /// The 验证码 field as typed, pasted or filled in from Mail: digits only, six at most. On 输入验证码 the sixth digit
    /// sends it (web: "six digits: off it goes").
    public func enterCode(_ text: String) {
        forms.code = AccountInput.code(text)
        if forms.code.count == 6, forms.mode == .verify, !busy { verify() }
    }

    /// 验证 (web verify): the code makes the account and signs it in; the app goes on as after 登录. A code the relay
    /// turns down is cleared for the next try.
    public func verify() {
        operation { [weak self] g in
            guard let self else { return }
            let code = self.forms.code
            guard code.count == 6 else { throw ReadFailure("请输入邮件里的 6 位验证码。") }
            do {
                try await self.client.verify(email: self.forms.email, pin: code)
            } catch {
                self.codeRefused(g, error)
                throw error
            }
            try await self.signedIn(g)
        }
    }

    /// 保存密码 (web resetcode): the code and the new password sign in; the app goes on as after 登录 and says 密码已更新.
    public func resetPassword(password: String) {
        operation { [weak self] g in
            guard let self else { return }
            let code = self.forms.code
            guard code.count == 6 else { throw ReadFailure("请输入邮件里的 6 位验证码。") }
            try AccountInput.newPassword(password)
            do {
                try await self.client.reset(email: self.forms.email, pin: code, password: password)
            } catch {
                self.codeRefused(g, error)
                throw error
            }
            try await self.signedIn(g)
            guard self.current(g) else { return }
            self.say("密码已更新")
        }
    }

    /// 重新发送 (web resend): the code mailed again, 注册's by /account/resend and 重置密码's by asking for it again. It
    /// runs beside the form, which stays usable. When the relay says to wait (429), the button counts the seconds down,
    /// 15 minutes at most as on the web.
    public func resend() {
        let mode = forms.mode, email = forms.email, client = client
        guard mode == .verify || mode == .reset, !forms.resending, forms.resendWait(at: clock()) == 0 else { return }
        forms.resending = true
        forms.said = nil
        error = nil
        Task { [weak self] in
            var failure: (any Error)?
            do {
                if mode == .verify { try await client.resendSignup(email: email) } else { try await client.forgot(email: email) }
            } catch {
                failure = error
            }
            guard let self else { return }
            self.forms.resending = false
            if let wait = (failure as? ServiceFailure)?.retryAfter, wait > 0 {
                self.forms.resendAt = self.clock().addingTimeInterval(Double(min(wait, 900)))
            }
            guard self.forms.mode == mode, self.forms.email == email else { return }
            if let failure {
                self.error = describe(failure)
            } else {
                self.forms.code = ""
                self.forms.said = "已重新发送"
            }
        }
    }

    /// 删除账号 (web account menu → 删除账号), asked again with the password: the relay deletes the account and all it
    /// keeps for it. This phone then signs out as 退出登录 does but asks the relay nothing more (it deleted this phone's
    /// 遥应通知 and islands with the account, and the sign-in is gone), and 登录 says 账号已删除. Unlike 退出登录, the
    /// phone keeps nothing of the account either: every island ends, and the sign-in's records go (drafts, sends,
    /// cached lists, each conversation's details). True once the account is gone; otherwise [forms.deleteError] has
    /// the relay's words (当前密码错误, 请在 N 秒后重试).
    public func deleteAccount(password: String) async -> Bool {
        guard !forms.deleting else { return false }
        forms.deleting = true
        forms.deleteError = nil
        defer { forms.deleting = false }
        do {
            guard !password.isEmpty else { throw ReadFailure("请输入当前密码。") }
            try await client.deleteAccount(password: password)
        } catch {
            forms.deleteError = describe(error)
            if (error as? ServiceFailure)?.status == 401 {  // the sign-in ran out meanwhile: 登录 waits under the sheet
                screen = .login
                expired = true
                live()
            }
            return false
        }
        pushForget()
        let gone = scope
        cancelWork()
        clearAll()
        scope = ""
        screen = .login
        forms.said = "账号已删除"
        live()
        await islandEndAllHere()
        guard !fixture else { return true }
        await persistSelection(scope: "", device: "")
        // A write still under way for the sign-in (a draft left a moment ago) lands before this and goes with the rest,
        // or after it and is dropped.
        await services.store.forget(scope: gone)
        return true
    }

    private func codeSent(to email: String, next: AccountForms.Mode, said: String) {
        forms.email = email
        forms.code = ""
        forms.mode = next
        forms.said = said
    }

    /// The relay turned the code down (验证码不对, 验证码已失效): the field empties for the next try. A lost connection
    /// keeps it, to be sent again as it is.
    private func codeRefused(_ g: Int, _ error: any Error) {
        guard current(g), (error as? ServiceFailure)?.status == 400 else { return }
        forms.code = ""
    }

    /// A line that is not an error, where the person is now: under 登录 or 我的电脑, or the list's passing note.
    func say(_ text: String) {
        if screen == .chats { notice = text } else { forms.said = text }
    }

    /// Now by the app's clock, which tests set.
    func clock() -> Date {
        Date(timeIntervalSince1970: Double(services.now()) / 1000)
    }
}
