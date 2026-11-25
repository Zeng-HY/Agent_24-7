package com.pocketagentdesk.teleply

import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.drawable.AnimatedImageDrawable
import android.graphics.drawable.Drawable
import android.os.Build
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.gestures.awaitEachGesture
import androidx.compose.foundation.gestures.awaitFirstDown
import androidx.compose.foundation.gestures.calculatePan
import androidx.compose.foundation.gestures.calculateZoom
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.pager.HorizontalPager
import androidx.compose.foundation.pager.rememberPagerState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.input.pointer.PointerInputScope
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.input.pointer.positionChange
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import java.io.File
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONObject

/**
 * 看图页 (§6.2): fills the screen, one picture per page of [HorizontalPager], 2/5 at the top. A pinch zooms to 8×, a
 * double tap goes between 1× and 2.5×, and while enlarged a drag moves the picture instead of turning the page. The
 * 1280 thumb (or 2048 for an SVG) shows first; a picture of at most 30 MB then swaps in its original from the phone's
 * file cache, while a larger one stays on the 2048 thumb. GIFs play from Android 9 on. ⋯ saves, shares, opens with
 * another app, or opens the file's page.
 */
@Composable
fun PictureViewerPage(vm: ReaderViewModel, data: JSONObject) {
    val c = vm.workspace
    val context = LocalContext.current
    val items = remember(data) { data.rows("items") { parseFileRef(it) } }
    if (items.isEmpty()) {
        LaunchedEffect(Unit) { c.close() }
        return
    }
    val start = remember(data) { data.optInt("index").coerceIn(0, items.lastIndex) }
    val pager = rememberPagerState(initialPage = start, pageCount = { items.size })
    var zoom by remember { mutableFloatStateOf(1f) }
    var pan by remember { mutableStateOf(Offset.Zero) }
    LaunchedEffect(pager.currentPage) { zoom = 1f; pan = Offset.Zero }
    val current = items.getOrNull(pager.currentPage) ?: items.first()
    val busy by c.state.collectAsStateWithLifecycle()

    var menu by remember { mutableStateOf(false) }
    var saving by remember { mutableStateOf<FileRef?>(null) }
    val save = rememberLauncherForActivityResult(ActivityResultContracts.CreateDocument("application/octet-stream")) { uri ->
        if (uri != null) saving?.let { c.saveFile(context, uri, it.toJson()) }
        saving = null
    }

    Box(Modifier.fillMaxSize().background(Color.Black)) {
        HorizontalPager(
            state = pager,
            modifier = Modifier.fillMaxSize(),
            userScrollEnabled = pagerTurnsAt(zoom),
            key = { items[it].id },
        ) { page ->
            val file = items[page]
            val active = page == pager.currentPage
            ViewerPicture(vm, file, if (active) zoom else 1f, if (active) pan else Offset.Zero, active) { next, at -> zoom = next; pan = at }
        }
        // The top bar: back, 2/5, and ⋯ (the page below stays edge to edge).
        Row(
            Modifier.align(Alignment.TopCenter).fillMaxWidth()
                .windowInsetsPadding(WindowInsets.safeDrawing.only(WindowInsetsSides.Top + WindowInsetsSides.Horizontal))
                .background(Color.Black.copy(alpha = 0.28f))
                .padding(horizontal = 8.dp, vertical = 6.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            TeleplyIconButton(TeleplyIcons.Back, "返回", c::close, tint = Color.White)
            Text(
                "${pager.currentPage + 1}/${items.size}",
                style = MaterialTheme.typography.bodyMedium,
                color = Color.White,
                modifier = Modifier.weight(1f).semantics { contentDescription = "第 ${pager.currentPage + 1} 张，共 ${items.size} 张" },
            )
            Box {
                TeleplyIconButton(TeleplyIcons.More, "图片菜单", { menu = true }, tint = Color.White)
                DropdownMenu(expanded = menu, onDismissRequest = { menu = false }) {
                    DropdownMenuItem(text = { Text("保存到手机") }, onClick = { menu = false; saving = current; save.launch(current.name.ifBlank { "图片" }) })
                    DropdownMenuItem(text = { Text("系统分享") }, onClick = { menu = false; c.shareFile(context, current.toJson(), false) })
                    DropdownMenuItem(text = { Text("用其他应用打开") }, onClick = { menu = false; c.shareFile(context, current.toJson(), true) })
                    DropdownMenuItem(text = { Text("在文件页打开") }, onClick = { menu = false; c.openAnswerFile(current) })
                }
            }
        }
        val note = busy.transfer.ifBlank { busy.error.orEmpty() }
        if (note.isNotBlank()) {
            Text(
                note, style = MaterialTheme.typography.bodySmall, color = Color.White,
                modifier = Modifier.align(Alignment.BottomCenter).fillMaxWidth().background(Color.Black.copy(alpha = 0.45f))
                    .windowInsetsPadding(WindowInsets.safeDrawing.only(WindowInsetsSides.Bottom)).padding(horizontal = 16.dp, vertical = 10.dp),
            )
        }
    }
}

/** One picture of the viewer, with its zoom and drag; the original replaces the thumb when it is small enough (§6.2). */
@Composable
private fun ViewerPicture(vm: ReaderViewModel, file: FileRef, zoom: Float, pan: Offset, active: Boolean, onTransform: (Float, Offset) -> Unit) {
    val loader = LocalAnswerThumb.current
    var highSvg by remember(file.id) { mutableStateOf(false) }
    var original by remember(file.id, file.version) { mutableStateOf<Bitmap?>(null) }
    var gifPath by remember(file.id, file.version) { mutableStateOf<String?>(null) }
    var failed by remember(file.id) { mutableStateOf(false) }
    val gif = file.name.endsWith(".gif", true)
    // The original only when it is at most 30 MB; a larger picture stays on the 2048 thumb (§5.8).
    val originalWidth = when {
        file.view == "svg" -> if (zoom > 2f || highSvg) 4096 else svgThumbWidth(zoom)
        !opensOriginal(file.size) || gif -> 2048
        else -> 1280
    }
    val thumb by produceState<Bitmap?>(null, file.id, file.version, originalWidth) {
        value = loader?.invoke(file, originalWidth)
        failed = value == null
    }
    LaunchedEffect(file.id, file.version, zoom > 2f) {
        // An SVG's original is kept for saving and sharing even though the viewer shows the computer's PNG (§6.2).
        if (file.view == "svg") { vm.workspace.cachedAnswerFile(file); return@LaunchedEffect }
        if ((gif || opensOriginal(file.size)) && original == null && gifPath == null) {
            val kept = vm.workspace.cachedAnswerFile(file) ?: return@LaunchedEffect
            withContext(Dispatchers.IO) {
                if (gif) gifPath = kept.path else original = decodePictureFile(kept)
            }
        }
    }
    // An SVG enlarged past 2× asks for the 4096 copy once (§6.2); smaller, the 2048 one.
    LaunchedEffect(active, zoom) {
        if (active && file.view == "svg" && needsSvgHighRes(zoom, highSvg)) highSvg = true
    }
    val shown = original ?: thumb
    val p = LocalTeleply.current
    val zoomNow by rememberUpdatedState(zoom)
    val panNow by rememberUpdatedState(pan)
    BoxWithConstraints(Modifier.fillMaxSize()) {
        val density = androidx.compose.ui.platform.LocalDensity.current
        val maxX = with(density) { (maxWidth.toPx() * (zoom - 1f)) / 2f }
        val maxY = with(density) { (maxHeight.toPx() * (zoom - 1f)) / 2f }
        val gestures = Modifier
            .pointerInput(active) { if (active) viewerGestures({ zoomNow }, { panNow }, onTransform) }
            .pointerInput(active) { if (active) detectTapGestures(onDoubleTap = { onTransform(doubleTapTarget(zoom), Offset.Zero) }) }
        Box(
            gestures.fillMaxSize()
                .graphicsLayer {
                    scaleX = zoom; scaleY = zoom
                    translationX = pan.x.coerceIn(-maxX, maxX)
                    translationY = pan.y.coerceIn(-maxY, maxY)
                },
            contentAlignment = Alignment.Center,
        ) {
            when {
                gif && gifPath != null -> gifPath?.let { GifPicture(File(it), Modifier.fillMaxSize()) }
                shown != null -> Image(shown.asImageBitmap(), contentDescription = "查看 ${file.name}", contentScale = ContentScale.Fit, modifier = Modifier.fillMaxSize())
                failed -> Text("没能打开这张图", color = Color.White, style = MaterialTheme.typography.bodyMedium)
                else -> Text(file.name.ifBlank { "图片" }, color = p.muted, style = MaterialTheme.typography.bodyMedium)
            }
        }
    }
}

/**
 * The viewer's own gestures: two fingers pinch and pan; one finger pans only while enlarged, so that at 1× the pager
 * still turns pages (§6.2).
 */
private suspend fun PointerInputScope.viewerGestures(zoom: () -> Float, pan: () -> Offset, onTransform: (Float, Offset) -> Unit) {
    awaitEachGesture {
        var scale = zoom()
        var at = pan()
        awaitFirstDown(requireUnconsumed = false)
        while (true) {
            val event = awaitPointerEvent()
            if (event.changes.size >= 2) {
                val factor = event.calculateZoom()
                val moved = event.calculatePan()
                if (factor != 1f || moved != Offset.Zero) {
                    scale = zoomBy(scale, factor)
                    at += moved
                    onTransform(scale, at)
                    event.changes.forEach { it.consume() }
                }
            } else if (scale > 1.01f) {
                val change = event.changes.firstOrNull()
                if (change != null) {
                    val moved = change.positionChange()
                    if (moved != Offset.Zero) {
                        at += moved
                        onTransform(scale, at)
                        change.consume()
                    }
                }
            }
            if (event.changes.none { it.pressed }) break
        }
    }
}

/** A GIF that plays (Android 9 and up), or its first frame on older phones (§6.2). */
@Composable
private fun GifPicture(file: File, modifier: Modifier) {
    if (Build.VERSION.SDK_INT < 28) {
        val first by produceState<Bitmap?>(null, file.path) { value = withContext(Dispatchers.IO) { decodePictureFile(file, 2048) } }
        first?.let { Image(it.asImageBitmap(), contentDescription = null, contentScale = ContentScale.Fit, modifier = modifier) }
        return
    }
    val drawable by produceState<Drawable?>(null, file.path) {
        value = withContext(Dispatchers.IO) {
            runCatching {
                android.graphics.ImageDecoder.decodeDrawable(android.graphics.ImageDecoder.createSource(file)) { decoder, info, _ ->
                    val sample = pictureSampleSize(info.size.width, info.size.height)
                    if (sample > 1) decoder.setTargetSize((info.size.width / sample).coerceAtLeast(1), (info.size.height / sample).coerceAtLeast(1))
                }
            }.getOrNull()
        }
    }
    AndroidView(
        factory = { context -> android.widget.ImageView(context).apply { scaleType = android.widget.ImageView.ScaleType.FIT_CENTER } },
        modifier = modifier,
        update = { view ->
            view.setImageDrawable(drawable)
            (drawable as? AnimatedImageDrawable)?.apply { repeatCount = AnimatedImageDrawable.REPEAT_INFINITE; start() }
        },
    )
}
