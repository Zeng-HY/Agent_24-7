package com.pocketagentdesk.teleply

import androidx.compose.animation.animateContentSize
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.PathEffect
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.semantics.stateDescription
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import org.json.JSONObject

/*
 * Cards of the timeline that are not plain messages, as the web draws them (remote.html renderPlan, renderNext,
 * renderTask, renderSubagent; codex-ui.js renderCard plan): Claude's checklist, its next-step box and proposed tasks,
 * a DeepSeek subagent, and a plan Codex made in plan mode. Content layer: opaque, like the question cards.
 */

private fun details(message: Message) = runCatching { JSONObject(message.details) }.getOrDefault(JSONObject())

/** The web's .plan-card / .next-card / .task-card: 16dp corners, a thin edge, the card colour. */
@Composable
private fun TimelineCard(modifier: Modifier = Modifier, content: @Composable ColumnScope.() -> Unit) {
    val p = LocalTeleply.current
    val shape = RoundedCornerShape(16.dp)
    Column(
        modifier.fillMaxWidth().padding(top = 16.dp).clip(shape).background(p.card).border(1.dp, if (p.dark) p.edge else p.line, shape)
            .animateContentSize().padding(horizontal = 16.dp, vertical = 14.dp),
        content = content,
    )
}

/** Claude's checklist (update_plan / TodoWrite): 进度 done / all, a ring per step, filled for the one under way, ticked when done. */
@Composable
fun ChecklistCard(message: Message) {
    val p = LocalTeleply.current
    val items = details(message).rows("items") { it }
    if (items.isEmpty()) return
    val done = items.count { it.string("status") == "completed" }
    TimelineCard(Modifier.semantics(mergeDescendants = true) { contentDescription = "计划进度 $done / ${items.size}：" + items.joinToString("；") { it.string("text") + "，" + stepState(it.string("status")) } }) {
        Text("进度 $done / ${items.size}", style = MaterialTheme.typography.bodySmall.copy(fontSize = 12.sp), color = p.muted, modifier = Modifier.padding(bottom = 4.dp))
        items.forEach { item ->
            val status = item.string("status")
            Row(Modifier.fillMaxWidth().padding(vertical = 5.dp), verticalAlignment = Alignment.Top) {
                StepMark(status, Modifier.padding(top = 3.dp))
                Spacer(Modifier.width(10.dp))
                Text(
                    item.string("text"),
                    style = MaterialTheme.typography.bodyMedium.copy(fontSize = 14.sp, lineHeight = 21.sp, fontWeight = if (status == "in_progress") FontWeight.SemiBold else FontWeight.Normal),
                    color = if (status == "completed") p.muted else p.text,
                )
            }
        }
    }
}

private fun stepState(status: String) = when (status) { "completed" -> "已完成"; "in_progress" -> "进行中"; else -> "待做" }

/** 16dp: a dashed ring to do, a ring with a dot under way, a green disc with a tick done (web .plan-mark). */
@Composable
private fun StepMark(status: String, modifier: Modifier = Modifier) {
    val p = LocalTeleply.current
    val todo = if (p.dark) p.edge else Color(0xFFB4BCCB)
    Canvas(modifier.size(16.dp)) {
        val r = size.minDimension / 2
        when (status) {
            "completed" -> {
                drawCircle(p.success, r)
                val w = 1.8.dp.toPx()
                val path = androidx.compose.ui.graphics.Path().apply {
                    moveTo(size.width * 0.30f, size.height * 0.52f)
                    lineTo(size.width * 0.45f, size.height * 0.67f)
                    lineTo(size.width * 0.72f, size.height * 0.36f)
                }
                drawPath(path, Color.White, style = Stroke(w, cap = androidx.compose.ui.graphics.StrokeCap.Round, join = androidx.compose.ui.graphics.StrokeJoin.Round))
            }
            "in_progress" -> {
                drawCircle(p.accent, r - 0.75.dp.toPx(), style = Stroke(1.5.dp.toPx()))
                drawCircle(p.accent, r - 3.dp.toPx())
            }
            else -> drawCircle(todo, r - 0.75.dp.toPx(), style = Stroke(1.5.dp.toPx(), pathEffect = PathEffect.dashPathEffect(floatArrayOf(2.5.dp.toPx(), 2.dp.toPx()))))
        }
    }
}

