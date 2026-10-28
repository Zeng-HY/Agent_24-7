package com.pocketagentdesk.teleply

import android.content.Context
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.selection.toggleable
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Switch
import androidx.compose.material3.SwitchDefaults
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalClipboardManager
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import org.json.JSONObject

/** A settings row with a switch; the whole row toggles it. */
@Composable
fun SwitchRow(title: String, checked: Boolean, enabled: Boolean = true, detail: String? = null, onChange: (Boolean) -> Unit) {
    val p = LocalTeleply.current
    Row(
        Modifier.fillMaxWidth().heightIn(min = 52.dp)
            .toggleable(checked, enabled = enabled, role = Role.Switch, onValueChange = onChange)
            .padding(horizontal = 16.dp, vertical = 8.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Column(Modifier.weight(1f)) {
            Text(title, style = MaterialTheme.typography.bodyLarge, color = p.text.copy(alpha = if (enabled) 1f else 0.45f))
            if (!detail.isNullOrBlank()) Text(detail, style = MaterialTheme.typography.bodySmall, color = p.muted)
        }
        Switch(checked, null, enabled = enabled, colors = SwitchDefaults.colors(checkedTrackColor = p.accent, checkedThumbColor = p.onAccent))
    }
}

/**
 * 手机通知 → ntfy (web notify-ui.js, as an Android phone shows it), as short as on the iPhone (user 10-28: "安卓端也相应
 * 搞简洁一点"): one switch, whether the phone is listening under it, then the topic and the computer's own address to
 * copy into the ntfy app. A line under it only when something went wrong. Bark is for iPhones and is not shown here.
 */
@Composable
fun NtfySettings(vm: ReaderViewModel, s: ReaderState) {
    val p = LocalTeleply.current
    val clipboard = LocalClipboardManager.current
    val scope = rememberCoroutineScope()
    var state by remember(s.device?.id) { mutableStateOf<JSONObject?>(null) }
    var busy by remember { mutableStateOf(false) }
    var failure by remember { mutableStateOf<String?>(null) }
    suspend fun load() { state = runCatching { vm.deviceCall("notify") }.getOrElse { e -> failure = e.message; state } }
    LaunchedEffect(s.device?.id) { if (s.device != null) load() }
    if (s.device == null) return
    val ntfy = state?.optJSONObject("ntfy")
    val on = ntfy?.optBoolean("on") == true
    val topic = ntfy?.string("topic")?.ifBlank { null } ?: "agent-remote"
    val server = ntfy?.string("server").orEmpty()
    CardSection {
        SwitchRow("ntfy 通知", on, enabled = state != null && !busy, detail = if (!on) null else if ((ntfy?.optInt("listening") ?: 0) > 0) "手机连着" else "手机没连着") { want ->
            if (busy) return@SwitchRow
            busy = true
            failure = null
            scope.launch {
                try { vm.deviceCall("notify/ntfy", body = JSONObject().put("on", want)) } catch (e: Exception) { failure = e.message ?: "电脑没有回应" }
                load(); busy = false
            }
        }
        CardDivider()
        CardRow("主题", { clipboard.setText(AnnotatedString(topic)) }, value = topic)
        CardDivider()
        CardRow("服务器", if (server.isNotBlank()) ({ clipboard.setText(AnnotatedString(server)) }) else null, value = server.ifBlank { "电脑没有给出地址" })
    }
    failure?.let { Text(it, style = MaterialTheme.typography.note, color = p.error, modifier = Modifier.semantics { liveRegion = LiveRegionMode.Polite }) }
}

private const val UiPrefs = "teleply_ui"
private const val TidyKey = "voice_tidy"

/** 录音后自动整理 (web voice-ui.js): on unless turned off here. */
fun voiceTidy(context: Context) = context.getSharedPreferences(UiPrefs, Context.MODE_PRIVATE).getBoolean(TidyKey, true)

/**
 * 语音输入 (web): 录音后自动整理 and 语音词典, both of the computer's voice service. When this computer has its voice
 * turned off, the microphone uses the phone's own recogniser instead, and this says so.
 */
@Composable
fun VoiceSettings(vm: ReaderViewModel, s: ReaderState) {
    val p = LocalTeleply.current
    val context = LocalContext.current
    var tidy by remember { mutableStateOf(voiceTidy(context)) }
    var terms by remember { mutableStateOf(false) }
    var available by remember(s.device?.id) { mutableStateOf<Boolean?>(null) }
    LaunchedEffect(s.device?.id) { available = if (s.device == null) null else runCatching { vm.voiceAvailable() }.getOrDefault(true) }
    CardSection {
        SwitchRow("录音后自动整理", tidy, enabled = available != false, detail = "电脑识别出文字后，再把口语整理成书面语；可以撤销。") {
            tidy = it
            context.getSharedPreferences(UiPrefs, Context.MODE_PRIVATE).edit().putBoolean(TidyKey, it).apply()
        }
        CardDivider()
        CardRow("语音词典", { terms = true }, chevron = true, enabled = s.device != null && available != false)
    }
    val line = when {
        s.device == null -> "选好电脑后可以用。录音交给电脑上的语音服务识别，不保存在手机上。"
        available == false -> "这台电脑没开语音：麦克风会改用手机自带的识别，结果同样只放进输入框。"
        else -> "录音交给电脑上的语音服务识别，不保存在手机上；识别出的文字只放进输入框，不会自动发送。"
    }
    Text(line, style = MaterialTheme.typography.note, color = p.muted)
    if (terms) VoiceTermsSheet(vm) { terms = false }
}

/** 语音词典 (web voiceTermsSheet): one word a line, kept on the computer. */
@Composable
private fun VoiceTermsSheet(vm: ReaderViewModel, onDismiss: () -> Unit) {
    val p = LocalTeleply.current
    val scope = rememberCoroutineScope()
    var text by remember { mutableStateOf<String?>(null) }
    var note by remember { mutableStateOf<String?>(null) }
    var busy by remember { mutableStateOf(false) }
    LaunchedEffect(Unit) { text = try { vm.deviceCall("voice/terms").string("text") } catch (e: Exception) { note = "没读到词典：" + (e.message ?: ""); "" } }
    TeleplySheet("语音词典", onDismiss) {
        TeleplyTextField(text.orEmpty(), { text = it }, "每行一个词", singleLine = false, minLines = 8, maxLines = 16, enabled = text != null && !busy)
        note?.let { Text(it, style = MaterialTheme.typography.note, color = p.muted, modifier = Modifier.semantics { liveRegion = LiveRegionMode.Polite }) }
        PillButton("保存", {
            busy = true
            scope.launch {
                try { val r = vm.deviceCall("voice/terms", body = JSONObject().put("text", text.orEmpty())); note = "已保存，${r.optInt("count")} 个词"; delay(600); onDismiss() }
                catch (e: Exception) { note = e.message ?: "没保存" }
                busy = false
            }
        }, style = PillStyle.Primary, enabled = text != null && !busy, modifier = Modifier.fillMaxWidth())
    }
}

/**
 * 诊断测速 (web): 显示操作耗时 times what carries a message or a file and shows each one for a moment; 测一下连接
 * times three status requests to the computer; the last ten records, until 清空记录.
 */
@Composable
fun DiagnosticsSettings(vm: ReaderViewModel, s: ReaderState) {
    val p = LocalTeleply.current
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val enabled by Diagnostics.enabled.collectAsStateWithLifecycle()
    val records by Diagnostics.records.collectAsStateWithLifecycle()
    var probing by remember { mutableStateOf(false) }
    CardSection {
        SwitchRow("显示操作耗时", enabled) { Diagnostics.set(context, it) }
        CardDivider()
        CardRow("测一下连接", {
            if (!probing) {
                probing = true
                scope.launch {
                    try {
                        for (i in 1..3) {
                            if (!Diagnostics.enabled.value) break
                            val timer = Diagnostics.start("连接请求 $i/3")
                            val result = try { vm.deviceCall("status"); "成功" } catch (e: ServiceFailure) { "HTTP ${e.status}" } catch (e: java.io.InterruptedIOException) { "超过10秒" } catch (e: kotlinx.coroutines.CancellationException) { throw e } catch (e: Exception) { "网络失败" }
                            Diagnostics.finish(timer, 0, result, notify = false)
                        }
                    } finally { probing = false }
                }
            }
        }, enabled = enabled && !probing && s.device != null)
        CardDivider()
        CardRow("清空记录", { Diagnostics.clear() }, enabled = records.isNotEmpty())
    }
    val text = if (records.isNotEmpty()) records.joinToString("\n\n") { it.time + " " + speedText(it) } else if (enabled) "暂无记录" else ""
    if (text.isNotBlank()) Text(text, style = MaterialTheme.typography.note, color = p.muted, modifier = Modifier.semantics { liveRegion = LiveRegionMode.Polite })
}

/** Each timed operation shown for a moment where the user is (web: a toast), while 显示操作耗时 is on. */
@Composable
fun DiagnosticToast(modifier: Modifier = Modifier) {
    val records by Diagnostics.records.collectAsStateWithLifecycle()
    var shown by remember { mutableLongStateOf(Diagnostics.records.value.firstOrNull()?.serial ?: 0L) }
    var current by remember { mutableStateOf<SpeedRecord?>(null) }
    val latest = records.firstOrNull()
    LaunchedEffect(latest?.serial) {
        if (latest != null && latest.serial > shown && latest.notify) { shown = latest.serial; current = latest; delay(2800); if (current?.serial == latest.serial) current = null }
    }
    AnimatedVisibility(current != null, modifier, enter = fadeIn(), exit = fadeOut()) {
        val r = current ?: return@AnimatedVisibility
        val ok = r.result in listOf("成功", "请求完成")
        Box(Modifier.padding(horizontal = 24.dp).clip(RoundedCornerShape(14.dp)).background(if (ok) Color(0xE6111111) else Color(0xE6B91C1C)).padding(horizontal = 16.dp, vertical = 10.dp).semantics { liveRegion = LiveRegionMode.Polite }) {
            Text(speedText(r), style = MaterialTheme.typography.bodyMedium.copy(fontSize = 13.sp), color = Color.White)
        }
    }
}
