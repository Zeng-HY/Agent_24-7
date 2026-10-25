package com.pocketagentdesk.nativepreview

import android.content.ClipData
import android.content.Context
import android.content.Intent
import androidx.core.content.FileProvider
import java.io.File
import java.util.UUID
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

class ShareFileProvider:FileProvider()

fun safeShareName(name:String):String {
    val base=name.substringAfterLast('/').substringAfterLast('\\').filter { !it.isISOControl() }.take(180).ifBlank { "file" }
    val safe=if(base in listOf(".","..")) "file" else base
    return safe
}
fun shareMime(name:String):String=when(name.substringAfterLast('.',"").lowercase()) {
    "pdf" -> "application/pdf";"png" -> "image/png";"jpg","jpeg" -> "image/jpeg";"webp" -> "image/webp"
    // HTML goes as a web page, so a browser opens it as one (user's choice, 2026-10-24).
    "html","htm" -> "text/html"
    "txt","md","csv","json","py","kt","js","ts","yaml","yml","xml" -> "text/plain"
    else -> "application/octet-stream"
}
object PlatformFiles {
    fun cleanExpired(context:Context,now:Long=System.currentTimeMillis()) {
        val root=File(context.cacheDir,"share").canonicalFile
        root.listFiles()?.filter { it.isDirectory && runCatching { UUID.fromString(it.name) }.isSuccess && it.canonicalFile.parentFile==root && now-it.lastModified()>24*60*60*1000L }?.forEach { it.deleteRecursively() }
    }
    suspend fun prepare(context:Context,api:ReadApi,key:ChatKey,id:String,name:String,valid:()->Boolean):File=withContext(Dispatchers.IO) {
        cleanExpired(context)
        val root=File(context.cacheDir,"share").apply { mkdirs() }.canonicalFile
        val folder=File(root,UUID.randomUUID().toString()).apply { check(mkdir()) }
        val file=File(folder,safeShareName(name))
        try {
            file.outputStream().use { output ->
                val guarded=object:java.io.FilterOutputStream(output) {
                    override fun write(buffer:ByteArray,offset:Int,length:Int) { check(valid()) { "会话已切换，分享已取消" };out.write(buffer,offset,length) }
                }
                api.downloadTo(key.device,key.chat,id,guarded)
            }
            check(valid()) { "会话已切换，分享已取消" }
            file
        } catch(e:Exception) { file.delete();folder.delete();throw e }
    }
    fun intent(context:Context,file:File,open:Boolean):Intent {
        val uri=FileProvider.getUriForFile(context,context.packageName+".files",file)
        val mime=shareMime(file.name)
        return Intent(if(open) Intent.ACTION_VIEW else Intent.ACTION_SEND).apply {
            if(open) setDataAndType(uri,mime) else { type=mime;putExtra(Intent.EXTRA_STREAM,uri) }
            clipData=ClipData.newUri(context.contentResolver,file.name,uri)
            addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
        }
    }
    /** An empty file the camera app writes the photo into (拍照); cleaned after a day like shared copies. */
    fun captureUri(context:Context):android.net.Uri {
        val root=File(context.cacheDir,"share").apply { mkdirs() }.canonicalFile
        val folder=File(root,UUID.randomUUID().toString()).apply { check(mkdir()) }
        return FileProvider.getUriForFile(context,context.packageName+".files",File(folder,"photo-${System.currentTimeMillis()}.jpg"))
    }
    fun launch(context:Context,file:File,open:Boolean) {
        context.startActivity(Intent.createChooser(intent(context,file,open),if(open) "选择打开方式" else "分享文件").addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
    }
}
