import SwiftUI
import TeleplyModel
import WebKit

/// Where one document's page stands (design 4.1): the system converter still at work with it, the file shown, or the
/// system's own error page instead.
enum DocumentPreviewState: Equatable {
    case loading
    case shown
    case failed
}

/// A Word, Excel or PowerPoint file, a picture the computer lists as a plain file, a sound or a video, inside its
/// page and drawn by the phone itself (user 10-28: "点开直接调用快速预览，不要这样转换了"): the web view hands Office
/// files to the system's Quick Look converter, as Safari and 快速查看 do, so nothing goes back to the computer. It
/// scrolls and zooms inside its own box. A throwaway web view with no cookie of this app and no bridge to it, allowed
/// to read this one file; a tapped link opens in Safari. The file must stay while it is shown (the workspace deletes
/// it when the page goes).
///
/// The converter cannot read every file (11-26 P3): it says so in a page of its own and finishes, or the load fails
/// outright. Both are reported through [onState] as `.failed`, so that the page can offer another way.
struct DocumentPreview: UIViewRepresentable {
    let url: URL
    /// Told on the main thread: `.loading` when the view starts, then `.shown` or `.failed` once the page has finished.
    let onState: (DocumentPreviewState) -> Void

    func makeCoordinator() -> Coordinator {
        Coordinator(onState: onState)
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
        view.navigationDelegate = nil
    }

    final class Coordinator: NSObject, WKNavigationDelegate {
        /// The page's words as the web view would read them: the first 400 characters of them, and only from a page
        /// that had fewer than 400. A longer page is a document, and the converter's error page is short (design 4.1).
        private static let bodyScript = "(function(){try{var t=(document.body&&document.body.innerText)||'';"
            + "return t.length<400?t:'';}catch(e){return '';}})()"

        private let onState: (DocumentPreviewState) -> Void

        init(onState: @escaping (DocumentPreviewState) -> Void) {
            self.onState = onState
        }

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

        /// The page finished. The converter's own error page finishes like any other, so its words are read (P3).
        func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
            // The completion-handler form on purpose, as above: Xcode 27.1 crashes bridging the async form.
            webView.evaluateJavaScript(Self.bodyScript) { value, _ in
                // No words to read (the script did not run): nothing says it failed, so the file is shown as it is.
                let body = value as? String ?? ""
                Task { @MainActor in
                    self.finished(body)
                }
            }
        }

        /// The page's words say whether the system could convert the file.
        private func finished(_ body: String) {
            onState(systemPreviewFailed(body) ? .failed : .shown)
        }

        func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: any Error) {
            failed(error)
        }

        func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: any Error) {
            failed(error)
        }

        /// A failed load is the failure page; a cancelled one is this page going away, not a failure.
        private func failed(_ error: any Error) {
            let ns = error as NSError
            guard ns.domain != NSURLErrorDomain || ns.code != NSURLErrorCancelled else { return }
            onState(.failed)
        }
    }
}

/// One document's page (design 4.1): 正在打开… while the system converts it (a large Word file takes ten seconds and
/// more), the file itself, or — when the phone's own preview cannot show it — our page with the file's type mark, the
/// reason in plain words and the ways out: its PDF if the answer had one, another app, or 保存到文件.
///
/// The state belongs to this view, and the page gives it to each file's own copy (`.id(url)`), so another file starts
/// again from 正在打开….
struct DocumentPreviewPage: View {
    let url: URL
    let name: String
    /// The answer's PDF of the same name: 看 PDF 版, which opens that PDF's own page.
    let pdf: FileRef?
    /// A download for saving or sharing is already under way: its buttons wait.
    let busy: Bool
    let openPDF: (FileRef) -> Void
    let share: () -> Void
    let save: () -> Void
    @State private var state = DocumentPreviewState.loading

    var body: some View {
        Group {
            if state == .failed {
                DocumentPreviewFailure(name: name, pdf: pdf, busy: busy, openPDF: openPDF, share: share, save: save)
            } else {
                ZStack {
                    DocumentPreview(url: url) { state = $0 }
                    if state == .loading {
                        VStack(spacing: 10) {
                            ProgressView()
                            Text("正在打开…")
                                .noteFont()
                                .foregroundStyle(Palette.muted)
                        }
                        .frame(maxWidth: .infinity, maxHeight: .infinity)
                        .background(Palette.page)
                        .accessibilityElement(children: .combine)
                        .accessibilityLabel(Text("正在打开…"))
                    }
                }
            }
        }
    }
}

/// The page a file gets when the phone's converter cannot show it (design 4.1): the type mark large, the name, what
/// went wrong in the user's own terms, and what can be done instead — the same document as a PDF when the answer has
/// one, another app from the system's share sheet, or saving it to the phone.
private struct DocumentPreviewFailure: View {
    let name: String
    let pdf: FileRef?
    let busy: Bool
    let openPDF: (FileRef) -> Void
    let share: () -> Void
    let save: () -> Void

    var body: some View {
        ScrollView {
            VStack(spacing: 12) {
                FileTypeIcon(name: name, size: 96)
                    .padding(.top, 48)
                Text(name)
                    .bodyFont(.medium)
                    .foregroundStyle(Palette.ink)
                    .multilineTextAlignment(.center)
                    .textSelection(.enabled)
                Text("iPhone 自带的预览打不开这份文件")
                    .headingFont()
                    .foregroundStyle(Palette.ink)
                    .multilineTextAlignment(.center)
                Text("文件本身没有问题。它太大或太复杂（比如几百页、几百张表），苹果系统自带的转换器处理不了。")
                    .noteFont()
                    .foregroundStyle(Palette.muted)
                    .multilineTextAlignment(.center)
                VStack(spacing: 8) {
                    if let pdf {
                        Button("看 PDF 版", systemImage: "doc.richtext") { openPDF(pdf) }
                            .buttonStyle(PillStyle(kind: .primary))
                    }
                    Button("用其他应用打开", systemImage: "square.and.arrow.up", action: share)
                        .buttonStyle(PillStyle(kind: pdf == nil ? .primary : .secondary))
                    Button("保存到文件", systemImage: "square.and.arrow.down", action: save)
                        .buttonStyle(PillStyle())
                }
                .disabled(busy)
                .padding(.top, 8)
            }
            .frame(maxWidth: 520)
            .frame(maxWidth: .infinity)
            .padding(.horizontal, 20)
            .padding(.bottom, 32)
        }
        .accessibilityElement(children: .contain)
    }
}
