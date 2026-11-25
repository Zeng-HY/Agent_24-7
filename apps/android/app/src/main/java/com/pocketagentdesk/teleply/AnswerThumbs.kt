package com.pocketagentdesk.teleply

import android.graphics.Bitmap
import android.graphics.BitmapFactory
import androidx.compose.runtime.staticCompositionLocalOf

/**
 * How a picture in an answer is fetched (§6.1): by its [FileRef] and a width, the computer's thumb into the app cache.
 * The timeline provides the workspace's reader; the single-message reader may provide none.
 */
val LocalAnswerThumb = staticCompositionLocalOf<(suspend (FileRef, Int) -> Bitmap?)?> { null }

/**
 * A thumb decoded at about the width it is shown at (§7): the smaller copy halves until the long edge no longer
 * exceeds [width], so a 2400 px photo is not held as 2400 px on a phone.
 */
fun decodeThumb(bytes: ByteArray, width: Int): Bitmap? {
    if (bytes.isEmpty()) return null
    val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
    BitmapFactory.decodeByteArray(bytes, 0, bytes.size, bounds)
    if (bounds.outWidth <= 0 || bounds.outHeight <= 0) return null
    val wanted = width.coerceIn(64, 2048)
    var sample = 1
    while (maxOf(bounds.outWidth, bounds.outHeight) / (sample * 2) >= wanted) sample *= 2
    val options = BitmapFactory.Options().apply { inSampleSize = sample }
    return BitmapFactory.decodeByteArray(bytes, 0, bytes.size, options)
}
