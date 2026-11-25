import Foundation

/// The viewer's fixed numbers (file-preview design §6.2, §5.8): how far a picture zooms, what a double tap asks for,
/// when a sideways drag pages or pans the picture, and which source a picture of a given size opens.
public let maxPictureZoom: Float = 8
public let doubleTapZoom: Float = 2.5
public let maxPdfZoom: Float = 3

/// Open the original up to this size; past it the computer's 2048 thumb (the viewer never pulls a huge picture in).
public let originalPictureLimit: Int64 = 30 * 1024 * 1024

/// A decoded picture's longer side is kept at or under this (§6.2).
public let pictureDecodeEdge = 4096

/// A pinch of [factor] on [scale], kept between 1× and [maxPictureZoom].
public func zoomBy(_ scale: Float, _ factor: Float) -> Float {
    min(max(scale * factor, 1), maxPictureZoom)
}

/// A double tap: back to 1× when already zoomed, else in to [doubleTapZoom].
public func doubleTapTarget(_ scale: Float) -> Float {
    scale > 1.01 ? 1 : doubleTapZoom
}

/// The pager turns pages only at 1×; zoomed in, a sideways drag moves the picture instead (§6.2).
public func pagerTurnsAt(_ scale: Float) -> Bool { scale <= 1.01 }

/// A PDF's pinch, kept between 1× and [maxPdfZoom].
public func pdfZoomBy(_ scale: Float, _ factor: Float) -> Float {
    min(max(scale * factor, 1), maxPdfZoom)
}

/// At or under [originalPictureLimit] the original is opened; larger pictures use the 2048 thumb (§5.8).
public func opensOriginal(_ size: Int64) -> Bool { size <= 0 || size <= originalPictureLimit }

/// What the viewer asks for an SVG: 2048 first, 4096 once it is enlarged past 2× (§6.2).
public func svgThumbWidth(_ scale: Float) -> Int { scale > 2 ? 4096 : 2048 }

/// Whether this frame should ask for the sharper SVG, once, after the picture went past 2×.
public func needsSvgHighRes(_ scale: Float, alreadyLoaded: Bool) -> Bool { !alreadyLoaded && scale > 2 }

/// A decoded picture's sample size, so its longer side stays under [maxEdge] (§6.2).
public func pictureSampleSize(width: Int, height: Int, maxEdge: Int = pictureDecodeEdge) -> Int {
    var sample = 1
    while max(width, height) / sample > maxEdge { sample *= 2 }
    return sample
}

/// A GIF or not by its name (the viewer animates it; its thumb is only the first frame).
public func isGIF(_ name: String) -> Bool { name.lowercased().hasSuffix(".gif") }

/// The thumb the viewer shows first for [file] at [scale]: an SVG's 2048/4096, a big picture's or GIF's 2048, else 1280.
public func viewerThumbWidth(_ file: FileRef, scale: Float) -> Int {
    if file.view == "svg" { return svgThumbWidth(scale) }
    if !opensOriginal(file.size) || isGIF(file.name) { return 2048 }
    return 1280
}

/// Whether the viewer then swaps in the original from the phone's kept copy (§6.2): never for an SVG (the computer's
/// PNG is shown), and only for a picture of at most 30 MB.
public func viewerLoadsOriginal(_ file: FileRef) -> Bool {
    file.view != "svg" && opensOriginal(file.size)
}

/// Why a file's page does not draw the file itself (§5.8): too large for its type, or a kind this phone cannot show.
/// A pure function so the page's `@ViewBuilder` only declares the answer, never assigns it inside an `if`.
public func unshownReason(kind: String, size: Int64, limit: Int64, looks: Bool) -> String {
    if size <= limit { return looks ? "这里不直接显示" : "手机上看不了这类文件" }
    switch kind {
    case "image":
        return "这张图超过 \(RelayClient.picturePreviewLimit / 1_048_576)MB，不直接显示"
    case "pdf":
        return "这个 PDF 超过 \(RelayClient.pdfPreviewLimit / 1_048_576)MB，不直接显示"
    default:
        return "超过 \(RelayClient.officePreviewLimit / 1_048_576)MB，不直接显示"
    }
}
