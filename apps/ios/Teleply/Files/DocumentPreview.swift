import SwiftUI
import WebKit

/// A Word, Excel or PowerPoint file, a picture the computer lists as a plain file, a sound or a video, inside its
/// page and drawn by the phone itself (user 10-28: "点开直接调用快速预览，不要这样转换了"): the web view hands Office
/// files to the system's Quick Look converter, as Safari and 快速查看 do, so nothing goes back to the computer. It
/// scrolls and zooms inside its own box. A throwaway web view with no cookie of this app and no bridge to it, allowed
/// to read this one file; a tapped link opens in Safari. The file must stay while it is shown (the workspace deletes
/// it when the page goes).
struct DocumentPreview: UIViewRepresentable {
    let url: URL

    func makeCoordinator() -> Coordinator {
        Coordinator()
    }

    func makeUIView(context: Context) -> WKWebView {
        let configuration = WKWebViewConfiguration()
        configuration.websiteDataStore = .nonPersistent()
        configuration.preferences.javaScriptCanOpenWindowsAutomatically = false
        configuration.allowsInlineMediaPlayback = true
        let view = WKWebView(frame: .zero, configuration: configuration)
        view.navigationDelegate = context.coordinator
        // On white, as a document is printed and as HtmlPreview shows a page.
        view.isOpaque = false
        view.backgroundColor = .white
        view.loadFileURL(url, allowingReadAccessTo: url)
        return view
    }

    func updateUIView(_ view: WKWebView, context: Context) {}

    static func dismantleUIView(_ view: WKWebView, coordinator: Coordinator) {
        view.stopLoading()
    }

    final class Coordinator: NSObject, WKNavigationDelegate {
        // The file and jumps within it stay; a tapped link opens in Safari; nothing from outside replaces the file.
        // The completion-handler form on purpose, as in HtmlPreview: Xcode 27.1 crashes bridging the async form.
        func webView(_ webView: WKWebView, decidePolicyFor action: WKNavigationAction,
                     decisionHandler: @escaping @MainActor @Sendable (WKNavigationActionPolicy) -> Void) {
            guard let url = action.request.url else { return decisionHandler(.cancel) }
            let outside = ["http", "https", "mailto", "tel"].contains(url.scheme?.lowercased() ?? "")
            if action.navigationType == .linkActivated && outside {
                UIApplication.shared.open(url)
            }
            decisionHandler(outside && action.targetFrame?.isMainFrame != false ? .cancel : .allow)
        }
    }
}
