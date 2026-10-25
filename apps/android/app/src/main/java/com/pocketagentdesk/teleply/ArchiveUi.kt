package com.pocketagentdesk.teleply

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.core.Animatable
import androidx.compose.animation.core.CubicBezierEasing
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.slideInVertically
import androidx.compose.animation.slideOutVertically
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.gestures.awaitEachGesture
import androidx.compose.foundation.gestures.awaitFirstDown
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Icon
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.hapticfeedback.HapticFeedbackType
import androidx.compose.ui.input.pointer.PointerEventPass
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.input.pointer.positionChange
import androidx.compose.ui.input.pointer.util.VelocityTracker
import androidx.compose.ui.layout.onSizeChanged
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.platform.LocalHapticFeedback
import androidx.compose.ui.semantics.CustomAccessibilityAction
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.customActions
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.semantics.stateDescription
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.IntOffset
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import org.json.JSONArray
import org.json.JSONObject
import kotlin.math.abs
import kotlin.math.max
import kotlin.math.min
import kotlin.math.roundToInt

private val ArchiveFill = Color(0xFF6366F1)
private val ArchiveArmed = Color(0xFF4338CA)
private val Settle = CubicBezierEasing(.32f, .72f, 0f, 1f)
private val Off = CubicBezierEasing(.33f, .7f, .35f, 1f)

/** Which row of the list is out of place (open on 归档 or under the finger); one at a time. */
class SwipeState { var open by mutableStateOf<String?>(null) }

/**
 * 左滑归档 (web archive-ui.js, second version): the row follows the finger and uncovers 归档 in its 88dp button. Let go
 * after a short slide and the row stays open on the button, which archives when tapped; slide on past about half the
 * row and 归档 darkens with a tick, and letting go there archives at once. A flick never archives. A tap on an open row,
 * another row's swipe or a scroll shuts it. A rightward drag of a shut row is left to the drawer. TalkBack gets 归档 as
 * an action of the row.
 */
