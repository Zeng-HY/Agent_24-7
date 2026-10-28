import Foundation
import Observation
import TeleplyIsland

/// What the system tells the app about its islands: one started from afar, a token made or changed, one gone.
public enum IslandEvent: Sendable, Equatable {
    case started(IslandRef, IslandIdentity, IslandState)
    case token(IslandRef, String)
    case dismissed(IslandRef)
}

/// An island the system still has (app start, foreground, after a remote start), for checking what the app knows.
public struct IslandSnapshot: Sendable, Equatable {
    public var ref: IslandRef
    public var identity: IslandIdentity
    public var state: IslandState

    public init(ref: IslandRef, identity: IslandIdentity, state: IslandState) {
        self.ref = ref
        self.identity = identity
        self.state = state
    }
}

/// The phone's side of 灵动岛, given by the app (ActivityKit); tests pass a fake. All of it is the system's:
/// whether the user allowed Live Activities, starting one, its push token, changing it, ending it.
@MainActor
public protocol IslandPlatform: Sendable {
    /// 设置 → 遥应 → 实时活动 (ActivityAuthorizationInfo().areActivitiesEnabled).
    func enabled() async -> Bool
    /// "production" for TestFlight and the App Store; "development" for a debug build.
    var environment: String { get }
    /// Whether this phone should show islands: the 开发者选项 switch before 0.6.0, 手机通知's switch after.
    func wanted() -> Bool
    func setWanted(_ on: Bool)
    /// Starts one and returns its handle; throws IslandFailure when the system will not.
    func start(_ identity: IslandIdentity, _ state: IslandState) async throws -> IslandRef
    /// The token Apple gave this island (for the relay), waiting up to `seconds` for it; nil when it never came.
    func token(_ ref: IslandRef, seconds: Double) async -> String?
    /// The push-to-start token, one per phone: how the relay starts an island for a turn on the computer.
    func startToken(seconds: Double) async -> String?
    /// Changes what the island shows.
    func update(_ ref: IslandRef, _ state: IslandState) async
    /// Ends it; `dismissIn` seconds later it leaves the lock screen too.
    func end(_ ref: IslandRef, _ state: IslandState, dismissIn: TimeInterval) async
    /// Ends every island this app started (the setting turned off, signing out).
    func endAll() async
    /// Watches the system: remote starts, tokens, dismissals. Called once at launch.
    func observe(_ handler: @escaping @MainActor @Sendable (IslandEvent) -> Void)
    /// The islands the system still has now.
    func running() async -> [IslandSnapshot]
}

/// The system said no, or has no islands at all; `message` is what the page shows.
public struct IslandFailure: Error, Sendable, Equatable {
    public let message: String

    public init(_ message: String) {
        self.message = message
    }
}

/// No islands (tests that do not ask for one; a build where the system has none).
public struct NoIsland: IslandPlatform {
    public init() {}
    public func enabled() async -> Bool { false }
    public var environment: String { "production" }
    public func wanted() -> Bool { false }
    public func setWanted(_ on: Bool) {}
    public func start(_ identity: IslandIdentity, _ state: IslandState) async throws -> IslandRef {
        throw IslandFailure("这台手机现在不能显示灵动岛。")
    }
    public func token(_ ref: IslandRef, seconds: Double) async -> String? { nil }
    public func startToken(seconds: Double) async -> String? { nil }
    public func update(_ ref: IslandRef, _ state: IslandState) async {}
    public func end(_ ref: IslandRef, _ state: IslandState, dismissIn: TimeInterval) async {}
    public func endAll() async {}
    public func observe(_ handler: @escaping @MainActor @Sendable (IslandEvent) -> Void) {}
    public func running() async -> [IslandSnapshot] { [] }
}

/// One island the app is keeping for the relay: what it names, what it shows, and whether its token is registered.
public struct IslandTrack: Sendable, Equatable {
    public var identity: IslandIdentity
    public var state: IslandState
    public var token: String?
    public var registered = false

    public init(identity: IslandIdentity, state: IslandState, token: String? = nil, registered: Bool = false) {
        self.identity = identity
        self.state = state
        self.token = token
        self.registered = registered
    }
}

/// 设置 → 开发者选项 → 灵动岛 as it stands (AppModel+Island). Before 0.6.0 the switch itself stays out of users'
/// way; from 0.6.0 on it moves to 设置 → 手机通知.
@Observable
public final class IslandModel {
    /// A start, update or end under way.
    public internal(set) var working = false
    /// What the last one came to, said under the buttons.
    public internal(set) var note: String?
    /// The demo island this launch started (试一下灵动岛), so 让中转改一下 can update the same one.
    public internal(set) var demo: IslandRef?
    /// Whether the system allows Live Activities; nil until read.
    public internal(set) var enabled: Bool?
    /// The 灵动岛 switch (0.6.0 前只在开发者选项，默认关).
    public internal(set) var wanted = false
    /// The real islands this app keeps, by Activity id.
    public internal(set) var live: [String: IslandTrack] = [:]
    /// Whether the system's events are being watched already.
    @ObservationIgnored var observing = false

    public init() {}
}
