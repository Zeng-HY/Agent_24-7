package com.pocketagentdesk.teleply

import android.content.Context
import android.content.Intent
import androidx.compose.animation.animateContentSize
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.gestures.scrollBy
import androidx.compose.foundation.interaction.collectIsDraggedAsState
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.IntrinsicSize
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.WindowInsetsSides
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.only
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawing
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.layout.windowInsetsPadding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Icon
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.LocalContentColor
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.Stable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateMapOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.runtime.snapshotFlow
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Rect
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.hapticfeedback.HapticFeedbackType
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.layout.LayoutCoordinates
import androidx.compose.ui.layout.boundsInRoot
import androidx.compose.ui.layout.onGloballyPositioned
import androidx.compose.ui.layout.onSizeChanged
import androidx.compose.ui.platform.LocalClipboardManager
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.platform.LocalHapticFeedback
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.semantics.CustomAccessibilityAction
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.customActions
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.semantics.stateDescription
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import kotlinx.coroutines.FlowPreview
import kotlinx.coroutines.flow.debounce
import kotlinx.coroutines.launch
import org.json.JSONArray
import org.json.JSONObject
import java.util.Locale

/** Reading widths (web #cvMsgs): text never wider than 820dp on wide windows. */
private val ReadingWidth = 820.dp

/**
 * The conversation page (spec 4.3). Messages scroll under the glass title bar and, since 0.4, under the glass input
 * card; the question and approval cards of all three sources sit in the timeline (user decision, differs from the web).
 */
