import PDFKit
import SwiftUI
import TeleplyModel

/// A PDF inside a file's page (web artifact-preview: an iframe; Android: PdfRenderer): its pages one under another,
/// fitted to the width, zoomable from fit width to [maxPdfZoom]× fit width. It scrolls and zooms inside its own box;
/// the page around it scrolls past it. The page number sits at the bottom right and follows the page in view (§6.2).
/// The file must stay while it is shown: a kept original does, a temporary copy is deleted when the page goes.
struct PDFPreview: View {
    let url: URL
    @State private var page = 1
    @State private var pages = 0

    var body: some View {
        ZStack(alignment: .bottomTrailing) {
            PDFKitView(url: url, page: $page, pages: $pages)
            if pages > 0 {
                Text("\(page) / \(pages)")
                    .noteFont()
                    .foregroundStyle(Palette.muted)
                    .monospacedDigit()
                    .padding(.horizontal, 8)
                    .padding(.vertical, 4)
                    .background(Palette.sheet.opacity(0.9), in: Capsule())
                    .padding(12)
                    .accessibilityLabel(Text("第 \(page) 页，共 \(pages) 页"))
            }
        }
    }
}

private struct PDFKitView: UIViewRepresentable {
    let url: URL
    @Binding var page: Int
    @Binding var pages: Int

    func makeCoordinator() -> Coordinator { Coordinator(page: $page, pages: $pages) }

    func makeUIView(context: Context) -> FitPDFView {
        let view = FitPDFView()
        view.displayMode = .singlePageContinuous
        view.displayDirection = .vertical
        view.backgroundColor = UIColor(named: "Panel") ?? .secondarySystemBackground
        view.autoScales = false
        view.document = PDFDocument(url: url)
        pages = view.document?.pageCount ?? 0
        page = 1
        NotificationCenter.default.addObserver(context.coordinator, selector: #selector(Coordinator.pageChanged(_:)),
                                               name: .PDFViewPageChanged, object: view)
        return view
    }

    func updateUIView(_ view: FitPDFView, context: Context) {
        guard view.document?.documentURL != url else { return }
        view.document = PDFDocument(url: url)
        pages = view.document?.pageCount ?? 0
        page = 1
        view.setNeedsLayout()
    }

    static func dismantleUIView(_ view: FitPDFView, coordinator: Coordinator) {
        NotificationCenter.default.removeObserver(coordinator, name: .PDFViewPageChanged, object: view)
    }

    final class Coordinator: NSObject {
        let page: Binding<Int>
        let pages: Binding<Int>

        init(page: Binding<Int>, pages: Binding<Int>) {
            self.page = page
            self.pages = pages
        }

        @objc func pageChanged(_ note: Notification) {
            guard let view = note.object as? PDFView, let document = view.document, let current = view.currentPage else { return }
            let index = document.index(for: current)
            guard index != NSNotFound else { return }
            page.wrappedValue = index + 1
            pages.wrappedValue = document.pageCount
        }
    }
}

/// A PDFView zoomed from fit width up to 3× fit width (§6.2): a pinch out never shrinks a page below the width it is
/// drawn at, and a pinch in stops at three times that. Turning the phone keeps a page that was at fit width at the new
/// fit width, and a zoomed page within the new limits.
private final class FitPDFView: PDFView {
    /// The scale at which the page fits the view, as of the last layout.
    private var fit: CGFloat = 0

    override func layoutSubviews() {
        super.layoutSubviews()
        guard let document = self.document, document.pageCount > 0 else { return }
        let newFit = scaleFactorForSizeToFit
        guard newFit.isFinite, newFit > 0 else { return }
        let wasAtFit = fit <= 0 || abs(scaleFactor - fit) < 0.01
        fit = newFit
        minScaleFactor = newFit
        maxScaleFactor = newFit * CGFloat(maxPdfZoom)
        let wanted = wasAtFit ? newFit : min(max(scaleFactor, newFit), newFit * CGFloat(maxPdfZoom))
        if abs(scaleFactor - wanted) > 0.001 { scaleFactor = wanted }
    }
}
