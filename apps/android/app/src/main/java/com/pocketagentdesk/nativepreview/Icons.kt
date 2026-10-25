package com.pocketagentdesk.nativepreview

import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.StrokeJoin
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.graphics.vector.addPathNodes
import androidx.compose.ui.unit.dp

/**
 * The web's line icons (remote.html ICONS): 24 viewport, 1.8 stroke, round caps and joins.
 * Icons the web lacks (mic, copy, share…) are drawn to the same rules; no filled Material icons are mixed in.
 */
object TeleplyIcons {
    val Menu by lazy { line("menu", "M4 6h16M4 12h16M4 18h16") }
    val Back by lazy { line("back", "m14 5-7 7 7 7") }
    val Close by lazy { line("close", "m6 6 12 12M18 6 6 18") }
    val New by lazy { line("new", "M12 5H5v14h14v-7M14 4l6 6M11 13l2-5 5-5 3 3-5 5z") }
    val More by lazy {
        line(
            "more",
            "M5 12m-1 0a1 1 0 1 0 2 0a1 1 0 1 0-2 0",
            "M12 12m-1 0a1 1 0 1 0 2 0a1 1 0 1 0-2 0",
            "M19 12m-1 0a1 1 0 1 0 2 0a1 1 0 1 0-2 0",
        )
    }
    val Send by lazy { line("send", "M12 19V5m-6 6 6-6 6 6") }
    val Down by lazy { line("down", "M12 5v14m-6-6 6 6 6-6") }
    val Chat by lazy { line("chat", "M4 4h16v12H9l-5 4z") }
    val Window by lazy { line("window", "M3 4h18v13H3zM8 21h8M12 17v4") }
    val Check by lazy { line("check", "m5 12 4 4L19 6") }
    /** A folder (0.9): the web sidebar's rounded one everywhere, so a folder looks the same on every page (design language §4). */
    val Folder by lazy { line("folder", "M3 8V6.5A2.5 2.5 0 0 1 5.5 4H9l2.5 2.5h7A2.5 2.5 0 0 1 21 9v8.5a2.5 2.5 0 0 1-2.5 2.5h-13A2.5 2.5 0 0 1 3 17.5V8Zm0 1h18") }
    val Box by lazy { line("box", "M4 4h16v16H4z") }
    val Settings by lazy {
        line(
            "settings",
            "M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2zM15 12a3 3 0 1 1-6 0 3 3 0 0 1 6 0z",
        )
    }
    val Plus by lazy { line("plus", "M12 4v16M4 12h16") }
    val ChevronRight by lazy { line("chevron-right", "m9 6 6 6-6 6") }
    val ChevronDown by lazy { line("chevron-down", "m6 9 6 6 6-6") }
    val ChevronLeft by lazy { line("chevron-left", "m15 6-6 6 6 6") }
    val Mic by lazy { line("mic", "M12 3a3 3 0 0 0-3 3v6a3 3 0 0 0 6 0V6a3 3 0 0 0-3-3z", "M19 11a7 7 0 0 1-14 0M12 18v3") }
    val Copy by lazy { line("copy", "M9 9h11v11H9z", "M5 15H4V4h11v1") }
    val Share by lazy { line("share", "M4 12v7a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-7M16 6l-4-4-4 4M12 2v13") }
    val Image by lazy { line("image", "M3 5h18v14H3z", "M8.5 11a1.5 1.5 0 1 0 0-3 1.5 1.5 0 0 0 0 3zM21 15l-5-5L5 19") }
    val File by lazy { line("file", "M14 3H6v18h12V7z", "M14 3v4h4") }
    val Warning by lazy { line("warning", "M12 9v4M12 17h.01", "M10.3 3.9 2 18a2 2 0 0 0 1.7 3h16.6a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z") }
    val Info by lazy { line("info", "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18z", "M12 16v-5M12 8h.01") }
    val Help by lazy { line("help", "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18z", "M9.5 9a2.5 2.5 0 0 1 4.9.7c0 1.7-2.4 2.3-2.4 3.8M12 17h.01") }
    val Clock by lazy { line("clock", "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18z", "M12 7v5l3 2") }
    val Stop by lazy { line("stop", "M7 7h10v10H7z") }
    val Search by lazy { line("search", "M11 4a7 7 0 1 0 0 14 7 7 0 0 0 0-14z", "m20 20-4-4") }
    val Refresh by lazy { line("refresh", "M21 12a9 9 0 1 1-9-9c2.5 0 4.9 1 6.7 2.7L21 8", "M21 3v5h-5") }
    val Skill by lazy { line("skill", "M12 3l8 4.5v9L12 21l-8-4.5v-9z") }
    val Text by lazy { line("text", "M4 6h16M4 12h10M4 18h7") }
    val Bell by lazy { line("bell", "M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9", "M10.3 21a1.9 1.9 0 0 0 3.4 0") }
    val Save by lazy { line("save", "M12 4v12m-5-5 5 5 5-5", "M4 20h16") }
    val Open by lazy { line("open", "M14 4h6v6M20 4l-9 9", "M18 14v6H4V6h6") }
    val Camera by lazy { line("camera", "M4 8h3l2-3h6l2 3h3v11H4z", "M12 16.5a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7z") }
    /** The web's archive icon (archive-ui.js). */
    val Archive by lazy { line("archive", "M3 4h18v4H3zM5 8v12h14V8M10 12h4") }
    /** The web's SPARK (static/new-chat-ui.js): the model row of a new conversation. */
    val Spark by lazy { line("spark", "M12 3.5l1.8 4.7 4.7 1.8-4.7 1.8-1.8 4.7-1.8-4.7-4.7-1.8 4.7-1.8z", "M18.5 15.5l.7 1.8 1.8.7-1.8.7-.7 1.8-.7-1.8-1.8-.7 1.8-.7z") }
    /** A project (0.9, web sidebar `folder()`): the rounded folder, 1.5 stroke; used wherever a project is named. */
    val Project by lazy { line("project", "M3 8V6.5A2.5 2.5 0 0 1 5.5 4H9l2.5 2.5h7A2.5 2.5 0 0 1 21 9v8.5a2.5 2.5 0 0 1-2.5 2.5h-13A2.5 2.5 0 0 1 3 17.5V8Zm0 1h18", width = 1.5f) }
    /** Conversations in no project (web sidebar LOOSE, 其他对话). */
    val Loose by lazy { line("loose", "M6 5h12a3 3 0 0 1 3 3v8a3 3 0 0 1-3 3H9l-5 3V8a3 3 0 0 1 2-3Z", width = 1.5f) }
    /** Eye for 显示密码 (account page reveal), same rules as the other line icons. */
    val Eye by lazy { line("eye", "M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12z", "M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6z") }
    val Logout by lazy { line("logout", "M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4", "M16 17l5-5-5-5M21 12H9") }
    val Pencil by lazy { line("pencil", "M4 20h4L19 9l-4-4L4 16z", "M13.5 6.5l4 4") }
    val Trash by lazy { line("trash", "M4 7h16M10 11v6M14 11v6", "M6 7l1 13h10l1-13M9 7V4h6v3") }
}

private fun line(name: String, vararg paths: String, width: Float = 1.8f): ImageVector =
    ImageVector.Builder(name = name, defaultWidth = 24.dp, defaultHeight = 24.dp, viewportWidth = 24f, viewportHeight = 24f).apply {
        for (d in paths) {
            addPath(
                pathData = addPathNodes(d),
                fill = null,
                stroke = SolidColor(Color.Black),
                strokeLineWidth = width,
                strokeLineCap = StrokeCap.Round,
                strokeLineJoin = StrokeJoin.Round,
            )
        }
    }.build()
