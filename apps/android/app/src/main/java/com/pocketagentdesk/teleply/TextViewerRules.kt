package com.pocketagentdesk.teleply

/**
 * Stage C's rules (file-preview design §6.2, §5.4): when code is highlighted, where a line request lands, how a cut
 * text says so, whether a CSV comes from the text route, and which files are played or listed as archives. Pure, so
 * they can be read on a plain JVM.
 */

/** Past 200 KB the code page shows line numbers only, no highlighting (§6.2). */
const val HighlightLimit = 200 * 1024

/** A zip listing shows at most this many names (§5.7). */
const val ZipEntryLimit = 2000

/** The most CSV/TSV rows the table page shows (§5.8). */
const val TableRowLimit = 5000

fun shouldHighlight(characters: Int): Boolean = characters <= HighlightLimit

/** A `line` from the computer, kept inside the text it has. */
fun jumpLine(requested: Int, lineCount: Int): Int = if (requested <= 0 || lineCount <= 0) 0 else requested.coerceIn(1, lineCount)

/** The language for highlight.js: the computer's `lang` when it gave one, else the file's ending (§5.1). */
fun codeLanguage(lang: String, name: String): String {
    if (lang.isNotBlank()) return lang
    val base = name.substringAfterLast('/').substringAfterLast('\\')
    if (base.equals("dockerfile", true)) return "dockerfile"
    val ext = name.substringAfterLast('.', "").lowercase()
    return when (ext) {
        "r" -> "r"; "py" -> "python"; "js", "mjs" -> "javascript"; "ts" -> "typescript"; "json" -> "json"
        "yaml", "yml" -> "yaml"; "xml" -> "xml"; "sql" -> "sql"; "sh", "bash" -> "bash"; "ps1" -> "powershell"
        "kt", "kts" -> "kotlin"; "swift" -> "swift"; "java" -> "java"; "c", "h" -> "c"; "cpp", "cc", "hpp" -> "cpp"
        "cs" -> "csharp"; "go" -> "go"; "rs" -> "rust"; "css" -> "css"; "md", "markdown" -> "markdown"
        "ini", "toml" -> "ini"; "diff", "patch" -> "diff"; "tex" -> "latex"; "dockerfile" -> "dockerfile"
        "csv", "tsv" -> "plaintext"; else -> "plaintext"
    }
}

/** What the page says when the computer sent only the start of a large text (§5.4, §6.2). */
fun truncationNotice(shown: Long, total: Long): String? =
    if (total > shown && shown > 0) "只显示了开头 ${mb(shown)} MB，共 ${mb(total)} MB，可以保存后看全文" else null

private fun mb(bytes: Long): String = String.format(java.util.Locale.ROOT, "%.1f", bytes / 1048576.0)

/** A newer computer's CSV/TSV comes from `/api/file/text`; an older one is read on the phone as before (§5.4). */
enum class CsvSource { TEXT, PHONE }

fun csvSource(newComputer: Boolean): CsvSource = if (newComputer) CsvSource.TEXT else CsvSource.PHONE

/** The table page's first [max] rows, and whether any were left out. */
fun limitCsvRows(text: String, max: Int = TableRowLimit): Pair<String, Boolean> {
    val lines = text.split('\n')
    return if (lines.size <= max) text to false else lines.take(max).joinToString("\n") to true
}

/** The archive kinds §5.7 reads; 7z and rar stay a file card. */
fun zipFile(name: String): Boolean = name.substringAfterLast('.', "").lowercase() == "zip"

/** A zip's entries, at most [ZipEntryLimit]; the computer says whether there were more. */
fun zipEntries(listing: org.json.JSONObject): List<org.json.JSONObject> {
    val array = listing.optJSONArray("entries") ?: return emptyList()
    return (0 until array.length()).mapNotNull { array.optJSONObject(it) }.take(ZipEntryLimit)
}

/** Whether the listing says some names are not shown (a cut list, or more than [shown]). */
fun zipMore(listing: org.json.JSONObject, shown: Int): Boolean =
    listing.optBoolean("truncated") || listing.optInt("total", shown) > shown

fun playable(name: String): String? = when (name.substringAfterLast('.', "").lowercase()) {
    "mp3", "m4a", "aac", "wav", "flac", "ogg" -> "audio"
    "mp4", "m4v", "mov", "webm", "mkv" -> "video"
    else -> null
}
