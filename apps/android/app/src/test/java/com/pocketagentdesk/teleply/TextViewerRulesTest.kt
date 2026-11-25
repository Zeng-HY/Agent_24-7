package com.pocketagentdesk.teleply

import kotlinx.coroutines.test.runTest
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test

/**
 * Stage C's rules (file-preview design §6.2, §5.4, §5.6, §5.7): the 200 KB highlight line, the line a code page jumps
 * to, a cut text's notice, where a CSV comes from, a zip's listing and cap, and the headers a player gets.
 */
class TextViewerRulesTest {
    @Test fun codeIsHighlightedUpToTwoHundredKilobytes() {
        assertTrue(shouldHighlight(0))
        assertTrue(shouldHighlight(200 * 1024))
        assertFalse(shouldHighlight(200 * 1024 + 1))
        assertFalse(shouldHighlight(2 * 1024 * 1024))
    }

    @Test fun aLineRequestLandsInsideTheText() {
        assertEquals(0, jumpLine(0, 100))
        assertEquals(0, jumpLine(-4, 100))
        assertEquals(12, jumpLine(12, 100))
        assertEquals(100, jumpLine(140, 100))
        assertEquals(0, jumpLine(5, 0))
    }

    @Test fun aCutTextSaysHowMuchIsHere() {
        assertNull(truncationNotice(1024, 1024))
        assertEquals("只显示了开头 2.0 MB，共 5.0 MB，可以保存后看全文", truncationNotice(2L * 1024 * 1024, 5L * 1024 * 1024))
        assertNull(truncationNotice(0, 0))
    }

    @Test fun csvComesFromTheTextRouteOnlyOnANewerComputer() {
        assertEquals(CsvSource.TEXT, csvSource(true))
        assertEquals(CsvSource.PHONE, csvSource(false))
        val (limited, more) = limitCsvRows((1..5001).joinToString("\n") { "行$it" })
        assertTrue(more)
        assertEquals(5000, limited.lines().size)
        val (all, none) = limitCsvRows("a,b\nc,d")
        assertFalse(none)
        assertEquals("a,b\nc,d", all)
    }

    @Test fun theLanguageUsesTheComputersWordOrTheEnding() {
        assertEquals("r", codeLanguage("r", "run.R"))
        assertEquals("powershell", codeLanguage("", "a.ps1"))
        assertEquals("latex", codeLanguage("", "a.tex"))
        assertEquals("dockerfile", codeLanguage("", "Dockerfile"))
        assertEquals("kotlin", codeLanguage("", "Main.kt"))
        assertEquals("plaintext", codeLanguage("", "a.unknown"))
        assertEquals("python", codeLanguage("python", "a.unknown"))
    }

    @Test fun archivesAndPlayersFollowTheirEndings() {
        assertTrue(zipFile("a.zip"));assertTrue(zipFile("A.ZIP"))
        assertFalse(zipFile("a.7z"));assertFalse(zipFile("a.rar"))
        assertEquals("audio", playable("a.mp3"));assertEquals("audio", playable("a.m4a"))
        assertEquals("video", playable("a.mp4"));assertEquals("video", playable("a.webm"))
        assertNull(playable("a.txt"))
    }

    @Test fun aZipListingIsCappedAndSaysSo() {
        val entries = JSONArray((1..2001).map { JSONObject().put("name", "f$it").put("size", it).put("dir", false) })
        val listing = JSONObject().put("entries", entries).put("total", 2001).put("truncated", true)
        val rows = zipEntries(listing)
        assertEquals(ZipEntryLimit, rows.size)
        assertEquals("f1", rows.first().string("name"))
        assertTrue(zipMore(listing, rows.size))
        val small = JSONObject().put("entries", JSONArray().put(JSONObject().put("name", "a").put("dir", false))).put("total", 1)
        assertFalse(zipMore(small, zipEntries(small).size))
    }

    @Test fun thePlayerGetsTheSameHeadersAsEveryRequest() = runTest {
        val source = FixtureApi().mediaSource("a".repeat(32), "chat", "file", "v1")
        assertEquals("2", source.headers["X-Teleply-Protocol"])
        assertTrue(source.headers["X-Teleply-Client"].orEmpty().startsWith("android/"))
        assertEquals("fixture=1", source.headers["Cookie"])
        assertTrue(source.url.contains("file=file"))
    }

    @Test fun aNewerComputersMarkdownPictureComesThroughTheResourceRoute() = runTest {
        val api = FixtureApi()
        val c = WorkspaceController(this, TestStore())
        c.bind(ChatKey("scope", "a".repeat(32), "file-preview", "codex"), api, false)
        val file = JSONObject().put("id", "fp-note").put("name", "说明文档.md").put("path", "D:\\fixture\\file-preview\\note.md").put("view", "markdown")
        assertNotNull(c.previewResource(file, "diagram.png"))
        assertEquals(1, api.world.resourceReads)
        // An older computer (no view) still looks in the conversation's file list, and the resource route is not asked.
        val old = JSONObject().put("id", "fixture-md").put("name", "说明.md").put("path", "D:\\fixture\\说明.md")
        assertNull(c.previewResource(old, "diagram.png"))
        assertEquals(1, api.world.resourceReads)
    }
}
