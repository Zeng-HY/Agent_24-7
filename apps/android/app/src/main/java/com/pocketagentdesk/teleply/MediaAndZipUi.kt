package com.pocketagentdesk.teleply

import android.media.MediaPlayer
import android.net.Uri
import android.widget.MediaController
import android.widget.VideoView
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Slider
import androidx.compose.material3.Text
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONObject

/**
 * Audio and video (§6.2): the system player streams the file route itself, with the same Cookie and protocol headers as
 * every request; nothing is downloaded whole first. A file the player turns down is offered to another app instead.
 */
@Composable
fun MediaPage(vm: ReaderViewModel, data: JSONObject) {
    val p = LocalTeleply.current
    val c = vm.workspace
    val context = LocalContext.current
    val file = remember(data) { parseFileRef(data) }
    val video = data.string("view") == "video"
    var source by remember(data) { mutableStateOf<MediaSource?>(null) }
    var failed by remember(data) { mutableStateOf(false) }
    LaunchedEffect(data) {
        source = c.mediaSource(file)
        failed = source == null
    }
    if (failed || source == null) {
        Column(Modifier.fillMaxSize().padding(24.dp), horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(12.dp)) {
            Text("这个${if (video) "视频" else "音频"}放不了。", style = MaterialTheme.typography.bodyLarge, color = p.text)
            PillButton("用其他应用打开", { c.shareFile(context, JSONObject(data.toString()), true) }, style = PillStyle.Primary, leading = TeleplyIcons.Open)
        }
        return
    }
    val src = source!!
    if (video) {
        var videoFailed by remember(data) { mutableStateOf(false) }
        if (videoFailed) {
            Text("这个视频放不了，可以保存后用其他应用打开。", style = MaterialTheme.typography.note, color = p.muted, modifier = Modifier.padding(24.dp))
            return
        }
        AndroidView(
            factory = { ctx ->
                VideoView(ctx).apply {
                    setOnErrorListener { _, _, _ -> videoFailed = true; true }
                    setVideoURI(Uri.parse(src.url), src.headers)
                    setMediaController(MediaController(ctx).also { it.setAnchorView(this) })
                    setOnPreparedListener { it.start() }
                }
            },
            modifier = Modifier.fillMaxSize().background(Color.Black),
        )
        return
    }
    // Audio: the system player with play/pause and a seek bar.
    var player by remember(data) { mutableStateOf<MediaPlayer?>(null) }
    var playing by remember(data) { mutableStateOf(false) }
    var duration by remember(data) { mutableIntStateOf(0) }
    var position by remember(data) { mutableIntStateOf(0) }
    var audioFailed by remember(data) { mutableStateOf(false) }
    DisposableEffect(data) {
        val mp = MediaPlayer()
        player = mp
        mp.setOnPreparedListener { duration = it.duration; it.start(); playing = true }
        mp.setOnCompletionListener { playing = false; position = 0 }
        mp.setOnErrorListener { _, _, _ -> audioFailed = true; true }
        runCatching {
            mp.setDataSource(context, Uri.parse(src.url), src.headers)
            mp.prepareAsync()
        }.onFailure { audioFailed = true }
        onDispose { runCatching { mp.release() }; player = null }
    }
    LaunchedEffect(player) {
        while (player != null) {
            val mp = player
            if (mp != null && playing && runCatching { mp.isPlaying }.getOrDefault(false)) position = runCatching { mp.currentPosition }.getOrDefault(position)
            kotlinx.coroutines.delay(500)
        }
    }
    if (audioFailed) {
        Column(Modifier.fillMaxSize().padding(24.dp), horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(12.dp)) {
            Text("这个音频放不了，可以保存后用其他应用打开。", style = MaterialTheme.typography.note, color = p.muted)
            PillButton("用其他应用打开", { c.shareFile(context, JSONObject(data.toString()), true) }, style = PillStyle.Primary)
        }
        return
    }
    Column(Modifier.fillMaxSize().padding(24.dp), horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.Center) {
        Text(file.name.ifBlank { "音频" }, style = MaterialTheme.typography.bodyLarge, color = p.text)
        Spacer(Modifier.height(20.dp))
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            PillButton(if (playing) "暂停" else "播放", {
                val mp = player ?: return@PillButton
                if (playing) { runCatching { mp.pause() }; playing = false }
                else { runCatching { mp.start() }; playing = true }
            }, style = PillStyle.Primary)
        }
        if (duration > 0) {
            Slider(value = position.toFloat().coerceIn(0f, duration.toFloat()), onValueChange = { next ->
                position = next.toInt();runCatching { player?.seekTo(position) }
            }, valueRange = 0f..duration.toFloat(), modifier = Modifier.fillMaxWidth().semantics { contentDescription = "播放进度" })
        }
    }
}

/**
 * A zip's listing (§5.7): names, sizes and folders, at most 2000; nothing is unpacked. 7z and rar never come here.
 */
@Composable
fun ZipPage(data: JSONObject) {
    val p = LocalTeleply.current
    val listing = remember(data) { runCatching { JSONObject(data.optString("zip")) }.getOrDefault(JSONObject()) }
    val rows = remember(data) { zipEntries(listing) }
    if (rows.isEmpty()) {
        Text(data.string("previewNote").ifBlank { "这个压缩包读不了，可以保存后用其他应用打开。" }, style = MaterialTheme.typography.note, color = p.muted, modifier = Modifier.padding(24.dp))
        return
    }
    Column(Modifier.fillMaxSize()) {
        val total = listing.optInt("total", rows.size)
        if (zipMore(listing, rows.size)) Text("只列了前 ${rows.size} 项，共 $total 项", style = MaterialTheme.typography.note, color = p.muted, modifier = Modifier.padding(horizontal = 16.dp, vertical = 8.dp))
        LazyColumn(Modifier.fillMaxSize()) {
            items(rows) { entry ->
                Row(Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 10.dp), verticalAlignment = Alignment.CenterVertically) {
                    Text(entry.string("name"), style = MaterialTheme.typography.bodyMedium, color = p.text, modifier = Modifier.weight(1f), maxLines = 2)
                    if (!entry.optBoolean("dir")) Text(fileSize(entry.optLong("size")), style = MaterialTheme.typography.note, color = p.muted)
                }
            }
        }
    }
}
