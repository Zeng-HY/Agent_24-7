package com.pocketagentdesk.teleply

import android.content.ClipData
import android.content.Context
import android.content.Intent
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Canvas
import android.graphics.Matrix
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
    "xlsx" -> "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    "pptx" -> "application/vnd.openxmlformats-officedocument.presentationml.presentation"
    "docx" -> "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    "pdf" -> "application/pdf";"png" -> "image/png";"jpg","jpeg" -> "image/jpeg";"webp" -> "image/webp"
    // HTML goes as a web page, so a browser opens it as one (user's choice, 2026-10-24).
    "html","htm" -> "text/html"
    "txt","md","csv","json","py","kt","js","ts","yaml","yml","xml" -> "text/plain"
    else -> "application/octet-stream"
}
/** The folder of picked pictures' previews (their tiles, and tapped, the large view): in the app's caches. */
const val PhotoFolder="teleply-photos"

/**
 * A picked picture's preview (user 10-27, as on the iPhone): at most 1600 px on its longer side, turned as the camera
 * held it, as a JPEG in the caches' [PhotoFolder]. Its path, or null when the picture cannot be read: its tile then
 * shows the icon and name. The system's ExifInterface is sound from Android 8, the app's minimum (lint asks for androidx's).
 */
@android.annotation.SuppressLint("ExifInterface")
fun photoPreview(context:Context,source:File):String? = runCatching {
    val bounds=BitmapFactory.Options().apply { inJustDecodeBounds=true }
    BitmapFactory.decodeFile(source.path,bounds)
    val longest=maxOf(bounds.outWidth,bounds.outHeight)
    if(longest<=0) return null
    var sample=1
    while(longest/(sample*2)>=1600) sample*=2
    val decoded=BitmapFactory.decodeFile(source.path,BitmapFactory.Options().apply { inSampleSize=sample }) ?: return null
    val scale=minOf(1f,1600f/maxOf(decoded.width,decoded.height))
    val turn=when(android.media.ExifInterface(source.path).getAttributeInt(android.media.ExifInterface.TAG_ORIENTATION,android.media.ExifInterface.ORIENTATION_NORMAL)) {
        android.media.ExifInterface.ORIENTATION_ROTATE_90 -> 90f;android.media.ExifInterface.ORIENTATION_ROTATE_180 -> 180f;android.media.ExifInterface.ORIENTATION_ROTATE_270 -> 270f;else -> 0f
    }
    val sized=Bitmap.createBitmap(decoded,0,0,decoded.width,decoded.height,Matrix().apply { postScale(scale,scale);postRotate(turn) },true)
    // JPEG keeps no transparency: a see-through picture is laid on white, not black.
    val flat=if(!sized.hasAlpha()) sized else androidx.core.graphics.createBitmap(sized.width,sized.height).also { Canvas(it).apply { drawColor(android.graphics.Color.WHITE);drawBitmap(sized,0f,0f,null) } }
    val file=File(File(context.cacheDir,PhotoFolder).apply { mkdirs() },UUID.randomUUID().toString()+".jpg")
    file.outputStream().use { check(flat.compress(Bitmap.CompressFormat.JPEG,80,it)) }
    file.path
}.getOrNull()

/** A preview drawn small for its tile, about [px] on its shorter side; null once it is gone (the system may clear caches). */
fun photoThumbnail(path:String,px:Int):Bitmap? = runCatching {
    val bounds=BitmapFactory.Options().apply { inJustDecodeBounds=true }
    BitmapFactory.decodeFile(path,bounds)
    var sample=1
    while(minOf(bounds.outWidth,bounds.outHeight)/(sample*2)>=px) sample*=2
    BitmapFactory.decodeFile(path,BitmapFactory.Options().apply { inSampleSize=sample })
}.getOrNull()

/** A picture's preview goes with its row, removed or sent: only a file of ours, in the previews' folder. */
fun dropPhotoPreview(path:String) {
    if(path.isBlank()) return
    val file=File(path)
    if(file.parentFile?.name==PhotoFolder && file.name.endsWith(".jpg")) file.delete()
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
