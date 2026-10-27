package com.pocketagentdesk.teleply

import android.net.Uri
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.PickVisualMediaRequest
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.animation.animateContentSize
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.interaction.collectIsFocusedAsState
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.navigationBars
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.layout.windowInsetsPadding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.minimumInteractiveComponentSize
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.Stable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.input.key.Key
import androidx.compose.ui.input.key.KeyEventType
import androidx.compose.ui.input.key.isCtrlPressed
import androidx.compose.ui.input.key.key
import androidx.compose.ui.input.key.onPreviewKeyEvent
import androidx.compose.ui.input.key.type
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.semantics.stateDescription
import androidx.compose.ui.text.TextRange
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.TextFieldValue
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import org.json.JSONObject

private val EffortNames = mapOf("none" to "无", "minimal" to "最低", "low" to "低", "medium" to "中", "high" to "高", "xhigh" to "极高", "max" to "最高", "ultra" to "Ultra")

fun effortName(value: String) = EffortNames[value] ?: value

private fun json(value: String) = runCatching { JSONObject(value) }.getOrDefault(JSONObject())

private fun check(on: Boolean) = if (on) MenuTrailing.Checked else MenuTrailing.None

/**
 * The input area (spec 4.3, top to bottom): question bar, queue tray, pending check, the input card.
 * Since 0.4 it has no background of its own: messages slide under the glass card, and the page's bottom scroll edge
 * keeps it calm. Solid mode keeps the web's opaque .cv-bottom with its soft fade.
 */
@Composable
fun InputArea(s: ReaderState, vm: ReaderViewModel, chat: ComposerState, ws: WorkspaceState, raw: JSONObject, cards: List<PendingCard>, onAsk: () -> Unit) {
    val p = LocalTeleply.current
    val solid = LocalGlassMode.current == GlassMode.Solid
    Column(Modifier.fillMaxWidth()) {
        if (solid) BottomFade()
        Column(
            Modifier.fillMaxWidth().then(if (solid) Modifier.background(p.page) else Modifier)
                .imePadding()
                .windowInsetsPadding(WindowInsets.navigationBars)
                .padding(start = 12.dp, end = 12.dp, bottom = 8.dp),
        ) {
            val saved = remember(ws.saved) { json(ws.saved) }
            // Only the bars above the card animate their height: the animation clips, and would cut the card's shadow.
            Column(Modifier.fillMaxWidth().animateContentSize()) {
                AskBar(s.app, cards, saved, chat, vm, onAsk)
                QueueTray(s.app, chat, raw, vm, ws)
                val last = chat.submissions.firstOrNull { it.label != RemovedLabel }
                if (last != null && last.action == "send" && last.label == "未接收") RejectedBar(last, chat, vm)
                if (last != null && last.label == "送达状态待确认") {
                    Row(Modifier.fillMaxWidth().padding(bottom = 8.dp).clip(TeleplyShape.Tray).background(p.noteBg).padding(start = 14.dp, end = 4.dp), verticalAlignment = Alignment.CenterVertically) {
                        Text("上一条送达状态待确认", style = MaterialTheme.typography.note, color = p.noteText, modifier = Modifier.weight(1f).padding(vertical = 8.dp))
                        PillButton("核对待发送消息", { vm.composer.check(last) }, style = PillStyle.Text, minHeight = 36.dp, enabled = !chat.submitting)
                    }
                }
            }
            ComposerCard(s, vm, chat, ws, raw, saved)
        }
    }
}

/**
 * A message the computer turned away (web: the outbox card's 没发出去 ›): why, and what can be done. Claude's box on the
 * computer holding other text offers to send again replacing exactly that text; 恢复草稿 puts the message back in the
 * box; 移除 takes the record away. Nothing is sent again by itself.
 */
@OptIn(androidx.compose.foundation.layout.ExperimentalLayoutApi::class)
@Composable
private fun RejectedBar(record: Submission, chat: ComposerState, vm: ReaderViewModel) {
    val p = LocalTeleply.current
    val body = remember(record.body) { json(record.body) }
    val draft = body.string(DesktopDraftKey)
    val reason = body.string(SendErrorKey)
    Column(Modifier.fillMaxWidth().padding(bottom = 8.dp).clip(TeleplyShape.Tray).background(p.stopBg).padding(start = 14.dp, end = 6.dp, top = 8.dp, bottom = 4.dp)) {
        Text("上一条没发出去" + if (reason.isNotBlank()) "：$reason" else "", style = MaterialTheme.typography.note, color = p.stopText, maxLines = 3, overflow = TextOverflow.Ellipsis, modifier = Modifier.semantics { liveRegion = LiveRegionMode.Polite })
        androidx.compose.foundation.layout.FlowRow(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(2.dp)) {
            if (draft.isNotBlank()) {
                val shown = if (draft.length > 8) draft.take(8) + "…" else draft
                PillButton("换掉电脑上的「$shown」再发", { vm.composer.resendReplacing(record) }, style = PillStyle.Text, minHeight = 36.dp, enabled = !chat.submitting && chat.control.available, description = "换掉电脑上 Claude 输入框里的「$draft」，再发这条消息")
            }
            if (chat.draft.isBlank()) PillButton("恢复草稿", { vm.composer.restore(record) }, style = PillStyle.Text, minHeight = 36.dp, enabled = !chat.submitting)
            PillButton("移除", { vm.composer.dismiss(record) }, style = PillStyle.Text, minHeight = 36.dp, description = "移除这条没发出去的记录")
        }
    }
}

