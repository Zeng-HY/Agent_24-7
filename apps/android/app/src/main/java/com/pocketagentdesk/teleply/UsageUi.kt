package com.pocketagentdesk.teleply

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import java.time.Instant
import java.time.ZoneId
import kotlinx.coroutines.launch
import org.json.JSONObject

/**
 * 用量 (11-17): Codex's and Claude's limits and when they reset, read when the sheet opens and on 刷新 — no polling.
 * Codex's reset credits show here too; using one always goes through a confirmation, and a request id keeps a retry
 * from using a second. The sheet already scrolls its content (Overlays.kt), so nothing here scrolls by itself.
 */
@Composable
fun UsageSheet(vm: ReaderViewModel, onClose: () -> Unit) {
    val p = LocalTeleply.current
    val scope = rememberCoroutineScope()
    val zone = remember { ZoneId.systemDefault() }
    var report by remember { mutableStateOf<UsageReport?>(null) }
    var error by remember { mutableStateOf("") }
    var loading by remember { mutableStateOf(true) }
    var sending by remember { mutableStateOf(false) }
    var note by remember { mutableStateOf("") }
    var noteError by remember { mutableStateOf(false) }
    var noteMuted by remember { mutableStateOf(false) }
    var unconfirmed by remember { mutableStateOf(false) }
    var asking by remember { mutableStateOf(false) }
    var picked by remember { mutableStateOf<ResetCredit?>(null) }
    val attempt = remember { ResetAttempt() }

    fun load() {
        if (loading && report != null) return
        loading = true
        error = ""
        scope.launch {
            try {
                report = parseUsage(vm.deviceCall("usage", mapOf("live" to "1")))
            } catch (e: Exception) {
                error = e.message ?: "读不到用量"
            }
            loading = false
        }
    }
    LaunchedEffect(Unit) { load() }

    fun use(credit: ResetCredit?) {
        if (sending) return
        sending = true
        note = ""
        noteError = false
        noteMuted = false
        unconfirmed = false
        picked = credit
        scope.launch {
            try {
                val body = JSONObject().put("request_id", attempt.id()).put("confirmed", true)
                if (credit != null) body.put("credit_id", credit.id)
                val answer = vm.deviceCall("usage/codex-reset", body = body)
                attempt.done()
                note = answer.string("text")
                // Red is for failures only: a reset reads as ordinary text, the other outcomes in grey.
                noteMuted = answer.string("outcome") != "reset"
                val fresh = answer.optJSONObject("usage")
                if (fresh != null) report = (report ?: UsageReport()).copy(codex = parseCodexUsage(fresh)) else load()
            } catch (e: Exception) {
                if (attempt.keepsId(e)) {
                    unconfirmed = true
                    note = "没确认这次用成了没有。"
                } else {
                    attempt.done()
                    note = e.message ?: "没成功"
                }
                noteError = true
                noteMuted = false
            }
            sending = false
        }
    }

    TeleplySheet("用量", onClose) {
        Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
            Text("Codex 和 Claude 的用量", style = MaterialTheme.typography.bodyMedium, color = p.muted, modifier = Modifier.weight(1f))
            PillButton("刷新", { load() }, style = PillStyle.Text, enabled = !loading && !sending, minHeight = 36.dp)
        }
        if (loading && report == null) Text("读取中…", style = MaterialTheme.typography.note, color = p.muted)
        if (error.isNotBlank()) Text(error, style = MaterialTheme.typography.note, color = p.error)
        if (note.isNotBlank()) Text(note, style = MaterialTheme.typography.note, color = when {
            noteError -> p.error
            noteMuted -> p.muted
            else -> p.text
        })
        if (sending) Text("正在用…", style = MaterialTheme.typography.note, color = p.muted)
        if (unconfirmed) PillButton("再试一次（不会多用）", { use(picked) }, enabled = !sending, modifier = Modifier.fillMaxWidth())
        report?.let { data ->
            CodexBlock(data.codex, data.now, sending, zone) { credit ->
                picked = credit
                asking = true
            }
            ClaudeBlock(data.claude)
        }
    }
    if (asking) AlertDialog(
        onDismissRequest = { asking = false },
        title = { Text("用掉 1 次 Codex 重置？") },
        text = { Text(confirmText(picked, report?.codex?.windows.orEmpty(), zone)) },
        confirmButton = {
            TextButton(onClick = {
                asking = false
                use(picked)
            }) { Text("用掉 1 次", color = p.error) }
        },
        dismissButton = { TextButton(onClick = { asking = false }) { Text("先不用") } },
    )
}

