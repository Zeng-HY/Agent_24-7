package com.pocketagentdesk.nativepreview
import org.junit.Test
import org.junit.Assert.*
import org.commonmark.node.*
import org.commonmark.ext.gfm.tables.TableBlock
class MarkdownTest {
    @Test fun parsesNativeBlocksWithoutChangingSource() {
        val source="# 标题\n\n段落 **加粗** [链接](https://example.com)\n\n- 项目\n\n> 引用\n\n```kotlin\na  b\n```\n\n| A | B |\n|---|---|\n|中|文|"
        val nodes=children(markdownDocument(source))
        assertTrue(nodes.any { it is Heading });assertTrue(nodes.any { it is BulletList });assertTrue(nodes.any { it is BlockQuote });assertTrue(nodes.any { it is TableBlock })
        assertEquals("a  b\n",(nodes.first { it is FencedCodeBlock } as FencedCodeBlock).literal)
    }
    @Test fun linksCannotInvokeLocalOrExecutableSchemes() {
        listOf("javascript:alert(1)","file:///etc/passwd","intent://test","https://name:secret@example.com","data:text/html,a").forEach { assertFalse(safeWebLink(it)) }
        assertTrue(safeWebLink("https://developer.android.com/"))
    }
    @Test fun duplicateTextNeverRemovesDifferentIds() {
        val old=listOf(Message("a","user","same"),Message("b","user","same"))
        assertEquals(2,mergeMessages(old,listOf(Message("b","user","updated")),false).size)
    }
}