/**
 * Claude's next-step box (its wrap_up, web renderNext): the recap, and while it waits on you its question and buttons,
 * the first the main one. A button presses the same one on the computer; done, the buttons give way to what was done.
 * An answered box keeps its recap only.
 */
@OptIn(ExperimentalLayoutApi::class)
@Composable
fun NextStepCard(message: Message, vm: ReaderViewModel, ws: WorkspaceState) {
    val p = LocalTeleply.current
    val d = details(message)
    val recap = d.string("recap")
    val ask = d.string("ask")
    val toolId = d.string("tool_id")
    if (!d.optBoolean("open")) {
        if (recap.isNotBlank()) Text(recap, style = MaterialTheme.typography.bodyMedium.copy(fontSize = 14.sp, lineHeight = 23.sp), color = p.muted, modifier = Modifier.fillMaxWidth().padding(top = 12.dp))
        return
    }
    val actions = d.rows("actions") { it }
    val status = ws.cards["next:$toolId"]
    TimelineCard {
        if (recap.isNotBlank()) Text(recap, style = MaterialTheme.typography.bodyMedium.copy(fontSize = 14.sp, lineHeight = 23.sp), color = p.muted)
        if (ask.isNotBlank()) Text(ask, style = MaterialTheme.typography.card.copy(fontWeight = FontWeight.SemiBold), color = p.text, modifier = Modifier.padding(top = if (recap.isNotBlank()) 10.dp else 0.dp).semantics { heading() })
        when {
            status?.startsWith("done:") == true -> CardNote(status.removePrefix("done:"), p.accent)
            actions.isNotEmpty() -> {
                FlowRow(Modifier.fillMaxWidth().padding(top = 12.dp), horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    actions.forEachIndexed { index, action ->
                        val label = action.string("label")
                        val pressing = status == "pressing:$label"
                        PillButton(
                            if (pressing) "$label…" else label,
                            { vm.workspace.claudeButton("next:$toolId", "claude/next", JSONObject().put("tool_id", toolId).put("index", index).put("label", label), label) },
                            style = if (index == 0) PillStyle.Primary else PillStyle.Secondary,
                            enabled = !ws.pressing,
                            minHeight = 40.dp,
                            description = "在电脑上点「$label」",
                        )
                    }
                }
                if (status?.startsWith("error:") == true) CardNote(status.removePrefix("error:"), p.error)
            }
        }
    }
}

/**
 * A task Claude proposes in a card of its own (web renderTask): its title and brief (a tap shows all of it); 开始,
 * 在这里做 and 不要了 press the card's buttons on the computer. An offer asks on the computer only. Once the computer
 * shows the conversation without the card, it has been dealt with there and the buttons go.
 */
