package com.pocketagentdesk.teleply

import java.io.File
import java.nio.file.Files
import org.junit.Assert.*
import org.junit.Test

/**
 * Stage B's numbers (file-preview design §6.2, §5.8) and the file cache (§7): how far a picture or a PDF zooms, when
 * the pager turns, which source a picture opens, when an SVG asks for 4096, and how kept originals are named and
 * dropped. All data made up; no computer is read.
 */
class ViewerRulesTest {
    @Test fun aPictureZoomsBetweenOneAndEight() {
        assertEquals(1f, zoomBy(1f, 0.4f), 0.001f)
        assertEquals(4f, zoomBy(2f, 2f), 0.001f)
        assertEquals(8f, zoomBy(4f, 4f), 0.001f)
        assertEquals(8f, zoomBy(8f, 3f), 0.001f)
    }

    @Test fun aDoubleTapGoesInToTwoAndAHalfAndBack() {
        assertEquals(2.5f, doubleTapTarget(1f), 0.001f)
        assertEquals(2.5f, doubleTapTarget(1.01f), 0.001f)
        assertEquals(1f, doubleTapTarget(1.02f), 0.001f)
        assertEquals(1f, doubleTapTarget(2.5f), 0.001f)
    }

    @Test fun thePagerTurnsOnlyAtOneTimes() {
        assertTrue(pagerTurnsAt(1f))
        assertTrue(pagerTurnsAt(1.01f))
        assertFalse(pagerTurnsAt(1.02f))
        assertFalse(pagerTurnsAt(4f))
    }

    @Test fun aPdfZoomsBetweenOneAndThree() {
        assertEquals(1f, pdfZoomBy(1f, 0.5f), 0.001f)
        assertEquals(2f, pdfZoomBy(1f, 2f), 0.001f)
        assertEquals(3f, pdfZoomBy(2f, 2f), 0.001f)
        assertEquals(3f, pdfZoomBy(3f, 2f), 0.001f)
    }

    @Test fun aPictureAtMostThirtyMegabytesOpensItsOriginal() {
        assertTrue(opensOriginal(0))
        assertTrue(opensOriginal(1))
        assertTrue(opensOriginal(30L * 1024 * 1024))
        assertFalse(opensOriginal(30L * 1024 * 1024 + 1))
        assertFalse(opensOriginal(80L * 1024 * 1024))
    }

    @Test fun anSvgIsTwoThousandAndFortyEightUntilPastTwoTimes() {
        assertEquals(2048, svgThumbWidth(1f))
        assertEquals(2048, svgThumbWidth(2f))
        assertEquals(4096, svgThumbWidth(2.01f))
        assertEquals(4096, svgThumbWidth(6f))
        assertTrue(needsSvgHighRes(2.5f, false))
        assertFalse(needsSvgHighRes(2.5f, true))
        assertFalse(needsSvgHighRes(1.5f, false))
    }

    @Test fun aDecodedPictureStaysUnderFourThousandAndNinetySix() {
        assertEquals(1, pictureSampleSize(4096, 3000))
        assertEquals(4, pictureSampleSize(12000, 9000))
        assertEquals(16, pictureSampleSize(40000, 30000))
        assertEquals(1, pictureSampleSize(800, 600))
    }

    @Test fun keptOriginalsAreNamedByFileAndVersionAndDroppedLeastRecentlyUsed() {
        val dir = Files.createTempDirectory("teleply-files").toFile()
        try {
            val cache = FileCache(dir, maxBytes = 100)
            val first = cache.write("pc-a", "file-1", "v1", "png") { it.write(ByteArray(60)) }
            assertNotNull(first)
            assertTrue(first!!.isFile)
            assertEquals(60, cache.totalBytes())
            assertTrue(dir.walkTopDown().none { it.name.endsWith(".part") })
            assertTrue(FileCache.name("file-1", "v1", "png").endsWith(".png"))
            assertNotEquals(FileCache.name("file-1", "v1", "png"), FileCache.name("file-1", "v2", "png"))
            assertFalse(FileCache.name("file-1", "v1", "png").contains("file-1"))
            assertEquals("png", FileCache.safeExt("图表.PNG"))
            assertEquals("bin", FileCache.safeExt("没有后缀"))
            first.setLastModified(1_000)
            cache.write("pc-b", "file-2", "v1", "pdf") { it.write(ByteArray(60)) }
            assertTrue(cache.totalBytes() <= 100)
            assertFalse(first.exists())
            // Clearing one computer leaves another's files.
            val other = cache.write("pc-c", "file-3", "v1", "txt") { it.write(ByteArray(10)) }
            assertNotNull(other)
            cache.clear("pc-c")
            assertFalse(other!!.exists())
            assertTrue(File(dir, "pc-b").isDirectory)
        } finally {
            dir.deleteRecursively()
        }
    }

    /** 退出登录 clears everything; 移除一台电脑 clears only that computer's thumbs and files (§7). */
    @Test fun clearingOneComputerLeavesTheOthers() {
        val cacheRoot = Files.createTempDirectory("teleply-caches").toFile()
        try {
            File(cacheRoot, "$ThumbCacheFolder/pc-a").mkdirs()
            File(cacheRoot, "$ThumbCacheFolder/pc-b").mkdirs()
            File(cacheRoot, "$FileCacheFolder/pc-a").mkdirs()
            File(cacheRoot, "$FileCacheFolder/pc-b").mkdirs()
            AnswerCaches.clearComputer(cacheRoot, "pc-a")
            assertFalse(File(cacheRoot, "$ThumbCacheFolder/pc-a").exists())
            assertFalse(File(cacheRoot, "$FileCacheFolder/pc-a").exists())
            assertTrue(File(cacheRoot, "$ThumbCacheFolder/pc-b").exists())
            AnswerCaches.clearAll(cacheRoot)
            assertFalse(File(cacheRoot, ThumbCacheFolder).exists())
            assertFalse(File(cacheRoot, FileCacheFolder).exists())
        } finally {
            cacheRoot.deleteRecursively()
        }
    }
}
