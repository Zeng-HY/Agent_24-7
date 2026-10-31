import SafariServices
import UIKit

/// A web page shown inside 遥应 by the system's Safari view, over whatever is on screen (设置 included), with its own
/// 完成 to come back: 隐私政策 opens here rather than switching to Safari (App Review). The page gets none of the app's
/// sign-in or cookies.
enum InAppBrowser {
    static func open(_ url: URL) {
        let scenes = UIApplication.shared.connectedScenes.compactMap { $0 as? UIWindowScene }
        guard let scene = scenes.first(where: { $0.activationState == .foregroundActive }) ?? scenes.first,
              var top = scene.keyWindow?.rootViewController else { return }
        while let next = top.presentedViewController, !next.isBeingDismissed { top = next }
        top.present(SFSafariViewController(url: url), animated: true)
    }
}
