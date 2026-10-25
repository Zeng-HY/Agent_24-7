package com.pocketagentdesk.teleply

import androidx.activity.compose.BackHandler
import androidx.compose.animation.core.Animatable
import androidx.compose.animation.core.MutableTransitionState
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.rememberTransition
import androidx.compose.animation.core.snap
import androidx.compose.animation.core.tween
import androidx.compose.foundation.background
import androidx.compose.foundation.gestures.Orientation
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.gestures.draggable
import androidx.compose.foundation.gestures.rememberDraggableState
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.WindowInsetsSides
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.navigationBars
import androidx.compose.foundation.layout.only
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawing
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.layout.windowInsetsPadding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.SideEffect
import androidx.compose.runtime.Stable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.key
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.runtime.withFrameNanos
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.semantics.clearAndSetSemantics
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.paneTitle
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.dp
import com.pocketagentdesk.teleply.glass.layerBackdrop
import com.pocketagentdesk.teleply.glass.rememberLayerBackdrop
import kotlinx.coroutines.launch

/**
 * Bottom sheets and detail pages drawn in the app window (spec 2.5, 4.7). Material's ModalBottomSheet opens its own
 * window, and glass in another window cannot sample the page. Each sheet registers with the [SheetHost] while it is
 * composed and animates out after it leaves; Back and a tap on the dimmed page close the top one.
 */
enum class SheetStyle {
    /** Reading and form panels: opaque card colour, 24dp top corners, attached to the bottom. */
    Opaque,

    /** Short choices (model, mode, permission): large-tier glass floating 8dp in, 28dp corners, like iOS 26. */
    Glass,

    /** A full-screen detail page (file preview, diff); it brings its own title bar. */
    Page,
}

@Stable
internal class SheetEntry(val id: Long) {
    var title by mutableStateOf("")
    var trailing by mutableStateOf<String?>(null)
    var style by mutableStateOf(SheetStyle.Opaque)
    var onDismiss by mutableStateOf<() -> Unit>({})
    var content by mutableStateOf<@Composable ColumnScope.() -> Unit>({})
    /** Its caller still shows it. The motion follows a frame later (see [SheetLayer]); closing starts at once. */
    var wanted by mutableStateOf(false)
    val visible = MutableTransitionState(false)
}

@Stable
class SheetHostState {
    internal val entries = mutableStateListOf<SheetEntry>()
    private var next = 0L
    internal fun create() = SheetEntry(next++)
    val isOpen: Boolean get() = entries.any { it.wanted }
}

val LocalSheetHost = staticCompositionLocalOf<SheetHostState?> { null }

@Composable
fun SheetHost(content: @Composable () -> Unit) {
    val state = remember { SheetHostState() }
    val glass = LocalGlassMode.current != GlassMode.Solid
    val record = rememberLayerBackdrop()
    val glassOpen = state.entries.any { it.style == SheetStyle.Glass }
    val open = state.entries.any { it.wanted }
    CompositionLocalProvider(LocalSheetHost provides state) {
        Box(Modifier.fillMaxSize()) {
            Box(
                Modifier.fillMaxSize()
                    .then(if (glass && glassOpen) Modifier.layerBackdrop(record) else Modifier)
                    .graphicsLayer()
                    .then(if (open) Modifier.clearAndSetSemantics { } else Modifier),
            ) { content() }
            val top = state.entries.lastOrNull { it.wanted }
            CompositionLocalProvider(LocalGlassBackdrop provides if (glass) record else null) {
                state.entries.toList().forEach { entry -> key(entry.id) { SheetLayer(state, entry, entry === top) } }
            }
        }
    }
}

/**
 * A bottom sheet (web .sheet): 17sp/600 title, round close button top right, the web's dimmed page behind.
 * Typing into it is a draft; closing it does not discard what the caller keeps (spec 7).
 */
@Composable
fun TeleplySheet(
    title: String,
    onDismiss: () -> Unit,
    trailing: String? = null,
    style: SheetStyle = SheetStyle.Opaque,
    content: @Composable ColumnScope.() -> Unit,
) {
    val host = LocalSheetHost.current ?: return
    val entry = remember(host) { host.create() }
    SideEffect {
        entry.title = title
        entry.trailing = trailing
        entry.style = style
        entry.onDismiss = onDismiss
        entry.content = content
    }
    DisposableEffect(entry) {
        entry.title = title
        entry.trailing = trailing
        entry.style = style
        entry.onDismiss = onDismiss
        entry.content = content
        host.entries.add(entry)
        entry.wanted = true
        onDispose {
            entry.wanted = false
            entry.visible.targetState = false
        }
    }
}

/** Full-screen detail page in the same window; [content] draws its own title bar ([DetailTopBar]). */
@Composable
fun DetailPage(label: String, onDismiss: () -> Unit, content: @Composable ColumnScope.() -> Unit) =
    TeleplySheet(label, onDismiss, style = SheetStyle.Page, content = content)

