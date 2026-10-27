package com.pocketagentdesk.teleply

import androidx.compose.foundation.background
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.*
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import org.commonmark.ext.gfm.tables.*
import org.commonmark.node.*
import org.commonmark.node.Text as MdText
import org.commonmark.parser.Parser

private val markdownParser = Parser.builder().extensions(listOf(TablesExtension.create())).build()
fun markdownDocument(source: String): Node = markdownParser.parse(source)
class MarkdownCache(private val limit:Int=32,private val maxChars:Int=256000) {
    private val entries=object:LinkedHashMap<String,Node>(16,0.75f,true) {}
    @Synchronized fun document(source:String):Node {
        entries[source]?.let { return it }
        val node=markdownDocument(source)
        if(source.length<=maxChars) {
            entries[source]=node
            while(entries.size>limit || entries.keys.sumOf { it.length }>maxChars) entries.remove(entries.keys.first())
        }
        return node
    }
    @Synchronized fun clear()=entries.clear()
    @Synchronized fun size()=entries.size
}
private val renderCache=MarkdownCache()
fun clearMarkdownCache()=renderCache.clear()
fun children(node: Node): List<Node> = buildList { var child=node.firstChild; while(child!=null) { add(child); child=child.next } }
fun plain(node: Node): String = when(node) { is MdText -> node.literal; is Code -> node.literal; is SoftLineBreak, is HardLineBreak -> "\n"; else -> children(node).joinToString("") { plain(it) } }
fun safeWebLink(destination: String): Boolean = runCatching { val u=java.net.URI(destination); u.scheme in listOf("https","http") && !u.host.isNullOrBlank() && u.userInfo==null }.getOrDefault(false)

/** Codex's memory citations, which it adds for itself at the end of an answer. */
private val MemoryCitation=Regex("""\s*<oai-mem-citation>[\s\S]*?</oai-mem-citation>""")
/** Codex's file citation: :codex-file-citation{path="…" purpose="output"}. */
private val FileCitation=Regex(""":codex-file-citation\{[^}]*?path="([^"]+)"[^}]*\}""")

/**
 * What Codex writes for itself goes before an answer is shown, copied or shared (user 10-27: a phone user asked what
 * the lines at the bottom were; as on the iPhone, MarkdownReader.tidy): its memory citations go whole, and a file
 * citation becomes a link to the file, which opens like any file link. [shown] is for the reader, whose parser takes a
 * backslash before a punctuation mark for an escape: the path's backslashes are doubled to come through whole
 * (D:\a\.claude); copied text keeps them single.
 */
