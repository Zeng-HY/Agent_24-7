package com.pocketagentdesk.teleply

import org.commonmark.node.Image
import org.commonmark.node.Link
import org.commonmark.node.Node
import org.junit.Assert.*
import org.junit.Test

/**
 * Answers as the user saw them on 10-27 (as on the iPhone): Codex's memory citations are not shown, copied or shared;
 * its file citations and links to files on the computer open the file's page instead of reading （链接未开放）.
 */
class AnswerLinksTest {
    private val answer = """
已合并为一份。

:codex-file-citation{path="D:\Personal\agent_remote\.claude\合并稿.docx" purpose="output"}

<oai-mem-citation>
<citation_entries>
MEMORY.md:694-696|note=[used Windows Word rendering fallback workflow]
</citation_entries>
<rollout_ids>
01a0bef3-b1d0-79d3-b7e4-4251056b2729
</rollout_ids>
</oai-mem-citation>
""".trimIndent()

    private fun links(node: Node): List<String> = buildList {
        if (node is Link) add(node.destination)
        if (node is Image) add(node.destination)
        var child = node.firstChild
        while (child != null) { addAll(links(child)); child = child.next }
    }

    @Test fun codexMemoryNotesGoAndAFileCitationBecomesALink() {
        val copied = tidyAnswer(answer)
        assertFalse(copied.contains("oai-mem-citation") || copied.contains("MEMORY.md") || copied.contains("codex-file-citation"))
        assertEquals("已合并为一份。\n\n[合并稿.docx](<D:\\Personal\\agent_remote\\.claude\\合并稿.docx>)", copied)
        // Shown: the reader's parser would take "\." for an escape; the path comes through whole.
        val shown = markdownDocument(tidyAnswer(answer, shown = true))
        assertEquals(listOf("D:\\Personal\\agent_remote\\.claude\\合并稿.docx"), links(shown))
        assertEquals("没有注记", tidyAnswer("没有注记"))
        // Windows dev.22 writes the citation as a link itself, with forward slashes: nothing left to tidy, it opens the same.
        val fromDev22 = "已合并为一份。\n\n[合并稿.docx](<D:/Personal/语言桥/合并稿.docx>)"
        assertEquals(fromDev22, tidyAnswer(fromDev22, shown = true))
        assertEquals(listOf("D:/Personal/语言桥/合并稿.docx"), links(markdownDocument(fromDev22)).map { localPath(it) })
        assertEquals(normalizePath("D:\\Personal\\语言桥\\合并稿.docx"), normalizePath("D:/Personal/语言桥/合并稿.docx"))
        // Not closed (a cut message): left as it is.
        assertEquals("a <oai-mem-citation>b", tidyAnswer("a <oai-mem-citation>b"))
    }

    /**
     * Codex names a conversation it made on a line of its own (user 10-27: it showed raw on the phone); the web draws
     * 打开新建对话 under the text instead. Inside code the line stays; a clientThreadId one is not made yet (iPhone 0.5.2).
     */
    @Test fun aConversationCodexMadeIsAButtonNotALine() {
        val answer = "已新建对话。\n\n::created-thread{threadId=\"0000-made-1\"}"
        assertEquals("已新建对话。\n", tidyAnswer(answer))
        assertEquals(listOf(CreatedThread("0000-made-1", true)), createdThreads(answer))
        assertEquals(listOf(CreatedThread("c-1", false)), createdThreads("  ::created-thread{clientThreadId=\"c-1\"}\r"))
        val code = "```text\n::created-thread{threadId=\"x\"}\n```"
        assertEquals(code, tidyAnswer(code));assertTrue(createdThreads(code).isEmpty())
        assertTrue(createdThreads("见 ::created-thread{threadId=\"x\"}").isEmpty())
        assertTrue(createdThreads("::created-thread{threadId=\"a b\"}").isEmpty())
        assertEquals("# 计划", tidyAnswer("<proposed_plan>\n# 计划\n</proposed_plan>"))
        // The demo's reply: one made, one being made, and one inside code that stays as written.
        assertEquals(listOf(CreatedThread(FixtureWorld.MADE_THREAD, true), CreatedThread("fixture-making-2", false)), createdThreads(FixtureWorld.MADE_ANSWER))
        assertEquals(1, Regex("created-thread").findAll(tidyAnswer(FixtureWorld.MADE_ANSWER)).count())
        // Shown: a paragraph only, the line gone.
        assertEquals(listOf("已新建对话。"), children(markdownDocument(tidyAnswer(answer, shown = true))).map { plain(it) })
    }

    @Test fun filesOnTheComputerAreLinkedWithoutLineNumbersOrEscapes() {
        assertEquals("D:\\Personal\\语言桥\\确认单.docx", localPath("D:\\Personal\\语言桥\\确认单.docx"))
        assertEquals("D:/a/说明.md", localPath("D:/a/%E8%AF%B4%E6%98%8E.md:3"))
        assertEquals("D:\\a\\b.md", localPath("D:\\a\\b.md:12-20"))
        assertEquals("C:\\pics\\a+b c.png", localPath("C:\\pics\\a+b%20c.png"))
        // A % that is not an escape: the path as written.
        assertEquals("D:\\a\\100%.txt", localPath("D:\\a\\100%.txt"))
        assertNull(localPath("https://example.com/a.md"))
        assertNull(localPath("docs/a.md"))
        assertNull(localPath("D:"))
        val path = "D:\\Personal\\语言桥\\合并稿 v2.docx"
        assertEquals(path, fileLinkPath(fileLink(path)))
        assertNull(fileLinkPath("https://example.com"))
        // As parsed from an answer: a link and a picture on the computer, and a web link left as it was.
        val document = markdownDocument("[确认单](D:\\Personal\\语言桥\\确认单.docx) ![图](C:\\pics\\a.png) [网页](https://example.com)")
        assertEquals(listOf("D:\\Personal\\语言桥\\确认单.docx", "C:\\pics\\a.png", null), links(document).map { localPath(it) })
    }

    @Test fun aLinkWhoseBackslashTheReaderAteStillFindsItsFile() {
        // An answer's own link to D:\a\.claude\x.md arrives as D:\a.claude\x.md.
        val listed = "D:\\Personal\\agent_remote\\.claude\\x.md"
        val linked = links(markdownDocument("[x](D:\\Personal\\agent_remote\\.claude\\x.md)")).single()
        assertEquals("D:\\Personal\\agent_remote.claude\\x.md", linked)
        assertNotEquals(normalizePath(listed), normalizePath(linked))
        assertEquals(looseFilePath(listed), looseFilePath(linked))
        assertEquals(normalizePath("d:/PERSONAL/x.md"), normalizePath("D:\\Personal\\x.md"))
    }
}