@Composable
fun SwipeArchive(key: String, swipe: SwipeState, running: Boolean, enabled: Boolean, onArchive: () -> Unit, onRefused: () -> Unit, content: @Composable () -> Unit) {
    val p = LocalTeleply.current
    val density = LocalDensity.current
    val haptic = LocalHapticFeedback.current
    val scope = rememberCoroutineScope()
    val button = with(density) { 88.dp.toPx() }
    val hold = with(density) { 30.dp.toPx() }
    val give = 0.3f
    var width by remember { mutableFloatStateOf(0f) }
    val out = remember { Animatable(0f) }
    var armed by remember { mutableStateOf(false) }
    var leaving by remember { mutableStateOf(false) }
    val archive by rememberUpdatedState(onArchive)
    val refused by rememberUpdatedState(onRefused)
    val isRunning by rememberUpdatedState(running)
    val mark = max(button + with(density) { 70.dp.toPx() }, min(width * 0.48f, width - with(density) { 80.dp.toPx() }))
    fun outFor(d: Float): Float {
        if (d <= 0f) return max(-8f, d / 5f)
        val f = if (d <= button) d else if (d <= button + hold) button + (d - button) * give else d - hold * (1 - give)
        val most = width * 0.86f
        return if (f > most) most + (f - most) / 4f else f
    }
    fun fingerFor(f: Float) = if (f <= button) f else if (f <= button + hold * give) button + (f - button) / give else f + hold * (1 - give)
    fun shut() { armed = false; scope.launch { out.animateTo(0f, tween(300, easing = Settle)) }; if (swipe.open == key) swipe.open = null }
    fun leave() {
        if (isRunning) { shut(); refused(); return }
        leaving = true; armed = false
        scope.launch {
            out.animateTo(width + with(density) { 24.dp.toPx() }, tween(380, easing = Off))
            delay(80)
            archive()
            if (swipe.open == key) swipe.open = null
        }
    }
    // Another row taken, or the list scrolled: this one goes back.
    LaunchedEffect(swipe.open) { if (swipe.open != key && out.value != 0f && !leaving) { armed = false; out.animateTo(0f, tween(300, easing = Settle)) } }
    // The finger is followed from the row's place in the list, which does not move: the row slides under it.
    // Decided in the Initial pass, before the row's own tap handling takes the touch: sideways (1.3 times more than
    // up or down, as the web) is a swipe, the rest is a scroll, a tap or the drawer's.
    val gesture = if (!enabled) Modifier else Modifier.pointerInput(key) {
        awaitEachGesture {
            val down = awaitFirstDown(requireUnconsumed = false, pass = PointerEventPass.Initial)
            if (leaving) return@awaitEachGesture
            val start = out.value
            // An open row: a touch on 归档 is the button's; anywhere else on the row a tap only shuts it.
            val onButton = start > 0f && down.position.x >= width - start
            if (start > 0f && !onButton) down.consume()
            val slop = viewConfiguration.touchSlop
            var moved = Offset.Zero
            while (true) {
                val event = awaitPointerEvent(PointerEventPass.Initial)
                val change = event.changes.firstOrNull { it.id == down.id } ?: return@awaitEachGesture
                if (!change.pressed) {
                    if (start > 0f && !onButton) { change.consume(); shut() }
                    return@awaitEachGesture
                }
                moved += change.positionChange()
                if (abs(moved.x) > slop && abs(moved.x) > 1.3f * abs(moved.y)) {
                    if (start == 0f && moved.x > 0f) return@awaitEachGesture  // rightward on a shut row: the drawer's
                    change.consume()
                    break
                }
                if (abs(moved.y) > slop) { if (start > 0f) shut(); return@awaitEachGesture }  // a scroll
            }
            swipe.open = key
            val tracker = VelocityTracker()
            var finger = fingerFor(start) - moved.x
            scope.launch { out.snapTo(outFor(finger)) }
            while (true) {
                val event = awaitPointerEvent(PointerEventPass.Initial)
                val change = event.changes.firstOrNull { it.id == down.id } ?: break
                tracker.addPosition(change.uptimeMillis, change.position)
                if (!change.pressed) { change.consume(); break }
                finger -= change.positionChange().x
                val f = outFor(finger)
                scope.launch { out.snapTo(f) }
                val nowArmed = f >= mark
                if (nowArmed != armed) { armed = nowArmed; if (nowArmed) haptic.performHapticFeedback(HapticFeedbackType.LongPress) }
                change.consume()
            }
            val v = tracker.calculateVelocity().x / 1000f  // px per ms; negative is leftward
            val f = outFor(finger)
            when {
                f >= mark && v < 0.3f -> leave()
                v > 0.3f || (v > -0.3f && f < button / 2) -> shut()
                else -> { armed = false; scope.launch { out.animateTo(button, tween(300, easing = Settle)) } }
            }
        }
    }
    Box(Modifier.fillMaxWidth().onSizeChanged { width = it.width.toFloat() }.then(gesture)) {
        val shown = out.value
        if (shown > 0.5f) {
            Box(Modifier.matchParentSize().clip(RoundedCornerShape(8.dp)).background(if (armed) ArchiveArmed else ArchiveFill)) {
                // 归档 waits in its button, then keeps beside the row's edge once the row has passed it.
                val labelWidth = with(density) { max(shown, button).toDp() }
                Row(
                    Modifier.align(Alignment.CenterEnd).width(labelWidth).fillMaxHeight()
                        .then(if (!leaving && swipe.open == key && shown >= button - 1f) Modifier.clickable(role = Role.Button) { leave() } else Modifier),
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.Start,
                ) {
                    Spacer(Modifier.width(with(density) { ((min(shown, button) - 64.dp.toPx()) / 2).coerceAtLeast(8.dp.toPx()).toDp() }))
                    Icon(TeleplyIcons.Archive, contentDescription = null, tint = Color.White, modifier = Modifier.size(20.dp).graphicsLayer { val s = if (armed) 1.2f else 1f; scaleX = s; scaleY = s })
                    Spacer(Modifier.width(5.dp))
                    Text("归档", style = MaterialTheme.typography.labelLarge.copy(fontSize = 14.sp, fontWeight = FontWeight.SemiBold), color = Color.White, maxLines = 1, modifier = Modifier.graphicsLayer { alpha = (shown / with(density) { 64.dp.toPx() }).coerceIn(0.3f, 1f) })
                }
            }
        }
        Box(
            Modifier.fillMaxWidth().offset { IntOffset(-out.value.roundToInt(), 0) }.background(p.page)
                .semantics { if (enabled) customActions = listOf(CustomAccessibilityAction("归档") { if (isRunning) refused() else archive(); true }) },
        ) { content() }
    }
}

