package com.pocketagentdesk.teleply

import androidx.compose.foundation.Image as ComposeImage
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.platform.LocalUriHandler
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.*
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import org.commonmark.ext.gfm.tables.*
import org.commonmark.node.*
import org.commonmark.node.Text as MdText
import org.commonmark.parser.Parser

private val markdownParser = Parser.builder().extensions(listOf(TablesExtension.create())).build()
fun markdownDocument(source: String): Node = markdownParser.parse(source)
/**
 * Parsed Markdown by its source, the least recently used going first. Bounded by characters, and with room for whole
 * pages: 60 messages of the most the computer sends whole (6,000 characters) are 360,000 (10-27: 32 entries were
 * fewer than a page, so a page scrolled back and forth was parsed again and again).
 */
class MarkdownCache(private val limit:Int=1500,private val maxChars:Int=800_000) {
    private val entries=LinkedHashMap<String,Node>(64,0.75f,true)
    private var chars=0L
    @Synchronized fun document(source:String):Node {
        entries[source]?.let { return it }
        val node=markdownDocument(source)
        if(source.length<=maxChars) {
            entries[source]=node;chars+=source.length
            val eldest=entries.entries.iterator()
            while((entries.size>limit || chars>maxChars) && eldest.hasNext()) { chars-=eldest.next().key.length;eldest.remove() }
        }
        return node
    }
    @Synchronized fun clear() { entries.clear();chars=0 }
    @Synchronized fun size()=entries.size
    /** Characters kept, for tests. */
    @Synchronized fun characters()=chars
}
private val renderCache=MarkdownCache()
fun clearMarkdownCache()=renderCache.clear()
/** A reply tidied for reading and parsed, kept by its source: what the timeline draws, and what finds its pictures. */
fun answerDocument(source:String):Node = renderCache.document(tidyAnswer(source,shown=true))
fun children(node: Node): List<Node> = buildList { var child=node.firstChild; while(child!=null) { add(child); child=child.next } }
fun plain(node: Node): String = when(node) { is MdText -> node.literal; is Code -> node.literal; is SoftLineBreak, is HardLineBreak -> "\n"; else -> children(node).joinToString("") { plain(it) } }
fun safeWebLink(destination: String): Boolean = runCatching { val u=java.net.URI(destination); u.scheme in listOf("https","http") && !u.host.isNullOrBlank() && u.userInfo==null }.getOrDefault(false)

/** Codex's memory citations, which it adds for itself at the end of an answer. */
private val MemoryCitation=Regex("""\s*<oai-mem-citation>[\s\S]*?</oai-mem-citation>""")
/** Codex's file citation: :codex-file-citation{path="…" purpose="output"}. */
private val FileCitation=Regex(""":codex-file-citation\{[^}]*?path="([^"]+)"[^}]*\}""")

/** A conversation a Codex reply says it made (web remote.html assistantMarkdown): a threadId one opens; a clientThreadId one is still being made. */
data class CreatedThread(val id: String, val ready: Boolean)
/** Codex naming a conversation it made, on a line of its own: ::created-thread{threadId="…"} or clientThreadId. */
private val CreatedThreadLine=Regex("""^::created-thread\{(threadId|clientThreadId)="([a-zA-Z0-9-]+)"\}$""")
/** A code fence's line (web: three or more ` or ~ at the start, after any spaces); what is inside one stays as written. */
private val FenceLine=Regex("""^\s*(`{3,}|~{3,})""")

/**
 * The lines Codex writes for its desktop, outside code (web remote.html assistantMarkdown; iPhone MarkdownReader
 * directives): a line of its own naming a conversation it made, and its plan's <proposed_plan> tags, leave the text.
 * The conversations come back in order, for a button each under the text ([createdThreads]).
 */
