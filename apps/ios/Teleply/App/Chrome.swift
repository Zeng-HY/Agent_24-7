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
    /// ask [tapsAllowed] first.
    @ObservationIgnored var pulling = false
    @ObservationIgnored var pulledAt = Date.distantPast

    var tapsAllowed: Bool { !pulling && Date().timeIntervalSince(pulledAt) > 0.3 }

    /// [action] unless its tap ends a sidebar swipe.
    func tap(_ action: @escaping () -> Void) -> () -> Void {
        { [weak self] in if self?.tapsAllowed != false { action() } }
    }

    func openDrawer() {
        drawerOpenings += 1
        drawer = true
    }

    func closeDrawer() {
        drawer = false
    }
}
