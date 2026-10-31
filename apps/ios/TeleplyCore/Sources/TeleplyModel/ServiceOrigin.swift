import Foundation

/// The service a phone talks to: an HTTPS root address with no user, path, query or fragment (Android
/// serviceOrigin()). The relay accepts exactly one Host and one Origin, so the address is normalised the way
/// OkHttp does: lower-case host, no default port.
public struct ServiceOrigin: Sendable, Hashable {
    /// Teleply's own service (spec 4.8): users never type it. On its domain since it moved from the IP below
    /// (docs/handoff-domain.md).
    public static let defaultAddress = "https://app.pocketagentdesk.com"
    public static let `default` = try! ServiceOrigin(defaultAddress)
    /// The same service's address before the domain. The relay still answers on it, for the same accounts; a phone
    /// that used it moves to the domain once, signed in (AppModel.moveToDomain).
    public static let formerDefault = try! ServiceOrigin("https://8.166.15.235")

    /// "https://host[:port]", the exact Origin header the relay expects on every POST.
    public let header: String

    /// "https://host[:port]/", what the login is kept under (Android RelayApi.key).
    public var key: String { header + "/" }

    public init(_ text: String) throws {
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard let parts = URLComponents(string: trimmed),
              parts.scheme?.lowercased() == "https",
              let rawHost = parts.host, !rawHost.isEmpty,
              parts.user == nil, parts.password == nil,
              parts.query == nil, parts.fragment == nil,
              parts.path.isEmpty || parts.path == "/"
        else { throw ServiceOriginError.invalid }
        var host = rawHost.lowercased()
        if host.contains(":"), !host.hasPrefix("[") { host = "[" + host + "]" }
        var header = "https://" + host
        if let port = parts.port, port != 443 { header += ":\(port)" }
        self.header = header
    }

    /// The full address of a route on this service; query values are percent-encoded the way OkHttp's
    /// addQueryParameter does (a "+" stays a plus, not a space). Nil values are left out.
    public func url(_ path: String, query: [(String, String?)] = []) -> URL {
        var text = header + path
        let pairs = query.compactMap { name, value in value.map { Self.encode(name) + "=" + Self.encode($0) } }
        if !pairs.isEmpty { text += "?" + pairs.joined(separator: "&") }
        guard let url = URL(string: text) else { preconditionFailure("Route must be ASCII: \(path)") }
        return url
    }

    private static let unreserved = CharacterSet(charactersIn:
        "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~")

    static func encode(_ text: String) -> String {
        text.addingPercentEncoding(withAllowedCharacters: unreserved) ?? ""
    }
}

public enum ServiceOriginError: Error, Sendable, Equatable {
    case invalid

    public var message: String { "请输入 HTTPS 服务根地址，不含账号、路径或参数。" }
}