/** The bar under the list after an archive (web .undo-bar): 对话已归档 and the title, 撤销 for six seconds. */
@Composable
fun UndoBar(undo: ArchiveUndo?, onUndo: () -> Unit, onTimeout: (Long) -> Unit, modifier: Modifier = Modifier) {
    LaunchedEffect(undo?.serial, undo?.waiting) { if (undo != null && !undo.waiting) { delay(6000); onTimeout(undo.serial) } }
    AnimatedVisibility(undo != null, modifier, enter = slideInVertically { it } + fadeIn(), exit = slideOutVertically { it } + fadeOut()) {
        val u = undo ?: return@AnimatedVisibility
        Row(
            Modifier.widthIn(max = 520.dp).fillMaxWidth().padding(horizontal = 12.dp).clip(RoundedCornerShape(16.dp)).background(Color(0xFF1F2430))
                .padding(start = 16.dp, end = 6.dp, top = 6.dp, bottom = 6.dp).semantics(mergeDescendants = true) { liveRegion = LiveRegionMode.Polite },
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Column(Modifier.weight(1f)) {
                Text(if (u.waiting) "正在归档…" else "对话已归档", style = MaterialTheme.typography.bodyMedium.copy(fontSize = 14.sp), color = Color.White)
                Text(u.chat.title, style = MaterialTheme.typography.bodySmall.copy(fontSize = 12.sp), color = Color(0xFFAAB3C5), maxLines = 1, overflow = TextOverflow.Ellipsis)
            }
            Box(
                Modifier.heightIn(min = 44.dp).clip(RoundedCornerShape(12.dp)).clickable(enabled = !u.waiting, role = Role.Button, onClick = onUndo).padding(horizontal = 14.dp),
                contentAlignment = Alignment.Center,
            ) { Text("撤销", style = MaterialTheme.typography.labelLarge.copy(fontSize = 15.sp, fontWeight = FontWeight.Bold), color = Color(0xFF9FB8FF).copy(alpha = if (u.waiting) 0.4f else 1f)) }
        }
    }
}

/** A line shown at the bottom for three seconds (the web's toast): why something did not happen. */
@Composable
fun NoticeToast(text: String?, onDone: () -> Unit, modifier: Modifier = Modifier) {
    LaunchedEffect(text) { if (text != null) { delay(3200); onDone() } }
    AnimatedVisibility(text != null, modifier, enter = fadeIn(), exit = fadeOut()) {
        Box(Modifier.padding(horizontal = 24.dp).clip(RoundedCornerShape(14.dp)).background(Color(0xE6111111)).padding(horizontal = 16.dp, vertical = 10.dp).semantics { liveRegion = LiveRegionMode.Polite }) {
            Text(text.orEmpty(), style = MaterialTheme.typography.bodyMedium.copy(fontSize = 14.sp), color = Color.White)
        }
    }
}

/**
 * 设置 → 已归档对话 (web archivedSheet): by source; 恢复 brings one back. Codex ones can be ticked and deleted for good
 * after a confirmation; DeepSeek has no delete, so its rows only restore; Claude's restore when the computer has it.
 */