@Composable
private fun CodexBlock(codex: CodexUsage, now: Long, sending: Boolean, zone: ZoneId, onUse: (ResetCredit?) -> Unit) {
    val p = LocalTeleply.current
    Text("Codex", style = MaterialTheme.typography.labelMedium.copy(fontSize = 13.sp, fontWeight = FontWeight.SemiBold), color = p.muted)
    if (!codex.available) {
        Text(codex.reason.ifBlank { "读不到 Codex 的用量" }, style = MaterialTheme.typography.note, color = p.muted)
        return
    }
    if (codex.reached != null) Text("Codex 的用量用完了", style = MaterialTheme.typography.note, color = p.error)
    codex.windows.forEach { window -> WindowRow(window, resetLine(window, codex.source, now, zone)) }
    val from = sourceLine(codex.source, codex.asOf, now, zone)
    if (from.isNotBlank()) Text(from, style = MaterialTheme.typography.bodySmall.copy(fontSize = 12.sp), color = p.muted)
    if (codex.liveError.isNotBlank()) {
        Text("读不到实时用量：${codex.liveError}", style = MaterialTheme.typography.bodySmall.copy(fontSize = 12.sp), color = p.muted)
    }
    when {
        !codex.resets -> if (codex.source == "records") {
            Text("重置次数要实时读到才显示，点「刷新」再读一次", style = MaterialTheme.typography.bodySmall.copy(fontSize = 12.sp), color = p.muted)
        }
        codex.resetsAvailable == 0 -> Text("没有可用的重置次数", style = MaterialTheme.typography.note, color = p.muted)
        else -> {
            Text("可用重置：${codex.resetsAvailable ?: codex.credits?.size ?: 0} 次", style = MaterialTheme.typography.bodyMedium, color = p.text)
            val credits = codex.credits
            if (credits == null) {
                PillButton("用掉一次", { onUse(null) }, enabled = !sending, modifier = Modifier.fillMaxWidth())
            } else {
                credits.forEach { credit ->
                    Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                        Column(Modifier.weight(1f)) {
                            Text(credit.title.ifBlank { "用量重置" }, style = MaterialTheme.typography.bodyMedium, color = p.text)
                            Text(expiryLine(credit, zone), style = MaterialTheme.typography.bodySmall.copy(fontSize = 12.sp), color = p.muted)
                        }
                        Spacer(Modifier.width(8.dp))
                        PillButton("用掉这一次", { onUse(credit) }, enabled = !sending, minHeight = 36.dp)
                    }
                }
            }
        }
    }
}

@Composable
private fun ClaudeBlock(claude: ClaudeUsage) {
    val p = LocalTeleply.current
    Text("Claude", style = MaterialTheme.typography.labelMedium.copy(fontSize = 13.sp, fontWeight = FontWeight.SemiBold), color = p.muted)
    if (!claude.available) {
        Text(claude.reason.ifBlank { "读不到 Claude 的用量" }, style = MaterialTheme.typography.note, color = p.muted)
        return
    }
    if (claude.windows.isEmpty()) {
        if (claude.text.isNotBlank()) Text(claude.text, style = MaterialTheme.typography.bodyMedium, color = p.text)
    } else {
        claude.windows.forEach { window -> WindowRow(window, if (window.resetsText.isNotBlank()) "${window.resetsText} 重置" else "") }
    }
    Text(
        "读自电脑上的 Claude 窗口。Claude 只显示最紧的那一档。" + if (claude.minimized) "Claude 窗口最小化了，数字可能是旧的。" else "",
        style = MaterialTheme.typography.bodySmall.copy(fontSize = 12.sp), color = p.muted,
    )
}

/** One limit: its name and how much is used, a bar, and the line under it (when it resets, or nothing). */
@Composable
private fun WindowRow(window: UsageWindow, line: String) {
    val p = LocalTeleply.current
    Column(Modifier.fillMaxWidth()) {
        Text("${window.name}　已用 ${window.usedPercent}%", style = MaterialTheme.typography.bodyMedium, color = p.text)
        LinearProgressIndicator(
            progress = { window.usedPercent / 100f },
            modifier = Modifier.fillMaxWidth().height(4.dp).padding(top = 2.dp),
            color = if (window.usedPercent >= 90) p.error else p.accent,
            trackColor = p.line,
        )
        if (line.isNotBlank()) Text(line, style = MaterialTheme.typography.bodySmall.copy(fontSize = 12.sp), color = p.muted)
    }
}

private fun expiryLine(credit: ResetCredit, zone: ZoneId): String {
    val at = credit.expiresAt ?: return "不会过期"
    val day = Instant.ofEpochMilli(at * 1000).atZone(zone).toLocalDate()
    return "${day.monthValue}月${day.dayOfMonth}日 到期"
}
