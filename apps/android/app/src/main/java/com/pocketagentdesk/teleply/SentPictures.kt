package com.pocketagentdesk.teleply

import org.json.JSONObject

/**
 * A picture sent with a message through this service (web codex-ui.js renderImages; iPhone SentPicture): the computer
 * keeps it and a small copy, by its id (GET /api/codex/image).
 */
data class SentPicture(val id: String, val name: String)

/** One of the computer's records of a picture ({id, name, url, thumbnail, …}); null without a usable id. */
private fun sentPicture(j: JSONObject): SentPicture? {
    val id = j.string("id")
    if (id.isEmpty() || id.length > 64 || !id.all { it in 'a'..'z' || it in 'A'..'Z' || it in '0'..'9' || it == '-' }) return null
    return SentPicture(id, j.string("name").ifBlank { "图片" })
}

/**
 * The pictures to show in each user message, by the message's id (user 10-27: a sent picture showed as "[图片]"; web
 * message-projection.js decorate; iPhone sentPictures). The computer keeps a record of each send with pictures (state
 * `images`, oldest first) and Codex keeps that send's request id on its message, so those go by it. Claude keeps none:
 * a send of its goes to the newest message not yet taken whose words after its [图片] mark are the send's, written no
 * earlier than 5 s before the send. Newest first, as the page holds the newest messages: an older send whose message is
 * not loaded gets none.
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
