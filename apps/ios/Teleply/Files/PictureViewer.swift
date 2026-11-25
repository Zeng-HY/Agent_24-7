import Foundation
import ImageIO
import QuickLook
import SwiftUI
import TeleplyModel
import UIKit

/// 看图页 (§6.2): fills the screen, one picture per page, 2/5 at the top. A pinch zooms to 8×, a double tap goes
/// between 1× and 2.5×, and while enlarged a sideways drag moves the picture instead of turning the page. The 1280
/// thumb (or 2048 for an SVG or a big picture) shows first; a picture of at most 30 MB then swaps in its original from
/// the phone's kept copy, while a larger one stays on the 2048 thumb. GIFs play; the ⋯ menu saves, shares, opens with
/// Quick Look or another app, or opens the file's page. The close button and a downward swipe close it.
struct PictureViewerPage: View {
    let model: AppModel
    @State private var index = 0
    @State private var saving: URL?
    @State private var sharing: URL?
    @State private var quickLook: URL?
    @State private var note: String?

    var body: some View {
        let workspace = model.workspace
        let files = workspace.pictureFiles
        ZStack {
            Color.black.ignoresSafeArea()
            if files.isEmpty {
                ProgressView().tint(.white)
            } else {
                PicturePager(files: files, index: min(max(workspace.pictureIndex, 0), files.count - 1), current: $index,
                             thumb: { await workspace.answerThumb($0, width: $1) },
                             original: { await workspace.cachedAnswerFile($0) },
                             onClose: { workspace.close() })
                    .ignoresSafeArea()
                VStack(spacing: 0) {
                    topBar(files)
                    Spacer(minLength: 0)
                    if let note {
                        Text(note)
                            .noteFont()
                            .foregroundStyle(.white)
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .padding(.horizontal, 16)
                            .padding(.vertical, 10)
                            .background(.black.opacity(0.45))
                    }
                }
            }
        }
        .statusBarHidden()
        .onAppear { index = min(max(workspace.pictureIndex, 0), max(files.count - 1, 0)) }
        .fileMover(isPresented: Binding(get: { saving != nil }, set: { if !$0 { saving = nil } }), file: saving) { result in
            if case .success = result { note = "已保存到所选位置" } else { note = "没保存" }
            saving = nil
        }
        .sheet(isPresented: Binding(get: { sharing != nil }, set: { if !$0 { sharing = nil } })) {
            if let sharing {
                ShareSheet(items: [sharing]) { done in note = done ? "已分享" : nil }
                    .presentationDetents([.medium, .large])
            }
        }
        .quickLookPreview($quickLook)
    }

    private func topBar(_ files: [FileRef]) -> some View {
        let current = files[min(max(index, 0), files.count - 1)]
        return HStack(spacing: 8) {
            Button { model.workspace.close() } label: {
                Image(systemName: "xmark")
                    .font(.system(size: 17, weight: .semibold))
                    .foregroundStyle(.white)
                    .frame(width: 44, height: 44)
                    .contentShape(Rectangle())
            }
            .accessibilityLabel(Text("关闭"))
            Text("\(index + 1)/\(files.count)")
                .bodyFont()
                .foregroundStyle(.white)
                .monospacedDigit()
                .accessibilityLabel(Text("第 \(index + 1) 张，共 \(files.count) 张"))
            Spacer(minLength: 0)
            Menu {
                Button("保存到手机", systemImage: "square.and.arrow.down") { copy(current) { saving = $0 } }
                Button("分享", systemImage: "square.and.arrow.up") { copy(current) { sharing = $0 } }
                if quickLooks(current.name) {
                    Button("用快速查看打开", systemImage: "eye") { copy(current) { quickLook = $0 } }
                } else {
                    Button("用其他应用打开", systemImage: "square.and.arrow.up") { copy(current) { sharing = $0 } }
                }
                Button("在文件页打开", systemImage: "doc.text") { openFilePage(current) }
            } label: {
                Image(systemName: "ellipsis")
                    .font(.system(size: 18, weight: .semibold))
                    .foregroundStyle(.white)
                    .frame(width: 44, height: 44)
                    .contentShape(Rectangle())
            }
            .accessibilityLabel(Text("图片菜单"))
        }
        .padding(.horizontal, 8)
        .padding(.top, 4)
        .background(.black.opacity(0.28))
    }

    private func copy(_ file: FileRef, then: @escaping (URL) -> Void) {
        guard model.workspace.transferring == false else { return }
        Task {
            do {
                then(try await model.workspace.copyForViewer(file))
            } catch is CancellationError {
                note = "已取消"
            } catch {
                note = describe(error)
            }
        }
    }