private fun answerDirectives(source: String): Pair<String,List<CreatedThread>> {
    if("::created-thread{" !in source && "proposed_plan>" !in source) return source to emptyList()
    val lines=mutableListOf<String>();val threads=mutableListOf<CreatedThread>();var fence:Char?=null
    for(line in source.split('\n')) {
        val marker=FenceLine.find(line)?.groupValues?.get(1)?.first()
        if(marker!=null) { if(fence==null) fence=marker else if(fence==marker) fence=null;lines+=line;continue }
        if(fence==null) {
            val bare=line.trim()
            val made=CreatedThreadLine.matchEntire(bare)
            if(made!=null) { threads+=CreatedThread(made.groupValues[2],made.groupValues[1]=="threadId");continue }
            if(bare=="<proposed_plan>" || bare=="</proposed_plan>") continue
        }
        lines+=line
    }
    return lines.joinToString("\n") to threads
}

/** The conversations a reply says it made: 打开新建对话 under the text for each (user 10-27: the line showed raw on the phone). */
fun createdThreads(source: String): List<CreatedThread> = answerDirectives(source).second

/**
 * What Codex writes for itself goes before an answer is shown, copied or shared (user 10-27: a phone user asked what
 * the lines at the bottom were; as on the iPhone, MarkdownReader.tidy): its memory citations go whole, and a file
 * citation becomes a link to the file, which opens like any file link. A conversation it made goes from the text too,
 * to a button under it ([createdThreads]), and so do its plan's tags. [shown] is for the reader, whose parser takes a
 * backslash before a punctuation mark for an escape: the path's backslashes are doubled to come through whole
 * (D:\a\.claude); copied text keeps them single.
 */
fun tidyAnswer(source: String, shown: Boolean=false): String {
    val text=answerDirectives(source).first
    if("oai-mem-citation" !in text && ":codex-file-citation" !in text) return text
    return text.replace(MemoryCitation,"").replace(FileCitation) { m ->
        val path=m.groupValues[1]
        val name=path.substringAfterLast('/').substringAfterLast('\\').ifBlank { path }
        "[$name](<${if(shown) path.replace("\\","\\\\") else path}>)"
    }
}

/**
 * A file on the computer an answer links to (web markdown-ui.js local): a drive letter and a slash, after any
 * %-escapes. A line number after the file (report.md:12 or :12-20) names the same file (message_files references).
 */
fun localPath(destination: String): String? {
    val path=if('%' in destination) runCatching { java.net.URLDecoder.decode(destination.replace("+","%2B"),"UTF-8") }.getOrDefault(destination) else destination
    if(!Regex("""^[A-Za-z]:[\\/]""").containsMatchIn(path)) return null
    return path.replace(Regex(""":\d+(?:-\d+)?$"""),"")
}

private const val FileScheme="teleply-file:"
/** The link a file in an answer carries on screen; the app opens the file's page for it (fileLinkPath, ReaderApp). */
fun fileLink(path: String)=FileScheme+java.net.URLEncoder.encode(path,"UTF-8")
/** The path behind a link drawn by [fileLink]; null for any other address. */
fun fileLinkPath(link: String): String? = if(link.startsWith(FileScheme)) runCatching { java.net.URLDecoder.decode(link.removePrefix(FileScheme),"UTF-8") }.getOrNull() else null

/** Link colour, inline-code fill and the grey of a note saying why a link cannot be opened (§6.1). */
internal data class MdInk(val link: Color, val code: Color, val muted: Color)

/**
 * A link that opens one of the answer's files by the very entry the computer listed (§5.1, 6.1): the file page opens
 * with it, without reading the conversation's whole file list first.
 */
private const val ItemScheme = "teleply-item:"
fun itemLink(file: FileRef): String = ItemScheme + java.net.URLEncoder.encode(file.toJson().toString(), "UTF-8")
fun itemLinkFile(link: String): FileRef? = if (link.startsWith(ItemScheme)) runCatching {
    parseFileRef(org.json.JSONObject(java.net.URLDecoder.decode(link.removePrefix(ItemScheme), "UTF-8")))
}.getOrNull() else null

/** The grey note's own link: opening it shows the whole reason (§6.4). */
private const val WhyScheme = "teleply-why:"
fun whyLink(note: FileNote): String = WhyScheme + java.net.URLEncoder.encode(
    org.json.JSONObject().put("href", note.href).put("reason", note.reason).put("text", note.text).toString(), "UTF-8")
fun whyLinkNote(link: String): FileNote? = if (link.startsWith(WhyScheme)) runCatching {
    val j = org.json.JSONObject(java.net.URLDecoder.decode(link.removePrefix(WhyScheme), "UTF-8"))
    FileNote(j.optString("href"), j.optString("reason"), j.optString("text"))
}.getOrNull() else null

