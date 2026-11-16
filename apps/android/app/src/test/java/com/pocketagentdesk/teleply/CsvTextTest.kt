package com.pocketagentdesk.teleply

import java.nio.charset.Charset
import org.junit.Assert.*
import org.junit.Test

/**
 * 11-16: how the phone reads a CSV's or TSV's bytes. The computer's text preview knows only UTF-8 and UTF-16; a CSV
 * saved by Chinese Excel is GBK, so the phone reads the bytes itself.
 */
class CsvTextTest {
    private val text="编号,问题\n01,\"第一段\n- **依据**：a,b\"\n02,第二行"
    @Test fun aUtf8FileWithoutAMarkIsReadAsUtf8() {
        assertEquals(text,decodeCsvText(text.toByteArray(Charsets.UTF_8)))
    }
    @Test fun aUtf8FileWithAMarkIsReadAsUtf8WithoutTheMark() {
        val bytes=byteArrayOf(0xEF.toByte(),0xBB.toByte(),0xBF.toByte())+text.toByteArray(Charsets.UTF_8)
        assertEquals(text,decodeCsvText(bytes))
    }
    @Test fun aUtf16FileWithAMarkIsReadAsUtf16() {
        for((mark,charset) in listOf(byteArrayOf(0xFF.toByte(),0xFE.toByte()) to Charsets.UTF_16LE,byteArrayOf(0xFE.toByte(),0xFF.toByte()) to Charsets.UTF_16BE))
            assertEquals(text,decodeCsvText(mark+text.toByteArray(charset)))
    }
    @Test fun aGbkFileIsReadAsGb18030() {
        val bytes=text.toByteArray(Charset.forName("GBK"))
        assertFalse(bytes.contentEquals(text.toByteArray(Charsets.UTF_8)))
        assertEquals(text,decodeCsvText(bytes))
    }
    /** An empty file is empty text, not a guess at GB18030. */
    @Test fun anEmptyFileIsEmptyText() {
        assertEquals("",decodeCsvText(ByteArray(0)))
    }
}
