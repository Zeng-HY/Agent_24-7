import ActivityKit
import Foundation
import TeleplyIsland
import TeleplyState

/// 灵动岛 on this phone: ActivityKit's side of IslandPlatform. The app starts an island (试一下灵动岛, later a sent
/// message), keeps its handle, and gives the relay the token Apple made for it; the relay's pushes then change what
/// the extension draws.
///
/// `Activity`'s handles are kept on the main actor, where everything here runs.
@MainActor
final class SystemIsland: IslandPlatform {
    /// The islands this launch started, by Activity's id.
    private var islands: [String: Activity<IslandAttributes>] = [:]

    func enabled() async -> Bool {
        ActivityAuthorizationInfo().areActivitiesEnabled
    }

    var environment: String {
        #if DEBUG
        return "development"
        #else
        return "production"  // the App Store profile, which TestFlight builds are signed with
        #endif
    }

    func start(_ identity: IslandIdentity, _ state: IslandState) async throws -> IslandRef {
        guard ActivityAuthorizationInfo().areActivitiesEnabled else {
            throw IslandFailure("系统里关了遥应的实时活动：到系统设置 → 遥应 里打开。")
        }
        do {
            let activity = try Activity.request(attributes: IslandAttributes(identity),
                                                content: ActivityContent(state: state, staleDate: staleDate(state)),
                                                pushType: .token)
            islands[activity.id] = activity
            return IslandRef(raw: activity.id)
        } catch {
            throw IslandFailure("系统没有开这个岛：" + String(describing: error))
        }
    }

    /// The token Apple made for this island, polled for up to `seconds`.
    func token(_ ref: IslandRef, seconds: Double) async -> String? {
        guard let activity = islands[ref.raw] else { return nil }
        for _ in 0..<max(1, Int(seconds * 10)) {
            if let token = activity.pushToken { return Self.hex(token) }
            try? await Task.sleep(for: .milliseconds(100))
        }
        return nil
    }

    func update(_ ref: IslandRef, _ state: IslandState) async {
        guard let activity = islands[ref.raw] else { return }
        await activity.update(ActivityContent(state: state, staleDate: staleDate(state)))
    }

    func end(_ ref: IslandRef, _ state: IslandState, dismissIn: TimeInterval) async {
        guard let activity = islands.removeValue(forKey: ref.raw) else { return }
        let content = ActivityContent(state: state, staleDate: nil)
        if dismissIn <= 0 {
            await activity.end(content, dismissalPolicy: .immediate)
        } else {
            await activity.end(content, dismissalPolicy: .after(Date().addingTimeInterval(dismissIn)))
        }
    }

    func endAll() async {
        for activity in Activity<IslandAttributes>.activities {
            await activity.end(nil, dismissalPolicy: .immediate)
        }
        islands.removeAll()
    }

    /// 在干活 that heard nothing for 15 minutes says 可能不是最新 (the relay's pushes carry the same limit).
    private func staleDate(_ state: IslandState) -> Date? {
        state.status == .working ? Date().addingTimeInterval(15 * 60) : nil
    }

    private static func hex(_ token: Data) -> String {
        token.map { String(format: "%02x", $0) }.joined()
    }
}