/**
 * Question bar: orange dot, one line of summary, the web's wording on the right ("去选择 ›" / "去处理 ›").
 * A tap scrolls to the first open card in the timeline. After Codex got an answer: "答案已提交，等 Codex 接着做".
 */
@Composable
private fun AskBar(app: String, cards: List<PendingCard>, saved: JSONObject, chat: ComposerState, vm: ReaderViewModel, onAsk: () -> Unit) {
    val p = LocalTeleply.current
    val first = cards.firstOrNull() ?: return
    val codexSent = app == "codex" && saved.optJSONObject("pending_action")?.let { it.string("route") == "codex/answer" && it.string("status") == "done" } == true
    val (summary, go, action) = when {
        codexSent -> Triple("答案已提交，等 Codex 接着做", "刷新 ›", { vm.composer.refreshControl() })
        app == "deepseek" -> Triple(first.summary + if (first.count > 1) "（共 ${first.count} 项）" else "", "去处理 ›", onAsk)
        app == "claude" -> Triple(first.summary + if (first.progress.isNotBlank()) "（${first.progress}）" else "", "去选择 ›", onAsk)
        else -> Triple(first.summary, "去选择 ›", onAsk)
    }
    Row(
        Modifier.fillMaxWidth().padding(bottom = 8.dp).heightIn(min = 44.dp).clip(TeleplyShape.AskPill)
            .background(p.noteBg)
            .clickable(role = Role.Button, onClick = action)
            .semantics(mergeDescendants = true) { contentDescription = "$summary，$go".removeSuffix(" ›") }
            .padding(horizontal = 14.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Box(Modifier.size(16.dp), contentAlignment = Alignment.Center) {
            Box(Modifier.size(14.dp).clip(CircleShape).background(p.askDot.copy(alpha = 0.22f)))
            Box(Modifier.size(8.dp).clip(CircleShape).background(p.askDot))
        }
        Spacer(Modifier.width(10.dp))
        Text(summary, style = MaterialTheme.typography.note, color = p.noteText, maxLines = 1, overflow = TextOverflow.Ellipsis, modifier = Modifier.weight(1f))
        Text(go, style = MaterialTheme.typography.note.copy(fontWeight = FontWeight.SemiBold), color = p.askGo, modifier = Modifier.padding(start = 8.dp))
    }
}

/** Queued messages right above the input card; each can be handed to the running turn now (立即补充) or withdrawn. */
@Composable
private fun QueueTray(app: String, chat: ComposerState, raw: JSONObject, vm: ReaderViewModel, ws: WorkspaceState) {
    val p = LocalTeleply.current
    val menus = LocalMenuHost.current
    data class Row3(val id: String, val text: String, val token: String)
    val rows = if (app == "claude") raw.rows("queued") { Row3(it.string("id"), it.string("text"), it.string("token")) }
    else chat.control.queued.map { Row3(it.id, it.text, "") }
    if (rows.isEmpty()) return
    Column(Modifier.fillMaxWidth().padding(bottom = 8.dp).clip(TeleplyShape.Tray).background(p.tray).padding(vertical = 4.dp)) {
        rows.forEach { row ->
            val anchor = remember(row.id) { MenuAnchor() }
            Row(Modifier.fillMaxWidth().padding(start = 14.dp, end = 4.dp), verticalAlignment = Alignment.CenterVertically) {
                Icon(TeleplyIcons.Clock, contentDescription = null, tint = p.muted, modifier = Modifier.size(16.dp))
                Spacer(Modifier.width(8.dp))
                Text(row.text, style = MaterialTheme.typography.bodyMedium, color = p.text, maxLines = 2, overflow = TextOverflow.Ellipsis, modifier = Modifier.weight(1f).padding(vertical = 8.dp))
                val running = chat.control.running
                PillButton(
                    "立即补充",
                    { if (app == "claude") vm.workspace.action("claude/choose", JSONObject().put("token", row.token)) else vm.composer.promote(row.id) },
                    style = PillStyle.Text,
                    minHeight = 36.dp,
                    enabled = running && !chat.submitting && !ws.busy && (app != "claude" || row.token.isNotBlank()),
                    description = "立即补充：${row.text}",
                )
                if (app != "claude") TeleplyIconButton(TeleplyIcons.More, "这条排队消息的更多操作", {
                    menus?.show(MenuRequest(anchor.bounds, MenuPlacement.BelowEnd, "排队消息", width = 220.dp) {
                        MenuRow("撤回这条", { vm.composer.cancel(row.id) }, enabled = chat.control.queueAvailable && !chat.submitting, danger = true)
                    })
                }, modifier = Modifier.menuAnchor(anchor), style = IconButtonStyle.Plain, tint = p.muted)
            }
        }
    }
}

/**
 * The status line at the top of the input card (spec 0.4 §4.3): an error, a model switch result, a voice note, why the
 * computer cannot take the next message ([away], with 电脑上打开) or the last receipt (B03). Takes no room when there is
 * nothing to say. A source action whose result is unknown offers 核对.
 */
@Composable
private fun StatusLine(chat: ComposerState, ws: WorkspaceState, saved: JSONObject, local: String, vm: ReaderViewModel, away: String?, pill: VoicePill? = null) {
    val p = LocalTeleply.current
    if (pill != null) {
        // Voice says what it is doing, with the one thing that can be done about it (web .voice-pill).
        Row(Modifier.fillMaxWidth().padding(start = 10.dp, end = 2.dp, top = 2.dp), verticalAlignment = Alignment.CenterVertically) {
            Text(pill.text, style = MaterialTheme.typography.note, color = if (pill.error) p.error else p.muted, maxLines = 2, overflow = TextOverflow.Ellipsis, modifier = Modifier.weight(1f).padding(vertical = 4.dp).semantics { liveRegion = LiveRegionMode.Polite })
            if (pill.action != null && pill.run != null) PillButton(pill.action, pill.run, style = PillStyle.Text, minHeight = 32.dp)
        }
        return
    }
    val receipt = chat.submissions.firstOrNull { it.label != RemovedLabel }?.label?.takeIf { it != "未接收" }
    val unknown = saved.optJSONObject("pending_action")?.string("status") == "unknown"
    val (text, color) = when {
        chat.error != null -> chat.error to p.error
        ws.error != null && ws.pane == null -> ws.error to p.error
        local.isNotBlank() -> local to p.muted
        ws.result.isNotBlank() && ws.pane == null -> ws.result to p.muted
        unknown -> "上次操作的结果还没确认" to p.muted
        // The computer's words on why the next message cannot go, in place of an old receipt (10-27).
        away != null -> away to p.muted
        receipt != null && receipt != "送达状态待确认" -> receipt to p.muted
        else -> null to p.muted
    }
    if (text == null && !unknown) return
    val opens = !unknown && away != null && text == away
    Row(Modifier.fillMaxWidth().padding(start = 10.dp, end = 2.dp, top = 2.dp), verticalAlignment = Alignment.CenterVertically) {
        Text(
            text.orEmpty(),
            style = MaterialTheme.typography.note,
            color = color,
            // The computer's reason whole: it says what to do.
            maxLines = if (opens) 3 else 2,
            overflow = TextOverflow.Ellipsis,
            modifier = Modifier.weight(1f).padding(vertical = 4.dp).semantics { liveRegion = LiveRegionMode.Polite },
        )
        if (unknown) PillButton("核对上次操作", vm.workspace::checkAction, style = PillStyle.Text, minHeight = 32.dp, enabled = !ws.busy)
        else if (opens) PillButton("电脑上打开", vm.workspace::openOnComputer, style = PillStyle.Text, minHeight = 32.dp, enabled = !ws.busy)
    }
}

/**
 * The input card (spec 0.4 §4.3): glass, 26dp corners, no coloured edge. Status line on top, attachments, the text,
 * then ＋, the model and mode chips, voice and send. Solid mode is the web card: white (dark #1E1E1E with a #767676
 * edge), its shadow deepening on focus.
 */
@Composable
private fun ComposerCard(s: ReaderState, vm: ReaderViewModel, chat: ComposerState, ws: WorkspaceState, raw: JSONObject, saved: JSONObject) {
    val p = LocalTeleply.current
    val controller = vm.composer
    val menus = LocalMenuHost.current
    val plus = remember { MenuAnchor() }
    val modelAnchor = remember { MenuAnchor() }
    val modeAnchor = remember { MenuAnchor() }
    var note by remember(chat.key) { mutableStateOf("") }
    var confirm by remember { mutableStateOf<JSONObject?>(null) }
    val pickers = rememberAttachPickers(vm) { note = it }
    val voice = rememberPcVoice(vm)
    voice.pill?.let { pill -> LaunchedEffect(pill.serial) { if (pill.hideAfter > 0) { kotlinx.coroutines.delay(pill.hideAfter); if (voice.pill?.serial == pill.serial) voice.pill = null } } }
    val hasExtras = saved.rows("uploads") { it }.isNotEmpty() || saved.rows("references") { it }.isNotEmpty()
    val newPage = isNewPage(s.chat)
    // TextFieldValue keeps IME composition and selection across state emissions.
    var input by remember(chat.key) { mutableStateOf(TextFieldValue(chat.draft)) }
    LaunchedEffect(chat.key, chat.draftReset) {
        // An IME key may arrive after composition schedules this effect: read the controller's current value.
        val current = controller.state.value
        if (current.key == chat.key && input.text != current.draft) input = TextFieldValue(current.draft, TextRange(current.draft.length))
    }
    val focus = remember { MutableInteractionSource() }
    val focused by focus.collectIsFocusedAsState()
    // 继续修改 on a Codex plan puts the cursor here, with the hint in the empty box.
    val requester = remember { androidx.compose.ui.focus.FocusRequester() }
    val keyboard = androidx.compose.ui.platform.LocalSoftwareKeyboardController.current
    LaunchedEffect(chat.focus) { if (chat.focus > 0) runCatching { requester.requestFocus(); keyboard?.show() } }
    val lift by animateFloatAsState(if (focused) 1f else 0f, label = "composer-focus")
    val queue = chat.control.running && chat.control.queueAvailable
    // Claude's message goes while the computer shows another conversation: the computer opens it (web sendConv).
    val reachable = chat.control.available || sendsWhileAway(s.app)
    val canSend = chat.ready && reachable && !chat.submitting && input.composition == null && (chat.draft.isNotBlank() || hasExtras) && chat.draft.trim().length <= 20000
    val send = { if (canSend) controller.send(queue) }
    val narrow = LocalConfiguration.current.screenWidthDp < 370
    val shape = TeleplyShape.Composer
    val surface = if (LocalGlassMode.current == GlassMode.Solid) {
        Modifier.softShadow(shape, p, TeleplyShadow.ComposerNear, TeleplyShadow.composerFar(lift))
            .clip(shape)
            .background(p.card)
            .then(if (p.dark) Modifier.border(1.dp, p.edge, shape) else Modifier)
    } else {
        Modifier.glass(shape, GlassSize.Card).clip(shape)
    }
    val maxField = (LocalConfiguration.current.screenHeightDp * 0.3f).dp
    Column(Modifier.fillMaxWidth().then(surface).padding(start = 6.dp, end = 6.dp, top = 6.dp, bottom = 4.dp)) {
        StatusLine(chat, ws, saved, note, vm, awayReason(s.app, raw), voice.pill)
        if (!voice.active) Attachments(saved, vm)
        // While recording, the card shows what is heard in place of the text box (web: the box becomes the recorder).
        if (voice.active) VoiceLive(voice, Modifier.padding(horizontal = 10.dp, vertical = 8.dp))
        else Box(Modifier.fillMaxWidth().padding(horizontal = 10.dp, vertical = 8.dp)) {
            if (input.text.isEmpty()) Text(if (newPage) "可以先写下一条，创建完成后发送" else chat.hint.ifBlank { "输入消息…" }, style = MaterialTheme.typography.bodyLarge, color = p.muted)
            BasicTextField(
                input,
                { input = it; controller.edit(it.text) },
                Modifier.fillMaxWidth().heightIn(min = 24.dp, max = maxField).testTag("composer").focusRequester(requester)
                    .semantics { contentDescription = "输入消息" }
                    .onPreviewKeyEvent { event ->
                        if (event.type == KeyEventType.KeyDown && event.key == Key.Enter && event.isCtrlPressed) { send(); true } else false
                    },
                enabled = chat.ready,
                textStyle = MaterialTheme.typography.bodyLarge.copy(color = p.text),
                cursorBrush = SolidColor(p.accent),
                keyboardOptions = KeyboardOptions(imeAction = ImeAction.Default),
                interactionSource = focus,
            )
        }
        Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
            if (voice.active) VoiceBar(voice, Modifier.weight(1f))
            // A new conversation's page (0.8, web): words only, sent once the conversation exists; no files or chips yet.
            else if (newPage) Spacer(Modifier.weight(1f))
            else {
            TeleplyIconButton(TeleplyIcons.Plus, "添加附件或引用", {
                menus?.show(MenuRequest(plus.bounds, MenuPlacement.BelowStart, "添加附件或引用", width = 240.dp) { AttachMenu(s.app, ws.ready, pickers, vm) })
            }, modifier = Modifier.menuAnchor(plus), style = IconButtonStyle.Plain, tint = p.muted, enabled = ws.ready)
            Row(Modifier.weight(1f).horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(4.dp), verticalAlignment = Alignment.CenterVertically) {
                if (chipAway(s.app, raw)) {
                    // Not open on the computer: the chip opens it there, as its menus would act on another conversation
                    // (web codex-ui.js, claude-ui.js "away"); the mode chip waits until then.
                    ComposerChip("电脑上打开", vm.workspace::openOnComputer, narrow, description = "电脑上打开这个对话", away = true, enabled = !ws.busy)
                } else {
                    val (model, mode, plan) = chipLabels(s.app, raw, saved)
                    val modeName = if (s.app == "deepseek") "权限" else "模式"
                    ComposerChip(model, {
                        menus?.show(MenuRequest(modelAnchor.bounds, MenuPlacement.BelowStart, "模型", width = 300.dp, scrolls = false, maxHeight = 480.dp) { ModelMenu(vm) })
                    }, narrow, description = "模型：$model", modifier = Modifier.menuAnchor(modelAnchor))
                    ComposerChip(mode, {
                        menus?.show(MenuRequest(modeAnchor.bounds, MenuPlacement.BelowStart, modeName, width = 280.dp) { ModeMenu(vm) { confirm = it } })
                    }, narrow, selected = plan, description = "$modeName：$mode", modifier = Modifier.menuAnchor(modeAnchor))
                }
            }
            }
            MicButton(vm, voice, s, { input.selection.min to input.selection.max }) { note = it }
            if (!voice.active) SendButton(if (queue) "发送并排队" else "发送", canSend, chat.submitting, send)
        }
    }
    confirm?.let { option ->
        AlertDialog(
            onDismissRequest = { confirm = null },
            title = { Text("确认改成「${option.string("name")}」？") },
            text = { Text(option.string("description")) },
            confirmButton = {
                TextButton(onClick = {
                    confirm = null
                    vm.workspace.action("deepseek/permission", JSONObject().put("preset", option.string("value")).put("confirmed", true))
                }) { Text("确认选择此权限") }
            },
            dismissButton = { TextButton(onClick = { confirm = null }) { Text("取消") } },
        )
    }
}

