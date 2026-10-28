// ActivityKit's `Activity` is not Sendable-annotated in this SDK; every call here stays on the main actor anyway
// (the class is @MainActor), so the pre-concurrency import keeps Swift 6 from refusing the await.
@preconcurrency import ActivityKit
import Foundation
import TeleplyIsland
import TeleplyState

/// 灵动岛 on this phone: ActivityKit's side of IslandPlatform. The app starts an island (a message sent, 试一下灵动岛),
/// keeps its handle, and gives the relay the token Apple made for it; the relay's pushes then change what the
/// extension draws. Remote-started islands arrive through `activityUpdates`.
///
/// `Activity`'s handles are kept on the main actor, where everything here runs.
@MainActor
final class SystemIsland: IslandPlatform {
    private static let wantedKey = "teleply.island.wanted"

    /// The islands this app started or learned about, by Activity's id.
    private var islands: [String: Activity<IslandAttributes>] = [:]
    private var handler: (@MainActor @Sendable (IslandEvent) -> Void)?
    private var tasks: [Task<Void, Never>] = []
    private var watched: Set<String> = []
    private var observing = false

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

    func wanted() -> Bool {
        // 0.6.0: islands follow 遥应通知 until the user touches this switch (then the choice is kept).
        if let stored = UserDefaults.standard.object(forKey: Self.wantedKey) as? Bool { return stored }
        return UserDefaults.standard.bool(forKey: "teleply.push.wanted")
    }
    func setWanted(_ on: Bool) { UserDefaults.standard.set(on, forKey: Self.wantedKey) }

    func start(_ identity: IslandIdentity, _ state: IslandState) async throws -> IslandRef {
        guard ActivityAuthorizationInfo().areActivitiesEnabled else {
            throw IslandFailure("系统里关了遥应的实时活动：到系统设置 → 遥应 里打开。")
        }
        do {
            let activity = try Activity.request(attributes: IslandAttributes(identity),
                                                content: ActivityContent(state: state, staleDate: staleDate(state)),
                                                pushType: .token)
            islands[activity.id] = activity
            watch(activity, started: false)
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

    /// The phone's push-to-start token, polled for up to `seconds` (iOS 17.2 and later).
    func startToken(seconds: Double) async -> String? {
        for _ in 0..<max(1, Int(seconds * 10)) {
            if let token = Activity<IslandAttributes>.pushToStartToken { return Self.hex(token) }
            try? await Task.sleep(for: .milliseconds(100))
        }
        return nil
    }

    func update(_ ref: IslandRef, _ state: IslandState) async {
        guard let activity = islands[ref.raw] else { return }
        await activity.update(ActivityContent(state: state, staleDate: staleDate(state)))
    }

    func end(_ ref: IslandRef, _ state: IslandState, dismissIn: TimeInterval) async {
        watched.remove(ref.raw)
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
        watched.removeAll()
    }

    func observe(_ handler: @escaping @MainActor @Sendable (IslandEvent) -> Void) {
        self.handler = handler
        guard !observing else { return }
        observing = true
        for activity in Activity<IslandAttributes>.activities { watch(activity, started: false) }
        tasks.append(Task { [weak self] in
            for await activity in Activity<IslandAttributes>.activityUpdates {
                await MainActor.run { self?.watch(activity, started: true) }
            }
        })
    }

    func running() async -> [IslandSnapshot] {
        Activity<IslandAttributes>.activities.map {
            IslandSnapshot(ref: IslandRef(raw: $0.id), identity: $0.attributes.identity, state: $0.content.state)
        }
    }

    /// Watches one island's token and dismissal; a remote-started one is also told to the app now.
    private func watch(_ activity: Activity<IslandAttributes>, started: Bool) {
        let ref = IslandRef(raw: activity.id)
        guard !watched.contains(ref.raw) else { return }
        watched.insert(ref.raw)
        islands[ref.raw] = activity
        if started { handler?(.started(ref, activity.attributes.identity, activity.content.state)) }
        tasks.append(Task { [weak self] in
            for await token in activity.pushTokenUpdates {
                let hex = token.map { String(format: "%02x", $0) }.joined()
                await MainActor.run { self?.handler?(.token(ref, hex)) }
            }
        })
        tasks.append(Task { [weak self] in
            for await state in activity.activityStateUpdates {
                if state == .dismissed || state == .ended {
                    await MainActor.run { self?.handler?(.dismissed(ref)) }
                }
            }
        })
    }

    /// 在干活 that heard nothing for 15 minutes says 可能不是最新 (the relay's pushes carry the same limit).
    private func staleDate(_ state: IslandState) -> Date? {
        state.status == .working ? Date().addingTimeInterval(15 * 60) : nil
    }

    private static func hex(_ token: Data) -> String {
        token.map { String(format: "%02x", $0) }.joined()
    }
}