    private func openFilePage(_ file: FileRef) {
        model.workspace.close()
        Task {
            try? await Task.sleep(for: .milliseconds(120))
            model.workspace.openAnswerFile(file)
        }
    }

    private func quickLooks(_ name: String) -> Bool { FilePage.quickLooks(name.lowercased()) }
}

/// The horizontal pager: a UIScrollView of pages, each a zooming picture. UIKit because a pinch, a double tap and the
/// pager's own sideways drag fight when laid over one another in SwiftUI; while the page shown is enlarged its drag
/// moves the picture and the pager stays still (§6.2).
private struct PicturePager: UIViewRepresentable {
    let files: [FileRef]
    let index: Int
    @Binding var current: Int
    let thumb: (FileRef, Int) async -> Data?
    let original: (FileRef) async -> URL?
    let onClose: () -> Void

    func makeCoordinator() -> Coordinator { Coordinator(self) }

    func makeUIView(context: Context) -> PicturePagerView {
        let view = PicturePagerView(files: files, index: index, thumb: thumb, original: original)
        view.onIndex = { [weak coordinator = context.coordinator] next in
            guard let coordinator else { return }
            if coordinator.parent.current != next { coordinator.parent.current = next }
        }
        view.onClose = onClose
        return view
    }

    func updateUIView(_ view: PicturePagerView, context: Context) {
        context.coordinator.parent = self
        view.update(files: files, thumb: thumb, original: original, onClose: onClose)
    }

    final class Coordinator {
        var parent: PicturePager
        init(_ parent: PicturePager) { self.parent = parent }
    }
}

/// The pager's own view: a paging scroll view, its pages, the page in view and the close gesture.
private final class PicturePagerView: UIView, UIScrollViewDelegate, UIGestureRecognizerDelegate {
    private let pages = UIScrollView()
    private var pageViews: [PicturePageView] = []
    private var files: [FileRef] = []
    private var thumb: (FileRef, Int) async -> Data?
    private var original: (FileRef) async -> URL?
    private var current = 0
    private var built = false
    private var lastWidth: CGFloat = 0
    var onIndex: ((Int) -> Void)?
    var onClose: (() -> Void)?

    init(files: [FileRef], index: Int, thumb: @escaping (FileRef, Int) async -> Data?,
         original: @escaping (FileRef) async -> URL?) {
        self.files = files
        self.thumb = thumb
        self.original = original
        self.current = min(max(index, 0), max(files.count - 1, 0))
        super.init(frame: .zero)
        backgroundColor = .black
        pages.backgroundColor = .black
        pages.isPagingEnabled = true
        pages.showsHorizontalScrollIndicator = false
        pages.showsVerticalScrollIndicator = false
        pages.delegate = self
        addSubview(pages)
        let down = UISwipeGestureRecognizer(target: self, action: #selector(swipedDown))
        down.direction = .down
        down.delegate = self
        down.cancelsTouchesInView = false
        addGestureRecognizer(down)
        build()
    }

    required init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }

    func update(files: [FileRef], thumb: @escaping (FileRef, Int) async -> Data?,
                original: @escaping (FileRef) async -> URL?, onClose: @escaping () -> Void) {
        self.thumb = thumb
        self.original = original
        self.onClose = onClose
        if files != self.files {
            self.files = files
            build()
        }
        if let page = currentPage { pages.isScrollEnabled = !page.isZoomed }
    }

    private var currentPage: PicturePageView? {
        guard pageViews.indices.contains(current) else { return nil }
        return pageViews[current]
    }

    private func build() {
        pageViews.forEach { $0.removeFromSuperview() }
        current = min(max(current, 0), max(files.count - 1, 0))
        pageViews = files.map { file in
            let page = PicturePageView(file: file, thumb: thumb, original: original)
            page.onZoomChange = { [weak self, weak page] zoomed in
                guard let self, let page, self.currentPage === page else { return }
                self.pages.isScrollEnabled = !zoomed
                if !zoomed { page.resetPan() }
            }
            pages.addSubview(page)
            return page
        }
        built = true
        lastWidth = 0
        setNeedsLayout()
        layoutIfNeeded()
        jump(to: current)
    }

    private func jump(to index: Int) {
        guard built, bounds.width > 0 else { return }
        pages.setContentOffset(CGPoint(x: CGFloat(index) * bounds.width, y: 0), animated: false)
        if let page = pageViews[safe: index] {
            pages.isScrollEnabled = !page.isZoomed
        }
    }

