import ImageIO
import SwiftUI
import TeleplyModel
import UIKit

/// The bubble's width on this phone, in points: an answer's page is at most 820 wide with 20 points either side
/// (ConversationView). The thumbnail width is picked from this in pixels (§6.3, §7), not from points: a 411 pt phone at
/// 3× draws a bubble over 1,000 px wide, where 640 would be soft.
@MainActor
private func answerBubbleWidth() -> CGFloat {
    let screen = UIApplication.shared.connectedScenes.compactMap { $0 as? UIWindowScene }.first?.screen
    let width = screen?.bounds.width ?? 430
    return min(max(width - 40, 200), 820)
}

/// A thumb decoded at about the size it is shown at (§7): ImageIO makes the smaller picture while reading, so a
/// 2400 px photo is never held as 2400 px on a phone.
nonisolated func decodeThumbnail(_ url: URL, maxPixel: Int) -> UIImage? {
    guard let source = CGImageSourceCreateWithURL(url as CFURL, nil) else { return nil }
    let options: [CFString: Any] = [
        kCGImageSourceCreateThumbnailFromImageAlways: true,
        kCGImageSourceCreateThumbnailWithTransform: true,
        kCGImageSourceShouldCacheImmediately: true,
        kCGImageSourceThumbnailMaxPixelSize: max(64, maxPixel),
    ]
    guard let image = CGImageSourceCreateThumbnailAtIndex(source, 0, options as CFDictionary) else { return nil }
    return UIImage(cgImage: image)
}

/// A picture drawn where the answer put it (§6.1): the bubble's width, at most about 360 points high, its place kept by
/// the computer's `w`/`h` (4:3 when it gave none) while the thumb comes. Grey with the file's name until then; a line
/// and 重试 when it cannot be had. A tall picture keeps its whole height: the box narrows instead of cropping its
/// middle. A tap opens that file's page (the picture page comes with stage B).
struct AnswerPicture: View {
    let file: FileRef
    var thumb: ((FileRef, Int) async -> URL?)? = nil
    @Environment(\.displayScale) private var displayScale
    @Environment(\.openURL) private var openURL
    @State private var image: UIImage?
    @State private var failed = false
    @State private var attempt = 0

    private var ratio: CGFloat {
        guard file.width > 0, file.height > 0 else { return 4 / 3 }
        return CGFloat(file.width) / CGFloat(file.height)
    }

    private var width: CGFloat { answerBubbleWidth() }

    private var height: CGFloat { min(width / ratio, 360) }

    private var shownWidth: CGFloat { height * ratio }

    /// 640 or 1280: the bubble's width in pixels (§6.3).
    private var bucket: Int { pictureWidth(Double(width * displayScale)) }

    private var label: String { file.name.isEmpty ? "图片" : file.name }

    var body: some View {
        HStack(spacing: 0) {
            Spacer(minLength: 0)
            picture
            Spacer(minLength: 0)
        }
        .padding(.top, 4)
        .task(id: "\(file.id)|\(file.version)|\(file.view)|\(bucket)|\(attempt)") { await load() }
    }

    private var picture: some View {
        ZStack {
            RoundedRectangle(cornerRadius: 12, style: .continuous)
                .fill(Palette.panel)
            if let image {
                Image(uiImage: image)
                    .resizable()
                    .scaledToFit()
            } else if failed {
                HStack(spacing: 12) {
                    Text("没能加载缩略图")
                        .noteFont()
                        .foregroundStyle(Palette.muted)
                    Button("重试") { attempt += 1 }
                        .noteFont()
                        .foregroundStyle(Palette.accent)
                }
            } else {
                Text(label)
                    .noteFont()
                    .foregroundStyle(Palette.muted)
                    .lineLimit(2)
                    .multilineTextAlignment(.center)
                    .padding(.horizontal, 16)
            }
        }
        .frame(width: shownWidth, height: height)
        .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
        .contentShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
        .onTapGesture {
            guard let url = URL(string: answerItemLink(file)) else { return }
            openURL(url)
        }
        .accessibilityElement(children: .combine)
        .accessibilityLabel(Text("查看 " + label))
    }

