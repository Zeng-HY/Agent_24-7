import PDFKit
import SwiftUI

/// A PDF inside a file's page (web artifact-preview: an iframe; Android: PdfRenderer): its pages one under another,
/// fitted to the width. It scrolls and zooms inside its own box; the page around it scrolls past it, as the HTML
/// preview does. The file must stay while it is shown (the workspace deletes it when the page goes).
struct PDFPreview: UIViewRepresentable {
    let url: URL

    func makeUIView(context: Context) -> PDFView {
        let view = PDFView()
        view.displayMode = .singlePageContinuous
        view.displayDirection = .vertical
        view.backgroundColor = UIColor(named: "Panel") ?? .secondarySystemBackground
        view.document = PDFDocument(url: url)
        view.autoScales = true
        return view
    }

    func updateUIView(_ view: PDFView, context: Context) {
        guard view.document?.documentURL != url else { return }
        view.document = PDFDocument(url: url)
        view.autoScales = true
    }
}