@OptIn(ExperimentalLayoutApi::class)
@Composable
fun TaskCard(message: Message, raw: JSONObject, vm: ReaderViewModel, ws: WorkspaceState) {
    val p = LocalTeleply.current
    val d = details(message)
    val title = d.string("title")
    val brief = d.string("brief")
    val offer = d.optBoolean("offer")
    var full by rememberSaveable(message.id) { mutableStateOf(false) }
    var dismissing by remember { mutableStateOf(false) }
    val tasks = raw.optJSONArray("tasks")
    val settled = raw.optBoolean("on_screen") && tasks != null && (0 until tasks.length()).none { tasks.optString(it) == title }
    val status = ws.cards["task:$title"]
    TimelineCard {
        Text(if (offer) "Claude 问要不要新开一个对话" else "Claude 提议新开一个任务", style = MaterialTheme.typography.bodySmall.copy(fontSize = 12.sp), color = p.muted, modifier = Modifier.padding(bottom = 6.dp))
        Text(title, style = MaterialTheme.typography.card.copy(fontWeight = FontWeight.SemiBold), color = p.text, modifier = Modifier.semantics { heading() })
        if (brief.isNotBlank()) Text(
            brief,
            style = MaterialTheme.typography.bodySmall.copy(fontSize = 13.sp, lineHeight = 21.sp),
            color = p.muted,
            maxLines = if (full) Int.MAX_VALUE else 3,
            overflow = TextOverflow.Ellipsis,
            modifier = Modifier.padding(top = 6.dp).clip(RoundedCornerShape(6.dp)).clickable(role = Role.Button, onClickLabel = if (full) "收起说明" else "展开说明") { full = !full }
                .semantics { stateDescription = if (full) "已展开" else "已收起" },
        )
        when {
            offer -> CardNote("要在电脑上选「New session」或「Do it here」。", p.muted)
            // What this phone just did there says more than that it was dealt with (开始 adds where the task goes).
            status?.startsWith("done:") == true -> CardNote(status.removePrefix("done:"), p.accent)
            settled -> CardNote("电脑上已经处理过了：开始了、在这里做了，或者关掉了。", p.muted)
            else -> {
                FlowRow(Modifier.fillMaxWidth().padding(top = 12.dp), horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    listOf("start" to "开始", "here" to "在这里做", "dismiss" to "不要了").forEach { (kind, label) ->
                        val pressing = status == "pressing:$label"
                        PillButton(
                            if (pressing) "$label…" else label,
                            { if (kind == "dismiss") dismissing = true else vm.workspace.claudeButton("task:$title", "claude/task", JSONObject().put("title", title).put("button", kind), label) },
                            style = if (kind == "start") PillStyle.Primary else PillStyle.Secondary,
                            enabled = !ws.pressing,
                            minHeight = 40.dp,
                            description = "在电脑上$label：$title",
                        )
                    }
                }
                if (status?.startsWith("error:") == true) CardNote(status.removePrefix("error:"), p.error)
            }
        }
    }
    if (dismissing) AlertDialog(
        onDismissRequest = { dismissing = false },
        title = { Text("不要这个任务了？") },
        text = { Text("电脑上的这张卡片也会关掉，任务不会开始。") },
        confirmButton = { TextButton(onClick = { dismissing = false; vm.workspace.claudeButton("task:$title", "claude/task", JSONObject().put("title", title).put("button", "dismiss"), "不要了") }) { Text("不要了", color = p.error) } },
        dismissButton = { TextButton(onClick = { dismissing = false }) { Text("留着") } },
    )
}

@Composable
private fun CardNote(text: String, color: Color) {
    Text(text, style = MaterialTheme.typography.note, color = color, modifier = Modifier.padding(top = 10.dp).semantics { liveRegion = LiveRegionMode.Polite })
}

