import Foundation

/// What the relay checks before it mails a code or keeps a password (relay_identity.py email, relay_accounts.py
/// password_hash), in its own words, checked here first: the relay mails at most ten codes an hour per network, so a
/// typo should not spend one.
public enum AccountInput {
    /// The address without the spaces around it, when it is one the relay takes: at most 254 characters, no spaces,
    /// `<`, `>` or second `@`, and a dot in the part after the `@` with something on both sides.
    public static func email(_ text: String) throws -> String {
        let email = text.trimmingCharacters(in: .whitespacesAndNewlines)
        let refused: (Character) -> Bool = { $0.isWhitespace || "@<>".contains($0) }
        let parts = email.split(separator: "@", omittingEmptySubsequences: false)
        guard email.unicodeScalars.count <= 254, parts.count == 2, !parts[0].isEmpty, !parts[0].contains(where: refused),
              !parts[1].contains(where: refused), parts[1].dropFirst().dropLast().contains(".")
        else { throw ReadFailure("请输入有效的邮箱地址") }
        return email
    }

    /// A new password (注册, 保存密码): 12 to 256 characters, counted as the relay counts them.
    public static func newPassword(_ text: String) throws {
        guard (12...256).contains(text.unicodeScalars.count) else { throw ReadFailure("密码须为 12 至 256 个字符") }
    }

    /// What the code field keeps of what was typed or pasted: digits only, six at most (web #code).
    public static func code(_ text: String) -> String {
        String(text.filter { $0.isASCII && $0.isNumber }.prefix(6))
    }
}

/// 创建账号, 忘记密码 and 删除账号 on the relay (relay_service.py account; web relay_account.js): posts of strings, each
/// carrying the Origin of the address it goes to like every POST. 验证 and 保存密码 sign in the way 登录 does.
extension RelayClient {
    /// 注册: the relay keeps the password with the sign-up and mails six digits to [email].
    public func register(email: String, password: String) async throws {
        _ = try await json(accountPost("/account/register", ["email": email, "password": password]))
    }

    /// 重新发送 on 输入验证码: the sign-up's code again (nothing is sent when no sign-up waits; the answer is the same).
    public func resendSignup(email: String) async throws {
        _ = try await json(accountPost("/account/resend", ["email": email]))
    }

    /// 验证: the six digits make the account and sign it in.
    public func verify(email: String, pin: String) async throws {
        try keepSignIn(try await send(accountPost("/account/verify", ["email": email, "pin": pin])))
    }

    /// 发送验证码 on 忘记密码, and its 重新发送: six digits to [email] when it has an account (the answer is the same
    /// either way, so nobody learns which addresses do).
    public func forgot(email: String) async throws {
        _ = try await json(accountPost("/account/forgot", ["email": email]))
    }

    /// 保存密码: the six digits and the new password. The relay ends the account's other sign-ins and its phones'
    /// notifications, and signs this one in.
    public func reset(email: String, pin: String, password: String) async throws {
        try keepSignIn(try await send(accountPost("/account/reset", ["email": email, "pin": pin, "password": password])))
    }

    /// 删除账号, asked again with the password: the account and all the relay keeps for it go (sign-ins, email, its
    /// computers' access, the phones and islands its notices went to). The sign-in here goes with it.
    public func deleteAccount(password: String) async throws {
        _ = try await json(accountPost("/account/delete", ["password": password]))
        try? vault?.write(origin.key, nil)
    }
}