fun tidyAnswer(source: String, shown: Boolean=false): String {
    if("oai-mem-citation" !in source && ":codex-file-citation" !in source) return source
    return source.replace(MemoryCitation,"").replace(FileCitation) { m ->
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

/** Link colour and inline-code fill: the blue user bubble needs its own colours. */
private data class MdInk(val link: Color, val code: Color)

private fun inline(node: Node, ink: MdInk): AnnotatedString = buildAnnotatedString {
    fun appendNode(n: Node) {
        when(n) {
            is MdText -> append(n.literal)
            is Code -> withStyle(SpanStyle(fontFamily=FontFamily.Monospace,background=ink.code)) { append(n.literal) }
            is SoftLineBreak -> append(" ")
            is HardLineBreak -> append("\n")
            is StrongEmphasis -> withStyle(SpanStyle(fontWeight=FontWeight.Bold)) { children(n).forEach(::appendNode) }
            is Emphasis -> withStyle(SpanStyle(fontStyle=FontStyle.Italic)) { children(n).forEach(::appendNode) }
            is Link -> {
                // A file on the computer opens its page, to look at, save or share (web: the link downloads it, 10-27).
                val file=localPath(n.destination)
                when {
                    file!=null -> withLink(LinkAnnotation.Url(fileLink(file),TextLinkStyles(SpanStyle(color=ink.link)))) { children(n).forEach(::appendNode) }
                    safeWebLink(n.destination) -> withLink(LinkAnnotation.Url(n.destination,TextLinkStyles(SpanStyle(color=ink.link)))) { children(n).forEach(::appendNode) }
                    else -> { children(n).forEach(::appendNode); append("（链接未开放）") }
                }
            }
            is Image -> {
                val file=localPath(n.destination)
                if(file!=null) withLink(LinkAnnotation.Url(fileLink(file),TextLinkStyles(SpanStyle(color=ink.link)))) { append("[图片：${plain(n).ifBlank { file.substringAfterLast('/').substringAfterLast('\\') }}]") }
                else append("[图片：${plain(n).ifBlank { "未命名" }} · 可在当前文件中查看已授权资源]")
            }
            is HtmlInline -> append(n.literal)
            else -> children(n).forEach(::appendNode)
        }
    }
    appendNode(node)
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
) {
    val p=LocalTeleply.current
    val root=remember(source) { renderCache.document(tidyAnswer(source,shown=true)) }
    val ink=MdInk(if(linkColor==Color.Unspecified) p.accent else linkColor,if(codeBackground==Color.Unspecified) p.codeFill else codeBackground)
    val blocks=@Composable {
        Column(verticalArrangement=Arrangement.spacedBy(12.dp)) { children(root).forEachIndexed { index,node -> MarkdownBlock(node,textModifier,ink,index==0,reader) } }
    }
    if(selectable) SelectionContainer(modifier) { blocks() } else Box(modifier) { blocks() }
}
@Composable private fun MarkdownBlock(node: Node,textModifier:Modifier,ink:MdInk,first:Boolean=false,reader:Boolean=false) {
    val p=LocalTeleply.current
    val type=MaterialTheme.typography
    val body=if(reader) type.reader else type.reading
    when(node) {
        is Heading -> {
            val text=remember(node,ink) { inline(node,ink) }
            val style=when(node.level) { 1 -> type.titleMedium.copy(fontSize=18.sp,lineHeight=26.sp); 2 -> type.titleMedium; else -> body.copy(fontWeight=FontWeight.SemiBold) }
            Text(text,style=style,modifier=textModifier.padding(top=if(first) 0.dp else 8.dp).semantics { heading() })
        }
        is org.commonmark.node.Paragraph -> { val text=remember(node,ink) { inline(node,ink) }; Text(text,style=body,modifier=textModifier) }
        is FencedCodeBlock -> CodePanel(node.info.ifBlank { "代码" },node.literal.removeSuffix("\n"),if(node.info.isBlank()) "复制代码" else "复制 ${node.info} 代码")
        is IndentedCodeBlock -> CodePanel("代码",node.literal.removeSuffix("\n"),"复制代码")
        is BlockQuote -> Row(Modifier.height(IntrinsicSize.Min)) {
            Box(Modifier.width(3.dp).fillMaxHeight().background(p.line))
            Column(Modifier.padding(start=12.dp),verticalArrangement=Arrangement.spacedBy(8.dp)) { children(node).forEach { MarkdownBlock(it,textModifier,ink,reader=reader) } }
        }
        is BulletList, is OrderedList -> Column(verticalArrangement=Arrangement.spacedBy(6.dp)) { children(node).forEachIndexed { index,item ->
            Row {
                Text(if(node is OrderedList) "${node.markerStartNumber+index}." else "•",style=body,modifier=Modifier.widthIn(min=20.dp))
                Column(Modifier.weight(1f),verticalArrangement=Arrangement.spacedBy(6.dp)) { children(item).forEach { MarkdownBlock(it,textModifier,ink,reader=reader) } }
            }
        } }
        is TableBlock -> MarkdownTable(node,ink)
        is ThematicBreak -> HorizontalDivider(color=p.line)
        is HtmlBlock -> Text(node.literal,style=type.bodyMedium,modifier=textModifier) // Native text, never executable HTML.
        else -> children(node).forEach { MarkdownBlock(it,textModifier,ink,reader=reader) }
    }
}
@Composable private fun MarkdownTable(node:TableBlock,ink:MdInk) {
    val p=LocalTeleply.current
    val cellWidth=200.dp*LocalDensity.current.fontScale.coerceIn(1f,1.6f)
    val rows=children(node).flatMap { children(it) }
    // Wide tables scroll inside their own box; the message itself never moves sideways (B16).
    Column(Modifier.fillMaxWidth().horizontalScroll(rememberScrollState())) { rows.forEachIndexed { index,row ->
        Row(Modifier.background(if(index==0) p.panel else p.page)) {
            children(row).forEach { cell ->
                val text=remember(cell,ink) { inline(cell,ink) }
                Text(text,style=MaterialTheme.typography.bodyMedium,fontWeight=if(index==0) FontWeight.SemiBold else FontWeight.Normal,modifier=Modifier.width(cellWidth).padding(12.dp))
            }
        }
        HorizontalDivider(color=p.line)
    } }
}
