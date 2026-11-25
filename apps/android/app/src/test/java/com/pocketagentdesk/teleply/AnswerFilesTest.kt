package com.pocketagentdesk.teleply

import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.LinkAnnotation
import androidx.compose.ui.text.TextLinkStyles
import androidx.compose.ui.text.withLink
import java.nio.file.Files
import org.commonmark.node.Node
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test

/**
 * The answer side of the file-preview design, first stage (Android 1.0.11): an answer's `files` and `file_notes`
 * (§5.1), a link found by its path (§6.1), the reasons (§6.4), the file strip's cards and the thumb cache (§7).
 * Everything is made up; no computer is read.
 */
class AnswerFilesTest {
    private fun ref(
        id: String, path: String = "D:\\work\\out\\$id", view: String = "code", via: List<String> = listOf("link"),
        thumb: Boolean = false, texts: List<String> = emptyList(), state: String = "current",
    ) = FileRef(id = id, name = id, path = path, kind = if (view == "image" || view == "svg") "image" else "text",
        view = view, state = state, version = "v1", thumb = thumb, texts = texts, via = via)

    @Test fun aParagraphWithAPictureSplitsIntoWordsPictureWords() {
        val ink = MdInk(Color.Black, Color.LightGray, Color.Gray)
        val files = listOf(ref("fig", "D:\\a\\fig.png", view = "image", thumb = true))
        fun pieces(markdown: String): List<ParagraphPiece> {
            val paragraph: Node = children(markdownDocument(markdown)).first()
            return paragraphPieces(paragraph, ink, files, emptyList())
        }
        val three = pieces("前文 ![图](<D:/a/fig.png>) 后文")
        assertEquals(3, three.size)
        assertEquals("fig", (three[1] as ParagraphPiece.Picture).file.id)
        assertTrue((three[0] as ParagraphPiece.Words).text.text.contains("前文"))
        assertTrue((three[2] as ParagraphPiece.Words).text.text.contains("后文"))
        // A picture inside a link or emphasis is still found, not turned into a line of text.
        assertTrue(pieces("[![图](<D:/a/fig.png>)](https://example.invalid)").any { it is ParagraphPiece.Picture })
        assertTrue(pieces("**![图](<D:/a/fig.png>)**").any { it is ParagraphPiece.Picture })
        // Without a picture (or without the newer computer's files) the paragraph stays one piece.
        assertEquals(1, pieces("只有文字，没有图。").size)
        val paragraph: Node = children(markdownDocument("前文 ![图](<D:/a/fig.png>) 后文")).first()
        assertEquals(1, paragraphPieces(paragraph, ink, null, emptyList()).size)
        // A picture the computer cannot thumb stays words, as §5.1 says.
        val svg = listOf(ref("svg", "D:\\a\\fig.svg", view = "svg", thumb = false))
        assertEquals(1, paragraphPieces(paragraph, ink, svg, emptyList()).size)
    }

    @Test fun theThumbWidthFollowsTheBubbleInPixels() {
        assertEquals(640, pictureWidth(320f))
        assertEquals(640, pictureWidth(640f))
        assertEquals(1280, pictureWidth(641f))
        assertEquals(1280, pictureWidth(1069f))
    }

    @Test fun anOlderComputerStillSaysWhenAFileLikeLinkCannotOpen() {
        assertTrue(fileLikeLink("out/old.png"))
        assertTrue(fileLikeLink("/D:/work/out/a.pdf"))
        assertTrue(fileLikeLink("file:///D:/a/b.png"))
        assertTrue(fileLikeLink("~/notes/a.md"))
        assertTrue(fileLikeLink("docs\\release.md"))
        assertFalse(fileLikeLink("https://example.invalid/a"))
        assertFalse(fileLikeLink("#part-2"))
        assertFalse(fileLikeLink("mailto:a@example.invalid"))
        assertFalse(fileLikeLink("javascript:alert(1)"))
    }