private fun linkStyle(color: Color) = TextLinkStyles(SpanStyle(color = color))

/** A link over the words [block] adds, its range kept so that no second target is put over the same words (§5.1). */
private fun AnnotatedString.Builder.linkTo(url: String, color: Color, links: MutableList<IntRange>, block: AnnotatedString.Builder.() -> Unit) {
    val start = length
    withLink(LinkAnnotation.Url(url, linkStyle(color)), block)
    links.add(start until length)
}

private fun AnnotatedString.Builder.appendChildren(n: Node, ink: MdInk, files: List<FileRef>?, notes: List<FileNote>, links: MutableList<IntRange>) {
    children(n).forEach { appendNode(it, ink, files, notes, links) }
}

private fun AnnotatedString.Builder.grey(text: String, ink: MdInk) = withStyle(SpanStyle(color = ink.muted)) { append(text) }

/** The short grey note after a link, and, tapped, the whole reason (§6.1, 6.4). */
private fun AnnotatedString.Builder.appendNote(note: FileNote, ink: MdInk, links: MutableList<IntRange>) {
    append(" ")
    linkTo(whyLink(note), ink.muted, links) { append("（${note.short}）") }
}

/**
 * One node as words. With the answer's `files` (a newer computer), a link is matched with them by its path and opens
 * that entry; one that cannot be given says why in grey (§6.1). Without them (an older computer) every link goes the
 * 1.0.10 way. `#`, `mailto:` and other protocols are words only; a web address on the computer itself says so.
 */
private fun AnnotatedString.Builder.appendNode(n: Node, ink: MdInk, files: List<FileRef>?, notes: List<FileNote>, links: MutableList<IntRange>) {
    when(n) {
        is MdText -> append(n.literal)
        is Code -> withStyle(SpanStyle(fontFamily=FontFamily.Monospace,background=ink.code)) { append(n.literal) }
        is SoftLineBreak -> append(" ")
        is HardLineBreak -> append("\n")
        is StrongEmphasis -> withStyle(SpanStyle(fontWeight=FontWeight.Bold)) { appendChildren(n, ink, files, notes, links) }
        is Emphasis -> withStyle(SpanStyle(fontStyle=FontStyle.Italic)) { appendChildren(n, ink, files, notes, links) }
        is Link -> {
            val destination = n.destination
            val file = files?.let { fileForLink(it, destination) }
            val note = if (files != null) noteForLink(notes, destination) else null
            val path = localPath(destination)
            when {
                // A file on the computer opens its page, to look at, save or share (web: the link downloads it, 10-27).
                file != null -> linkTo(itemLink(file), ink.link, links) { appendChildren(n, ink, files, notes, links) }
                path != null && files == null -> linkTo(fileLink(path), ink.link, links) { appendChildren(n, ink, files, notes, links) }
                // A newer computer did not list it; its note says why, if it gave one.
                path != null -> {
                    appendChildren(n, ink, files, notes, links)
                    if (note != null) appendNote(note, ink, links) else { append(" "); grey("（找不到文件）", ink) }
                }
                // A link that looked like a file but cannot be given: its words stay, the reason follows in grey.
                note != null -> {
                    linkTo(whyLink(note), ink.link, links) { appendChildren(n, ink, files, notes, links) }
                    appendNote(note, ink, links)
                }
                localWebLink(destination) -> { appendChildren(n, ink, files, notes, links); append(" "); grey("（电脑本机网址，手机打不开）", ink) }
                safeWebLink(destination) -> linkTo(destination, ink.link, links) { appendChildren(n, ink, files, notes, links) }
                // An older computer keeps 1.0.10's words for an address that looks like a file; #, mailto: and the
                // rest are words only (§6.1).
                else -> {
                    appendChildren(n, ink, files, notes, links)
                    if (files == null && fileLikeLink(destination)) append("（链接未开放）")
                }
            }
        }
        is Image -> {
            val destination = n.destination
            val file = files?.let { fileForLink(it, destination) }
            val path = localPath(destination)
            val label = plain(n).ifBlank { file?.name?.ifBlank { null } ?: path?.substringAfterLast('/')?.substringAfterLast('\\') ?: "未命名" }
            when {
                file != null -> linkTo(itemLink(file), ink.link, links) { append("[图片：$label]") }
                path != null -> linkTo(fileLink(path), ink.link, links) { append("[图片：$label]") }
                else -> append("[图片：$label · 可在当前文件中查看已授权资源]")
            }
        }
        is HtmlInline -> append(n.literal)
        else -> appendChildren(n, ink, files, notes, links)
    }
}