@Composable
private fun SheetLayer(state: SheetHostState, entry: SheetEntry, top: Boolean) {
    val p = LocalTeleply.current
    // 0.9.1: the sheet is composed, measured and drawn in its first frame while still invisible, and the motion starts
    // with the next one. That first frame is the heaviest (it lays the whole sheet out); inside the motion it made the
    // opening jump ahead.
    LaunchedEffect(entry) {
        withFrameNanos { }
        if (entry.wanted) entry.visible.targetState = true
    }
    val transition = rememberTransition(entry.visible, label = "sheet")
    val animate = remember { TeleplyMotion.enabled() }
    // Web values (spec 5): 200 ms from 12dp below and 0.98; the dimmed page fades in 160 ms; closing 120 ms.
    val progress by transition.animateFloat(
        transitionSpec = { if (!animate) tween(80) else if (targetState) tween(200, easing = TeleplyMotion.StandardDecelerate) else tween(120) },
        label = "sheet-progress",
    ) { if (it) 1f else 0f }
    val scrim by transition.animateFloat(transitionSpec = { if (targetState) tween(160) else tween(120) }, label = "sheet-scrim") { if (it) 1f else 0f }
    LaunchedEffect(entry.wanted, entry.visible.currentState, entry.visible.isIdle) {
        if (!entry.wanted && entry.visible.isIdle && !entry.visible.currentState) state.entries.remove(entry)
    }
    val closing = !entry.wanted
    if (top && !closing) BackHandler { entry.onDismiss() }
    val page = entry.style == SheetStyle.Page
    Box(
        Modifier.fillMaxSize()
            .then(if (!top) Modifier.clearAndSetSemantics { } else Modifier),
    ) {
        if (!page) {
            Box(
                Modifier.fillMaxSize()
                    .graphicsLayer { alpha = scrim }
                    .background(p.scrim)
                    .pointerInput(entry, closing) { if (!closing) detectTapGestures { entry.onDismiss() } },
            )
        }
        val density = LocalDensity.current
        val drag = remember(entry) { Animatable(0f) }
        val scope = rememberCoroutineScope()
        val dragState = rememberDraggableState { delta -> scope.launch { drag.snapTo((drag.value + delta).coerceAtLeast(0f)) } }
        BoxWithConstraints(Modifier.fillMaxSize()) {
            val maxSheet = maxHeight * 0.88f
            // Where the sheet stands stays outside the motion; what it is made of (glass, card, shadow, page colour) moves
            // and fades with its content (0.9.1: these stood still, so an empty panel popped in before the content and
            // stayed after it, then vanished in one frame).
            val frame = when (entry.style) {
                SheetStyle.Page -> Modifier.fillMaxSize()
                SheetStyle.Glass -> Modifier
                    .align(Alignment.BottomCenter)
                    .windowInsetsPadding(WindowInsets.navigationBars)
                    .padding(start = 8.dp, end = 8.dp, bottom = 8.dp)
                    .widthIn(max = 560.dp)
                    .fillMaxWidth()
                    .heightIn(max = maxSheet)
                SheetStyle.Opaque -> Modifier
                    .align(Alignment.BottomCenter)
                    .widthIn(max = 640.dp)
                    .fillMaxWidth()
                    .heightIn(max = maxSheet)
            }
            val skin = when (entry.style) {
                SheetStyle.Page -> Modifier.background(p.page)
                SheetStyle.Glass -> Modifier.glass(GlassSheetShape, GlassSize.Large).clip(GlassSheetShape)
                SheetStyle.Opaque -> Modifier
                    .softShadow(TeleplyShape.SheetTop, p, TeleplyShadow.Panel)
                    .clip(TeleplyShape.SheetTop)
                    .background(p.card)
                    .windowInsetsPadding(WindowInsets.navigationBars)
            }
            Column(
                Modifier
                    .imePadding()
                    .then(frame)
                    .graphicsLayer {
                        alpha = progress
                        if (page) {
                            translationX = (1f - progress) * 24.dp.toPx()
                        } else {
                            val s = 0.98f + 0.02f * progress
                            scaleX = s
                            scaleY = s
                            translationY = (1f - progress) * 12.dp.toPx() + drag.value
                        }
                    }
                    .then(skin)
                    .semantics { paneTitle = entry.title },
            ) {
                if (page) {
                    entry.content(this)
                } else {
                    Row(
                        Modifier.fillMaxWidth()
                            .draggable(
                                dragState,
                                Orientation.Vertical,
                                enabled = !closing,
                                onDragStopped = { velocity ->
                                    val far = drag.value > with(density) { 96.dp.toPx() } || velocity > 1200f
                                    if (far) entry.onDismiss() else drag.animateTo(0f, tween(160))
                                },
                            )
                            .padding(start = 16.dp, end = 8.dp, top = 8.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Text(entry.title, style = MaterialTheme.typography.sheetTitle, color = p.text, modifier = Modifier.weight(1f).semantics { heading() })
                        entry.trailing?.let { Text(it, style = MaterialTheme.typography.note, color = p.muted, modifier = Modifier.padding(end = 4.dp)) }
                        TeleplyIconButton(TeleplyIcons.Close, "关闭", { entry.onDismiss() }, style = IconButtonStyle.Plain, enabled = !closing)
                    }
                    Column(
                        Modifier.fillMaxWidth().verticalScroll(rememberScrollState()).padding(start = 16.dp, end = 16.dp, top = 8.dp, bottom = 20.dp),
                        verticalArrangement = Arrangement.spacedBy(12.dp),
                    ) { entry.content(this) }
                }
            }
        }
    }
}

/** 28dp on all corners: the floating short-choice sheet (spec 2.5 item 3). */
private val GlassSheetShape = RoundedCornerShape(28.dp)

