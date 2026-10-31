import Foundation
import Observation
import TeleplyModel

/// The forms of 登录 besides 登录 itself, and 删除账号 (web relay_account.js FORMS and its 删除账号 dialog; App Review 4
/// and 5.1.1(v): nothing leaves for Safari): which one shows, the address the code went to, the code as typed, how
/// long 重新发送 waits, and the line that is not an error. Email and passwords stay in the page's own fields.
@Observable
public final class AccountForms {
    public enum Mode: String, Sendable {
        /// 登录: 邮箱或账号, 密码.
        case login
        /// 创建账号: 邮箱, 密码（至少 12 位）, 注册.
        case register
        /// 输入验证码 after 注册: 验证码 (six digits send themselves), 验证.
        case verify
        /// 忘记密码: 邮箱, 发送验证码.
        case forgot
        /// 重置密码: 验证码, 新密码（至少 12 位）, 保存密码.
        case reset
    }

    public internal(set) var mode = Mode.login
    /// Where the code went (web `pending`), shown under the title of 输入验证码 and 重置密码.
    public internal(set) var email = ""
    /// The 验证码 field: digits only, six at most (AppModel.enterCode).
    public internal(set) var code = ""
    /// The line under the form that is not an error (web say): 验证码已发送, 请查收邮件, 已重新发送, 账号已删除; under 我的电脑,
    /// 密码已更新.
    public internal(set) var said: String?
    /// 重新发送 under way.
    public internal(set) var resending = false
    /// When 重新发送 may be pressed again after the relay said to wait (429 retry_after; web wait(), 15 minutes at most).
    public internal(set) var resendAt: Date?
    /// 删除账号 under way, and why the relay refused it, said in its sheet.
    public internal(set) var deleting = false
    public var deleteError: String?

    public init() {}

    /// Whole seconds left before 重新发送 may be pressed; 0 when it may.
    public func resendWait(at now: Date) -> Int {
        guard let resendAt else { return 0 }
        return max(0, Int(resendAt.timeIntervalSince(now).rounded(.up)))
    }

    /// Back to 登录 with nothing typed or said (signed out, another service, signed in).
    func reset() {
        mode = .login
        email = ""
        code = ""
        said = nil
        resendAt = nil
    }
}
