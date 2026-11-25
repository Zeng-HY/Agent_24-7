package com.pocketagentdesk.teleply

import java.io.File
import java.security.MessageDigest

/** The folder under the app cache that holds answer thumbnails, apart from the pictures sent with messages (§7). */
const val ThumbCacheFolder = "answer-thumbs"

/** What answer thumbnails may take on the phone (§7): 200 MB, the least recently used going first. */
const val ThumbCacheLimit = 200L * 1024 * 1024

/**
 * The answer thumbnails on this phone (§7): one file per (computer, file id, `v`, width), so an address whose `v` did
 * not change never asks the computer again. A fetched picture is written under a temporary name first and renamed when
 * whole, the way [SentPictures]' copies are; reading touches it, and past [maxBytes] the least recently used go.
 * Kept free of Android types so the cache can be read on a plain JVM in tests.
 */
class ThumbCache(private val root: File, private val maxBytes: Long = ThumbCacheLimit) {
    /** Where the thumb of one address lives (whether or not it is there yet). */
    fun entry(computer: String, file: String, version: String, width: Int): File =
        File(File(root, computer), name(computer, file, version, width))

    /** The thumb's bytes, touching it as used; null when it is not kept here. */
    fun read(computer: String, file: String, version: String, width: Int): ByteArray? {
        val kept = entry(computer, file, version, width)
        if (!kept.isFile) return null
        val bytes = runCatching { kept.readBytes() }.getOrNull() ?: return null
        kept.setLastModified(System.currentTimeMillis())
        return bytes
    }

    /** Keeps [bytes] as this address's thumb, written aside first; null when it could not be kept. */
    fun write(computer: String, file: String, version: String, width: Int, bytes: ByteArray): File? {
        if (bytes.isEmpty()) return null
        val kept = entry(computer, file, version, width)
        kept.parentFile?.mkdirs()
        val part = File.createTempFile(kept.name, ".part", kept.parentFile)
        return try {
            part.outputStream().use { it.write(bytes) }
            require(part.renameTo(kept) || kept.isFile) { "缩略图没能存到手机上" }
            kept.setLastModified(System.currentTimeMillis())
            trim()
            kept
        } catch (e: Exception) {
            null
        } finally {
            part.delete()
        }
    }

    /** Past [maxBytes] over the whole [root] (§7: all computers together), the least recently used go until it fits. */
    @Synchronized fun trim() {
        if (!root.isDirectory) return
        val files = root.walkTopDown().filter { it.isFile }.toList()
        var total = files.sumOf { it.length() }
        if (total <= maxBytes) return
        files.sortedBy { it.lastModified() }.forEach { old ->
            if (total > maxBytes) { val size = old.length(); if (old.delete()) total -= size }
        }
    }

    /** What the cache takes, all computers together. */
    fun totalBytes(): Long = if (!root.isDirectory) 0 else root.walkTopDown().filter { it.isFile }.sumOf { it.length() }

    companion object {
        const val Suffix = ".thumb"

        /** The file name of one address: a digest, so that no computer or file name ever appears on the phone's disk. */
        fun name(computer: String, file: String, version: String, width: Int): String =
            digest("$computer\n$file\n$version\n$width") + Suffix

        internal fun digest(text: String): String =
            MessageDigest.getInstance("SHA-256").digest(text.toByteArray(Charsets.UTF_8)).joinToString("") { "%02x".format(it.toInt() and 0xff) }
    }
}
