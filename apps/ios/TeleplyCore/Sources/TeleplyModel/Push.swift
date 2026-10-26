import Foundation

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
}
