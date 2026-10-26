import SwiftUI

/// What the window shows on top of the pages: 设置 and the sidebar. Kept apart from the app's state because only
/// the screen cares (Android ReaderViewModel keeps its own settings and drawer flags for the same reason).
@Observable
final class Chrome {
    var settings = false
    private(set) var drawer = false
    /// Goes up each time the sidebar opens, so its sources arrive again (web lbrRowIn).
    private(set) var drawerOpenings = 0
    /// Where the source chips are on screen while they scroll sideways: a swipe there moves them, not the sidebar.
    @ObservationIgnored var noPull: CGRect = .null
    /// A sidebar swipe is moving, or ended a moment ago. The row under the finger takes the lift as a tap (the 0.4.1
    /// tour: a swipe right on a row opened that conversation under the sidebar), so rows and the sidebar's buttons
    /// act through [tap].
    @ObservationIgnored var pulling = false
    @ObservationIgnored var pulledAt = Date.distantPast

    var tapsAllowed: Bool { !pulling && Date().timeIntervalSince(pulledAt) > 0.3 }

    /// [action] a tenth of a second after its tap, unless that tap ended a sidebar swipe. The row hears the lift
    /// before the swipe has told anyone it moved (0.4.2 tour), so it is asked again a moment later.
    func tap(_ action: @escaping () -> Void) -> () -> Void {
        {
            Task { @MainActor in
                try? await Task.sleep(for: .milliseconds(100))
                if self.tapsAllowed { action() }
            }
        }
    }

    func openDrawer() {
        drawerOpenings += 1
        drawer = true
    }

    func closeDrawer() {
        drawer = false
    }
}
