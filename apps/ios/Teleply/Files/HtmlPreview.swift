import SwiftUI
import TeleplyModel
import TeleplyState
import WebKit

/// The made-up scheme a page's own files are asked from: the files beside it on the computer, as this
/// conversation lists them (Android PreviewHost).
private let previewScheme = "teleply-preview"

/// The page's base address: its own folder, so that relative paths (with ..) resolve as on the computer.
private func previewBase(_ filePath: String) -> URL? {
    let folder = filePath.replacingOccurrences(of: "\\", with: "/").split(separator: "/").dropLast()
    let encoded = folder.map { $0.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed.subtracting(CharacterSet(charactersIn: "/"))) ?? String($0) }
    return URL(string: previewScheme + "://page/" + encoded.joined(separator: "/") + (encoded.isEmpty ? "" : "/"))
}

/// The type a file beside the page is handed over as; anything else goes as plain bytes.
private let resourceTypes = [
    "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "webp": "image/webp", "gif": "image/gif", "svg": "image/svg+xml",
    "css": "text/css", "js": "text/javascript", "mjs": "text/javascript", "json": "application/json", "html": "text/html", "htm": "text/html",
    "woff": "font/woff", "woff2": "font/woff2", "ttf": "font/ttf", "otf": "font/otf", "txt": "text/plain", "csv": "text/csv",
]

/// 查看页面 of an HTML file (spec 8.3; Android HtmlPreview): the page as a browser shows it, scripts and what it
/// loads from the internet included (user 2026-10-25: "可以允许加载html文件，不要禁止"). Its own pictures, styles and
/// scripts beside it come from the files this conversation lists, matched exactly by path. What stays apart: a
/// throwaway web view with no cookie of this app and no bridge to it, no reading of the phone's files, and a
/// tapped link opens in Safari; the page cannot go elsewhere by itself.
struct HtmlPreview: UIViewRepresentable {
    let model: AppModel
    let source: String
    let file: JSONValue

    func makeCoordinator() -> Coordinator {
        Coordinator(model: model, file: file)
    }

    func makeUIView(context: Context) -> WKWebView {
        let configuration = WKWebViewConfiguration()
        configuration.websiteDataStore = .nonPersistent()
        configuration.setURLSchemeHandler(context.coordinator, forURLScheme: previewScheme)
        configuration.preferences.javaScriptCanOpenWindowsAutomatically = false
        configuration.defaultWebpagePreferences.allowsContentJavaScript = true
        let view = WKWebView(frame: .zero, configuration: configuration)
        view.navigationDelegate = context.coordinator
        view.uiDelegate = context.coordinator
        view.isOpaque = false
        view.backgroundColor = .white
        let page = "<meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">" + source
        view.loadHTMLString(page, baseURL: previewBase(file["path"].string()))
        return view
    }

    func updateUIView(_ view: WKWebView, context: Context) {}

    static func dismantleUIView(_ view: WKWebView, coordinator: Coordinator) {
        view.stopLoading()
        coordinator.stop()
    }

    final class Coordinator: NSObject, WKNavigationDelegate, WKUIDelegate, WKURLSchemeHandler {
        let model: AppModel
        let file: JSONValue
        /// At most 64 files and 32 MB in all for one page.
        private var count = 0
        private var budget = 32 * 1024 * 1024
        private var loads: [ObjectIdentifier: Task<Void, Never>] = [:]

        init(model: AppModel, file: JSONValue) {
            self.model = model
            self.file = file
        }

        func stop() {
            for load in loads.values { load.cancel() }
            loads = [:]
        }

        // A jump within the page stays; a tapped link opens in Safari; nothing else leaves. The completion-handler
        // form on purpose: Xcode 27.1 crashes bridging the async form of such delegate methods.
        func webView(_ webView: WKWebView, decidePolicyFor action: WKNavigationAction,
                     decisionHandler: @escaping @MainActor @Sendable (WKNavigationActionPolicy) -> Void) {
            guard let url = action.request.url else { return decisionHandler(.cancel) }
            if url.scheme == previewScheme {
                decisionHandler(action.navigationType == .linkActivated && url.fragment == nil ? .cancel : .allow)
                return
            }
            if url.scheme == "about" || url.scheme == "data" {
                decisionHandler(.allow)
                return
            }
            if action.navigationType == .linkActivated, ["http", "https"].contains(url.scheme ?? "") {
                UIApplication.shared.open(url)
            }
            decisionHandler(action.targetFrame?.isMainFrame == false ? .allow : .cancel)
        }

        // A new window is never opened; a tapped link that asked for one goes to Safari.
        func webView(_ webView: WKWebView, createWebViewWith configuration: WKWebViewConfiguration, for action: WKNavigationAction,
                     windowFeatures: WKWindowFeatures) -> WKWebView? {
            if action.navigationType == .linkActivated, let url = action.request.url, ["http", "https"].contains(url.scheme ?? "") {
                UIApplication.shared.open(url)
            }
            return nil
        }

        func webView(_ webView: WKWebView, start task: any WKURLSchemeTask) {
            let url = task.request.url
            let path = String((url?.path ?? "").drop { $0 == "/" })
            let ext = (path as NSString).pathExtension.lowercased()
            count += 1
            guard count <= 64, !path.isEmpty else {
                Self.missing(task)
                return
            }
            let id = ObjectIdentifier(task)
            loads[id] = Task { [weak self] in
                guard let self else { return }
                let data = await self.model.workspace.previewResource(for: self.file, path: path)
                guard !Task.isCancelled, self.loads[id] != nil else { return }
                self.loads[id] = nil
                guard let data, self.budget - data.count >= 0, let url else {
                    Self.missing(task)
                    return
                }
                self.budget -= data.count
                task.didReceive(URLResponse(url: url, mimeType: resourceTypes[ext] ?? "application/octet-stream", expectedContentLength: data.count, textEncodingName: nil))
                task.didReceive(data)
                task.didFinish()
            }
        }

        func webView(_ webView: WKWebView, stop task: any WKURLSchemeTask) {
            loads.removeValue(forKey: ObjectIdentifier(task))?.cancel()
        }

        private static func missing(_ task: any WKURLSchemeTask) {
            guard let url = task.request.url, let response = HTTPURLResponse(url: url, statusCode: 404, httpVersion: "HTTP/1.1", headerFields: nil) else {
                task.didFailWithError(URLError(.fileDoesNotExist))
                return
            }
            task.didReceive(response)
            task.didReceive(Data())
            task.didFinish()
        }
    }
}