/** The words of a `code` or `path` file (§5.1 `texts`): each as the answer wrote it becomes a link to that file. Words
 *  already inside another link ([occupied]) stay as that link: one piece of text never carries two targets. */
internal fun AnnotatedString.Builder.linkFileTexts(files: List<FileRef>?, ink: MdInk, occupied: MutableList<IntRange>) {
    if (files == null || length == 0) return
    val text = toAnnotatedString().text
    files.forEach { file ->
        file.texts.forEach { words ->
            if (words.isBlank()) return@forEach
            var at = text.indexOf(words)
            while (at >= 0) {
                val end = at + words.length
                if (occupied.none { at < it.last + 1 && end > it.first }) {
                    addLink(LinkAnnotation.Url(itemLink(file), linkStyle(ink.link)), at, end)
                    occupied.add(at until end)
                }
                at = text.indexOf(words, end)
            }
        }
    }
}

private fun inline(node: Node, ink: MdInk, files: List<FileRef>? = null, notes: List<FileNote> = emptyList()): AnnotatedString {
    val builder = AnnotatedString.Builder()
    val links = mutableListOf<IntRange>()
    builder.appendNode(node, ink, files, notes, links)
    builder.linkFileTexts(files, ink, links)
    return builder.toAnnotatedString()
}

/** A paragraph's parts: its words, then a picture where the answer put one, then more words (§6.1). */
internal sealed class ParagraphPiece {
    internal class Words(val text: AnnotatedString) : ParagraphPiece()
    internal class Picture(val file: FileRef) : ParagraphPiece()
}

/** Whether a node holds an `Image` anywhere: a link or emphasis wrapped around one counts (§6.1). */
private fun containsImage(node: Node): Boolean {
    var child = node.firstChild
    while (child != null) {
        if (child is Image || containsImage(child)) return true
        child = child.next
    }
    return false
}

/** The picture a node is, or wraps whole (a link or emphasis whose only child is the picture). */
private fun wrappedImage(node: Node): Image? {
    if (node is Image) return node
    if (node !is Link && node !is Emphasis && node !is StrongEmphasis) return null
    val only = node.firstChild ?: return null
    return if (only.next == null) wrappedImage(only) else null
}

/**
 * A paragraph split around the pictures drawn where it put them. The test is by node, not by its words: an image's
 * alt text never contains `![`, so looking at the words alone kept every picture as a line of text. A paragraph without
 * one stays the single [Words] it always was, so an answer with no pictures is drawn exactly as before and as fast.
 */
internal fun paragraphPieces(node: Node, ink: MdInk, files: List<FileRef>?, notes: List<FileNote>): List<ParagraphPiece> {
    if (files == null || !containsImage(node)) return listOf(ParagraphPiece.Words(inline(node, ink, files, notes)))
    val out = mutableListOf<ParagraphPiece>()
    var words = AnnotatedString.Builder()
    val links = mutableListOf<IntRange>()
    fun flush() {
        if (words.length > 0) {
            words.linkFileTexts(files, ink, links)
            out += ParagraphPiece.Words(words.toAnnotatedString())
            words = AnnotatedString.Builder()
            links.clear()
        }
    }
    children(node).forEach { child ->
        val file = wrappedImage(child)?.let { pictureForImage(files, it.destination) }
        if (file != null) { flush(); out += ParagraphPiece.Picture(file) } else words.appendNode(child, ink, files, notes, links)
    }
    flush()
    return out
}

/**
 * Native Markdown blocks in the web's reading style (16sp, line height 1.7).
 * selectable: only the "选择文字" panel; in the timeline long-press belongs to the message menu.
 * textModifier: added to every paragraph, used to give TalkBack "更多操作" without merging a long reply into one focus.
 * HTML is shown as text, never executed.
 */
