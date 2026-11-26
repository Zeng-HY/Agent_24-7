package com.pocketagentdesk.teleply

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.size
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.lerp
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.sp

/** How one kind of file is drawn (11-26, iPhone and Android alike): the short words on the page, and the page's colour. */
data class FileTypeMark(val label: String, val color: Long)

/**
 * The file type marks of the 11-26 design §4.3, by extension in lower case. One table for both phones: the words and the
 * colours are the same on the iPhone. No company's logo is drawn, only a page with a folded corner and these words.
 */
private val FileTypeMarks: Map<String, FileTypeMark> = listOf(
    FileTypeMark("PDF", 0xFFE5483B) to "pdf",
    FileTypeMark("W", 0xFF2F6FDE) to "doc docx docm dotx rtf odt pages",
    FileTypeMark("X", 0xFF1E8E4F) to "xls xlsx xlsm xlsb ods numbers",
    FileTypeMark("CSV", 0xFF2E9E6B) to "csv tsv",
    FileTypeMark("P", 0xFFE46A2C) to "ppt pptx pptm odp key",
    FileTypeMark("ZIP", 0xFFB7862C) to "zip rar 7z tar gz tgz bz2 xz",
    FileTypeMark("TXT", 0xFF7A8594) to "txt log",
    FileTypeMark("MD", 0xFF5F6B7A) to "md markdown",
    FileTypeMark("</>", 0xFF7A55D6) to "py r js ts tsx jsx kt kts swift java c h cpp hpp cs go rs rb php sh ps1 bat sql json yaml yml toml xml html htm css ipynb",
    FileTypeMark("IMG", 0xFF12A3A3) to "png jpg jpeg gif webp heic heif bmp tif tiff",
    FileTypeMark("SVG", 0xFF0E8F8F) to "svg",
    FileTypeMark("♪", 0xFFD24C8E) to "mp3 wav m4a aac flac ogg",
    FileTypeMark("▶", 0xFF5B5BD6) to "mp4 mov m4v avi mkv webm",
    FileTypeMark("APK", 0xFF3DA35D) to "apk",
    FileTypeMark("EXE", 0xFF4B5563) to "exe msi",
).flatMap { (mark, extensions) -> extensions.split(' ').map { it to mark } }.toMap()

/** The grey of every other file (design §4.3, last row). */
private const val OtherFileColor = 0xFF8B95A1

/** A name's extension in lower case: after its last dot, and nothing for a name without one (or a leading dot only). */
fun fileExtension(name: String): String {
    val dot = name.lastIndexOf('.')
    return if (dot <= 0 || dot == name.lastIndex) "" else name.substring(dot + 1).lowercase()
}

/**
 * A file's mark (design §4.3): the table's words and colour; for anything else the extension in capitals, at most four
 * letters, and no words at all for a name without an extension.
 */
fun fileTypeMark(name: String): FileTypeMark {
    val extension = fileExtension(name)
    return FileTypeMarks[extension] ?: FileTypeMark(extension.take(4).uppercase(), OtherFileColor)
}

/**
 * A file type icon (11-26 design §4.2): a page with its top right corner folded over a shade lighter, the table's colour,
 * and its short words in white bold on it. Drawn in code, no company's logo and no image asset; the dark theme uses the
 * same colours. [size] is the page's height; it is a little narrower than that.
 */
@Composable
fun FileTypeIcon(name: String, size: Dp, modifier: Modifier = Modifier) {
    val mark = remember(name) { fileTypeMark(name) }
    val page = Color(mark.color)
    val fold = lerp(page, Color.White, 0.34f)
    val words = if (mark.label.length > 3) size.value * 0.24f else size.value * 0.32f
    Box(modifier.size(width = size * 0.80f, height = size), contentAlignment = Alignment.Center) {
        Canvas(Modifier.fillMaxSize()) {
            val w = this.size.width
            val h = this.size.height
            val corner = w * 0.36f
            drawPath(Path().apply {
                moveTo(0f, 0f)
                lineTo(w - corner, 0f)
                lineTo(w, corner)
                lineTo(w, h)
                lineTo(0f, h)
                close()
            }, page)
            drawPath(Path().apply {
                moveTo(w - corner, 0f)
                lineTo(w - corner, corner)
                lineTo(w, corner)
                close()
            }, fold)
        }
        if (mark.label.isNotEmpty()) {
            Text(
                mark.label, color = Color.White, fontWeight = FontWeight.Bold, fontSize = words.sp,
                lineHeight = words.sp, textAlign = TextAlign.Center, maxLines = 1, softWrap = false,
                modifier = Modifier.align(Alignment.Center),
            )
        }
    }
}