/**
 * Model and mode chips (web .composer-chip): transparent capsule, 12sp/500 (11sp under 370dp), a small arrow. An [away]
 * chip (电脑上打开, web .is-away) takes the accent colour and no arrow: it opens no menu.
 */
@Composable
private fun ComposerChip(text: String, onClick: () -> Unit, narrow: Boolean, selected: Boolean = false, description: String, modifier: Modifier = Modifier, away: Boolean = false, enabled: Boolean = true) {
    val p = LocalTeleply.current
    val tint = (if (selected) p.onSelected else if (away) p.accent else p.muted).copy(alpha = if (enabled) 1f else 0.45f)
    Row(
        modifier.minimumInteractiveComponentSize().heightIn(min = 32.dp).widthIn(max = 150.dp).clip(CircleShape)
            .background(if (selected) p.selected else Color.Transparent)
            .clickable(enabled = enabled, role = Role.Button, onClick = onClick)
            .semantics(mergeDescendants = true) { contentDescription = description; if (selected) stateDescription = "计划模式" }
            .padding(horizontal = 10.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(text, style = MaterialTheme.typography.labelMedium.copy(fontSize = if (narrow) 11.sp else 12.sp), color = tint, maxLines = 1, overflow = TextOverflow.Ellipsis, modifier = Modifier.weight(1f, fill = false))
        if (!away) Icon(TeleplyIcons.ChevronDown, contentDescription = null, tint = tint, modifier = Modifier.padding(start = 2.dp).size(12.dp))
    }
}

/** Claude's recorded modes by the names its desktop gives them (web claude-ui.js modeShown). */
private val ClaudeModes = mapOf("auto" to "Auto", "default" to "Manual", "acceptEdits" to "Accept edits")

/**
 * What the chips say, per source (spec 4.3): Codex model·effort and 普通执行/计划; DeepSeek model and permission.
 * Claude as the web paints it (claude-ui.js paint): the desktop's model label, else the name kept for the recorded
 * model, else its id; the recorded effort, else the desktop's; the desktop's mode, else the recorded one. So a
 * conversation the computer is not showing reads "Opus 5.5 · 高" and "Auto", not its bare id and 默认 (10-27).
 */
fun chipLabels(app: String, raw: JSONObject, saved: JSONObject): Triple<String, String, Boolean> {
    val settings = raw.optJSONObject("settings") ?: JSONObject()
    return when (app) {
        "claude" -> {
            val name = listOf(raw.string("model_label"), raw.string("recorded_label"), settings.string("model")).firstOrNull { it.isNotBlank() }
            val recorded = settings.string("effort")
            val effort = if (recorded.isNotBlank()) effortName(recorded) else raw.string("effort_label")
            val shown = raw.string("mode_label")
            val plan = if (shown.isNotBlank()) shown.startsWith("plan", ignoreCase = true) else settings.string("mode") == "plan"
            val mode = if (plan) "计划模式" else shown.ifBlank { ClaudeModes[settings.string("mode")] ?: "普通执行" }
            Triple(if (name == null) "模型" else "$name · ${effort.ifBlank { "默认" }}", mode, plan)
        }
        "deepseek" -> {
            val model = settings.string("model").ifBlank { "模型" }
            val effort = effortName(settings.string("reasoningEffort"))
            Triple(if (effort.isNotBlank()) "$model · $effort" else model, raw.string("permission_name").ifBlank { "权限" }, false)
        }
        else -> {
            val chosen = saved.optJSONObject("settings") ?: settings
            val id = chosen.string("model")
            val name = raw.optJSONObject("catalog")?.rows("models") { it }?.firstOrNull { it.string("id") == id }?.string("name")?.ifBlank { null } ?: id.ifBlank { "模型" }
            val effort = effortName(chosen.string("effort"))
            val plan = chosen.string("mode") == "plan"
            Triple(if (effort.isNotBlank()) "$name · $effort" else name, if (plan) "计划" else "普通执行", plan)
        }
    }
}

/** The computer read the conversation and it is not the one open there (its state says `available` false). */
private fun notOnComputer(raw: JSONObject) = raw.has("available") && !raw.optBoolean("available")

/**
 * The model chip says 电脑上打开 and opens the conversation there instead of its menu (web codex-ui.js and
 * claude-ui.js "away"): Codex not open on the computer; Claude not shown there with nothing recorded, since a pick in a
 * recorded Claude conversation switches the computer to it by itself.
 */
fun chipAway(app: String, raw: JSONObject): Boolean {
    if (!notOnComputer(raw)) return false
    return when (app) {
        "codex" -> true
        "claude" -> (raw.optJSONObject("settings") ?: JSONObject()).string("model").isBlank()
        else -> false
    }
}

/**
 * Why the next message cannot go now, in the computer's own words, for the status line: otherwise the send button
 * stays grey with no word on why (10-27). Claude's messages go all the same (the computer opens the conversation
 * itself, as on the web), so only its away chip says why there.
 */
fun awayReason(app: String, raw: JSONObject): String? {
    if (!notOnComputer(raw) || app == "claude" && !chipAway(app, raw)) return null
    return raw.string("reason").ifBlank { if (app == "deepseek") null else "电脑上没有打开这个对话；点「电脑上打开」后再发" }
}

/**
 * Whether a message can go while the computer shows another conversation: Claude's can (web sendConv; the computer
 * opens it, Windows 0.27.0-dev.19 and later), the others' cannot.
 */
fun sendsWhileAway(app: String) = app == "claude"

/**
 * Claude's effort choices in the model menu. The desktop shows them as named levels (Low, Medium, High…) or as one
 * slider: its steps are listed, at most 20, by the names the computer learnt for them, else the current one's label or
 * 第 N 档 (web renderCatalog). A slider without a step above 0 lists none: on the iPhone a list of named levels taken for
 * a slider with a step of 0 made the app quit (0.5.0, 10-27). [steps] are (value, label); [slider] is the effort a
 * picked step is set on, null for named levels.
 */
internal class ClaudeEfforts(val steps: List<Pair<String, String>>, val selected: String?, val slider: JSONObject?)

internal fun claudeEfforts(efforts: List<JSONObject>): ClaudeEfforts {
    val slider = efforts.singleOrNull()?.takeIf { it.optJSONObject("range") != null }
        ?: return ClaudeEfforts(efforts.map { it.string("name") }.filter { it.isNotBlank() }.map { it to it }, efforts.find { it.optBoolean("selected") }?.string("name"), null)
    val range = slider.getJSONObject("range")
    val min = range.optDouble("min", 0.0)
    val max = range.optDouble("max", Double.NaN)
    val step = range.optDouble("step", 0.0)
    // A borrowed list has no current step (value null).
    val value = (range.opt("value") as? Number)?.toDouble()
    val values = if (step > 0 && step.isFinite() && min.isFinite()) (0 until 20).map { min + it * step }.filter { it <= max } else emptyList()
    val steps = values.mapIndexed { i, v ->
        val learnt = range.optJSONObject("labels")?.string(v.toInt().toString()).orEmpty()
        v.toString() to learnt.ifBlank { range.string("label").takeIf { v == value && it.isNotBlank() } ?: "第 ${i + 1} 档" }
    }
    return ClaudeEfforts(steps, value?.toString(), slider)
}

// ---------------------------------------------------------------------------------------------
// The chips' menus (spec 0.4 §4.3): opened from the chip, a tap applies and closes.

/** A DeepSeek model with the provider group it belongs to. */
private class Pick(val provider: String, val group: String, val model: JSONObject)

/**
 * The model list scrolls inside the menu; the effort row under it always stays in view, so a long list never pushes
 * it out of reach.
 */
@Composable
internal fun MenuScope.ChoiceList(efforts: List<Pair<String, String>>, effort: String?, enabled: Boolean, onEffort: (String) -> Unit, footer: @Composable () -> Unit = {}, rows: @Composable () -> Unit) {
    Column(Modifier.fillMaxWidth()) {
        Column(Modifier.weight(1f, fill = false).verticalScroll(rememberScrollState())) { rows() }
        if (efforts.isNotEmpty()) {
            MenuDivider()
            MenuCaption("推理强度")
            MenuSegments(efforts, effort, enabled, onEffort)
        }
        footer()
    }
}

/**
 * The model chip's menu: models with a check on the current one, then the current model's effort steps.
 * Codex binds the choice to the next message; Claude and DeepSeek switch on the computer, and the status line shows
 * the result. Claude's and DeepSeek's lists show at once as last read and are checked behind (0.8, web): the computer
 * answers from the list it keeps, and only 刷新 has it open Claude's menus again.
 */
@Composable
private fun MenuScope.ModelMenu(vm: ReaderViewModel) {
    val chat by vm.composer.state.collectAsStateWithLifecycle()
    val ws by vm.workspace.state.collectAsStateWithLifecycle()
    val app = ws.key?.app ?: return
    val c = vm.workspace
    val raw = remember(chat.control.raw) { json(chat.control.raw) }
    val saved = remember(ws.saved) { json(ws.saved) }
    val choices = remember(ws.choices) { json(ws.choices) }
    val current = raw.optJSONObject("settings") ?: JSONObject()
    LaunchedEffect(app, ws.key) { c.loadChoices(model = current.string("model")) }
    // A menu the computer opened for a pick is closed again with the phone's (web closeMenu).
    DisposableEffect(app, ws.key) { onDispose { if (app == "claude") c.closeClaudeMenu() } }
    val idle = !ws.busy
    when (app) {
        "codex" -> {
            val chosen = saved.optJSONObject("settings") ?: current
            val models = raw.optJSONObject("catalog")?.rows("models") { it }.orEmpty()
            val model = models.find { it.string("id") == chosen.string("model") }
            ChoiceList(model?.strings("efforts").orEmpty().map { it to effortName(it) }, chosen.string("effort"), idle, { e ->
                c.selectSettings(JSONObject(chosen.toString()).put("effort", e), current)
            }) {
                if (models.isEmpty()) MenuHint("电脑没有给出可选的模型")
                models.forEach { m ->
                    val id = m.string("id")
                    val on = id == chosen.string("model")
                    MenuRow(m.string("name").ifBlank { id }, {
                        if (!on) c.selectSettings(JSONObject(chosen.toString()).put("model", id).put("effort", m.string("default_effort")), current)
                    }, trailing = check(on), enabled = idle)
                }
            }
        }
        "claude" -> {
            val catalog = choices.optJSONObject("source_catalog")
            if (catalog == null) {
                // Only a conversation never read before waits here: the computer opens Claude's menus once.
                ws.choicesError?.let { MenuHint(it) } ?: MenuLoading("首次读取电脑上的模型列表…")
                return
            }
            val expected = catalog.string("model_id")
            fun set(kind: String, name: String, value: Any) = c.claudeSetting(kind, name, value, expected)
            val refreshing = choices.optBoolean("refreshing") && ws.choicesBusy
            val footer: @Composable () -> Unit = {
                MenuDivider()
                val time = catalog.optLong("updated_at").takeIf { it > 0 }?.let { java.text.SimpleDateFormat("M月d日 HH:mm", java.util.Locale.CHINA).format(java.util.Date(it)) }
                when {
                    refreshing -> MenuLoading("正在电脑上重新读取…")
                    ws.choicesError != null -> MenuHint(ws.choicesError.orEmpty())
                    catalog.optBoolean("borrowed") -> MenuHint("先用同一模型的列表；这个对话现在的选项点「刷新」核对。")
                    time != null -> MenuHint("列表读于 $time；选了以后应用到这个对话。")
                }
                MenuRow("刷新电脑上的列表", { c.loadChoices(fresh = true, model = current.string("model")) }, detail = "会在电脑上打开 Claude 的模型菜单读一遍", enabled = idle && !refreshing, dismissOnClick = false)
            }
            // Named levels or one slider's steps (claudeEfforts: a slider without a usable step lists none).
            val efforts = claudeEfforts(catalog.rows("effort") { it })
            val slider = efforts.slider
            ChoiceList(efforts.steps, efforts.selected, idle, { v -> if (slider != null) set("effort", slider.string("name"), v.toDouble()) else set("effort", v, true) }, footer) {
                catalog.rows("model") { it }.forEach { m ->
                    val on = m.optBoolean("selected")
                    MenuRow(m.string("name"), { if (!on) set("model", m.string("name"), true) }, trailing = check(on), enabled = idle)
                }
                catalog.rows("fast") { it }.forEach { f ->
                    val on = f.optBoolean("selected")
                    MenuRow(f.string("name"), { set("fast", f.string("name"), !on) }, trailing = check(on), enabled = idle)
                }
            }
        }
        else -> {
            val catalog = choices.optJSONObject("source_catalog")
            if (catalog == null) {
                ws.choicesError?.let { MenuHint(it) } ?: MenuLoading("正在读取电脑上的模型…")
                return
            }
            val groups = catalog.rows("groups") { it }
            val picks = groups.flatMap { g -> g.rows("models") { Pick(g.string("id"), g.string("name"), it) } }
            val selected = picks.find { it.model.string("id") == current.string("model") }
            fun efforts(m: JSONObject) = m.optJSONObject("reasoning")?.rows("efforts") { it }.orEmpty()
            fun choose(pick: Pick, effort: String?) = c.action("deepseek/model", JSONObject().put("settings", JSONObject().put("provider", pick.provider).put("model", pick.model.string("id")).apply { if (!effort.isNullOrBlank()) put("reasoningEffort", effort) }))
            val steps = selected?.let { pick -> efforts(pick.model).map { it.string("id") to it.string("name").ifBlank { it.string("id") } } }.orEmpty()
            ChoiceList(steps, current.string("reasoningEffort"), idle, { e -> selected?.let { choose(it, e) } }) {
                var group = ""
                picks.forEach { pick ->
                    if (groups.size > 1 && pick.group != group) { group = pick.group; MenuCaption(group) }
                    val on = pick === selected
                    MenuRow(pick.model.string("name").ifBlank { pick.model.string("id") }, {
                        // Keeps the current effort when the new model has it; otherwise the computer picks its default.
                        if (!on) choose(pick, current.string("reasoningEffort").takeIf { e -> efforts(pick.model).any { it.string("id") == e } })
                    }, trailing = check(on), enabled = idle)
                }
            }
        }
    }
}

/** The mode chip's menu: Codex 普通执行／计划, Claude the desktop's modes, DeepSeek the permissions (some confirm first). */
@Composable
private fun MenuScope.ModeMenu(vm: ReaderViewModel, onConfirm: (JSONObject) -> Unit) {
    val chat by vm.composer.state.collectAsStateWithLifecycle()
    val ws by vm.workspace.state.collectAsStateWithLifecycle()
    val app = ws.key?.app ?: return
    val c = vm.workspace
    val raw = remember(chat.control.raw) { json(chat.control.raw) }
    val saved = remember(ws.saved) { json(ws.saved) }
    val idle = !ws.busy
    val current = raw.optJSONObject("settings") ?: JSONObject()
    when (app) {
        "codex" -> {
            val chosen = saved.optJSONObject("settings") ?: current
            val mode = chosen.string("mode").ifBlank { "default" }
            listOf(Triple("default", "普通执行", null), Triple("plan", "计划", "先出计划，你确认后再执行")).forEach { (value, label, detail) ->
                MenuRow(label, { if (mode != value) c.selectSettings(JSONObject(chosen.toString()).put("mode", value), current) }, detail = detail, trailing = check(mode == value), enabled = idle)
            }
        }
        "claude" -> {
            val options = raw.rows("mode_options") { it }
            if (options.isEmpty()) MenuHint("电脑没有给出可选的模式")
            options.forEach { option ->
                val on = current.string("mode") == option.string("name")
                MenuRow(option.string("label").ifBlank { option.string("name") }, {
                    if (!on) c.claudeSetting("mode", option.string("name"))
                }, trailing = check(on), enabled = idle)
            }
        }
        else -> {
            LaunchedEffect(ws.key) { c.loadChoices() }
            val permissions = remember(ws.choices) { json(ws.choices).optJSONObject("permissions") }
            if (permissions == null) {
                ws.choicesError?.let { MenuHint(it) } ?: MenuLoading("正在读取电脑上的权限…")
                return
            }
            permissions.rows("options") { it }.forEach { option ->
                val on = raw.string("permission") == option.string("value")
                MenuRow(option.string("name"), {
                    if (!on) {
                        if (option.optBoolean("confirm")) onConfirm(option)
                        else c.action("deepseek/permission", JSONObject().put("preset", option.string("value")).put("confirmed", false))
                    }
                }, detail = option.string("description").ifBlank { null }, trailing = check(on), enabled = idle)
            }
        }
    }
}

// ---------------------------------------------------------------------------------------------
// Attachments: the ＋ menu of both composers, and the tiles inside the card.

/** The phone's pickers for ＋, remembered by the composer so a result still arrives after the menu closed. */
@Stable
class AttachPickers internal constructor(private val start: () -> Unit, private val photoPicker: () -> Unit, private val filePicker: () -> Unit, private val cameraApp: () -> Unit) {
    fun photo() { start(); photoPicker() }
    fun file() { start(); filePicker() }
    fun camera() { start(); cameraApp() }
}

@Composable
fun rememberAttachPickers(vm: ReaderViewModel, onNote: (String) -> Unit): AttachPickers {
    val context = LocalContext.current
    var pickerKey by remember { mutableStateOf<ChatKey?>(null) }
    var shot by rememberSaveable { mutableStateOf<Uri?>(null) }
    val photo = rememberLauncherForActivityResult(ActivityResultContracts.PickVisualMedia()) { uri -> if (uri != null && vm.workspace.state.value.key == pickerKey) vm.workspace.importUri(context, uri, true) }
    val document = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { uri -> if (uri != null && vm.workspace.state.value.key == pickerKey) vm.workspace.importUri(context, uri, false) }
    val camera = rememberLauncherForActivityResult(ActivityResultContracts.TakePicture()) { ok ->
        val uri = shot
        shot = null
        if (ok && uri != null && vm.workspace.state.value.key == pickerKey) vm.workspace.importUri(context, uri, true)
    }
    return remember(vm, photo, document, camera) {
        AttachPickers(
            { pickerKey = vm.workspace.state.value.key },
            { photo.launch(PickVisualMediaRequest(ActivityResultContracts.PickVisualMedia.ImageOnly)) },
            { document.launch(arrayOf("*/*")) },
            {
                runCatching { PlatformFiles.captureUri(context).also { shot = it; camera.launch(it) } }
                    .onFailure { shot = null; onNote("这台手机没有可用的相机") }
            },
        )
    }
}

/** ＋ (web newAddMenu, spec 4.3 and 4.4): the camera, the phone's photos and files, the computer's files, references. */
@Composable
fun MenuScope.AttachMenu(app: String, ready: Boolean, pickers: AttachPickers, vm: ReaderViewModel) {
    MenuRow("拍照", pickers::camera, icon = TeleplyIcons.Camera, enabled = ready)
    MenuRow("手机照片", pickers::photo, icon = TeleplyIcons.Image, enabled = ready)
    MenuRow("手机文件", pickers::file, icon = TeleplyIcons.File, enabled = ready)
    MenuRow("从电脑选择文件", { vm.workspace.panel("remote") }, icon = TeleplyIcons.Window, enabled = ready)
    MenuRow("引用对话", { vm.workspace.panel("chat") }, icon = TeleplyIcons.Chat, enabled = ready)
    if (app != "deepseek") MenuRow("引用技能", { vm.workspace.panel("skill") }, icon = TeleplyIcons.Skill, enabled = ready)
}

/** Attachment and reference tiles inside the card; each removable, failures say why (spec 8.2). */
@Composable
fun Attachments(saved: JSONObject, vm: ReaderViewModel) {
    val uploads = saved.rows("uploads") { it }
    val refs = saved.rows("references") { it }
    if (uploads.isEmpty() && refs.isEmpty()) return
    Row(Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()).padding(start = 6.dp, end = 6.dp, top = 4.dp), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
        uploads.forEach { row ->
            val status = when (row.string("status")) { "ready" -> null; "uploading", "checking" -> "上传中"; else -> "上传失败" }
            Tile(if (row.optBoolean("image")) TeleplyIcons.Image else TeleplyIcons.File, row.string("name"), status, status == "上传失败", "移除附件 ${row.string("name")}") { vm.workspace.removeUpload(row.string("local")) }
        }
        refs.forEach { ref ->
            val name = ref.string("name").ifBlank { ref.string("title") }
            Tile(if (ref.string("kind") == "skill") TeleplyIcons.Skill else if (ref.string("kind") == "chat") TeleplyIcons.Chat else TeleplyIcons.Folder, name, null, false, "移除引用 $name") { vm.workspace.removeReference(ref.string("id")) }
        }
    }
}