@Composable fun Markdown(
    source: String,
    modifier: Modifier=Modifier,
    selectable: Boolean=false,
    textModifier: Modifier=Modifier,
    linkColor: Color=Color.Unspecified,
    codeBackground: Color=Color.Unspecified,
    reader: Boolean=false,
    files: List<FileRef>? = null,
    notes: List<FileNote> = emptyList(),
) {
    val p=LocalTeleply.current
    val root=remember(source) { answerDocument(source) }
    val ink=MdInk(if(linkColor==Color.Unspecified) p.accent else linkColor,if(codeBackground==Color.Unspecified) p.codeFill else codeBackground,p.muted)
    val blocks=@Composable {
        Column(verticalArrangement=Arrangement.spacedBy(12.dp)) { children(root).forEachIndexed { index,node -> MarkdownBlock(node,textModifier,ink,index==0,reader,files,notes) } }
    }
    if(selectable) SelectionContainer(modifier) { blocks() } else Box(modifier) { blocks() }
}
@Composable private fun MarkdownBlock(node: Node,textModifier:Modifier,ink:MdInk,first:Boolean=false,reader:Boolean=false,files:List<FileRef>? = null,notes:List<FileNote> = emptyList()) {
    val p=LocalTeleply.current
    val type=MaterialTheme.typography
    val body=if(reader) type.reader else type.reading
    when(node) {
        is Heading -> {
            val text=remember(node,ink,files,notes) { inline(node,ink,files,notes) }
            val style=when(node.level) { 1 -> type.titleMedium.copy(fontSize=18.sp,lineHeight=26.sp); 2 -> type.titleMedium; else -> body.copy(fontWeight=FontWeight.SemiBold) }
            Text(text,style=style,modifier=textModifier.padding(top=if(first) 0.dp else 8.dp).semantics { heading() })
        }
        is org.commonmark.node.Paragraph -> {
            val pieces=remember(node,ink,files,notes) { paragraphPieces(node,ink,files,notes) }
            if(pieces.size==1 && pieces[0] is ParagraphPiece.Words) Text((pieces[0] as ParagraphPiece.Words).text,style=body,modifier=textModifier)
            else Column(verticalArrangement=Arrangement.spacedBy(8.dp)) { pieces.forEach { piece ->
                when(piece) {
                    is ParagraphPiece.Words -> if(piece.text.isNotBlank()) Text(piece.text,style=body,modifier=textModifier)
                    is ParagraphPiece.Picture -> MarkdownPicture(piece.file)
                }
            } }
        }
        is FencedCodeBlock -> CodePanel(node.info.ifBlank { "代码" },node.literal.removeSuffix("\n"),if(node.info.isBlank()) "复制代码" else "复制 ${node.info} 代码")
        is IndentedCodeBlock -> CodePanel("代码",node.literal.removeSuffix("\n"),"复制代码")
        is BlockQuote -> Row(Modifier.height(IntrinsicSize.Min)) {
            Box(Modifier.width(3.dp).fillMaxHeight().background(p.line))
            Column(Modifier.padding(start=12.dp),verticalArrangement=Arrangement.spacedBy(8.dp)) { children(node).forEach { MarkdownBlock(it,textModifier,ink,reader=reader,files=files,notes=notes) } }
        }
        is BulletList, is OrderedList -> Column(verticalArrangement=Arrangement.spacedBy(6.dp)) { children(node).forEachIndexed { index,item ->
            Row {
                Text(if(node is OrderedList) "${node.markerStartNumber+index}." else "•",style=body,modifier=Modifier.widthIn(min=20.dp))
                Column(Modifier.weight(1f),verticalArrangement=Arrangement.spacedBy(6.dp)) { children(item).forEach { MarkdownBlock(it,textModifier,ink,reader=reader,files=files,notes=notes) } }
            }
        } }
        is TableBlock -> MarkdownTable(node,ink,files,notes)
        is ThematicBreak -> HorizontalDivider(color=p.line)
        is HtmlBlock -> Text(node.literal,style=type.bodyMedium,modifier=textModifier) // Native text, never executable HTML.
        else -> children(node).forEach { MarkdownBlock(it,textModifier,ink,reader=reader,files=files,notes=notes) }
    }
}
@Composable private fun MarkdownTable(node:TableBlock,ink:MdInk,files:List<FileRef>? = null,notes:List<FileNote> = emptyList()) {
    val p=LocalTeleply.current
    val cellWidth=200.dp*LocalDensity.current.fontScale.coerceIn(1f,1.6f)
    val rows=children(node).flatMap { children(it) }
    // Wide tables scroll inside their own box; the message itself never moves sideways (B16).
    Column(Modifier.fillMaxWidth().horizontalScroll(rememberScrollState())) { rows.forEachIndexed { index,row ->
        Row(Modifier.background(if(index==0) p.panel else p.page)) {
            children(row).forEach { cell ->
                val text=remember(cell,ink,files,notes) { inline(cell,ink,files,notes) }
                Text(text,style=MaterialTheme.typography.bodyMedium,fontWeight=if(index==0) FontWeight.SemiBold else FontWeight.Normal,modifier=Modifier.width(cellWidth).padding(12.dp))
            }
        }
        HorizontalDivider(color=p.line)
    } }
}

