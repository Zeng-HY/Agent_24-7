package com.pocketagentdesk.teleply

import java.nio.ByteBuffer
import java.nio.charset.CharacterCodingException
import java.nio.charset.Charset
import java.nio.charset.CodingErrorAction

/** GB18030 covers GBK, which Chinese Excel writes for a "CSV" by default (11-16). */
private val CsvGb18030:Charset=Charset.forName("GB18030")

/**
 * The text of a CSV or TSV file read on the phone (11-16). The marks decide UTF-8 and UTF-16 (both byte orders); text
 * that is wholly valid UTF-8 is UTF-8; anything else is GB18030, which is what Chinese Excel writes for a "CSV". The
 * computer's `/api/file/text` knows only UTF-8 and UTF-16 and refuses a GBK file, so these files are read here.
 *
 * Throws [CharacterCodingException] for bytes that are neither (almost never a text file): the page then says the
 * phone cannot show it, as before.
 */
fun decodeCsvText(bytes:ByteArray):String {
    fun marked(mark:IntArray,charset:Charset):String? {
        if(bytes.size<mark.size) return null
        for(i in mark.indices) if((bytes[i].toInt() and 0xff)!=mark[i]) return null
        return String(bytes,mark.size,bytes.size-mark.size,charset)
    }
    marked(intArrayOf(0xEF,0xBB,0xBF),Charsets.UTF_8)?.let { return it }
    marked(intArrayOf(0xFF,0xFE),Charsets.UTF_16LE)?.let { return it }
    marked(intArrayOf(0xFE,0xFF),Charsets.UTF_16BE)?.let { return it }
    strict(bytes,Charsets.UTF_8)?.let { return it }
    return CsvGb18030.newDecoder().onMalformedInput(CodingErrorAction.REPORT)
        .onUnmappableCharacter(CodingErrorAction.REPORT).decode(ByteBuffer.wrap(bytes)).toString()
}
/** [bytes] as [charset], or null when they are not wholly valid text in it. */
private fun strict(bytes:ByteArray,charset:Charset):String? = try {
    charset.newDecoder().onMalformedInput(CodingErrorAction.REPORT)
        .onUnmappableCharacter(CodingErrorAction.REPORT).decode(ByteBuffer.wrap(bytes)).toString()
} catch(_:CharacterCodingException) { null }
