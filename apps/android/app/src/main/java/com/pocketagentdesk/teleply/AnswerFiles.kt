package com.pocketagentdesk.teleply

import java.net.URI
import java.net.URLDecoder
import org.commonmark.node.Image
import org.commonmark.node.Node

/**
 * Matching an answer's words with the files the computer listed for it (file-preview design §5.1, 6.1). Everything here
 * is pure so that the timeline can ask it on every redraw, and so that it can be read without a phone.
 */

/** The files an answer carries; null for an older computer, which has no `files` field and keeps 1.0.10's way. */
fun answerFiles(message: Message): List<FileRef>? = message.files

/**
 * The file a link in an answer names: the link's path folded as [normalizePath] and compared with each `path` (exact
 * first, then the reader's dropped backslashes, [looseFilePath]). Null when the link is not a path at all or nothing
 * matches.
 */
fun fileForLink(files: List<FileRef>, destination: String): FileRef? {
    val path = localPath(destination) ?: return null
    val exact = normalizePath(path)
    return files.firstOrNull { it.path.isNotBlank() && normalizePath(it.path) == exact }
        ?: files.firstOrNull { it.path.isNotBlank() && looseFilePath(it.path) == looseFilePath(path) }
}

/** The file an `![…](…)` in an answer draws in place: an image or SVG the computer can make a thumb of (§6.1). */
fun pictureForImage(files: List<FileRef>, destination: String): FileRef? =
    fileForLink(files, destination)?.takeIf { it.picture }

/** The note that says why a link cannot be given: its `href`, %-decoded, equals the link's (§5.1). */
fun noteForLink(notes: List<FileNote>, destination: String): FileNote? {
    val wanted = decodedHref(destination)
    return notes.firstOrNull { decodedHref(it.href) == wanted }
        ?: notes.firstOrNull { decodedHref(it.href).replace('\\', '/') == wanted.replace('\\', '/') }
}

private fun decodedHref(href: String): String = if ('%' !in href) href else
    runCatching { URLDecoder.decode(href.replace("+", "%2B"), "UTF-8") }.getOrDefault(href)

/** `#…`, `mailto:` and the rest: the words show, but they are not a link the app can open (§6.1). */
fun plainLink(destination: String): Boolean =
    destination.startsWith("#") || runCatching { URI(destination).scheme?.lowercase() !in setOf("http", "https") }.getOrDefault(true)

/** A web address on the computer itself (`localhost`, `127.0.0.1`, `[::1]`): it says so after the words (§6.1). */
fun localWebLink(destination: String): Boolean = runCatching {
    val uri = URI(destination)
    uri.scheme?.lowercase() in setOf("http", "https") &&
        uri.host?.lowercase() in setOf("localhost", "127.0.0.1", "[::1]", "::1")
}.getOrDefault(false)

/** The ways a file reaches the strip: linked, cited or sent by an agent, not a path written in code (§6.1). */
val FileStripVias = setOf("link", "citation", "presented", "tool")

/** At most this many file cards in one answer's strip; more say 还有 N 个. */
const val FileStripMax = 8

/**
 * The files under an answer (§6.1, second point): those from link, citation, presented or tool, by `id` deduplicated in
 * the order the computer listed them, without the pictures drawn where the answer put them ([drawn]). `code` and `path`
 * files are left out on purpose: their words open them, and a code answer would otherwise end in a long row of cards.
 */
fun stripFiles(message: Message, drawn: Set<String> = emptySet()): List<FileRef> {
    val files = message.files ?: return emptyList()
    val seen = HashSet<String>()
    return files.filter { file ->
        file.id.isNotBlank() && file.id !in drawn && (file.via.isEmpty() || file.via.any { it in FileStripVias })
    }.filter { file -> seen.add(file.id) }
}

/** How many files the strip does not show: 还有 N 个. */
fun stripExtra(files: List<FileRef>): Int = (files.size - FileStripMax).coerceAtLeast(0)

/**
 * The ids of the pictures the answer draws in place: each `![…](…)` matched with the files, and only those the strip
 * must then leave out.
 */
fun drawnPictureIds(message: Message): Set<String> {
    val files = message.files ?: return emptySet()
    if (files.isEmpty() || "![" !in message.text) return emptySet()
    val root: Node = answerDocument(message.text)
    val ids = mutableSetOf<String>()
    fun walk(node: Node) {
        if (node is Image) pictureForImage(files, node.destination)?.let { ids += it.id }
        var child = node.firstChild
        while (child != null) { walk(child); child = child.next }
    }
    walk(root)
    return ids
}
