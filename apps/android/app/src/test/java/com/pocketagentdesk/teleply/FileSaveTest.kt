package com.pocketagentdesk.teleply

import android.app.Application
import android.content.Context
import android.database.Cursor
import android.database.MatrixCursor
import android.os.ParcelFileDescriptor
import android.provider.DocumentsContract
import android.provider.DocumentsProvider
import androidx.test.core.app.ApplicationProvider
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.first
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import org.robolectric.shadows.ShadowContentResolver
import java.io.File

class SaveDocuments:DocumentsProvider() {
    lateinit var target:File
    override fun onCreate()=true
    override fun queryRoots(projection:Array<out String>?):Cursor=MatrixCursor(arrayOf("root_id"))
    override fun queryDocument(documentId:String,projection:Array<out String>?):Cursor=MatrixCursor(arrayOf("document_id"))
    override fun queryChildDocuments(parentDocumentId:String,projection:Array<out String>?,sortOrder:String?):Cursor=MatrixCursor(arrayOf("document_id"))
    override fun openDocument(documentId:String,mode:String,signal:android.os.CancellationSignal?):ParcelFileDescriptor=ParcelFileDescriptor.open(target,ParcelFileDescriptor.MODE_READ_WRITE or ParcelFileDescriptor.MODE_CREATE or ParcelFileDescriptor.MODE_TRUNCATE)
    override fun deleteDocument(documentId:String) { check(target.delete()) }
}
@RunWith(RobolectricTestRunner::class)
@Config(sdk=[35],application=Application::class)
class FileSaveTest {
    @Test fun savesExactBytesAndFailedDownloadRemovesPartialDocument()=runBlocking {
        val context=ApplicationProvider.getApplicationContext<Application>()
        val provider=SaveDocuments();val info=android.content.pm.ProviderInfo().apply { authority="save.test";exported=true;grantUriPermissions=true;readPermission="android.permission.MANAGE_DOCUMENTS";writePermission=readPermission }
        provider.attachInfo(context,info);ShadowContentResolver.registerProviderInternal("save.test",provider)
        val uri=DocumentsContract.buildDocumentUri("save.test","result")
        for(mode in listOf(0,1,2)) {
            val written=CompletableDeferred<Unit>()
            provider.target=File.createTempFile("result-",".xlsx",context.cacheDir)
            val bytes=byteArrayOf(80,75,0,1,2,3)
            val api=object:ReadApi by FixtureApi() {
                override suspend fun downloadTo(device:String,chat:String,file:String,output:java.io.OutputStream) { output.write(bytes);written.complete(Unit);if(mode==1) throw java.io.IOException("interrupted");if(mode==2) awaitCancellation() }
            }
            val scope=CoroutineScope(SupervisorJob()+Dispatchers.Unconfined)
            val c=WorkspaceController(scope,TestStore());c.bind(ChatKey("owner","a".repeat(32),"chat"),api,false)
            withTimeout(5000) { c.state.first { it.ready } }
            c.saveFile(context,uri,JSONObject().put("id","ticket").put("name","报告.xlsx").put("size",bytes.size))
            if(mode==2) { written.await();c.cancelSave() }
            withTimeout(5000) { c.state.first { !it.savingFile } }
            if(mode!=0) { assertFalse(provider.target.exists());assertNull(c.state.value.savedUri);assertTrue("mode=$mode transfer=${c.state.value.transfer}",c.state.value.transfer.contains(if(mode==2) "已取消" else "保存失败")) }
            else { assertArrayEquals(bytes,provider.target.readBytes());assertEquals(uri.toString(),c.state.value.savedUri);provider.target.delete() }
            scope.cancel()
        }
    }
}
