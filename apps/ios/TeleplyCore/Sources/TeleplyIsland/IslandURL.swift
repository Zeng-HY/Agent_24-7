import Foundation

/// The addresses the island (and later the quota island) opens 遥应 with. Only these are answered: any web page can
/// open a custom scheme, so the app checks the computer, the source and the conversation before opening one.
public enum IslandURL {
    public static let scheme = "teleply"

    /// teleply://open?d=<computer>&a=<source>&c=<conversation>
    public static func open(_ identity: IslandIdentity) -> URL? {
        open(device: identity.device, app: identity.app, chat: identity.chat)
    }

    public static func open(device: String, app: String, chat: String) -> URL? {
        url(host: "open", items: [URLQueryItem(name: "d", value: device), URLQueryItem(name: "a", value: app),
                                  URLQueryItem(name: "c", value: chat)])
    }

    /// teleply://list?d=<computer>&status=running: 方案七, and 0.6.5's "还有 N 个", open this computer's list.
    public static func list(device: String, status: String? = nil) -> URL? {
        var items = [URLQueryItem(name: "d", value: device)]
        if let status, !status.isEmpty { items.append(URLQueryItem(name: "status", value: status)) }
        return url(host: "list", items: items)
    }

    private static func url(host: String, items: [URLQueryItem]) -> URL? {
        var parts = URLComponents()
        parts.scheme = scheme
        parts.host = host
        parts.queryItems = items
        return parts.url
    }
}
