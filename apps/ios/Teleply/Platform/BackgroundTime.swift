import UIKit

/// A little time in the background for a send under way (spec 6.10): asked for when send is tapped and given back
/// once the result is kept. When the system ends it first, [expired] cancels the request and the send becomes
/// 送达状态待确认 (B04). No background upload: the system would retry it by itself.
enum BackgroundTime {
    private final class Grant {
        var id = UIBackgroundTaskIdentifier.invalid

        func end() {
            guard id != .invalid else { return }
            UIApplication.shared.endBackgroundTask(id)
            id = .invalid
        }
    }

    static func begin(_ expired: @escaping @MainActor @Sendable () -> Void) -> @MainActor () -> Void {
        let grant = Grant()
        grant.id = UIApplication.shared.beginBackgroundTask(withName: "遥应发送") {
            expired()
            grant.end()
        }
        return { grant.end() }
    }
}
