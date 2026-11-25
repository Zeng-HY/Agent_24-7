import Foundation
import Testing
@testable import TeleplyModel

/// The viewer's fixed numbers (file-preview design §6.2, §5.8): zoom limits, the double tap, when the pager turns,
/// which source a picture opens, the SVG's two sizes and the decode ceiling.
struct ViewerRulesTests {
    private func file(_ id: String = "f", name: String = "图.png", view: String = "image", size: Int64 = 1024,
                      thumb: Bool = true) -> FileRef {
        FileRef(id: id, name: name, kind: view == "image" ? "image" : "download", view: view, size: size,
                version: "v1", thumb: thumb)
    }

    @Test func aPinchStaysBetweenOneAndEight() {
        #expect(zoomBy(1, 2) == 2)
        #expect(zoomBy(6, 2) == maxPictureZoom)
        #expect(zoomBy(1, 0.2) == 1)
        #expect(doubleTapTarget(1) == doubleTapZoom)
        #expect(doubleTapTarget(2.5) == 1)
        #expect(doubleTapTarget(1.02) == 1)
        #expect(pagerTurnsAt(1))
        #expect(!pagerTurnsAt(1.02))
    }

    @Test func aPdfPinchStaysBetweenFitAndThreeTimes() {
        #expect(pdfZoomBy(1, 2) == 2)
        #expect(pdfZoomBy(2.5, 2) == maxPdfZoom)
        #expect(pdfZoomBy(1, 0.1) == 1)
    }

    @Test func theOriginalOpensUpToThirtyMegabytes() {
        #expect(opensOriginal(0))
        #expect(opensOriginal(originalPictureLimit))
        #expect(!opensOriginal(originalPictureLimit + 1))
        #expect(viewerLoadsOriginal(file()))
        #expect(!viewerLoadsOriginal(file(size: originalPictureLimit + 1)))
        // An SVG always shows the computer's PNG, never the original in the viewer.
        #expect(!viewerLoadsOriginal(file(view: "svg")))
    }

    @Test func aSmallPictureStartsAt1280AndABigOrMovingOneAt2048() {
        #expect(viewerThumbWidth(file(), scale: 1) == 1280)
        #expect(viewerThumbWidth(file(size: originalPictureLimit + 1), scale: 1) == 2048)
        #expect(viewerThumbWidth(file(name: "动图.gif"), scale: 1) == 2048)
        #expect(viewerThumbWidth(file(name: "标志.svg", view: "svg"), scale: 1) == 2048)
        #expect(viewerThumbWidth(file(name: "标志.svg", view: "svg"), scale: 2.1) == 4096)
        #expect(svgThumbWidth(2) == 2048)
        #expect(svgThumbWidth(2.01) == 4096)
        #expect(needsSvgHighRes(2.1, alreadyLoaded: false))
        #expect(!needsSvgHighRes(2.1, alreadyLoaded: true))
        #expect(!needsSvgHighRes(1.5, alreadyLoaded: false))
        #expect(isGIF("动图.GIF"))
        #expect(!isGIF("图.png"))
    }

    @Test func aFileThePageCannotShowSaysWhy() {
        #expect(unshownReason(kind: "image", size: RelayClient.picturePreviewLimit + 1,
                             limit: RelayClient.picturePreviewLimit, looks: true) == "这张图超过 30MB，不直接显示")
        #expect(unshownReason(kind: "pdf", size: RelayClient.pdfPreviewLimit + 1,
                             limit: RelayClient.pdfPreviewLimit, looks: true) == "这个 PDF 超过 100MB，不直接显示")
        #expect(unshownReason(kind: "download", size: RelayClient.officePreviewLimit + 1,
                             limit: RelayClient.officePreviewLimit, looks: true) == "超过 30MB，不直接显示")
        #expect(unshownReason(kind: "download", size: 10, limit: RelayClient.officePreviewLimit, looks: true) == "这里不直接显示")
        #expect(unshownReason(kind: "download", size: 10, limit: RelayClient.officePreviewLimit, looks: false) == "手机上看不了这类文件")
    }

    @Test func aDecodedPictureHalvesUntilItFitsTheEdge() {
        #expect(pictureSampleSize(width: 6000, height: 4000) == 2)
        #expect(pictureSampleSize(width: 4096, height: 100) == 1)
        #expect(pictureSampleSize(width: 8194, height: 100) == 4)
    }
}
