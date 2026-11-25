package com.pocketagentdesk.teleply

/**
 * The viewer's fixed numbers (file-preview design §6.2, §5.8): how far a picture zooms, what a double tap asks for,
 * when a horizontal swipe pages or pans the picture, and which source a picture of a given size opens.
 */
const val MaxPictureZoom = 8f
const val DoubleTapZoom = 2.5f
const val MaxPdfZoom = 3f

/** Open the original up to this size; past it the computer's 2048 thumb (the viewer never pulls 100 MB into memory). */
const val OriginalPictureLimit = 30L * 1024 * 1024

/** A decoded picture's longer side is kept at or under this (§6.2). */
const val PictureDecodeEdge = 4096

/** A pinch of [factor] on [scale], kept between 1× and [MaxPictureZoom]. */
fun zoomBy(scale: Float, factor: Float): Float = (scale * factor).coerceIn(1f, MaxPictureZoom)

/** A double tap: back to 1× when already zoomed, else in to [DoubleTapZoom]. */
fun doubleTapTarget(scale: Float): Float = if (scale > 1.01f) 1f else DoubleTapZoom

/** The pager turns pages only at 1×; zoomed in, a sideways drag moves the picture instead (§6.2). */
fun pagerTurnsAt(scale: Float): Boolean = scale <= 1.01f

/** A PDF's pinch, kept between 1× and 3×. */
fun pdfZoomBy(scale: Float, factor: Float): Float = (scale * factor).coerceIn(1f, MaxPdfZoom)

/** At or under [OriginalPictureLimit] the original is opened; larger pictures use the 2048 thumb (§5.8). */
fun opensOriginal(size: Long): Boolean = size <= 0 || size <= OriginalPictureLimit

/** What the viewer asks for an SVG: 2048 first, 4096 once it is enlarged past 2× (§6.2). */
fun svgThumbWidth(scale: Float): Int = if (scale > 2f) 4096 else 2048

/** Whether this frame should ask for the sharper SVG, once, after the picture went past 2×. */
fun needsSvgHighRes(scale: Float, alreadyLoaded: Boolean): Boolean = !alreadyLoaded && scale > 2f

/** A decoded picture's sample size, so its longer side stays under [maxEdge] (§6.2). */
fun pictureSampleSize(width: Int, height: Int, maxEdge: Int = PictureDecodeEdge): Int {
    var sample = 1
    while (maxOf(width, height) / sample > maxEdge) sample *= 2
    return sample
}