    @Test fun wordsAlreadyInALinkKeepOneTarget() {
        val ink = MdInk(Color.Black, Color.LightGray, Color.Gray)
        val builder = AnnotatedString.Builder()
        builder.withLink(LinkAnnotation.Url("https://example.invalid", TextLinkStyles())) { append("D:/a/run.R") }
        builder.linkFileTexts(listOf(ref("run", texts = listOf("D:/a/run.R"))), ink, mutableListOf(0 until 8))
        val linked = builder.toAnnotatedString()
        assertEquals(1, linked.getLinkAnnotations(0, linked.length).size)
        // Words not inside a link do become one.
        val plain = AnnotatedString.Builder().apply { append("见 D:/a/run.R。") }
        plain.linkFileTexts(listOf(ref("run", texts = listOf("D:/a/run.R"))), ink, mutableListOf())
        val plainText = plain.toAnnotatedString()
        assertEquals(1, plainText.getLinkAnnotations(0, plainText.length).size)
    }

    @Test fun aNewComputerSaysSoWithFilesEvenAnEmptyList() {
        val plain = parseMessage(JSONObject("""{"id":"m1","role":"assistant","text":"hi"}"""))
        assertNull(plain.files)
        assertTrue(plain.fileNotes.isEmpty())
        val empty = parseMessage(JSONObject("""{"id":"m2","role":"assistant","text":"hi","files":[]}"""))
        assertEquals(emptyList<FileRef>(), empty.files)
        val full = parseMessage(JSONObject("""
            {"id":"m3","role":"assistant","text":"x",
             "files":[{"id":"3f0c","name":"chart.png","path":"D:\\work\\out\\chart.png","kind":"image","view":"image",
                       "size":183422,"state":"current","v":"9f2c41d0","w":2400,"h":1500,"thumb":true,"via":["image","link"]}],
             "file_notes":[{"href":"out/old.png","reason":"not_found","text":"电脑上没找到这个文件"}]}
        """))
        assertEquals(1, full.files?.size)
        val file = full.files!!.single()
        assertEquals("chart.png", file.name)
        assertEquals(2400, file.width); assertEquals(1500, file.height)
        assertTrue(file.picture); assertTrue("link" in file.via)
        assertEquals(FileNote("out/old.png", "not_found", "电脑上没找到这个文件"), full.fileNotes.single())
        // The entry carries over into the file page's JSON unchanged, with the address's `v`.
        assertEquals("9f2c41d0", file.toJson().string("v"))
        assertEquals("image", file.toJson().string("view"))
    }

    @Test fun aLinkFindsItsFileByPathAndAPictureOnlyWhenItCanBeDrawn() {
        val files = listOf(
            ref("a", "D:\\Work\\Out\\A.R", view = "code"),
            ref("b", "D:\\work\\out\\b.png", view = "image", thumb = true),
            ref("c", "D:\\work\\out\\c.svg", view = "svg", thumb = false),
        )
        // Slashes and case do not matter (§5.1); a line number after the path names the same file.
        assertEquals("a", fileForLink(files, "D:/work/out/a.R:12-20")?.id)
        assertEquals("b", fileForLink(files, "D:\\work\\out\\b.png")?.id)
        assertNull(fileForLink(files, "D:\\work\\out\\missing.png"))
        assertNull(fileForLink(files, "https://example.com/a"))
        // An SVG the computer cannot make a thumb of stays a card, not a picture in the text (§5.1, 6.1).
        assertNull(pictureForImage(files, "D:\\work\\out\\c.svg"))
        assertEquals("b", pictureForImage(files, "D:\\work\\out\\b.png")?.id)
        // The reader's dropped backslash still finds the file (looseFilePath): the answer wrote \.Out, the reader ate it.
        val dropped = listOf(ref("d", "D:\\Work\\.Out\\A.R"))
        assertEquals("d", fileForLink(dropped, "D:\\Work.Out\\A.R")?.id)
    }

    @Test fun theReasonIsFoundByItsDecodedHrefAndSaysWhatTheDesignSays() {
        val notes = listOf(FileNote("out/%E6%97%A7%E5%9B%BE.png", "not_found"), FileNote("//nas/share/r.pdf", "not_local"))
        assertEquals("not_found", noteForLink(notes, "out/旧图.png")?.reason)
        assertEquals("not_local", noteForLink(notes, "//nas/share/r.pdf")?.reason)
        assertNull(noteForLink(notes, "out/other.png"))
        assertEquals("找不到文件", fileNoteShort("not_found"))
        assertEquals("电脑上没找到这个文件（回答写的是相对位置，在对话文件夹里没找到）", fileNoteFull("not_found"))
        assertEquals("文件在网络位置或别的电脑上，遥应只读这台电脑自己的磁盘", fileNoteFull("not_local"))
        assertEquals("文件已移动或删除", fileNoteFull("missing"))
        assertEquals("这是电脑本机的网址，手机打不开", fileNoteFull("local_web"))
    }

