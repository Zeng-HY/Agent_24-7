import SwiftUI
import UIKit

/// iPadOS 26 draws a window's controls — the three dots for close, minimize and full screen — at its top-left. When
/// the window is not the whole screen they sit over the content, and a title bar the app draws itself has to leave
/// room for them (the system's own navigation bars do that by themselves).
enum WindowControls {
    /// The room a title bar drawn by the app leaves at its leading edge. 72 points clears the three dots (about 68
    /// wide) with a small margin; a full-screen window and a phone get 0.
    @MainActor static var inset: CGFloat {
        guard UIDevice.current.userInterfaceIdiom == .pad,
              let scene = UIApplication.shared.connectedScenes.compactMap({ $0 as? UIWindowScene }).first
        else { return 0 }
        let screen = scene.screen.bounds.size
        // The largest window in the scene is the app's own (a sheet is a window of its own and is smaller).
        let windows = scene.windows.filter { !$0.isHidden }
        guard let window = windows.max(by: { $0.bounds.width * $0.bounds.height < $1.bounds.width * $1.bounds.height })
        else { return 0 }
        let size = window.bounds.size
        let whole = (abs(size.width - screen.width) < 2 && abs(size.height - screen.height) < 2)
            || (abs(size.width - screen.height) < 2 && abs(size.height - screen.width) < 2)
        return whole ? 0 : 72
    }
}
