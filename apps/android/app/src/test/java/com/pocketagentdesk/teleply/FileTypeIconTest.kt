package com.pocketagentdesk.teleply

import org.junit.Assert.*
import org.junit.Test

/**
 * The file type marks of the 11-26 design §4.3: every row of the table, in letters that are the iPhone's too, and what
 * an unknown or missing extension gets.
 */
class FileTypeIconTest {
    private fun mark(name: String) = fileTypeMark(name)
    private fun assertMark(name: String, label: String, color: Long) {
        assertEquals("$name label", label, mark(name).label)
        assertEquals("$name colour", color, mark(name).color)
    }

    @Test fun everyRowOfTheTable() {
        assertMark("合同.pdf", "PDF", 0xFFE5483B)
        for (ext in listOf("doc", "docx", "docm", "dotx", "rtf", "odt", "pages")) assertMark("发布说明.$ext", "W", 0xFF2F6FDE)
        for (ext in listOf("xls", "xlsx", "xlsm", "xlsb", "ods", "numbers")) assertMark("预算.$ext", "X", 0xFF1E8E4F)
        for (ext in listOf("csv", "tsv")) assertMark("数据.$ext", "CSV", 0xFF2E9E6B)
        for (ext in listOf("ppt", "pptx", "pptm", "odp", "key")) assertMark("汇报.$ext", "P", 0xFFE46A2C)
        for (ext in listOf("zip", "rar", "7z", "tar", "gz", "tgz", "bz2", "xz")) assertMark("归档.$ext", "ZIP", 0xFFB7862C)
        for (ext in listOf("txt", "log")) assertMark("日志.$ext", "TXT", 0xFF7A8594)
        for (ext in listOf("md", "markdown")) assertMark("说明.$ext", "MD", 0xFF5F6B7A)
        for (ext in listOf("py", "r", "js", "ts", "tsx", "jsx", "kt", "kts", "swift", "java", "c", "h", "cpp", "hpp", "cs", "go", "rs", "rb", "php", "sh", "ps1", "bat", "sql", "json", "yaml", "yml", "toml", "xml", "html", "htm", "css", "ipynb")) {
            assertMark("源文件.$ext", "</>", 0xFF7A55D6)
        }
        for (ext in listOf("png", "jpg", "jpeg", "gif", "webp", "heic", "heif", "bmp", "tif", "tiff")) assertMark("截图.$ext", "IMG", 0xFF12A3A3)
        assertMark("标志.svg", "SVG", 0xFF0E8F8F)
        for (ext in listOf("mp3", "wav", "m4a", "aac", "flac", "ogg")) assertMark("提示音.$ext", "♪", 0xFFD24C8E)
        for (ext in listOf("mp4", "mov", "m4v", "avi", "mkv", "webm")) assertMark("短片.$ext", "▶", 0xFF5B5BD6)
        assertMark("安装包.apk", "APK", 0xFF3DA35D)
        for (ext in listOf("exe", "msi")) assertMark("安装包.$ext", "EXE", 0xFF4B5563)
    }

    @Test fun otherExtensionsAreTheirOwnCapitalsAtMostFour() {
        assertMark("备份.bak", "BAK", 0xFF8B95A1)
        assertMark("备份.xyzzy", "XYZZ", 0xFF8B95A1)
        assertMark("项目.长扩展名测试", "长扩展名", 0xFF8B95A1)
        // The extension is read in either case, and from after the last dot.
        assertMark("发布说明.DOCX", "W", 0xFF2F6FDE)
        assertMark("打包.tar.GZ", "ZIP", 0xFFB7862C)
        assertMark("名字.带点.pdf", "PDF", 0xFFE5483B)
    }

    @Test fun aNameWithoutAnExtensionHasNoWords() {
        assertEquals("", mark("没有扩展名").label)
        assertEquals("", mark("点.").label)
        assertEquals("", mark(".gitignore").label)
        assertEquals(0xFF8B95A1, mark("没有扩展名").color)
    }

    @Test fun theExtensionIsWhatFollowsTheLastDot() {
        assertEquals("gz", fileExtension("归档.tar.gz"))
        assertEquals("pdf", fileExtension("合同.PDF"))
        assertEquals("", fileExtension("没有扩展名"))
        assertEquals("", fileExtension("结尾点."))
        assertEquals("", fileExtension(".hidden"))
    }
}
