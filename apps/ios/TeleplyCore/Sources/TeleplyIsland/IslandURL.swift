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

    /// teleply://list?d=<computer>: 方案七 opens this computer's conversation list.
    public static func list(device: String) -> URL? {
        url(host: "list", items: [URLQueryItem(name: "d", value: device)])
    }

    private static func url(host: String, items: [URLQueryItem]) -> URL? {
        var parts = URLComponents()
        parts.scheme = scheme
        parts.host = host
        parts.queryItems = items
        return parts.url
    }
}