    override func layoutSubviews() {
        super.layoutSubviews()
        pages.frame = bounds
        let width = bounds.width
        guard width > 0 else { return }
        for (index, page) in pageViews.enumerated() {
            page.frame = CGRect(x: CGFloat(index) * width, y: 0, width: width, height: bounds.height)
        }
        pages.contentSize = CGSize(width: width * CGFloat(pageViews.count), height: bounds.height)
        if width != lastWidth {
            lastWidth = width
            pages.setContentOffset(CGPoint(x: CGFloat(current) * width, y: 0), animated: false)
        }
    }

    func scrollViewDidEndDecelerating(_ scrollView: UIScrollView) { settle() }
    func scrollViewDidEndDragging(_ scrollView: UIScrollView, willDecelerate decelerate: Bool) {
        if !decelerate { settle() }
    }

    private func settle() {
        guard bounds.width > 0 else { return }
        let next = min(max(Int(round(pages.contentOffset.x / bounds.width)), 0), max(pageViews.count - 1, 0))
        guard next != current else { return }
        pageViews[safe: current]?.resetZoom()
        current = next
        onIndex?(next)
        if let page = pageViews[safe: next] { pages.isScrollEnabled = !page.isZoomed }
    }

    @objc private func swipedDown() {
        guard currentPage?.isZoomed != true else { return }
        onClose?()
    }

    func gestureRecognizer(_ gestureRecognizer: UIGestureRecognizer,
                           shouldRecognizeSimultaneouslyWith other: UIGestureRecognizer) -> Bool { true }
}

/// One picture in the viewer: a zooming scroll view, its double tap, and the thumb-then-original loading (§6.2).
private final class PicturePageView: UIView, UIScrollViewDelegate {
    private let scroll = UIScrollView()
    private let imageView = UIImageView()
    private let label = UILabel()
    private let file: FileRef
    private let thumb: (FileRef, Int) async -> Data?
    private let original: (FileRef) async -> URL?
    private var highRes = false
    private var loading = false
    var onZoomChange: ((Bool) -> Void)?

    var isZoomed: Bool { !pagerTurnsAt(Float(scroll.zoomScale)) }

    init(file: FileRef, thumb: @escaping (FileRef, Int) async -> Data?, original: @escaping (FileRef) async -> URL?) {
        self.file = file
        self.thumb = thumb
        self.original = original
        super.init(frame: .zero)
        backgroundColor = .black
        scroll.backgroundColor = .black
        scroll.delegate = self
        scroll.minimumZoomScale = 1
        scroll.maximumZoomScale = CGFloat(maxPictureZoom)
        scroll.bouncesZoom = true
        scroll.bounces = false
        scroll.showsHorizontalScrollIndicator = false
        scroll.showsVerticalScrollIndicator = false
        // At 1× the inner scroll view has nothing to pan, so its pan would still swallow the pager's sideways drag:
        // keep it off until the picture is enlarged (a pinch is a gesture of its own and still works).
        scroll.panGestureRecognizer.isEnabled = false
        addSubview(scroll)
        imageView.contentMode = .scaleAspectFit
        imageView.clipsToBounds = true
        scroll.addSubview(imageView)
        let shownName = file.name.isEmpty ? "图片" : file.name
        label.text = shownName
        label.textColor = .white.withAlphaComponent(0.7)
        label.font = .preferredFont(forTextStyle: .body)
        label.textAlignment = .center
        label.numberOfLines = 2
        label.translatesAutoresizingMaskIntoConstraints = false
        addSubview(label)
        NSLayoutConstraint.activate([
            label.centerXAnchor.constraint(equalTo: centerXAnchor),
            label.centerYAnchor.constraint(equalTo: centerYAnchor),
            label.leadingAnchor.constraint(greaterThanOrEqualTo: leadingAnchor, constant: 24),
            label.trailingAnchor.constraint(lessThanOrEqualTo: trailingAnchor, constant: -24),
        ])
        let doubleTap = UITapGestureRecognizer(target: self, action: #selector(doubleTapped))
        doubleTap.numberOfTapsRequired = 2
        scroll.addGestureRecognizer(doubleTap)
        isAccessibilityElement = true
        accessibilityLabel = "查看 " + shownName
        load()
    }

    required init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }

    override func layoutSubviews() {
        super.layoutSubviews()
        scroll.frame = bounds
        if scroll.zoomScale <= 1.01 {
            imageView.frame = scroll.bounds
            scroll.contentSize = scroll.bounds.size
        }
    }

