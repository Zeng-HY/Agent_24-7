import Foundation
import Observation
import TeleplyModel

/// What the system allows 遥应 to show.
public enum PushPermission: Sendable, Equatable {
    case notAsked, allowed, denied
}

/// The phone's side of 遥应通知, given by the app (UserNotifications and UIApplication); tests pass a fake.
@MainActor
public protocol PushPlatform: Sendable {
    /// The system's switch for 遥应's notifications now.
    func permission() async -> PushPermission
    /// Shows the system's question (it shows only once in an install); true when allowed.
    func ask() async -> Bool
    /// Asks iOS for this app's push token; it comes back through AppModel.pushToken(_:) or pushTokenFailed(_:).
    func register()
    /// "production" for TestFlight and the App Store, as the App Store profile says.
    var environment: String { get }
    /// How the phone shows on the service, and the app's version.
    var label: String { get }
    var version: String { get }
    /// Whether this phone should get them: turned on here and not turned off or signed out since. Kept on the phone.
    func wanted() -> Bool
    func setWanted(_ on: Bool)
}

/// No push: tests that do not ask for it.
public struct NoPush: PushPlatform {
    public init() {}
    public func permission() async -> PushPermission { .denied }
    public func ask() async -> Bool { false }
    public func register() {}
    public var environment: String { "production" }
    public var label: String { "iPhone" }
    public var version: String { "" }
    public func wanted() -> Bool { false }
    public func setWanted(_ on: Bool) {}
}

/// 设置 → 手机通知 → 遥应通知 as it stands (AppModel+Push).
@Observable
public final class PushModel {
    public enum Phase: Sendable, Equatable {
        /// Not read yet.
        case checking
        /// The system allows it (or has not asked yet) and this phone is not on the service for the account.
        case off
        /// This phone gets the account's notifications.
        case on
        /// Turned off for 遥应 in the system's settings: only there can it be turned on again.
        case denied
        /// The service has no APNs key yet (configure-push.py), so nothing can be sent.
        case unavailable
    }

    public internal(set) var phase = Phase.checking
    /// 打开、试推 or 关掉 under way.
    public internal(set) var working = false
    /// What the last of them came to, said under the group.
    public var note: String?
    /// The push token iOS gave this launch (hex), once it came.
    public internal(set) var token: String?
    /// A tapped notification waiting for the launch or a sign-in to be done.
    public internal(set) var waiting: PushTarget?
    /// Why iOS gave no token this time (no network, push not allowed for this build).
    @ObservationIgnored var tokenFailure: String?

    public init() {}
}