/** A subagent this conversation opened (web renderSubagent): where it runs is the computer's; the card only reports. */
@Composable
fun SubagentCard(message: Message) {
    val p = LocalTeleply.current
    val d = details(message)
    val running = d.string("status") == "running"
    val done = d.string("status") == "done"
    val shape = RoundedCornerShape(14.dp)
    val edge = if (running) p.accent.copy(alpha = 0.35f) else if (p.dark) p.edge else p.line
    Row(
        Modifier.fillMaxWidth().padding(top = 12.dp).clip(shape)
            .background(if (running) p.selected else p.panel)
            .drawBehind {
                val w = 1.dp.toPx()
                drawRoundRect(edge, topLeft = androidx.compose.ui.geometry.Offset(w / 2, w / 2), size = androidx.compose.ui.geometry.Size(size.width - w, size.height - w), cornerRadius = CornerRadius(14.dp.toPx()), style = Stroke(w, pathEffect = PathEffect.dashPathEffect(floatArrayOf(4.dp.toPx(), 3.dp.toPx()))))
            }
            .semantics(mergeDescendants = true) { }
            .padding(horizontal = 14.dp, vertical = 10.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Box(Modifier.size(8.dp).clip(CircleShape).background(if (running) p.accent else p.muted))
        Spacer(Modifier.width(8.dp))
        Text("子智能体 · " + d.string("label").ifBlank { d.string("child") }, style = MaterialTheme.typography.bodyMedium.copy(fontSize = 14.sp), color = p.text, modifier = Modifier.weight(1f))
        if (running || done) Text(if (running) "运行中" else "已完成", style = MaterialTheme.typography.bodySmall.copy(fontSize = 12.sp), color = p.muted, modifier = Modifier.padding(start = 8.dp))
    }
}

/** "来自其他对话" above a message forwarded from another conversation (web .message-origin). */
@Composable
fun OriginLabel(message: Message, modifier: Modifier = Modifier) {
    if (details(message).string("origin") != "other_chat") return
    Text("来自其他对话", style = MaterialTheme.typography.bodySmall.copy(fontSize = 12.sp), color = LocalTeleply.current.muted, modifier = modifier.padding(bottom = 4.dp))
}

/** The plan Codex keeps in its state, when it has one with its words. */
fun codexPlan(raw: JSONObject): JSONObject? = raw.optJSONObject("plan")?.takeIf { it.string("id").isNotBlank() && it.string("text").isNotBlank() }

/** Whether [message] is [plan]'s own record (its id, or the record it came from). */
fun codexPlanIs(plan: JSONObject, message: Message): Boolean {
    val id = plan.string("id")
    return message.id == id || "source_id" in message.details && details(message).string("source_id") == id
}

/** The plan Codex keeps in its state, when [message] is the plan's own record. */
fun codexPlanFor(raw: JSONObject, message: Message): JSONObject? = codexPlan(raw)?.takeIf { codexPlanIs(it, message) }

/**
 * A plan Codex made in plan mode (web codex-ui.js renderCard plan): 计划 · 待确认 with a preview; 执行计划 carries it
 * out in normal mode, 继续修改 keeps plan mode and puts the cursor in the box. An older plan folds into 历史计划.
 */
@Composable
fun CodexPlanCard(plan: JSONObject, chat: ComposerState, vm: ReaderViewModel, ws: WorkspaceState) {
    val p = LocalTeleply.current
    val id = plan.string("id")
    if (!plan.optBoolean("ready")) {
        var open by rememberSaveable(id) { mutableStateOf(false) }
        Column(Modifier.fillMaxWidth().padding(top = 16.dp)) {
            Row(
                Modifier.clip(RoundedCornerShape(8.dp)).clickable(role = Role.Button) { open = !open }.semantics { stateDescription = if (open) "已展开" else "已收起" }.heightIn(min = 36.dp).padding(end = 8.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Icon(if (open) TeleplyIcons.ChevronDown else TeleplyIcons.ChevronRight, contentDescription = null, tint = p.muted, modifier = Modifier.size(16.dp))
                Spacer(Modifier.width(6.dp))
                Text("历史计划", style = MaterialTheme.typography.process, color = p.muted)
            }
            if (open) Markdown(plan.string("text"), Modifier.fillMaxWidth().padding(top = 8.dp))
        }
        return
    }
    var full by rememberSaveable(id) { mutableStateOf(false) }
    val busy = chat.submitting
    QuestionCard(Modifier.padding(top = 16.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text("计划", style = MaterialTheme.typography.titleMedium, color = p.text, modifier = Modifier.semantics { heading() })
            Spacer(Modifier.width(8.dp))
            Box(Modifier.clip(RoundedCornerShape(6.dp)).background(p.selected).padding(horizontal = 8.dp, vertical = 2.dp)) {
                Text("待确认", style = MaterialTheme.typography.labelMedium, color = p.onSelected)
            }
        }
        Box(Modifier.fillMaxWidth().heightIn(max = if (full) Dp.Unspecified else 260.dp).clip(RoundedCornerShape(4.dp))) {
            Markdown(plan.string("text"), Modifier.fillMaxWidth())
        }
        PillButton(if (full) "收起计划" else "展开完整计划", { full = !full }, style = PillStyle.Text, minHeight = 36.dp)
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            PillButton("执行计划", { vm.composer.executePlan(id) }, style = PillStyle.Primary, enabled = !busy && chat.control.available && !chat.control.running, modifier = Modifier.weight(1f))
            PillButton("继续修改", {
                val raw = runCatching { JSONObject(chat.control.raw) }.getOrDefault(JSONObject())
                val current = raw.optJSONObject("settings") ?: JSONObject()
                val chosen = runCatching { JSONObject(ws.saved).optJSONObject("settings") }.getOrNull() ?: current
                vm.workspace.selectSettings(JSONObject(chosen.toString()).put("mode", "plan"), current)
                vm.composer.focusInput("写下需要调整的地方…")
            }, enabled = !busy, modifier = Modifier.weight(1f))
        }
    }
}