@Composable
fun ArchivedSheet(vm: ReaderViewModel, onDismiss: () -> Unit) {
    val p = LocalTeleply.current
    val scope = rememberCoroutineScope()
    var data by remember { mutableStateOf<JSONObject?>(null) }
    var picked by remember { mutableStateOf(setOf<String>()) }
    var busy by remember { mutableStateOf(false) }
    var confirm by remember { mutableStateOf(false) }
    var note by remember { mutableStateOf<String?>(null) }
    suspend fun load() {
        data = try { vm.deviceCall("chat/archived") } catch (e: Exception) { JSONObject().put("items", JSONArray()).put("problems", JSONArray().put(e.message ?: "读不到")) }
        val keys = data!!.rows("items") { it.string("app") + ":" + it.string("id") }.toSet()
        picked = picked.filter { it in keys }.toSet()
    }
    LaunchedEffect(Unit) { load() }
    val items = data?.rows("items") { it }.orEmpty()
    val deletable = data?.let { d -> d.optJSONArray("deletable")?.let { a -> (0 until a.length()).map { a.getString(it) }.toSet() } }.orEmpty()
    val apps = data?.optJSONArray("apps")?.let { a -> (0 until a.length()).map { a.getString(it) } }.orEmpty()
    val canDelete = items.filter { it.optBoolean("can_delete") && it.string("app") in deletable }
    TeleplySheet("已归档对话", onDismiss) {
        if (busy) LinearProgressIndicator(Modifier.fillMaxWidth().height(2.dp), color = p.accent, trackColor = p.line)
        val explain = listOfNotNull(
            "Codex 的可以恢复，也可以勾选后删除；删除后电脑上也找不回来。".takeIf { "codex" in apps },
            "DeepSeek 没有删除对话的功能，只能恢复。".takeIf { "deepseek" in apps },
            "Claude 可以归档和恢复，需电脑解锁；有工作副本的会话请在电脑上归档。暂不支持删除。".takeIf { "claude" in apps },
        ).joinToString("")
        if (explain.isNotBlank()) Text(explain, style = MaterialTheme.typography.bodySmall.copy(fontSize = 12.sp), color = p.muted)
        note?.let { Text(it, style = MaterialTheme.typography.note, color = p.muted, modifier = Modifier.semantics { liveRegion = LiveRegionMode.Polite }) }
        val d = data
        when {
            d == null -> Text("读取中…", style = MaterialTheme.typography.note, color = p.muted)
            else -> {
                d.optJSONArray("problems")?.let { a -> (0 until a.length()).forEach { Text("读不到 " + a.getString(it), style = MaterialTheme.typography.note, color = p.error) } }
                if (items.isEmpty() && (d.optJSONArray("problems")?.length() ?: 0) == 0) Text("没有已归档的对话。\n在对话列表里把一行往左滑，就能归档。", style = MaterialTheme.typography.note, color = p.muted)
                var app = ""
                CardSectionOrNothing(items.isNotEmpty()) {
                    items.forEachIndexed { index, v ->
                        if (v.string("app") != app) { app = v.string("app"); Text(sourceName(app), style = MaterialTheme.typography.labelMedium.copy(fontSize = 12.sp, fontWeight = FontWeight.SemiBold), color = p.muted, modifier = Modifier.padding(start = 16.dp, top = 10.dp, bottom = 4.dp)) }
                        else if (index > 0) CardDivider()
                        val k = v.string("app") + ":" + v.string("id")
                        val can = v.optBoolean("can_delete") && v.string("app") in deletable
                        ArchivedRow(v, picked.contains(k), can && !busy, !busy, onPick = { picked = if (k in picked) picked - k else picked + k }) {
                            busy = true
                            scope.launch {
                                try { vm.deviceCall("chat/unarchive", body = JSONObject().put("app", v.string("app")).put("id", v.string("id"))); note = "已恢复，回到对话列表里了"; vm.restored(v.string("app"), v.string("id")) }
                                catch (e: Exception) { note = (if (v.string("app") == "claude") "Claude：" else "没恢复：") + (e.message ?: "") }
                                busy = false; load()
                            }
                        }
                    }
                }
                if (canDelete.isNotEmpty()) Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    val all = canDelete.all { (it.string("app") + ":" + it.string("id")) in picked }
                    PillButton(if (all) "全不选" else "全选", { picked = if (all) emptySet() else canDelete.map { it.string("app") + ":" + it.string("id") }.toSet() }, enabled = !busy, modifier = Modifier.weight(1f))
                    PillButton(if (picked.isEmpty()) "删除" else "删除（${picked.size}）", { confirm = true }, style = PillStyle.Danger, enabled = !busy && picked.isNotEmpty(), modifier = Modifier.weight(1f))
                }
            }
        }
    }
    if (confirm) AlertDialog(
        onDismissRequest = { confirm = false },
        title = { Text("删除这 ${picked.size} 个对话？") },
        text = { Text("删除后在电脑上也找不回来。") },
        confirmButton = {
            TextButton(onClick = {
                confirm = false
                val chosen = items.filter { (it.string("app") + ":" + it.string("id")) in picked }
                busy = true
                scope.launch {
                    try {
                        val r = vm.deviceCall("chat/delete", body = JSONObject().put("items", JSONArray(chosen.map { JSONObject().put("app", it.string("app")).put("id", it.string("id")) })).put("confirmed", true))
                        val failed = r.rows("results") { it }.filter { !it.optBoolean("ok") }
                        note = if (failed.isNotEmpty()) "删了 ${r.optInt("deleted")} 个，${failed.size} 个没删：${failed.first().string("error")}" else "已删除 ${r.optInt("deleted")} 个对话"
                    } catch (e: Exception) { note = "没删除：" + (e.message ?: "") }
                    busy = false; picked = emptySet(); load()
                }
            }) { Text("删除", color = p.error) }
        },
        dismissButton = { TextButton(onClick = { confirm = false }) { Text("取消") } },
    )
}

