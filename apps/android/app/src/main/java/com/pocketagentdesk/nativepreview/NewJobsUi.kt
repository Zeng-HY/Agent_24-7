package com.pocketagentdesk.nativepreview

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle

/**
 * One row above the list per first message under way and not on screen (0.8, web #newJobDock): its source, where it
 * stands and its first words. A tap opens its page, its conversation once made, or its sheet when something went wrong.
 */
@Composable
fun NewJobDock(s: ReaderState, vm: ReaderViewModel) {
    val p = LocalTeleply.current
    val jobs by vm.jobs.jobs.collectAsStateWithLifecycle()
    val shown = jobs.filter { it.preview != s.chat?.id }
    if (shown.isEmpty()) return
    Column(Modifier.fillMaxWidth().padding(bottom = 8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        shown.forEach { job ->
            val shape = RoundedCornerShape(14.dp)
            Box(
                Modifier.fillMaxWidth().heightIn(min = 44.dp).clip(shape).background(p.card).border(1.dp, p.line, shape)
                    .clickable(role = Role.Button) { vm.openJob(job) }.padding(horizontal = 14.dp, vertical = 10.dp),
                contentAlignment = Alignment.CenterStart,
            ) {
                Text(newJobDock(job), style = MaterialTheme.typography.bodySmall, color = if (job.problem) p.error else p.muted, maxLines = 1, overflow = TextOverflow.Ellipsis)
            }
        }
    }
}

/**
 * A new conversation's first message on its page, the line under it saying where it stands (web renderFirst). A
 * problem's line opens its sheet. Shown also after the page became the conversation, until the record has it.
 */
@Composable
fun NewFirstMessage(text: String, status: String, problem: Boolean, onStatus: () -> Unit) {
    val p = LocalTeleply.current
    Column(Modifier.fillMaxWidth().padding(top = 8.dp), horizontalAlignment = Alignment.End) {
        UserBubble(text.ifBlank { "请查看这些图片或引用。" })
        if (status.isNotBlank()) Text(
            status,
            style = MaterialTheme.typography.bodySmall,
            color = if (problem) p.error else p.muted,
            textAlign = TextAlign.End,
            modifier = Modifier.padding(top = 4.dp, end = 4.dp)
                .then(if (problem) Modifier.clickable(role = Role.Button, onClick = onStatus) else Modifier)
                .semantics { liveRegion = LiveRegionMode.Polite; if (problem) contentDescription = "$status，打开处理" },
        )
    }
}

/** 新建对话的结果 (web #newJobSheet): where a first message stands and what can be done: 核对, 继续发送, 打开, 恢复, 移除. */
@OptIn(ExperimentalLayoutApi::class)
@Composable
fun NewJobSheet(s: ReaderState, vm: ReaderViewModel) {
    val rid = s.jobSheet ?: return
    val p = LocalTeleply.current
    val jobs by vm.jobs.jobs.collectAsStateWithLifecycle()
    val job = jobs.find { it.request == rid }
    var confirm by remember(rid) { mutableStateOf(false) }
    TeleplySheet("新建对话的结果", vm::closeJobSheet) {
        if (job == null) {
            Text("这一条已经处理过了。", style = MaterialTheme.typography.bodyMedium, color = p.text)
            return@TeleplySheet
        }
        val place = if (job.projectless) "无项目" else job.label.ifBlank { job.folder.substringAfterLast('/').substringAfterLast('\\') }
        Text(listOf(sourceName(job.app), place, job.text.replace(Regex("\\s+"), " ").trim().take(40).ifBlank { "只有图片或引用" }).filter { it.isNotBlank() }.joinToString(" · "),
            style = MaterialTheme.typography.note, color = p.muted)
        Text(newJobProgress(job), style = MaterialTheme.typography.bodyMedium, color = p.text, modifier = Modifier.semantics { liveRegion = LiveRegionMode.Polite })
        val pending = job.pendingJson()
        val retryable = pending.optBoolean("can_submit") || job.state == "failed" && pending.optBoolean("not_submitted") && pending.optBoolean("can_retry", true)
        FlowRow(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            if (job.state != "accepted") PillButton("核对结果", { vm.checkJob(job) })
            if (retryable) PillButton("继续发送", { vm.retryJob(job) }, style = PillStyle.Primary)
            if (pending.string("id").isNotBlank()) PillButton("打开对话", { vm.openJobChat(job) })
            if (job.state == "failed") PillButton("恢复草稿", { vm.restoreJob(job) })
            PillButton("移除", { confirm = true }, style = PillStyle.Text)
        }
    }
    if (confirm && job != null) AlertDialog(
        onDismissRequest = { confirm = false },
        title = { Text("移除这一条？") },
        text = { Text(when (job.state) {
            "failed" -> "这条首条消息没发出去。移除后手机上不再留着它的内容。"
            "accepted" -> "对话已经建好，在对话列表里能找到。移除的只是这条提示。"
            else -> "移除只是手机不再跟踪这一条，不会重复发送。电脑上如果已经建好对话，会照常出现在对话列表里。"
        }) },
        confirmButton = { TextButton({ confirm = false; vm.removeJob(job) }) { Text("移除") } },
        dismissButton = { TextButton({ confirm = false }) { Text("取消") } },
    )
}