@Composable
private fun Tile(icon: androidx.compose.ui.graphics.vector.ImageVector, name: String, status: String?, failed: Boolean, removeLabel: String, onRemove: () -> Unit) {
    val p = LocalTeleply.current
    Row(Modifier.widthIn(max = 200.dp).clip(TeleplyShape.Thumb).background(if (failed) p.stopBg else p.panel).padding(start = 10.dp), verticalAlignment = Alignment.CenterVertically) {
        Icon(icon, contentDescription = null, tint = if (failed) p.error else p.muted, modifier = Modifier.size(16.dp))
        Column(Modifier.weight(1f, fill = false).padding(start = 6.dp, top = 6.dp, bottom = 6.dp)) {
            Text(name, style = MaterialTheme.typography.bodySmall, color = p.text, maxLines = 1, overflow = TextOverflow.Ellipsis)
            if (status != null) Text(status, style = MaterialTheme.typography.labelSmall, color = if (failed) p.error else p.muted)
        }
        TeleplyIconButton(TeleplyIcons.Close, removeLabel, onRemove, style = IconButtonStyle.Plain, tint = p.muted)
    }
}

/**
 * 40dp accent circle, 48dp target, bottom right; shrinks to 0.88 when pressed. [label] is what TalkBack reads:
 * "发送并排队" while running (B05), "创建并发送" in a new conversation.
 */
@Composable
fun SendButton(label: String, enabled: Boolean, submitting: Boolean, onClick: () -> Unit) {
    val p = LocalTeleply.current
    val interaction = remember { MutableInteractionSource() }
    Box(
        Modifier.minimumInteractiveComponentSize().size(40.dp)
            .pressScale(interaction, 0.88f)
            .clip(CircleShape)
            .background(if (enabled) p.accent else p.control)
            .clickable(interaction, indication = null, enabled = enabled, role = Role.Button, onClick = onClick)
            .semantics { contentDescription = label; if (submitting) stateDescription = "提交中" },
        contentAlignment = Alignment.Center,
    ) {
        Icon(TeleplyIcons.Send, contentDescription = null, tint = if (enabled) p.onAccent else p.muted, modifier = Modifier.size(20.dp).graphicsLayer { alpha = if (submitting) 0.5f else 1f })
    }
}
