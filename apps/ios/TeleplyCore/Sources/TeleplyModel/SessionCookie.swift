import Foundation
import Synchronization

/// The relay's sign-in, `__Host-ar_account` (relay_service.py: Secure, HttpOnly, SameSite=Strict, Path=/, no
/// Domain, Max-Age 7 days). Only its name and value are ever sent back (Android RelayApi).
public struct SessionCookie: Sendable, Equatable, Codable {
    public static let name = "__Host-ar_account"

    public var value: String
    /// When the relay stops accepting it; nil when the response gave no lifetime.
    public var expires: Date?

    public init(value: String, expires: Date?) {
        self.value = value
        self.expires = expires
    }

    /// `Cookie: name=value` while it has not run out.
    public func header(at now: Date) -> String? {
        if let expires, expires <= now { return nil }
        return "\(Self.name)=\(value)"
    }

    /// The sign-in from a Set-Cookie header (several cookies may arrive joined by commas), kept only when it is
    /// the relay's own: Secure, HttpOnly, host-only and Path=/. Anything else is not a sign-in.
    public static func fromSetCookie(_ header: String, now: Date) -> SessionCookie? {
        for text in splitCookies(header) {
            let parts = text.split(separator: ";", omittingEmptySubsequences: false).map { $0.trimmingCharacters(in: .whitespaces) }
            guard let pair = parts.first, let equals = pair.firstIndex(of: "="),
                  pair[..<equals] == name else { continue }
            let value = String(pair[pair.index(after: equals)...])
            var secure = false, httpOnly = false, path = "", domain = false
            var maxAge: Double?
            var expires: Date?
            for attribute in parts.dropFirst() {
                let pieces = attribute.split(separator: "=", maxSplits: 1).map { $0.trimmingCharacters(in: .whitespaces) }
                switch pieces[0].lowercased() {
                case "secure": secure = true
                case "httponly": httpOnly = true
                case "path": path = pieces.count > 1 ? pieces[1] : ""
                case "domain": domain = true
                case "max-age": maxAge = pieces.count > 1 ? Double(pieces[1]) : nil
                case "expires": expires = pieces.count > 1 ? httpDate(pieces[1]) : nil
                default: break
                }
            }
            guard secure, httpOnly, !domain, path == "/", !value.isEmpty else { return nil }
            if let maxAge { expires = now.addingTimeInterval(maxAge) }
            if let expires, expires <= now { return nil }
            return SessionCookie(value: value, expires: expires)
        }
        return nil
    }

    /// A comma starts a new cookie only when a `name=` follows; the commas inside Expires dates do not.
    static func splitCookies(_ header: String) -> [String] {
        var cookies: [String] = []
        for piece in header.split(separator: ",", omittingEmptySubsequences: false) {
            let trimmed = piece.trimmingCharacters(in: .whitespaces)
            let startsCookie = trimmed.firstIndex(of: "=").map { index in
                let name = trimmed[..<index]
                return !name.isEmpty && name.allSatisfy { $0.isLetter || $0.isNumber || "!#$%&'*+-.^_`|~".contains($0) }
            } ?? false
            if startsCookie || cookies.isEmpty { cookies.append(trimmed) } else { cookies[cookies.count - 1] += "," + piece }
        }
        return cookies
    }

    static func httpDate(_ text: String) -> Date? {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.timeZone = TimeZone(identifier: "GMT")
        formatter.dateFormat = "EEE, dd MMM yyyy HH:mm:ss zzz"
        return formatter.date(from: text)
    }
}

/// Where the sign-in is kept, one entry per service address (RelayClient's origin key). The phone keeps it in
/// the keychain; tests and the local demo keep it in memory. A read that cannot happen now (phone locked)
/// throws; it is never taken as signed out.
public protocol CookieVault: Sendable {
    func read(_ key: String) throws -> SessionCookie?
    func write(_ key: String, _ cookie: SessionCookie?) throws
}

public final class MemoryCookieVault: CookieVault {
    private let entries = Mutex<[String: SessionCookie]>([:])

    public init() {}

    public func read(_ key: String) throws -> SessionCookie? {
        entries.withLock { $0[key] }
    }

    public func write(_ key: String, _ cookie: SessionCookie?) throws {
        entries.withLock { $0[key] = cookie }
    }
}
