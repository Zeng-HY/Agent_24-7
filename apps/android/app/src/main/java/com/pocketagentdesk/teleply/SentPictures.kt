package com.pocketagentdesk.teleply

import org.json.JSONObject

/**
 * A picture sent with a message through this service (web codex-ui.js renderImages; iPhone SentPicture): the computer
 * keeps it and a small copy, by its id (GET /api/codex/image).
 */
data class SentPicture(val id: String, val name: String)

/**
 * A picture a user message carries itself (11-26, design §8.2): the computer puts the pictures of a message in its own
 * `images`, which is also how a steering message's or a Codex new-channel message's pictures are found. [url] says
 * whether the computer's copy can be fetched at all; an entry with only a path cannot.
 */
data class MessageImage(val id: String, val name: String, val url: String)

/** The id rule the computer's copies keep to; a path digest or anything else is not drawn. */
private fun pictureId(id: String) =
    id.isNotEmpty() && id.length <= 64 && id.all { it in 'a'..'z' || it in 'A'..'Z' || it in '0'..'9' || it == '-' }

/** One of the computer's records of a picture ({id, name, url, thumbnail, …}); null without a usable id. */
private fun sentPicture(j: JSONObject): SentPicture? {
    val id = j.string("id")
    if (!pictureId(id)) return null
    return SentPicture(id, j.string("name").ifBlank { "图片" })
}

/** A message's own picture, when the computer keeps it where every assistant's pictures are kept (design §8.2). */
private fun messagePicture(image: MessageImage): SentPicture? {
    if (!image.url.startsWith("/api/codex/image") || !pictureId(image.id)) return null
    return SentPicture(image.id, image.name.ifBlank { "图片" })
}

/**
 * The pictures to show in each user message, by the message's id (user 10-27: a sent picture showed as "[图片]"; web
 * message-projection.js decorate; iPhone sentPictures). The computer keeps a record of each send with pictures (state
 * `images`, oldest first) and Codex keeps that send's request id on its message, so those go by it. Claude keeps none:
 * a send of its goes to the newest message not yet taken whose words after its [图片] mark are the send's, written no
 * earlier than 5 s before the send. Newest first, as the page holds the newest messages: an older send whose message is
 * not loaded gets none. Since 11-26 a message's own `images` (design §8.2) are drawn too, after those paired here.
 */
fun sentPictures(messages: List<Message>, records: List<JSONObject>): Map<String, List<SentPicture>> {
    val users = messages.filter { it.role == "user" }
    val taken = mutableMapOf<String, List<SentPicture>>()
    for (record in records.asReversed()) {
        val pictures = record.rows("images") { it }.mapNotNull(::sentPicture)
        if (pictures.isEmpty()) continue
        val request = record.string("request_id")
        val found = (if (request.isEmpty()) null else users.lastOrNull { it.id !in taken && it.request == request }) ?: run {
            // A picture sent without words reaches Claude as 请查看这些图片。 (remote.py _send_with_references).
            val words = squeezed(record.string("text").trim().ifEmpty { "请查看这些图片。" })
            val since = record.optDouble("created", 0.0) - 5
            users.lastOrNull { m -> m.id !in taken && m.request.isEmpty() && picturedWords(m.text)?.let(::squeezed) == words && (writtenAt(m) ?: Double.MAX_VALUE) >= since }
        }
        if (found != null) taken[found.id] = pictures
    }
    // 11-26 (design 3.2): a message's own pictures come after the ones paired from the send records, and a picture id
    // already shown is not drawn twice. A steering message or a Codex new-channel message has no record to pair with,
    // so this is the only way its pictures reach the bubble.
    for (message in users) {
        val own = message.images.mapNotNull(::messagePicture)
        if (own.isEmpty()) continue
        val paired = taken[message.id].orEmpty()
        val seen = paired.map { it.id }.toSet()
        val merged = paired + own.filter { it.id !in seen }.distinctBy { it.id }
        if (merged.isNotEmpty()) taken[message.id] = merged
    }
    return taken
}

/** The [图片] marks the computer writes before a user message's words for its pictures (chats.py). */
private val PictureMarks = Regex("""^(\[图片\]\s*)+""")

/** A user message's words after its [图片] marks, or null without one. */
fun picturedWords(text: String): String? = PictureMarks.find(text)?.let { text.substring(it.range.last + 1) }

/** Text without any whitespace, as the web compares a send with its message (codex-ui.js normalize). */
private fun squeezed(text: String) = text.filterNot { it.isWhitespace() }

/** When the record wrote a message (its `time`, ISO 8601), in seconds since 1970 as the computer counts a send's. */
private fun writtenAt(message: Message): Double? {
    val time = runCatching { JSONObject(message.details).string("time") }.getOrDefault("")
    if (time.isBlank()) return null
    return runCatching { java.time.OffsetDateTime.parse(time).toInstant() }.getOrNull()?.let { it.epochSecond + it.nano / 1e9 }
}
