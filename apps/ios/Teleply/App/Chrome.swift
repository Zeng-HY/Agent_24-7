import SwiftUI

/// What the window shows on top of the pages: 设置 and the sidebar. Kept apart from the app's state because only
/// the screen cares (Android ReaderViewModel keeps its own settings and drawer flags for the same reason).
@Observable
final class Chrome {
    var settings = false
    private(set) var drawer = false
    /// Goes up each time the sidebar opens, so its sources arrive again (web lbrRowIn).
    private(set) var drawerOpenings = 0

    func openDrawer() {
        drawerOpenings += 1
        drawer = true
    }

    func closeDrawer() {
        drawer = false
    }
}