@OptIn(FlowPreview::class)
@Composable
fun ChatScreen(s: ReaderState, vm: ReaderViewModel, onBack: (() -> Unit)?) {
    val p = LocalTeleply.current
    val density = LocalDensity.current
    val chat by vm.composer.state.collectAsStateWithLifecycle()
    val workspace by vm.workspace.state.collectAsStateWithLifecycle()
    val key = Triple(s.app, s.device?.id, s.chat?.id)
    var follow by remember(key) { mutableStateOf(true) }
    var unseen by remember(key) { mutableStateOf(false) }
    var restored by remember(key) { mutableStateOf(false) }
    val list = rememberLazyListState()
    val scope = rememberCoroutineScope()
    var barHeight by remember { mutableStateOf(0.dp) }
    var inputHeight by remember { mutableStateOf(0.dp) }
    val sheets = remember(key) { ChatSheets() }
    val folds = remember(key) { mutableStateMapOf<String, Boolean>() }
    val currentMessages by rememberUpdatedState(s.messages)
    val dragged by list.interactionSource.collectIsDraggedAsState()
    val currentDragged by rememberUpdatedState(dragged)
    val raw = remember(chat.control.raw) { runCatching { JSONObject(chat.control.raw) }.getOrDefault(JSONObject()) }
    val saved = remember(workspace.saved) { runCatching { JSONObject(workspace.saved) }.getOrDefault(JSONObject()) }
    val cards = remember(raw, s.app) { pendingCards(s.app, raw) }
    // A new conversation's page before it exists, and its first message after, until the record shows it (0.8).
    val newPage = isNewPage(s.chat)
    val jobs by vm.jobs.jobs.collectAsStateWithLifecycle()
    val job = if (newPage) jobs.find { it.preview == s.chat?.id } else null
    val handoff = s.handoff?.takeIf { h -> h.id == s.chat?.id && h.app == s.app && s.messages.none { it.role == "user" } }

    // Reading position (B09): follow the bottom only when the reader is at the bottom.
    LaunchedEffect(list) {
        snapshotFlow { currentDragged to list.canScrollForward }.collect { (dragging, forward) ->
            if (dragging) follow = false
            if (!forward && !dragging) { follow = true; unseen = false }
        }
    }
    LaunchedEffect(chat.revision) {
        if (restored && chat.revision > 0 && s.messages.isNotEmpty()) {
            if (follow && !s.newer) scrollToEnd(list) else unseen = true
        }
    }
    LaunchedEffect(s.app, s.device?.id, s.chat?.id, s.scrollRevision) {
        if (s.messages.isNotEmpty()) {
            val index = s.anchor?.let { a -> s.messages.indexOfFirst { it.id == a.message }.takeIf { it >= 0 } }
            follow = index == null && !s.newer
            if (index != null) list.scrollToItem(index + 1, s.anchor?.offset ?: 0) else scrollToEnd(list)
            restored = true
        }
    }
    // The input area grows (queue, prompt bar, multi-line draft) or the keyboard opens: stay at the bottom if there.
    LaunchedEffect(inputHeight) { if (restored && follow && !s.newer) scrollToEnd(list) }
    LaunchedEffect(list, s.app, s.device?.id, s.chat?.id, restored) {
        if (restored) snapshotFlow { list.firstVisibleItemIndex to list.firstVisibleItemScrollOffset }.debounce(400).collect { (index, offset) ->
            currentMessages.getOrNull(index - 1)?.let { vm.saveAnchor(it.id, offset, s.scope, s.device?.id, s.chat?.id, s.app) }
        }
    }
    androidx.compose.runtime.DisposableEffect(s.app, s.device?.id, s.chat?.id) {
        onDispose { currentMessages.getOrNull(list.firstVisibleItemIndex - 1)?.let { vm.saveAnchor(it.id, list.firstVisibleItemScrollOffset, s.scope, s.device?.id, s.chat?.id, s.app) } }
    }
    val lastUser = s.messages.indexOfLast { it.role == "user" }
    GlassScreen(
        Modifier.fillMaxSize().background(p.page),
        topEdge = barHeight + 12.dp,
        bottomEdge = inputHeight + 12.dp,
        content = {
            LazyColumn(
                Modifier.fillMaxSize().testTag("messages"),
                state = list,
                contentPadding = PaddingValues(start = 20.dp, end = 20.dp, top = barHeight + 4.dp, bottom = inputHeight + 16.dp),
            ) {
                item(key = "history-tools") {
                    Column(Modifier.fillMaxWidth(), horizontalAlignment = Alignment.CenterHorizontally) {
                        if (s.older) PillButton("加载更早消息", vm::older, enabled = !s.busy, style = PillStyle.Text)
                        if (s.newer) InfoNote("这里是历史位置，后面还有更新的消息。", Modifier.padding(vertical = 8.dp))
                        if (!s.busy && s.messages.isEmpty() && !newPage && handoff == null) Text("暂无消息", style = MaterialTheme.typography.note, color = p.muted, modifier = Modifier.padding(24.dp))
                    }
                }
                // A new conversation (0.8, web): its first message with where it stands, until the record has it.
                if (newPage) item(key = "new-first") {
                    Reading {
                        if (job == null) InfoNote("这个创建请求已经处理过了，请从对话列表打开。", Modifier.padding(vertical = 16.dp))
                        else NewFirstMessage(job.text, newJobInline(job), job.problem) { vm.openJob(job) }
                    }
                }
                if (handoff != null) item(key = "handoff") { Reading { NewFirstMessage(handoff.text, "", false) {} } }
                itemsIndexed(s.messages, key = { _, m -> "msg:${m.id}" }, contentType = { _, m -> m.role + m.kind + m.phase }) { index, message ->
                    Reading {
                        TimelineItem(s, vm, message, index, lastUser, chat, cards.isNotEmpty(), folds, sheets, raw, workspace)
                    }
                }
                item(key = "interactions") {
                    Reading {
                        Column(Modifier.fillMaxWidth().padding(top = if (cards.isEmpty()) 0.dp else 16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
                            InlineCards(s.app, raw, saved, vm, workspace)
                        }
                    }
                }
                if (s.newer) item(key = "latest") {
                    Box(Modifier.fillMaxWidth().padding(top = 16.dp), contentAlignment = Alignment.Center) { PillButton("回到最新", { follow = true; unseen = false; vm.latest() }, enabled = !s.busy) }
                }
                val outbox = chat.submissions.filter { it.action == "send" && it.label == "提交中" && s.messages.none { m -> m.request == it.request } }
                if (outbox.isNotEmpty()) item(key = "outbox") {
                    Reading { Column(Modifier.fillMaxWidth().padding(top = 16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) { outbox.forEach { UserBubble(it.text, receipt = it.label, sending = true) } } }
                }
            }
        },
        overlay = {
            Column(Modifier.fillMaxWidth().onSizeChanged { barHeight = with(density) { it.height.toDp() } }) {
                ChatTopBar(s, vm, chat, raw, onBack, sheets)
                ProgressLine(s.busy)
                if (s.fixture) NoteBar("本地示例 · 固定数据 · 未连接真实服务", NoteTone.Info)
                s.error?.let { NoteBar(it, NoteTone.Error, action = "重试", actionEnabled = !s.busy, onAction = vm::retry) }
                if (chat.connection.contains("中断") || chat.connection.contains("失效")) NoteBar(chat.connection, NoteTone.Connection)
            }
            Column(
                Modifier.align(Alignment.BottomCenter).fillMaxWidth()
                    .onSizeChanged { inputHeight = with(density) { it.height.toDp() } },
                horizontalAlignment = Alignment.CenterHorizontally,
            ) {
                if (unseen && !follow) {
                    GlassPill("有新消息", { follow = true; unseen = false; if (s.newer) vm.latest() else scope.launch { scrollToEnd(list) } }, Modifier.padding(bottom = 8.dp), leading = TeleplyIcons.Down, description = "有新消息，回到底部")
                }
                InputArea(s, vm, chat, workspace, raw, cards) {
                    scope.launch { list.animateScrollToItem(s.messages.size + 1) }
                }
            }
        },
    )
    ChatSheetsHost(s, vm, chat, raw, sheets)
}

private suspend fun scrollToEnd(list: androidx.compose.foundation.lazy.LazyListState) {
    val count = list.layoutInfo.totalItemsCount
    if (count == 0) return
    list.scrollToItem(count - 1)
    list.layoutInfo.visibleItemsInfo.lastOrNull()?.let { last -> list.scrollBy((last.offset + last.size - list.layoutInfo.viewportEndOffset + list.layoutInfo.afterContentPadding).coerceAtLeast(0).toFloat()) }
}

/** Centres reading content at 820dp at most (web). */
@Composable
private fun Reading(content: @Composable () -> Unit) {
    Box(Modifier.fillMaxWidth(), contentAlignment = Alignment.TopCenter) { Box(Modifier.widthIn(max = ReadingWidth).fillMaxWidth()) { content() } }
}

/** Sheets and pages the conversation page can open. */
@Stable
class ChatSheets {
    var search by mutableStateOf(false)
    var pending by mutableStateOf(false)
    var prompts by mutableStateOf(false)
    var select by mutableStateOf<Message?>(null)
}

// ---------------------------------------------------------------------------------------------
// Title bar

@Composable
private fun ChatTopBar(s: ReaderState, vm: ReaderViewModel, chat: ComposerState, raw: JSONObject, onBack: (() -> Unit)?, sheets: ChatSheets) {
    val p = LocalTeleply.current
    val menus = LocalMenuHost.current
    val more = remember { MenuAnchor() }
    val runtime = runtimeOf(s, raw)
    val percent = runtime?.takeIf { it.string("context_state") == "available" && it.has("percent") }?.optDouble("percent")?.let { Math.round(it).toInt() }
    val meta = listOf(s.chat?.folder.orEmpty().ifBlank { JSONObject(s.runtime.ifBlank { "{}" }).string("folder") }, sourceName(s.app)).filter { it.isNotBlank() }.joinToString(" · ")
    Row(
        Modifier.fillMaxWidth()
            .windowInsetsPadding(WindowInsets.safeDrawing.only(WindowInsetsSides.Top + WindowInsetsSides.Horizontal))
            .padding(start = 12.dp, end = 12.dp, top = 8.dp, bottom = 8.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        if (onBack != null) TeleplyIconButton(TeleplyIcons.Back, "返回", onBack)
        Column(Modifier.weight(1f).padding(horizontal = 8.dp)) {
            Text(s.chat?.title ?: "对话", style = MaterialTheme.typography.chatTitle, color = p.text, maxLines = 1, overflow = TextOverflow.Ellipsis, modifier = Modifier.semantics { heading() })
            if (meta.isNotBlank()) Text(meta, style = MaterialTheme.typography.bodySmall, color = p.muted, maxLines = 1, overflow = TextOverflow.Ellipsis, modifier = Modifier.padding(top = 2.dp))
        }
        // A new conversation's page has nothing to stop and no menu yet (web .new-provisional).
        if (isNewPage(s.chat)) return@Row
        val claudeStop = raw.string("stop_token")
        val canStop = chat.control.running && (s.app != "claude" || claudeStop.isNotBlank())
        if (canStop) {
            StopPill("停止这一轮", enabled = chat.control.available && !chat.submitting, disabledReason = "暂时不能控制这个来源") {
                if (s.app == "claude") vm.workspace.action("claude/choose", JSONObject().put("token", claudeStop)) else vm.composer.stop()
            }
            Spacer(Modifier.width(8.dp))
        }
        // 会话状态 opens from the capsule like a menu (spec 0.4 §4.3), from the ring or from the ⋯ menu.
        val runtimePanel = { MenuRequest(more.bounds, MenuPlacement.BelowEnd, "会话状态", width = 300.dp) { RuntimePanel(vm) } }
        CapsuleToolbar(Modifier.menuAnchor(more)) {
            if (percent != null) ContextRing(percent, { menus?.show(runtimePanel()) })
            TeleplyIconButton(TeleplyIcons.More, "对话菜单", {
                menus?.show(MenuRequest(more.bounds, MenuPlacement.BelowEnd, "对话菜单") { ChatMenu(s, vm, chat, sheets) { menus.showAfter(runtimePanel()) } })
            }, style = IconButtonStyle.Plain)
        }
    }
}

@Composable
private fun MenuScope.ChatMenu(s: ReaderState, vm: ReaderViewModel, chat: ComposerState, sheets: ChatSheets, onRuntime: () -> Unit) {
    val unconfirmed = chat.submissions.count { it.label in listOf("提交中", "送达状态待确认") }
    MenuRow("电脑上打开", { vm.workspace.openOnComputer() }, icon = TeleplyIcons.Open)
    MenuRow("会话状态", onRuntime, icon = TeleplyIcons.Info)
    MenuRow("查找消息", { sheets.search = true }, icon = TeleplyIcons.Search)
    MenuRow("对话文件", { vm.workspace.panel("files") }, icon = TeleplyIcons.File)
    MenuRow("常用提示语", { sheets.prompts = true }, icon = TeleplyIcons.Text)
    if (unconfirmed > 0) MenuRow("待核对发送记录", { sheets.pending = true }, icon = TeleplyIcons.Clock, count = unconfirmed)
    if (!s.fixture) {
        MenuDivider()
        WatchRow(s)
    }
    val folder = JSONObject(s.runtime.ifBlank { "{}" }).let { it.string("cwd").ifBlank { it.string("folder") } }.ifBlank { s.chat?.folder.orEmpty() }
    if (folder.isNotBlank()) {
        MenuDivider()
        MenuHint(folder)
    }
}

/** 关注此会话状态: the Android-only system notification (spec 4.3); asks for the notification permission first. */
@Composable
private fun MenuScope.WatchRow(s: ReaderState) {
    val context = LocalContext.current
    val graph = context.applicationContext as? NativeApplication ?: return
    val target by graph.watch.state.collectAsStateWithLifecycle()
    val key = if (s.device != null && s.chat != null) ChatKey(s.scope, s.device.id, s.chat.id, s.app) else null
    val watching = target?.key == key && key != null
    val scope = rememberCoroutineScope()
    val allowed = graph.watch.allowed()
    MenuRow(
        if (watching) "已关注此会话状态" else "关注此会话状态",
        {
            if (key == null) return@MenuRow
            when {
                watching -> graph.watch.disable()
                !allowed -> runCatching { context.startActivity(Intent(android.provider.Settings.ACTION_APP_NOTIFICATION_SETTINGS).putExtra(android.provider.Settings.EXTRA_APP_PACKAGE, context.packageName).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) }
                else -> scope.launch { runCatching { graph.watch.enable(s.origin, key) } }
            }
        },
        icon = TeleplyIcons.Bell,
        detail = when { watching -> "再点一次关闭"; !allowed -> "先在系统设置里允许通知"; else -> "运行结束或需要回答时通知你" },
        trailing = if (watching) MenuTrailing.Checked else MenuTrailing.None,
        enabled = key != null,
    )
}

fun runtimeOf(s: ReaderState, raw: JSONObject): JSONObject? {
    // Claude's model and context come from the desktop (raw.runtime); the others from the session record (page meta).
    val fromControl = raw.optJSONObject("runtime")
    if (s.app == "claude" && fromControl != null) return fromControl
    return runCatching { JSONObject(s.runtime.ifBlank { "{}" }).optJSONObject("runtime") }.getOrNull() ?: fromControl
}

// ---------------------------------------------------------------------------------------------
// Timeline

private fun isProcess(m: Message) = m.role == "tool" || m.role == "assistant" && m.phase in setOf("commentary", "thinking") && !m.kind.contains("question") && !m.kind.contains("approval")

@Composable
private fun TimelineItem(s: ReaderState, vm: ReaderViewModel, message: Message, index: Int, lastUser: Int, chat: ComposerState, asking: Boolean, folds: MutableMap<String, Boolean>, sheets: ChatSheets, raw: JSONObject, ws: WorkspaceState) {
    val p = LocalTeleply.current
    val messages = s.messages
    val previous = messages.getOrNull(index - 1)
    val plan = if (s.app == "codex") codexPlanFor(raw, message) else null
    when {
        message.role == "user" -> {
            val receipt = chat.submissions.firstOrNull { it.request.isNotBlank() && it.request == message.request }?.label
            Column(Modifier.fillMaxWidth().padding(top = 20.dp), horizontalAlignment = Alignment.End) {
                OriginLabel(message, Modifier.padding(end = 4.dp))
                UserBubble(message.text, receipt = receipt, menus = LocalMenuHost.current, sheets = sheets)
            }
        }
        message.role == "plan" -> ChecklistCard(message)
        message.role == "next" -> NextStepCard(message, vm, ws)
        message.role == "task" -> TaskCard(message, raw, vm, ws)
        message.role == "subagent" -> SubagentCard(message)
        plan != null -> CodexPlanCard(plan, chat, vm, ws)
        isProcess(message) -> {
            // A run of process steps shares one fold; the first step carries the header.
            var start = index
            while (start > 0 && isProcess(messages[start - 1])) start--
            var end = index
            while (end < messages.lastIndex && isProcess(messages[end + 1])) end++
            val groupKey = messages[start].id
            val last = start > lastUser && messages.drop(end + 1).none { !isProcess(it) && it.role != "event" }
            val live = chat.control.running && last
            val waiting = asking && last
            // Running groups start open, finished ones folded; the reader's own choice wins (design language §8).
            val open = folds[groupKey] ?: live
            Column(Modifier.fillMaxWidth().padding(top = if (index == start) 16.dp else 0.dp)) {
                if (index == start) {
                    val steps = end - start + 1
                    Row(
                        Modifier.clip(RoundedCornerShape(8.dp)).clickable { folds[groupKey] = !open }
                            .semantics { stateDescription = if (open) "已展开" else "已收起" }
                            .heightIn(min = 36.dp).padding(end = 8.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Icon(if (open) TeleplyIcons.ChevronDown else TeleplyIcons.ChevronRight, contentDescription = null, tint = p.muted, modifier = Modifier.size(16.dp))
                        Spacer(Modifier.width(6.dp))
                        Text((if (waiting) "需要你回答" else if (live) "正在处理" else "处理过程") + " · $steps 步", style = MaterialTheme.typography.process, color = if (waiting) p.askGo else p.muted)
                    }
                }
                if (open) {
                    Row(Modifier.fillMaxWidth().height(IntrinsicSize.Min)) {
                        Box(Modifier.padding(start = 7.dp).width(3.dp).fillMaxHeight().background(p.line))
                        Column(Modifier.weight(1f).padding(start = 12.dp, top = 4.dp, bottom = 4.dp)) { ProcessStep(message, vm) }
                    }
                }
            }
        }
        message.kind.contains("question") || message.kind.contains("approval") -> {
            Column(Modifier.fillMaxWidth().padding(top = 16.dp)) {
                Text(if (message.kind.contains("approval")) "批准请求" else "问题", style = MaterialTheme.typography.labelMedium, color = p.askGo)
                Markdown(message.text, Modifier.fillMaxWidth().padding(top = 4.dp))
            }
        }
        message.role == "event" -> {
            Text(message.text, style = MaterialTheme.typography.bodySmall, color = p.muted, modifier = Modifier.fillMaxWidth().padding(top = 12.dp), textAlign = androidx.compose.ui.text.style.TextAlign.Center)
        }
        else -> {
            val menus = LocalMenuHost.current
            AnswerBlock(message, s, vm, menus, sheets, top = if (previous?.role == "user") 20.dp else 16.dp)
        }
    }
}

@Composable
private fun ProcessStep(message: Message, vm: ReaderViewModel) {
    val p = LocalTeleply.current
    if (message.role == "tool") {
        val details = remember(message.details) { runCatching { JSONObject(message.details) }.getOrDefault(JSONObject()) }
        Row(verticalAlignment = Alignment.CenterVertically) {
            val mark = when (message.status) { "running" -> "◌"; "no_matches" -> "∅"; "completed" -> "✓"; else -> "·" }
            Text("$mark " + details.string("title").ifBlank { message.text }, style = MaterialTheme.typography.process, color = p.text.copy(alpha = 0.85f), modifier = Modifier.weight(1f), maxLines = 3, overflow = TextOverflow.Ellipsis)
            if (message.status == "failed") Text("失败", style = MaterialTheme.typography.bodySmall, color = p.error, modifier = Modifier.padding(start = 8.dp))
        }
        details.rows("changes") { it }.forEach { change ->
            val ref = change.string("ref")
            Text(
                "本轮差异：${change.string("path")}",
                style = MaterialTheme.typography.process,
                color = if (ref.isNotBlank()) p.accent else p.muted,
                modifier = Modifier.padding(top = 4.dp).clip(RoundedCornerShape(6.dp)).then(if (ref.isNotBlank()) Modifier.clickable { vm.workspace.diff(ref) } else Modifier).padding(vertical = 4.dp),
            )
        }
    } else {
        Text(message.text, style = MaterialTheme.typography.process, color = p.muted)
    }
}

/** Long-press position in root coordinates, for menus that open at the finger. */
private class Anchor { var coordinates: LayoutCoordinates? = null }

/** User message bubble (web .bub.user): accent in light mode, #1E1E1E with a #333 edge in dark; long press for the menu. */
@Composable
fun UserBubble(text: String, receipt: String? = null, sending: Boolean = false, menus: MenuHostState? = null, sheets: ChatSheets? = null) {
    val p = LocalTeleply.current
    val haptic = LocalHapticFeedback.current
    val holder = remember { Anchor() }
    val message = remember(text) { Message("bubble", "user", text) }
    val openMenu: (Offset?) -> Unit = { at ->
        val coords = holder.coordinates
        if (coords != null && menus != null && sheets != null) {
            val point = at?.let { coords.localToRoot(it) } ?: coords.boundsInRoot().center
            menus.show(MenuRequest(Rect(point, point), MenuPlacement.AtPoint, "消息菜单", width = 220.dp) { MessageMenu(text, sheets, message) })
        }
    }
    Column(Modifier.fillMaxWidth(), horizontalAlignment = Alignment.End) {
        BoxWithConstraints(Modifier.fillMaxWidth(), contentAlignment = Alignment.CenterEnd) {
            Box(
                Modifier.widthIn(max = maxWidth * 0.88f)
                    .onGloballyPositioned { holder.coordinates = it }
                    .clip(TeleplyShape.Bubble)
                    .background(p.bubble)
                    .then(if (p.dark) Modifier.border(1.dp, p.bubbleEdge, TeleplyShape.Bubble) else Modifier)
                    .then(if (menus != null) Modifier.pointerInput(text) { detectTapGestures(onLongPress = { haptic.performHapticFeedback(HapticFeedbackType.LongPress); openMenu(it) }) } else Modifier)
                    .semantics { if (menus != null) customActions = listOf(CustomAccessibilityAction("更多操作") { openMenu(null); true }) }
                    .graphicsLayer { alpha = if (sending) 0.6f else 1f }
                    .padding(horizontal = 16.dp, vertical = 10.dp),
            ) {
                CompositionLocalProvider(LocalContentColor provides p.onBubble) {
                    Markdown(text, linkColor = if (p.dark) p.accent else Color.White, codeBackground = if (p.dark) p.codeFill else Color.White.copy(alpha = 0.18f))
                }
            }
        }
        if (receipt != null) Text(receipt, style = MaterialTheme.typography.bodySmall, color = if (receipt == "送达状态待确认") p.amber else p.muted, modifier = Modifier.padding(top = 4.dp, end = 4.dp).semantics { liveRegion = LiveRegionMode.Polite })
    }
}

/** An answer: open text, no card (web .bub.assistant); long press opens the message menu. */
@Composable
private fun AnswerBlock(message: Message, s: ReaderState, vm: ReaderViewModel, menus: MenuHostState?, sheets: ChatSheets, top: androidx.compose.ui.unit.Dp) {
    val p = LocalTeleply.current
    val haptic = LocalHapticFeedback.current
    val holder = remember { Anchor() }
    val openMenu: (Offset?) -> Unit = { at ->
        val coords = holder.coordinates
        if (coords != null && menus != null) {
            val point = at?.let { coords.localToRoot(it) } ?: coords.boundsInRoot().topCenter
            menus.show(MenuRequest(Rect(point, point), MenuPlacement.AtPoint, "消息菜单", width = 220.dp) { MessageMenu(message.text, sheets, message) })
        }
    }
    Column(
        Modifier.fillMaxWidth().padding(top = top)
            .onGloballyPositioned { holder.coordinates = it }
            .pointerInput(message.id) { detectTapGestures(onLongPress = { haptic.performHapticFeedback(HapticFeedbackType.LongPress); openMenu(it) }) }
            .semantics { customActions = listOf(CustomAccessibilityAction("更多操作") { openMenu(null); true }) },
    ) {
        OriginLabel(message)
        Markdown(message.text, Modifier.fillMaxWidth())
        if (message.truncated) PillButton("展开完整消息", { vm.expand(message) }, enabled = !s.busy, style = PillStyle.Text)
    }
}

/** 复制 · 选择文字 · 分享 (web message menu, static/reading-ui.js). */
@Composable
private fun MenuScope.MessageMenu(text: String, sheets: ChatSheets, message: Message) {
    val clipboard = LocalClipboardManager.current
    val context = LocalContext.current
    MenuRow("复制", { clipboard.setText(AnnotatedString(text)) }, icon = TeleplyIcons.Copy)
    MenuRow("选择文字", { sheets.select = message.copy(text = text) }, icon = TeleplyIcons.Text)
    MenuRow("分享", { shareText(context, text) }, icon = TeleplyIcons.Share)
}

private fun shareText(context: Context, text: String) {
    val send = Intent(Intent.ACTION_SEND).setType("text/plain").putExtra(Intent.EXTRA_TEXT, text)
    runCatching { context.startActivity(Intent.createChooser(send, "分享消息").addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) }
}

// ---------------------------------------------------------------------------------------------
// Inline question and approval cards (spec 4.3: all three sources answer in the timeline)

/** What is waiting for an answer, as short prompts for the ask bar; empty when nothing is pending. */
data class PendingCard(val kind: String, val summary: String, val progress: String = "", val count: Int = 1)

fun pendingCards(app: String, raw: JSONObject): List<PendingCard> = when (app) {
    "claude" -> buildList {
        raw.optJSONObject("prompt")?.let { add(PendingCard("choice", it.string("title"), it.string("progress"))) }
        if (raw.rows("actions") { it }.isNotEmpty()) add(PendingCard("actions", "计划与执行选项"))
    }
    "deepseek" -> {
        val approvals = raw.rows("interactions") { it }.filter { it.string("event") == "approval/request" }
        val questions = raw.rows("questions") { it } + raw.rows("interactions") { it }.filter { it.string("event") == "user-questions/request" }.mapNotNull { it.optJSONObject("request") }
        val total = approvals.size + questions.distinctBy { it.string("callId") }.size
        when {
            total == 0 -> emptyList()
            approvals.isNotEmpty() -> listOf(PendingCard("approval", "批准这一步吗？" + approvals.first().optJSONObject("request")?.string("toolName").orEmpty().let { if (it.isBlank()) "" else " · $it" }, count = total))
            else -> listOf(PendingCard("question", questions.first().rows("questions") { it }.firstOrNull()?.string("question").orEmpty().ifBlank { "有问题要回答" }, count = total))
        }
    }
    else -> raw.rows("questions") { it }.filter { it.string("status") == "pending" }.map { card -> PendingCard("question", card.rows("questions") { it }.firstOrNull()?.string("question").orEmpty().ifBlank { "Codex 有问题要问你" }) }
}

@Composable
private fun InlineCards(app: String, raw: JSONObject, saved: JSONObject, vm: ReaderViewModel, ws: WorkspaceState) {
    when (app) {
        "claude" -> ClaudeCards(raw, vm, ws)
        "deepseek" -> DeepSeekCards(raw, saved, vm, ws)
        else -> CodexCards(raw, saved, vm, ws)
    }
}

/** Web .codex-card: 20dp corners, thin edge, light shadow, 15sp text. */
@Composable
fun QuestionCard(modifier: Modifier = Modifier, content: @Composable ColumnScope.() -> Unit) {
    val p = LocalTeleply.current
    Column(
        modifier.fillMaxWidth()
            .softShadow(TeleplyShape.QuestionCard, p, TeleplyShadow.Card)
            .clip(TeleplyShape.QuestionCard)
            .background(p.card)
            .border(1.dp, if (p.dark) p.edge else p.line, TeleplyShape.QuestionCard)
            .animateContentSize()
            .padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp),
        content = content,
    )
}

@Composable
private fun CardTitle(text: String, tag: String? = null) {
    val p = LocalTeleply.current
    Row(verticalAlignment = Alignment.CenterVertically) {
        Text(text, style = MaterialTheme.typography.titleMedium, color = p.text, modifier = Modifier.weight(1f, fill = false).semantics { heading() })
        if (tag != null) {
            Spacer(Modifier.width(8.dp))
            Box(Modifier.clip(RoundedCornerShape(6.dp)).background(p.control).padding(horizontal = 8.dp, vertical = 2.dp)) {
                Text(tag, style = MaterialTheme.typography.labelMedium, color = p.muted, fontFamily = FontFamily.Monospace)
            }
        }
    }
}

@Composable
private fun CardStatus(text: String) {
    Text(text, style = MaterialTheme.typography.note, color = LocalTeleply.current.accent, modifier = Modifier.semantics { liveRegion = LiveRegionMode.Polite })
}

private fun pendingRoute(saved: JSONObject, route: String) = saved.optJSONObject("pending_action")?.takeIf { it.string("route") == route }

@Composable
private fun CodexCards(raw: JSONObject, saved: JSONObject, vm: ReaderViewModel, ws: WorkspaceState) {
    val p = LocalTeleply.current
    val c = vm.workspace
    raw.rows("questions") { it }.forEach { card ->
        val pending = card.string("status") == "pending"
        val editable = card.optBoolean("editable")
        if (!pending && !editable) return@forEach
        var editing by rememberSaveable(card.string("id"), card.string("answer_revision")) { mutableStateOf(false) }
        val questions = card.rows("questions") { it }
        if (!pending && !editing) {
            // Answered: one folded line in place; editable sources offer 修改答案.
            Row(Modifier.fillMaxWidth().clip(RoundedCornerShape(12.dp)).background(p.panel).padding(horizontal = 12.dp, vertical = 8.dp), verticalAlignment = Alignment.CenterVertically) {
                Text("已答 · " + questions.firstOrNull()?.string("question").orEmpty(), style = MaterialTheme.typography.process, color = p.muted, maxLines = 1, overflow = TextOverflow.Ellipsis, modifier = Modifier.weight(1f))
                if (editable) PillButton("修改答案", { editing = true }, style = PillStyle.Text, minHeight = 36.dp)
            }
            return@forEach
        }
        val identity = "answers:${card.string("id")}:${card.string("answer_revision")}"
        val answers = runCatching { JSONObject(saved.string(identity)) }.getOrDefault(JSONObject())
        val sent = pendingRoute(saved, "codex/answer")?.optJSONObject("body")?.string("question_id") == card.string("id")
        QuestionCard {
            CardTitle("Codex 想问你")
            questions.forEach { q ->
                val id = q.getString("id")
                val options = q.rows("options") { it }
                val selected = answers.strings(id)
                Text(q.string("question"), style = MaterialTheme.typography.card, color = p.text, fontWeight = FontWeight.Medium)
                options.forEach { option ->
                    val label = option.string("label")
                    OptionCard(label, option.string("description"), label in selected, enabled = !ws.busy, multiple = q.optBoolean("isMultiple"), description = "选择$label") { checked ->
                        val next = if (q.optBoolean("isMultiple")) (if (checked) selected + label else selected - label) else listOf(label)
                        c.edit(identity, JSONObject(answers.toString()).put(id, JSONArray(next)).toString())
                    }
                }
                TeleplyTextField(
                    selected.filter { answer -> options.none { it.string("label") == answer } }.joinToString("\n"),
                    { text ->
                        val chosen = if (q.optBoolean("isMultiple")) selected.filter { answer -> options.any { it.string("label") == answer } } else emptyList()
                        c.edit(identity, JSONObject(answers.toString()).put(id, JSONArray(chosen + listOf(text).filter { it.isNotBlank() })).toString())
                    },
                    "自由回答",
                    singleLine = false,
                    maxLines = 4,
                    enabled = !ws.busy,
                )
            }
            if (sent && saved.optJSONObject("pending_action")?.string("status") == "done") CardStatus("答案已提交，等 Codex 接着做")
            ws.error?.let { Text(it, style = MaterialTheme.typography.note, color = p.error) }
            PillButton(
                "提交回答",
                {
                    c.action("codex/answer", JSONObject().put("question_id", card.string("id")).put("answer_revision", card.string("answer_revision")).put("answers", answers), card)
                    editing = false
                },
                style = PillStyle.Primary,
                enabled = !ws.busy && questions.isNotEmpty() && questions.all { answers.strings(it.getString("id")).isNotEmpty() },
                modifier = Modifier.fillMaxWidth(),
            )
        }
    }
}

@Composable
private fun ClaudeCards(raw: JSONObject, vm: ReaderViewModel, ws: WorkspaceState) {
    val p = LocalTeleply.current
    val c = vm.workspace
    val busy = ws.busy && pendingRoute(JSONObject(ws.saved), "claude/choose") != null
    raw.optJSONObject("prompt")?.let { prompt ->
        QuestionCard {
            val progress = prompt.string("progress")
            CardTitle(prompt.string("title").ifBlank { "Claude 想问你" } + if (progress.isNotBlank()) "（$progress）" else "")
            prompt.rows("choices") { it }.forEach { choice ->
                val token = choice.string("token")
                // A tap clicks the same choice on the computer straight away (web: 正在电脑上点选…).
                OptionCard(choice.string("label"), choice.string("description"), false, enabled = !ws.busy && token.isNotBlank(), description = "选择${choice.string("label")}") {
                    c.action("claude/choose", JSONObject().put("token", token))
                }
            }
            if (busy) CardStatus("正在电脑上点选…")
            val nav = prompt.rows("nav") { it }
            if (nav.isNotEmpty()) Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                nav.forEach { item -> PillButton(item.string("label").ifBlank { item.string("name") }, { c.action("claude/choose", JSONObject().put("token", item.string("token"))) }, enabled = !ws.busy && item.string("token").isNotBlank(), style = if (item.string("name") == "submit") PillStyle.Primary else PillStyle.Secondary) }
            }
            if (prompt.optBoolean("other")) Text("要自己写答案的话，请在电脑上点「Other」填写。", style = MaterialTheme.typography.note, color = p.muted)
        }
    }
    val actions = raw.rows("actions") { it }
    if (actions.isNotEmpty()) QuestionCard {
        CardTitle("计划与执行选项")
        actions.forEach { action ->
            PillButton(action.string("label").ifBlank { action.string("name") }, { c.action("claude/choose", JSONObject().put("token", action.string("token"))) }, enabled = !ws.busy && action.string("token").isNotBlank(), modifier = Modifier.fillMaxWidth())
        }
    }
}

@Composable
private fun DeepSeekCards(raw: JSONObject, saved: JSONObject, vm: ReaderViewModel, ws: WorkspaceState) {
    val p = LocalTeleply.current
    val c = vm.workspace
    raw.rows("interactions") { it }.filter { it.string("event") == "approval/request" }.forEach { event ->
        val request = event.optJSONObject("request") ?: JSONObject()
        val waiting = pendingRoute(saved, "deepseek/approval")?.let { it.optJSONObject("body")?.string("event_id") == event.string("eventId") && it.string("status") == "unknown" } == true
        QuestionCard {
            CardTitle("批准这一步吗？", request.string("toolName").ifBlank { null })
            val action = request.string("reason").ifBlank { request.string("displayReason") }
            if (request.string("displayReason").isNotBlank() && request.string("displayReason") != action) Text(request.string("displayReason"), style = MaterialTheme.typography.card, color = p.text)
            if (action.isNotBlank()) CodePanel("要做的操作", action, "复制要做的操作")
            if (waiting) CardStatus("处理结果待核对")
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                PillButton("拒绝", { c.action("deepseek/approval", JSONObject().put("event_id", event.string("eventId")).put("choice", "rejected")) }, enabled = !ws.busy, modifier = Modifier.weight(1f))
                PillButton("仅允许本次", { c.action("deepseek/approval", JSONObject().put("event_id", event.string("eventId")).put("choice", "allowed-once")) }, style = PillStyle.Primary, enabled = !ws.busy, modifier = Modifier.weight(1f))
            }
            Text("只放行这一次；以后同样的操作还会再问。", style = MaterialTheme.typography.bodySmall, color = p.muted)
        }
    }
    val events = raw.rows("interactions") { it }.filter { it.string("event") == "user-questions/request" }
    val cards = (raw.rows("questions") { it } + events.mapNotNull { it.optJSONObject("request") }).distinctBy { it.string("callId") }
    cards.forEach { card ->
        val id = "deepseek-answers:${card.string("callId")}"
        val answers = runCatching { JSONObject(saved.string(id)) }.getOrDefault(JSONObject())
        val questions = card.rows("questions") { it }
        val waiting = pendingRoute(saved, "deepseek/answer")?.let { it.optJSONObject("body")?.string("call_id") == card.string("callId") && it.string("status") == "unknown" } == true
        QuestionCard {
            CardTitle("DeepSeek 想问你")
            questions.forEach { q ->
                val qid = q.string("id")
                val chosen = answers.strings(qid)
                Text(q.string("question"), style = MaterialTheme.typography.card, color = p.text, fontWeight = FontWeight.Medium)
                q.rows("options") { it }.forEach { option ->
                    val label = option.string("label")
                    OptionCard(label, option.string("description"), label in chosen, enabled = !ws.busy, multiple = q.optBoolean("multiSelect"), description = "选择$label") { on ->
                        c.edit(id, JSONObject(answers.toString()).put(qid, JSONArray(if (q.optBoolean("multiSelect")) (if (on) chosen + label else chosen - label) else listOf(label))).toString())
                    }
                }
                TeleplyTextField(answers.string("custom:$qid"), { c.edit(id, JSONObject(answers.toString()).put("custom:$qid", it).toString()) }, "补充回答（可不填）", singleLine = false, maxLines = 4, enabled = !ws.busy)
            }
            if (waiting) CardStatus("答案结果待核对")
            PillButton(
                "提交答案",
                {
                    val event = events.find { it.optJSONObject("request")?.string("callId") == card.string("callId") }
                    c.action("deepseek/answer", JSONObject().put("call_id", card.string("callId")).put("event_id", event?.string("eventId")).put("answers", JSONArray(questions.map { q -> JSONObject().put("id", q.string("id")).put("selected", JSONArray(answers.strings(q.string("id")))).put("custom", answers.string("custom:${q.string("id")}")) })))
                },
                style = PillStyle.Primary,
                enabled = !ws.busy && questions.isNotEmpty() && questions.all { answers.strings(it.string("id")).isNotEmpty() || answers.string("custom:${it.string("id")}").isNotBlank() },
                modifier = Modifier.fillMaxWidth(),
            )
        }
    }
}

// ---------------------------------------------------------------------------------------------
// Sheets of the conversation page

@Composable
private fun ChatSheetsHost(s: ReaderState, vm: ReaderViewModel, chat: ComposerState, raw: JSONObject, sheets: ChatSheets) {
    if (sheets.search) SearchSheet(s, vm) { sheets.search = false }
    if (sheets.pending) PendingSheet(chat, vm) { sheets.pending = false }
    if (sheets.prompts) PromptLibrarySheet(vm) { sheets.prompts = false }
    sheets.select?.let { message -> SelectTextSheet(message) { sheets.select = null } }
}

/** 16.9万 for 169,421: from ten thousand on, in 万 with one decimal (spec 0.4 §4.3). */
fun wan(n: Long): String = if (n < 10_000) "$n" else "%.1f".format(Locale.ROOT, n / 10_000.0).removeSuffix(".0") + "万"

/**
 * 会话状态 (spec 0.4 §4.3): a glass panel from the ring. Context first, as one big number with a bar and the token
 * counts; then model and effort as two tiles; then one line saying where the numbers come from and how fresh they
 * are. The same facts as the web sheet, read live while the panel is open.
 */
@Composable
private fun MenuScope.RuntimePanel(vm: ReaderViewModel) {
    val p = LocalTeleply.current
    val s by vm.state.collectAsStateWithLifecycle()
    val chat by vm.composer.state.collectAsStateWithLifecycle()
    val raw = remember(chat.control.raw) { runCatching { JSONObject(chat.control.raw) }.getOrDefault(JSONObject()) }
    val runtime = runtimeOf(s, raw) ?: JSONObject()
    if (runtime.length() == 0) {
        MenuHint("这个会话还没有可显示的状态。")
        return
    }
    val state = runtime.string("context_state")
    val percent = if (state == "available" && runtime.has("percent")) Math.round(runtime.optDouble("percent")).toInt().coerceIn(0, 100) else null
    val ink = if ((percent ?: 0) >= 80) p.amber else p.text
    val used = runtime.optLong("used_tokens")
    val window = runtime.optLong("context_window")
    val counts = if (used > 0 && window > 0) "已用${wan(used)} · 窗口${wan(window)}" else null
    Column(Modifier.fillMaxWidth().padding(start = 18.dp, end = 18.dp, top = 12.dp, bottom = 10.dp)) {
        Column(Modifier.semantics(mergeDescendants = true) {
            contentDescription = (if (percent != null) "上下文已用约 $percent%" else "上下文${contextText(state)}") + (counts?.let { "，" + it.replace(" · ", "，") } ?: "")
        }) {
            Row(verticalAlignment = Alignment.Bottom) {
                if (percent != null) {
                    Text("$percent", style = TextStyle(fontSize = 32.sp, lineHeight = 34.sp, fontWeight = FontWeight.SemiBold), color = ink)
                    Text("%", style = TextStyle(fontSize = 18.sp, lineHeight = 22.sp, fontWeight = FontWeight.SemiBold), color = ink, modifier = Modifier.padding(start = 1.dp, bottom = 3.dp))
                } else {
                    Text(contextText(state), style = TextStyle(fontSize = 20.sp, lineHeight = 26.sp, fontWeight = FontWeight.SemiBold), color = p.muted)
                }
                Text("上下文", style = MaterialTheme.typography.note, color = p.muted, modifier = Modifier.padding(start = 8.dp, bottom = 5.dp))
            }
            if (percent != null) {
                Box(Modifier.padding(top = 10.dp).fillMaxWidth().height(6.dp).clip(CircleShape).background(p.glassTrack)) {
                    Box(Modifier.fillMaxWidth(percent / 100f).fillMaxHeight().clip(CircleShape).background(if (percent >= 80) p.amber else p.accent))
                }
            }
            if (counts != null) Text(counts, style = MaterialTheme.typography.note, color = p.muted, modifier = Modifier.padding(top = 8.dp))
        }
        Row(Modifier.fillMaxWidth().padding(top = 14.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            val effort = runtime.string("effort")
            RuntimeTile("模型", modelLabel(s.app, raw, runtime.string("model")), null, Modifier.weight(1f))
            RuntimeTile("推理强度", if (effort.isBlank()) "暂无" else effortName(effort), effort.takeIf { effortName(it) != it }, Modifier.weight(1f))
        }
        val seconds = maxOf(runtime.optLong("model_time"), runtime.optLong("usage_time"))
        val ago = if (seconds > 0) agoLabel(if (seconds > 10_000_000_000L) seconds else seconds * 1000) else ""
        val fresh = when {
            ago.isBlank() -> null
            ago == "刚刚" -> "刚刚更新"
            ago.endsWith("前") -> "${ago}更新"
            else -> "$ago 更新"
        }
        val footer = listOfNotNull(if (s.app == "claude") "来自电脑上的 Claude" else "来自会话记录", fresh, if (percent != null) "比例是估算值" else null).joinToString(" · ")
        Text(footer, style = MaterialTheme.typography.bodySmall.copy(fontSize = 12.sp), color = p.muted, modifier = Modifier.padding(top = 12.dp))
    }
}

private fun contextText(state: String) = when (state) {
    "waiting" -> "等待更新"
    "partial" -> "数据不全"
    else -> "暂无数据"
}

/** The model's display name: Claude's desktop label, Codex's catalog name, otherwise the id. */
private fun modelLabel(app: String, raw: JSONObject, id: String): String {
    if (app == "claude") raw.string("model_label").takeIf { it.isNotBlank() }?.let { return it }
    val named = raw.optJSONObject("catalog")?.rows("models") { it }?.firstOrNull { it.string("id") == id }?.string("name")
    return named?.ifBlank { null } ?: id.ifBlank { "暂无" }
}

@Composable
private fun RuntimeTile(label: String, value: String, original: String?, modifier: Modifier) {
    val p = LocalTeleply.current
    Column(modifier.clip(RoundedCornerShape(14.dp)).background(p.glassFill).padding(horizontal = 12.dp, vertical = 10.dp).semantics(mergeDescendants = true) { }) {
        Text(label, style = MaterialTheme.typography.bodySmall.copy(fontSize = 12.sp), color = p.muted)
        Row(Modifier.padding(top = 2.dp), verticalAlignment = Alignment.Bottom) {
            Text(value, style = MaterialTheme.typography.titleSmall.copy(fontSize = 15.sp, fontWeight = FontWeight.SemiBold), color = p.text, maxLines = 2, overflow = TextOverflow.Ellipsis, modifier = Modifier.weight(1f, fill = false))
            if (original != null) Text(original, style = MaterialTheme.typography.labelSmall, color = p.muted, maxLines = 1, modifier = Modifier.padding(start = 4.dp, bottom = 1.dp))
        }
    }
}

@Composable
private fun SearchSheet(s: ReaderState, vm: ReaderViewModel, onDismiss: () -> Unit) {
    val p = LocalTeleply.current
    var query by rememberSaveable { mutableStateOf(s.searchQuery) }
    TeleplySheet("查找消息", onDismiss) {
        TeleplyTextField(query, { query = it }, "消息关键词")
        PillButton("查找", { vm.searchHistory(query) }, style = PillStyle.Primary, enabled = !s.busy && query.isNotBlank(), modifier = Modifier.fillMaxWidth())
        if (s.searched) {
            if (s.hits.isEmpty()) Text("没有找到匹配的消息", style = MaterialTheme.typography.note, color = p.muted)
            else CardSection {
                s.hits.forEachIndexed { index, hit ->
                    if (index > 0) CardDivider()
                    CardRow(hit.text, { onDismiss(); vm.jump(hit) }, detail = if (hit.role == "user") "你" else sourceName(s.app))
                }
            }
            if (s.hitMore) PillButton("更多结果", { vm.searchHistory(s.searchQuery, true) }, enabled = !s.busy, style = PillStyle.Text)
        }
    }
}

@Composable
private fun PendingSheet(chat: ComposerState, vm: ReaderViewModel, onDismiss: () -> Unit) {
    val p = LocalTeleply.current
    val rows = chat.submissions.filter { it.label in listOf("提交中", "送达状态待确认", "已接收", "已排队") }
    TeleplySheet("待核对发送记录", onDismiss, trailing = "${rows.size} 条") {
        InfoNote("这些消息的结果还没确认。核对只读取回执，不会重新发送。")
        if (rows.isEmpty()) Text("没有待核对的记录", style = MaterialTheme.typography.note, color = p.muted)
        rows.forEach { record ->
            QuestionCard {
                Text(record.label, style = MaterialTheme.typography.labelLarge, color = if (record.label == "送达状态待确认") p.amber else p.text)
                Text(record.text, style = MaterialTheme.typography.card, color = p.text, maxLines = 4, overflow = TextOverflow.Ellipsis)
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    PillButton("核对状态", { vm.composer.check(record) }, enabled = !chat.submitting)
                    if (record.action == "send") PillButton("恢复提交快照", { vm.composer.restore(record) }, enabled = chat.draft.isBlank() && !chat.submitting, style = PillStyle.Text)
                }
            }
        }
    }
}

/** 选择文字 (web #readerSheet): 17sp reading text the system selection handles can pick from, plus 复制全部. */
@Composable
private fun SelectTextSheet(message: Message, onDismiss: () -> Unit) {
    val clipboard = LocalClipboardManager.current
    TeleplySheet("选择文字", onDismiss) {
        Markdown(message.text, Modifier.fillMaxWidth(), selectable = true, reader = true)
        PillButton("复制全部", { clipboard.setText(AnnotatedString(message.text)); onDismiss() }, style = PillStyle.Primary, modifier = Modifier.fillMaxWidth())
    }
}

private const val PromptKey = "lbr_prompt_library"

private fun loadPrompts(context: Context): List<Pair<String, String>> = runCatching {
    val array = JSONArray(context.getSharedPreferences("teleply_ui", Context.MODE_PRIVATE).getString(PromptKey, "[]"))
    (0 until array.length()).map { array.getJSONObject(it).let { j -> j.string("name") to j.string("text") } }
}.getOrDefault(emptyList())

private fun savePrompts(context: Context, items: List<Pair<String, String>>) {
    val array = JSONArray(items.map { (name, text) -> JSONObject().put("name", name).put("text", text) })
    context.getSharedPreferences("teleply_ui", Context.MODE_PRIVATE).edit().putString(PromptKey, array.toString()).apply()
}

/** 常用提示语 (web prompt library): insert into the draft; add, edit and delete. Kept on this phone only. */
@Composable
private fun PromptLibrarySheet(vm: ReaderViewModel, onDismiss: () -> Unit) {
    val p = LocalTeleply.current
    val context = LocalContext.current
    var items by remember { mutableStateOf(loadPrompts(context)) }
    var editing by remember { mutableStateOf<Int?>(null) }
    var name by remember { mutableStateOf("") }
    var text by remember { mutableStateOf("") }
    var removing by remember { mutableStateOf<Int?>(null) }
    TeleplySheet("常用提示语", onDismiss) {
        if (items.isEmpty() && editing == null) Text("还没有提示语。点下面的按钮加一条，以后可以一点插入草稿。", style = MaterialTheme.typography.note, color = p.muted)
        if (editing == null) {
            items.forEachIndexed { index, (title, body) ->
                QuestionCard {
                    Text(title, style = MaterialTheme.typography.titleSmall, color = p.text)
                    Text(body, style = MaterialTheme.typography.bodyMedium, color = p.muted, maxLines = 3, overflow = TextOverflow.Ellipsis)
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        PillButton("插入", {
                            val current = vm.composer.state.value.draft
                            vm.composer.replaceDraft(if (current.isBlank()) body else current.trimEnd() + "\n" + body)
                            onDismiss()
                        }, style = PillStyle.Primary)
                        PillButton("编辑", { editing = index; name = title; text = body })
                        PillButton("删除", { removing = index }, style = PillStyle.Text)
                    }
                }
            }
            PillButton("添加提示语", { editing = -1; name = ""; text = "" }, leading = TeleplyIcons.Plus, modifier = Modifier.fillMaxWidth())
        } else {
            TeleplyTextField(name, { name = it }, "名称")
            TeleplyTextField(text, { text = it }, "内容", singleLine = false, minLines = 3, maxLines = 8)
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                PillButton("保存", {
                    val index = editing ?: -1
                    items = if (index >= 0) items.toMutableList().also { it[index] = name.trim() to text } else items + (name.trim() to text)
                    savePrompts(context, items)
                    editing = null
                }, style = PillStyle.Primary, enabled = name.isNotBlank() && text.isNotBlank())
                PillButton("取消", { editing = null })
            }
        }
    }
    removing?.let { index ->
        AlertDialog(
            onDismissRequest = { removing = null },
            title = { Text("删除这条提示语？") },
            text = { Text("「${items.getOrNull(index)?.first.orEmpty()}」会从这台手机上删除。") },
            confirmButton = { TextButton(onClick = { items = items.filterIndexed { i, _ -> i != index }; savePrompts(context, items); removing = null }) { Text("删除", color = p.error) } },
            dismissButton = { TextButton(onClick = { removing = null }) { Text("取消") } },
        )
    }
}