    @Test fun notEverythingIsALinkAndALocalAddressSaysSo() {
        assertTrue(plainLink("#part-2"))
        assertTrue(plainLink("mailto:a@example.invalid"))
        assertTrue(plainLink("javascript:alert(1)"))
        assertFalse(plainLink("https://example.invalid/a"))
        assertTrue(localWebLink("http://localhost:3000/a"))
        assertTrue(localWebLink("https://127.0.0.1:8443"))
        assertTrue(localWebLink("http://[::1]:3000"))
        assertFalse(localWebLink("https://example.invalid"))
        assertFalse(localWebLink("http://localhost.example.invalid"))
    }

    @Test fun theStripLeavesOutWhatIsDrawnOrWrittenAsAPathAndKeepsEight() {
        val drawn = setOf("pic")
        val many = (1..12).map { ref("f$it", view = "code", via = listOf("presented")) }
        val message = Message("m", "assistant", "t", files = many + listOf(
            ref("pic", view = "image", thumb = true, via = listOf("image")),
            ref("code", via = listOf("code")),
            ref("path", via = listOf("path")),
            ref("dup", via = listOf("link")),
            ref("dup", via = listOf("citation")),
        ))
        val strip = stripFiles(message, drawn)
        assertEquals(listOf("f1", "f2", "f3", "f4", "f5", "f6", "f7", "f8", "f9", "f10", "f11", "f12", "dup"), strip.map { it.id })
        assertEquals(5, stripExtra(strip))
        assertEquals(0, stripExtra(strip.take(FileStripMax)))
        // An older computer has no strip, and an answer without one has none either.
        assertTrue(stripFiles(Message("o", "assistant", "t")).isEmpty())
    }

    @Test fun aThumbIsKeptByComputerFileVersionAndWidth() {
        val dir = Files.createTempDirectory("teleply-thumbs").toFile()
        try {
            val cache = ThumbCache(dir, 150)
            val a = ThumbCache.name("pc-a", "file-1", "v1", 640)
            assertTrue(a.endsWith(ThumbCache.Suffix))
            assertEquals(a, ThumbCache.name("pc-a", "file-1", "v1", 640))
            val others = listOf(
                ThumbCache.name("pc-b", "file-1", "v1", 640), ThumbCache.name("pc-a", "file-2", "v1", 640),
                ThumbCache.name("pc-a", "file-1", "v2", 640), ThumbCache.name("pc-a", "file-1", "v1", 1280),
            )
            assertEquals(others.size, others.toSet().size)
            assertFalse(a in others)
            // A name never shows the computer or the file on disk (§7).
            assertFalse(a.contains("pc-a") || a.contains("file-1"))

            cache.write("pc-a", "file-1", "v1", 640, ByteArray(60))
            val reading = cache.read("pc-a", "file-1", "v1", 640)
            assertEquals(60, reading?.size)
            assertTrue(dir.listFiles().orEmpty().none { it.name.endsWith(".part") })
        } finally {
            dir.deleteRecursively()
        }
    }

    @Test fun pastTheLimitTheLeastRecentlyUsedThumbsGo() {
        val dir = Files.createTempDirectory("teleply-thumbs").toFile()
        try {
            val cache = ThumbCache(dir, maxBytes = 100)
            cache.write("pc", "old", "v1", 320, ByteArray(60))
            val old = cache.entry("pc", "old", "v1", 320)
            old.setLastModified(1_000)
            cache.write("pc", "new", "v1", 320, ByteArray(60))
            val fresh = cache.entry("pc", "new", "v1", 320)
            assertTrue("total ${cache.totalBytes()}", cache.totalBytes() <= 100)
            assertFalse(old.exists())
            assertTrue(fresh.exists())
            // Reading touches a file; the least recently used still goes when room is needed.
            assertNotNull(cache.read("pc", "new", "v1", 320))
            assertTrue(fresh.lastModified() > 1_000)
        } finally {
            dir.deleteRecursively()
        }
    }
}
