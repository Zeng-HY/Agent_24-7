package com.pocketagentdesk.teleply

import java.io.File
import java.io.OutputStream
import java.security.MessageDigest
import kotlinx.coroutines.runBlocking

/** The folder under the app cache that holds the original files the phone keeps (§7, second point). */
const val FileCacheFolder = "answer-files"

/** What the kept originals may take on the phone (§7): 500 MB, the least recently used going first. */
const val FileCacheLimit = 500L * 1024 * 1024

/**
 * The original files this phone keeps (§7): one file per (computer, file id, `v`), under a folder per computer so that
 * 移除一台电脑 can drop its own. Written aside first and renamed when whole, the way [SentPictures]' copies are; reading
 * touches it, and past [maxBytes] the least recently used go. Free of Android types, so the cache can be read on a
 * plain JVM in tests.
 */
class FileCache(private val root: File, private val maxBytes: Long = FileCacheLimit) {
    /** Where one file of one computer lives (whether or not it is there yet); [ext] keeps the share's type right. */
    fun entry(computer: String, file: String, version: String, ext: String = "bin"): File =
        File(File(root, computer), name(file, version, ext))

    /** The kept file, touching it as used; null when it is not here. */
    fun read(computer: String, file: String, version: String, ext: String = "bin"): File? {
        val kept = entry(computer, file, version, ext)
        if (!kept.isFile) return null
        kept.setLastModified(System.currentTimeMillis())
        return kept
    }

    /** Keeps a file written by [body], aside first; null when it could not be kept whole. */
    fun write(computer: String, file: String, version: String, ext: String, body: (OutputStream) -> Unit): File? =
        runBlocking { writeStream(computer, file, version, ext) { body(it) } }

    /** [write] for a body that suspends (a download from the computer), still written aside and renamed when whole. */
    suspend fun writeStream(computer: String, file: String, version: String, ext: String, body: suspend (OutputStream) -> Unit): File? {
        val folder = File(root, computer)
        folder.mkdirs()
        val kept = entry(computer, file, version, ext)
        val part = File.createTempFile(kept.name, ".part", folder)
        return try {
            part.outputStream().use { body(it) }
            require(part.renameTo(kept) || kept.isFile) { "文件没能存到手机上" }
            kept.setLastModified(System.currentTimeMillis())
            trim()
            kept
        } catch (e: Exception) {
            null
        } finally {
            part.delete()
        }
    }

    /** Past [maxBytes], the least recently read or written files go until the cache fits again. */
    @Synchronized fun trim() {
        if (!root.isDirectory) return
        val files = root.walkTopDown().filter { it.isFile }.toList()
        var total = files.sumOf { it.length() }
        if (total <= maxBytes) return
        files.sortedBy { it.lastModified() }.forEach { old ->
            if (total > maxBytes) { val size = old.length(); if (old.delete()) total -= size }
        }
    }

    /** 移除一台电脑: everything kept of it goes. */
    fun clear(computer: String) { File(root, computer).deleteRecursively() }

    /** 退出登录: everything goes. */
    fun clear() { root.deleteRecursively() }

    fun totalBytes(): Long = if (!root.isDirectory) 0 else root.walkTopDown().filter { it.isFile }.sumOf { it.length() }

    companion object {
        /** A digest, so that no file's name ever appears on the phone's disk. */
        fun name(file: String, version: String, ext: String): String =
            MessageDigest.getInstance("SHA-256").digest("$file\n$version".toByteArray(Charsets.UTF_8))
                .joinToString("") { "%02x".format(it.toInt() and 0xff) } + "." + cleanExt(ext)

        /** The extension for a cached file: letters and digits only, at most 8, else `bin`. */
        fun safeExt(name: String): String = cleanExt(name.substringAfterLast('.', "").lowercase())

        private fun cleanExt(ext: String): String {
            val clean = ext.lowercase()
            return if (clean.length in 1..8 && clean.all { it in 'a'..'z' || it in '0'..'9' }) clean else "bin"
        }
    }
}

/** 退出登录 and 移除一台电脑 clear this computer's cache, and with the whole account all of it (§7). */
object AnswerCaches {
    fun clearComputer(caches: File, computer: String) {
        File(File(caches, ThumbCacheFolder), computer).deleteRecursively()
        File(File(caches, FileCacheFolder), computer).deleteRecursively()
    }

    fun clearAll(caches: File) {
        File(caches, ThumbCacheFolder).deleteRecursively()
        File(caches, FileCacheFolder).deleteRecursively()
    }
}
