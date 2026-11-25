import Foundation
import SwiftUI
import TeleplyModel
import WebKit

/// 代码页 (file-preview design §6.2): highlight.js 11.12.0 from the app's own `Viewer` folder, with line numbers, wrap,
/// find, copy and the line the answer named. It loads nothing but those files and the one text; the private scheme has
/// no cookies and no bridge, http and https are blocked, and a navigation that is not the code page is cancelled.
/// Past 200 KB the page shows line numbers only; a cut text says what part of it is here.
struct CodeViewer: UIViewRepresentable {
    let text: String
    let file: JSONValue
    /// `lang=text` draws plain text; `code` keeps the file's language.
    let lang: String
    let truncated: Bool
    let totalSize: Int64
    let dark: Bool

    func makeCoordinator() -> Coordinator { Coordinator(text: text) }

    func makeUIView(context: Context) -> WKWebView {
        let configuration = WKWebViewConfiguration()
        configuration.websiteDataStore = .nonPersistent()
        configuration.setURLSchemeHandler(context.coordinator.handler, forURLScheme: viewerScheme)
        configuration.preferences.javaScriptCanOpenWindowsAutomatically = false
        configuration.defaultWebpagePreferences.allowsContentJavaScript = true
        // No bridge, no file access, no media autoplay of its own.
        configuration.preferences.javaScriptEnabled = true
        let view = WKWebView(frame: .zero, configuration: configuration)
        view.navigationDelegate = context.coordinator
        view.isOpaque = false
        view.backgroundColor = dark ? UIColor(red: 0x0d / 255, green: 0x11 / 255, blue: 0x17 / 255, alpha: 1)
                                   : UIColor(white: 1, alpha: 1)
        context.coordinator.load(view, text: text, file: file, lang: lang, truncated: truncated,
                                 totalSize: totalSize, dark: dark)
        return view
    }

    func updateUIView(_ view: WKWebView, context: Context) {
        context.coordinator.load(view, text: text, file: file, lang: lang, truncated: truncated,
                                 totalSize: totalSize, dark: dark)
    }

    static func dismantleUIView(_ view: WKWebView, coordinator: Coordinator) {
        view.stopLoading()
        view.navigationDelegate = nil
    }

    final class Coordinator: NSObject, WKNavigationDelegate {
        fileprivate let handler: ViewerSchemeHandler
        private var last: String?

        init(text: String) {
            self.handler = ViewerSchemeHandler(text: text)
        }

        func load(_ view: WKWebView, text: String, file: JSONValue, lang: String, truncated: Bool,
                  totalSize: Int64, dark: Bool) {
            let address = codePageURLString(dark: dark, lang: lang, line: file["line"].int(), truncated: truncated,
                                            shownBytes: text.utf8.count, totalBytes: Int(totalSize))
            let signature = address + "\u{1F}" + text
            guard signature != last else { return }
            last = signature
            handler.text = text
            guard let url = URL(string: address) else { return }
            view.load(URLRequest(url: url))
            // Code that must not reach the network: http and https are blocked in the page itself, and the view is
            // told again below for anything that is not the page's own scheme.
            let rules = #"[{"trigger":{"url-filter":"^https?://"},"action":{"type":"block"}}]"#
            WKContentRuleListStore.default().compileContentRuleList(forIdentifier: "teleply-viewer-offline",
                                                                   encodedContentRuleList: rules) { list, _ in
                guard let list else { return }
                DispatchQueue.main.async { [weak view] in view?.configuration.userContentController.add(list) }
            }
        }

        // Only the code page's own scheme and host are navigated to; every other address is stopped.
        func webView(_ webView: WKWebView, decidePolicyFor action: WKNavigationAction,
                     decisionHandler: @escaping @MainActor @Sendable (WKNavigationActionPolicy) -> Void) {
            guard let url = action.request.url else { return decisionHandler(.cancel) }
            decisionHandler(url.scheme == viewerScheme && url.host == viewerHost ? .allow : .cancel)
        }
    }
}

/// The page's only sources: the files in the app's `Viewer` folder and the one text, by exact name. `..`, a backslash,
/// a nested path or anything not in the list is a 404.
private final class ViewerSchemeHandler: NSObject, WKURLSchemeHandler {    var text: String

    init(text: String) {
        self.text = text
    }

    func webView(_ webView: WKWebView, start task: any WKURLSchemeTask) {
        guard let url = task.request.url, url.scheme == viewerScheme, url.host == viewerHost,
              let name = viewerResourceName(url.path) else {
            Self.missing(task)
            return
        }
        let data: Data
        if name == "text" {
            data = Data(text.utf8)
        } else {
            guard let source = Bundle.main.url(forResource: name, withExtension: nil, subdirectory: "Viewer"),
                  let read = try? Data(contentsOf: source) else {
                Self.missing(task)
                return
            }
            data = read
        }
        guard let response = HTTPURLResponse(url: url, statusCode: 200, httpVersion: "HTTP/1.1",
                                             headerFields: ["Content-Type": viewerResourceMime(name)]) else {
            Self.missing(task)
            return
        }
        task.didReceive(response)
        task.didReceive(data)
        task.didFinish()
    }

    func webView(_ webView: WKWebView, stop task: any WKURLSchemeTask) {}

    private static func missing(_ task: any WKURLSchemeTask) {
        guard let url = task.request.url,
              let response = HTTPURLResponse(url: url, statusCode: 404, httpVersion: "HTTP/1.1", headerFields: nil) else {
            task.didFailWithError(URLError(.fileDoesNotExist))
            return
        }
        task.didReceive(response)
        task.didReceive(Data())
        task.didFinish()
    }
}