    private func load() async {
        image = nil
        failed = false
        guard let thumb else {
            failed = true
            return
        }
        guard let url = await thumb(file, bucket), let decoded = decodeThumbnail(url, maxPixel: bucket) else {
            failed = true
            return
        }
        image = decoded
    }
}

/// The files an answer names, under its words (§6.1): those it did not draw in place, from link, citation, presented
/// or tool, by `id` deduplicated. Image and SVG cards show a small thumb; the rest a type mark, the name and the size,
/// with 已更新 / 已删除 when the computer says so. At most 8; 还有 N 个 opens the message's own file list.
struct AnswerFileStrip: View {
    let message: Message
    var thumb: ((FileRef, Int) async -> URL?)? = nil
    /// 还有 N 个: the message's files, in the 对话文件 sheet.
    var showAll: (String) -> Void = { _ in }
    @Environment(\.openURL) private var openURL

    var body: some View {
        let drawn = drawnPictureIDs(message)
        let files = fileStripFiles(message, drawn: drawn)
        if !files.isEmpty {
            let shown = Array(files.prefix(fileStripMax))
            let rows = stride(from: 0, to: shown.count, by: 4).map { Array(shown[$0..<min($0 + 4, shown.count)]) }
            VStack(alignment: .leading, spacing: 6) {
                ForEach(Array(rows.enumerated()), id: \.offset) { _, row in
                    HStack(alignment: .top, spacing: 8) {
                        ForEach(row) { file in
                            FileStripCard(file: file, thumb: thumb) { open(file) }
                        }
                    }
                }
                let extra = fileStripExtra(files)
                if extra > 0 {
                    Button("还有 \(extra) 个") { showAll(message.id) }
                        .noteFont()
                        .foregroundStyle(Palette.accent)
                        .frame(minHeight: 36)
                        .buttonStyle(.plain)
                }
            }
            .padding(.top, 10)
        }
    }

    private func open(_ file: FileRef) {
        guard let url = URL(string: answerItemLink(file)) else { return }
        openURL(url)
    }
}

/// One card of the strip: 48 pt square, the name and the size; a picture's small thumb (§6.3: 320), else a type mark.
private struct FileStripCard: View {
    let file: FileRef
    let thumb: ((FileRef, Int) async -> URL?)?
    let open: () -> Void
    @State private var image: UIImage?

    private var label: String { file.name.isEmpty ? "文件" : file.name }

    private var mark: String {
        switch file.state {
        case "updated": return " · 已更新"
        case "missing": return " · 已删除"
        default: return ""
        }
    }

    var body: some View {
        Button(action: open) {
            VStack(spacing: 3) {
                ZStack {
                    RoundedRectangle(cornerRadius: 6, style: .continuous)
                        .fill(Palette.panel)
                    if file.picture, let image {
                        Image(uiImage: image)
                            .resizable()
                            .scaledToFill()
                    } else {
                        Image(systemName: file.picture ? "photo" : "doc")
                            .font(.system(size: 20))
                            .foregroundStyle(Palette.muted.opacity(0.7))
                    }
                }
                .frame(width: 48, height: 48)
                .clipShape(RoundedRectangle(cornerRadius: 6, style: .continuous))
                Text(label)
                    .captionFont()
                    .foregroundStyle(Palette.ink)
                    .lineLimit(2)
                    .multilineTextAlignment(.center)
                if file.size > 0 || !mark.isEmpty {
                    Text(byteSize(file.size) + mark)
                        .captionFont()
                        .foregroundStyle(Palette.muted)
                        .lineLimit(1)
                }
            }
            .frame(width: 74)
            .padding(4)
            .contentShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
        }
        .buttonStyle(.plain)
        .accessibilityLabel(Text("打开 " + label))
        .task(id: "\(file.id)|\(file.version)|\(file.view)") {
            guard file.picture, let thumb, let url = await thumb(file, 320) else { return }
            image = decodeThumbnail(url, maxPixel: 320)
        }
    }
}
