import Foundation
import TeleplyIsland

/// What a notification of 遥应's own names (relay_push.py's "teleply" part): the computer, the source app and the
/// conversation, all ids that say nothing of the conversation. A tap opens it once the sign-in and the computer are
/// checked (AppModel.openNotification).
public struct PushTarget: Sendable, Equatable {
    public let device: String
    public let app: String
    public let chat: String

    /// Nil unless the computer is a 32-hex id, the app one of the sources and the conversation a short id.
    public init?(device: String, app: String, chat: String) {
        guard (try? RelayClient.devicePath(device, "")) != nil, sourceOrder.contains(app), !chat.isEmpty, chat.count <= 200 else {
            return nil
        }
        self.device = device
        self.app = app
        self.chat = chat
    }

    /// From a notification's userInfo ("teleply": {"d", "a", "c"}); nil for anything else, such as a 试推.
    public init?(userInfo: [AnyHashable: Any]) {
        guard let part = userInfo["teleply"] as? [String: Any], let device = part["d"] as? String, let app = part["a"] as? String,
              let chat = part["c"] as? String else { return nil }
        self.init(device: device, app: app, chat: chat)
    }

    /// From teleply://open?d=…&a=…&c=… (the island's tap, handoff 5.3). Any other address is ignored: a web page can
    /// open a custom scheme too.
    public init?(url: URL) {
        guard url.scheme == IslandURL.scheme, url.host == "open",
              let parts = URLComponents(url: url, resolvingAgainstBaseURL: false), let query = parts.queryItems else { return nil }
        func value(_ name: String) -> String? { query.first(where: { $0.name == name })?.value }
        guard let device = value("d"), let app = value("a"), let chat = value("c") else { return nil }
        self.init(device: device, app: app, chat: chat)
    }
}

/// 遥应通知 and how the app presents them (relay_push.py, 0.6.2). The relay sends every notice with [category], so the
/// lock screen groups one computer's notices in one stack and the group's summary reads [summaryFormat] (Apple's
/// categorySummaryFormat; "%u" is how many are under it). While 遥应 is in front the app shows a banner without a
/// sound, and not even that for the conversation on screen; a passive one (silent, the rest of a burst) never pops a
/// banner (user 10-28).
public enum PushNotice {
    /// Same string as relay_push.NOTICE_CATEGORY.
    public static let category = "teleply.conversation"
    public static let summaryFormat = "还有 %u 个对话"

    /// What the app shows for a notice that arrives while it is in front.
    public enum Foreground: Sendable, Equatable {
        /// The conversation on screen: nothing at all.
        case none
        /// A silent notice (passive, no sound): only the notification centre, no banner.
        case list
        /// Another page: the banner (and the list), never a sound.
        case banner
    }

    /// [showing]: 遥应 is in front showing this very conversation (AppModel.isShowing). [passive]: the notice is one
    /// of a burst's silent ones (user 10-28): even in front it does not pop a banner.
    public static func foreground(showing: Bool, passive: Bool = false) -> Foreground {
        if showing { return .none }
        return passive ? .list : .banner
    }
}

/// 遥应通知 for this account as the service sees it (POST /account/push/state): whether it can send at all (an
/// APNs key on the server), whether it has this phone's token, and how many phones the account has.
public struct PushStatus: Sendable, Equatable {
    public var available: Bool
    public var registered: Bool
    public var phones: Int

    public init(available: Bool, registered: Bool, phones: Int) {
        self.available = available
        self.registered = registered
        self.phones = phones
    }
}

/// The phone's side of 遥应通知 on the relay (relay_push.py): all POSTs, so the token travels in the body and never in
/// an address.
extension RelayClient {
    public func pushState(token: String?) async throws -> PushStatus {
        let state = try await json(post("/account/push/state", json: ["token": .string(token ?? "")]))
        return PushStatus(available: state["available"].bool(), registered: state["registered"].bool(), phones: Int(state["phones"].int64()))
    }

    /// Keeps this phone's token for the signed-in account (again, when it is there already).
    public func pushRegister(token: String, environment: String, label: String, version: String) async throws {
        _ = try await json(post("/account/push/register", json: ["token": .string(token), "platform": "ios", "environment": .string(environment),
                                                                  "label": .string(label), "version": .string(version)]))
    }

    public func pushUnregister(token: String) async throws {
        _ = try await json(post("/account/push/unregister", json: ["token": .string(token)]))
    }

    /// One to try, sent at once; the service's words for how it went.
    public func pushTest(token: String) async throws -> String {
        let reply = try await json(post("/account/push/test", json: ["token": .string(token)]))
        return reply["text"].string().isEmpty ? "刚推了一条，看看通知" : reply["text"].string()
    }

    // MARK: 灵动岛 (relay_push.py: POST /account/push/activity, /start-token, /island-test)

    /// Tells the relay this island's push token, so it can change the island; or, on unregister, forgets it.
    public func islandRegister(_ registration: IslandRegistration) async throws {
        _ = try await json(post("/account/push/activity", json: Self.islandBody(registration)))
    }

    /// The token Apple gives for remote-started islands, one per phone.
    public func islandStartToken(_ token: IslandStartToken) async throws {
        _ = try await json(post("/account/push/start-token",
                                json: ["token": .string(token.token), "environment": .string(token.environment)]))
    }

    /// 开发者选项 → 让中转改一下: one Live Activity push for this island, which proves the key may send its topic.
    public func islandTest(device: String, app: String, chat: String) async throws -> String {
        let reply = try await json(post("/account/push/island-test",
                                        json: ["device": .string(device), "app": .string(app), "chat": .string(chat)]))
        return reply["text"].string().isEmpty ? "中转推了一条，看看岛" : reply["text"].string()
    }

    private static func islandBody(_ registration: IslandRegistration) -> JSONValue {
        var fields: [String: JSONValue] = [
            "op": .string(registration.op), "token": .string(registration.token),
            "device": .string(registration.device), "app": .string(registration.app),
            "chat": .string(registration.chat), "environment": .string(registration.environment),
        ]
        if registration.op == "register" {
            fields["state"] = .string(registration.state)
            // The relay's account requests take strings only (relay_service.data); times are Unix seconds.
            fields["since"] = .string(String(registration.since))
            fields["turn"] = .string(String(registration.turn))
            fields["title"] = .string(registration.title)
        }
        return .object(fields)
    }
}
