package com.pocketagentdesk.teleply

import java.io.ByteArrayOutputStream
import java.nio.file.Files
import java.util.zip.ZipEntry
import java.util.zip.ZipOutputStream
import org.junit.Assert.*
import org.junit.Test

/** A zip of made-up parts: [part] pairs are a name and how many bytes of it (all `x`, so it compresses small). */
fun madeUpZip(vararg parts: Pair<String, Int>): ByteArray {
    val out = ByteArrayOutputStream()
    ZipOutputStream(out).use { zip ->
        parts.forEach { (name, size) ->
            zip.putNextEntry(ZipEntry(name))
            val buffer = ByteArray(65536) { 'x'.code.toByte() }
            var left = size
            while (left > 0) {
                val n = minOf(left, buffer.size)
                zip.write(buffer, 0, n)
                left -= n
            }
            zip.closeEntry()
        }
    }
    return out.toByteArray()
}

/**
 * The size limits that keep a Word or Excel file from being drawn on the phone (11-26, design §6.1): the file's own
 * size, and its body's (word/document.xml, or Excel's worksheets) — read from the zip's directory, never by unpacking
 * it — and the demo's big file that the failure page is for.
 */
class OfficeLimitsTest {
    @Test fun aZipsEntrySizesAreReadFromItsDirectoryInMemoryAndFromDisk() {
        val bytes = madeUpZip("word/document.xml" to 12_345, "docs/" to 0, "word/styles.xml" to 7)
        assertEquals(mapOf("word/document.xml" to 12_345L, "word/styles.xml" to 7L), zipEntrySizes(bytes))
        val file = Files.createTempFile("teleply-zip", ".docx").toFile()
        try {
            file.writeBytes(bytes)
            assertEquals(zipEntrySizes(bytes), zipEntrySizes(file))
        } finally {
            file.delete()
        }
        // Something that is not a zip at all has no entries, so the page tries it and its own failure page says so.
        assertEquals(emptyMap<String, Long>(), zipEntrySizes(byteArrayOf(1, 2, 3, 4)))
    }

    @Test fun aWordFileIsNotDrawnPastEightMegabytesOfItsDocumentXml() {
        val small = mapOf("word/document.xml" to OfficeBodyLimit)
        val big = mapOf("word/document.xml" to OfficeBodyLimit + 1)
        assertNull(officeTooLarge("word", 400_000, small))
        assertEquals(OfficeTooLargeNote, officeTooLarge("word", 400_000, big))
        // Word's other parts do not count towards its body.
        assertNull(officeTooLarge("word", 400_000, mapOf("word/styles.xml" to OfficeBodyLimit * 2)))
        // A .doc the phone hands to SheetJS has no document.xml: nothing says it is too big by its body.
        assertNull(officeTooLarge("word", 400_000, emptyMap()))
    }

    @Test fun anExcelFilesWorksheetsAreAddedUp() {
        val sheets = mapOf("xl/worksheets/sheet1.xml" to 5L * 1024 * 1024, "xl/worksheets/sheet2.xml" to 4L * 1024 * 1024)
        assertEquals(OfficeTooLargeNote, officeTooLarge("sheet", 400_000, sheets))
        val fits = mapOf("xl/worksheets/sheet1.xml" to 4L * 1024 * 1024, "xl/worksheets/sheet2.xml" to 3L * 1024 * 1024)
        assertNull(officeTooLarge("sheet", 400_000, fits))
        // Shared strings and styles are not worksheets.
        assertNull(officeTooLarge("sheet", 400_000, mapOf("xl/sharedStrings.xml" to OfficeBodyLimit * 2)))
        assertEquals(OfficeTooLargeNote, officeTooLarge("sheet", 400_000, sheets + ("xl/sharedStrings.xml" to 100L)))
    }

    @Test fun aFilePastFifteenMegabytesIsNotDrawnWhateverItsBody() {
        assertNull(officeTooLarge("word", OfficePreviewLimit, mapOf("word/document.xml" to 10)))
        assertEquals(OfficeTooLargeNote, officeTooLarge("word", OfficePreviewLimit + 1, mapOf("word/document.xml" to 10)))
        assertEquals(OfficeTooLargeNote, officeTooLarge("sheet", OfficePreviewLimit + 1, emptyMap()))
        assertNull(officeTooLarge("word", 0, mapOf("word/document.xml" to 10)))
    }

    /** The demo's 大文档.docx (design §6.1's reproduction file): made up on the phone, over the body limit, with its PDF. */
    @Test fun theDemosBigWordIsPastTheLimitAndHasASameNamedPdf() {
        val entries = zipEntrySizes(madeUpBigWord())
        assertTrue("document.xml=${entries["word/document.xml"]}", (entries["word/document.xml"] ?: 0) > OfficeBodyLimit)
        assertEquals(OfficeTooLargeNote, officeTooLarge("word", 415_598, entries))
        val word = FixtureWorld.PREVIEW_FILES.first { it.name == "大文档.docx" }
        val pdf = FixtureWorld.PREVIEW_FILES.first { it.name == "大文档.pdf" }
        assertEquals(fileExtension(word.name), "docx")
        assertEquals(word.name.substringBeforeLast('.'), pdf.name.substringBeforeLast('.'))
        assertEquals("pdf", fileExtension(pdf.name))
    }
}