    private func load() {
        guard !loading else { return }
        loading = true
        Task { @MainActor [weak self] in
            guard let self else { return }
            let width = viewerThumbWidth(self.file, scale: 1)
            if let data = await self.thumb(self.file, width), let image = decodeThumbnail(data, maxPixel: pictureDecodeEdge) {
                self.show(image)
            } else {
                self.fail()
                return
            }
            if viewerLoadsOriginal(self.file) {
                guard let url = await self.original(self.file) else { return }
                if isGIF(self.file.name) {
                    if let image = animatedGIF(url, maxPixel: 1600) { self.show(image) }
                } else if let image = decodeThumbnail(url, maxPixel: pictureDecodeEdge) {
                    self.show(image)
                }
            } else if self.file.view == "svg" {
                // The original is kept for saving and sharing even though the viewer shows the computer's PNG.
                _ = await self.original(self.file)
            }
            self.loading = false
        }
    }

    private func show(_ image: UIImage) {
        label.isHidden = true
        imageView.animationImages = nil
        imageView.image = image
        imageView.stopAnimating()
        if image.images != nil {
            imageView.animationImages = image.images
            imageView.animationDuration = image.duration
            imageView.animationRepeatCount = 0
            imageView.startAnimating()
        }
        scroll.setZoomScale(1, animated: false)
        scroll.contentSize = scroll.bounds.size
        imageView.frame = scroll.bounds
        onZoomChange?(false)
    }

    private func fail() {
        label.isHidden = false
        label.text = "没能打开这张图"
    }

    func resetZoom() { scroll.setZoomScale(1, animated: false); onZoomChange?(false) }
    func resetPan() {
        scroll.contentOffset = .zero
    }

    @objc private func doubleTapped() {
        let target = CGFloat(doubleTapTarget(Float(scroll.zoomScale)))
        scroll.setZoomScale(target, animated: true)
        onZoomChange?(!pagerTurnsAt(Float(target)))
    }

    func viewForZooming(in scrollView: UIScrollView) -> UIView? { imageView }

    func scrollViewDidZoom(_ scrollView: UIScrollView) {
        let dx = max(0, (scrollView.bounds.width - scrollView.contentSize.width) / 2)
        let dy = max(0, (scrollView.bounds.height - scrollView.contentSize.height) / 2)
        scrollView.contentInset = UIEdgeInsets(top: dy, left: dx, bottom: dy, right: dx)
        let turns = pagerTurnsAt(Float(scrollView.zoomScale))
        scrollView.panGestureRecognizer.isEnabled = !turns
        onZoomChange?(!turns)
        // An SVG enlarged past 2× asks the computer for its 4096 copy once (§6.2).
        if file.view == "svg", !highRes, needsSvgHighRes(Float(scrollView.zoomScale), alreadyLoaded: false) {
            highRes = true
            let width = svgThumbWidth(Float(scrollView.zoomScale))
            Task { @MainActor [weak self] in
                guard let self, let data = await self.thumb(self.file, width),
                      let image = decodeThumbnail(data, maxPixel: 4096) else { return }
                self.replace(image)
            }
        }
    }

    private func replace(_ image: UIImage) {
        let zoom = scroll.zoomScale
        imageView.image = image
        scroll.setZoomScale(zoom, animated: false)
    }
}

/// A GIF's frames, its own delays, at most 60 frames and 1600 px each so a many-frame GIF does not fill the phone
/// (§6.2); one frame stays a still picture.
nonisolated func animatedGIF(_ url: URL, maxPixel: Int) -> UIImage? {
    guard let source = CGImageSourceCreateWithURL(url as CFURL, nil) else { return nil }
    let count = min(CGImageSourceGetCount(source), 60)
    guard count > 0 else { return nil }
    let options: [CFString: Any] = [
        kCGImageSourceCreateThumbnailFromImageAlways: true,
        kCGImageSourceCreateThumbnailWithTransform: true,
        kCGImageSourceThumbnailMaxPixelSize: max(64, maxPixel),
    ]
    var frames: [UIImage] = []
    var duration = 0.0
    for index in 0..<count {
        if let image = CGImageSourceCreateThumbnailAtIndex(source, index, options as CFDictionary) {
            frames.append(UIImage(cgImage: image))
        }
        if let properties = CGImageSourceCopyPropertiesAtIndex(source, index, nil) as? [CFString: Any],
           let gif = properties[kCGImagePropertyGIFDictionary] as? [CFString: Any],
           let delay = gif[kCGImagePropertyGIFDelayTime] as? Double {
            duration += max(delay, 0.05)
        }
    }
    guard !frames.isEmpty else { return nil }
    guard frames.count > 1 else { return frames[0] }
    return UIImage.animatedImage(with: frames, duration: duration)
}

private extension Array {
    subscript(safe index: Int) -> Element? { indices.contains(index) ? self[index] : nil }
}