@Composable
private fun CardSectionOrNothing(show: Boolean, content: @Composable () -> Unit) { if (show) CardSection { content() } }

@Composable
private fun ArchivedRow(v: JSONObject, picked: Boolean, canPick: Boolean, enabled: Boolean, onPick: () -> Unit, onRestore: () -> Unit) {
    val p = LocalTeleply.current
    Row(Modifier.fillMaxWidth().heightIn(min = 60.dp).padding(start = 6.dp, end = 12.dp), verticalAlignment = Alignment.CenterVertically) {
        val title = v.string("title").ifBlank { "未命名对话" }
        Box(
            Modifier.size(44.dp).clip(CircleShape)
                .then(if (canPick) Modifier.clickable(role = Role.Checkbox, onClickLabel = if (picked) "不删除" else "选中删除", onClick = onPick) else Modifier)
                .semantics { contentDescription = (if (picked) "不删除 " else "选中删除 ") + title; stateDescription = if (picked) "已选中" else "未选中" }
                .graphicsLayer { alpha = if (canPick) 1f else 0f },
            contentAlignment = Alignment.Center,
        ) {
            Box(
                Modifier.size(22.dp).clip(CircleShape).background(if (picked) p.error else Color.Transparent)
                    .then(if (picked) Modifier else Modifier.border(1.5.dp, if (p.dark) p.edge else Color(0xFFC4C9D4), CircleShape)),
                contentAlignment = Alignment.Center,
            ) { if (picked) Icon(TeleplyIcons.Check, contentDescription = null, tint = Color.White, modifier = Modifier.size(14.dp)) }
        }
        Column(Modifier.weight(1f).padding(start = 4.dp)) {
            Text(title, style = MaterialTheme.typography.bodyLarge.copy(fontSize = 15.sp, fontWeight = FontWeight.Medium), color = p.text, maxLines = 1, overflow = TextOverflow.Ellipsis)
            val when_ = if (v.optLong("archived_at") > 0) "归档于 " + agoLabel(stamp(v.optLong("archived_at"))) else if (v.optLong("updated") > 0) "最后活动 " + agoLabel(stamp(v.optLong("updated"))) else ""
            val line = listOf(v.string("folder"), when_).filter { it.isNotBlank() }.joinToString(" · ")
            if (line.isNotBlank()) Text(line, style = MaterialTheme.typography.bodySmall.copy(fontSize = 12.sp), color = p.muted, maxLines = 1, overflow = TextOverflow.Ellipsis, modifier = Modifier.padding(top = 2.dp))
        }
        PillButton("恢复", onRestore, enabled = enabled, minHeight = 36.dp, description = "恢复 $title")
    }
}

/** Seconds or milliseconds since 1970, as milliseconds. */
private fun stamp(v: Long) = if (v < 10_000_000_000L) v * 1000 else v