/**
 * A picture drawn where the answer put it (§6.1): the bubble's width, at most about 360 dp high, its place kept by the
 * computer's `w`/`h` (4:3 when it gave none) while the thumb comes. Grey with the file's name until then; a line and
 * 重试 when it cannot be had. A tap opens the file's page (the picture page comes with stage B).
 */
@Composable private fun MarkdownPicture(file: FileRef) {
    val p = LocalTeleply.current
    val loader = LocalAnswerThumb.current
    val opener = LocalAnswerPicture.current
    val uri = LocalUriHandler.current
    val density = LocalDensity.current
    // The bubble's width in pixels, not in dp: a 411 dp phone at 2.6 draws a bubble over 1,000 px wide, where 640
    // would be soft (§6.3).
    val width = pictureWidth(LocalConfiguration.current.screenWidthDp * density.density)
    var attempt by remember(file.id) { mutableIntStateOf(0) }
    var failed by remember(file.id, attempt) { mutableStateOf(false) }
    val image by produceState<android.graphics.Bitmap?>(null, file.id, file.version, width, attempt) {
        value = null; failed = false
        val bitmap = loader?.invoke(file, width)
        value = bitmap; failed = bitmap == null
    }
    val ratio = if (file.width > 0 && file.height > 0) file.width.toFloat() / file.height else 4f / 3f
    BoxWithConstraints(Modifier.fillMaxWidth().padding(top = 4.dp)) {
        // A tall picture keeps its whole height: the box narrows instead of cropping its middle.
        val height = (maxWidth / ratio).coerceAtMost(360.dp)
        val shownWidth = height * ratio
        Box(Modifier.fillMaxWidth(), contentAlignment = Alignment.Center) {
            Box(
                Modifier.width(shownWidth).height(height).clip(RoundedCornerShape(12.dp)).background(p.panel)
                    .clickable(role = Role.Image) { opener?.invoke(file) ?: uri.openUri(itemLink(file)) }
                    .semantics { contentDescription = "查看 ${file.name.ifBlank { "图片" }}" },
                contentAlignment = Alignment.Center,
            ) {
                val bitmap = image
                when {
                    bitmap != null -> ComposeImage(bitmap.asImageBitmap(), contentDescription = null, contentScale = ContentScale.Fit, modifier = Modifier.fillMaxSize())
                    failed -> Row(verticalAlignment = Alignment.CenterVertically) {
                        Text("没能加载缩略图", style = MaterialTheme.typography.note, color = p.muted)
                        Text("重试", style = MaterialTheme.typography.note, color = p.accent,
                            modifier = Modifier.padding(start = 12.dp).clip(RoundedCornerShape(6.dp)).clickable { attempt++ }.padding(vertical = 4.dp))
                    }
                    else -> Text(file.name.ifBlank { "图片" }, style = MaterialTheme.typography.note, color = p.muted, maxLines = 2, overflow = TextOverflow.Ellipsis, modifier = Modifier.padding(horizontal = 16.dp))
                }
            }
        }
    }
}
