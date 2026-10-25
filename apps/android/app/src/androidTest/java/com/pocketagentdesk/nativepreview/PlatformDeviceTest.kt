package com.pocketagentdesk.nativepreview
import android.content.Intent
import androidx.core.content.FileProvider
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import org.junit.Test
import org.junit.Assert.*
import org.junit.runner.RunWith
import java.io.File
@RunWith(AndroidJUnit4::class)
class PlatformDeviceTest {
    private val context get()=ApplicationProvider.getApplicationContext<android.app.Application>()
    @Test fun fileProviderGrantsOnlySharedReadAccess() {
        val dir=File(context.cacheDir,"share/test").apply { mkdirs() };val file=File(dir,"test.txt").apply { writeText("fixture") }
        val intent=PlatformFiles.intent(context,file,false)
        assertEquals(Intent.ACTION_SEND,intent.action);assertEquals("text/plain",intent.type)
        assertTrue(intent.flags and Intent.FLAG_GRANT_READ_URI_PERMISSION!=0);assertEquals(0,intent.flags and Intent.FLAG_GRANT_WRITE_URI_PERMISSION)
        assertEquals("content",intent.clipData!!.getItemAt(0).uri.scheme)
        val private=File(context.filesDir,"private-test.txt").apply { writeText("not shared") }
        assertThrows(IllegalArgumentException::class.java) { FileProvider.getUriForFile(context,context.packageName+".files",private) }
        file.delete();private.delete();dir.delete()
    }
}
