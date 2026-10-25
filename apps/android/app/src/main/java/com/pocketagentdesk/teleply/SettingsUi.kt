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
 * 手机通知 → ntfy (web notify-ui.js, as an Android phone shows it): the ntfy app subscribes to the computer itself, so
 * the topic and the computer's own address are shown to copy; 打开并试推一条, 试推一条, 关掉; the last outcomes. Bark is
 * for iPhones and is not shown here.
 */
@Composable
fun NtfySettings(vm: ReaderViewModel, s: ReaderState) {
    val p = LocalTeleply.current
    val clipboard = LocalClipboardManager.current
    val scope = rememberCoroutineScope()
    var state by remember(s.device?.id) { mutableStateOf<JSONObject?>(null) }
    var busy by remember { mutableStateOf(false) }
    var note by remember { mutableStateOf<String?>(null) }
    suspend fun load() { state = runCatching { vm.deviceCall("notify") }.getOrElse { e -> note = e.message; state } }
    LaunchedEffect(s.device?.id) { if (s.device != null) load() }
    fun call(route: String, body: JSONObject) {
        if (busy) return
        busy = true
        scope.launch {
            note = try { vm.deviceCall(route, body = body).string("text").ifBlank { "好了" } } catch (e: Exception) { e.message ?: "电脑没有回应" }
            load(); busy = false
        }
    }
    if (s.device == null) { CardSection { CardRow("选好电脑后，可以在这里开关 ntfy 通知", null) }; return }
    val ntfy = state?.optJSONObject("ntfy")
    val on = ntfy?.optBoolean("on") == true
    val topic = ntfy?.string("topic")?.ifBlank { null } ?: "agent-remote"
    val server = ntfy?.string("server").orEmpty()
    CardSection {
        if (state == null) CardRow("正在读取电脑上的通知设置…", null)
        else {
            if (on) { CardRow("已开 · ntfy", null, value = if (ntfy?.optInt("listening") ?: 0 > 0) "手机连着" else "手机没连着"); CardDivider() }
            CardRow("主题", { clipboard.setText(AnnotatedString(topic)); note = "已复制主题" }, value = topic)
            CardDivider()
            CardRow("服务器", if (server.isNotBlank()) ({ clipboard.setText(AnnotatedString(server)); note = "已复制服务器地址" }) else null, value = server.ifBlank { "电脑没有给出地址" })
            CardDivider()
            if (on) {
                CardRow("试推一条", { call("notify/test", JSONObject().put("channel", "ntfy")) }, enabled = !busy)
                CardDivider()
                CardRow("关掉", { call("notify/ntfy", JSONObject().put("on", false)) }, enabled = !busy, danger = true)
            } else CardRow("打开并试推一条", { call("notify/ntfy", JSONObject().put("on", true)) }, enabled = !busy)
        }
    }
    val explain = when {
        state == null -> null
        !on -> "安卓手机用 ntfy App 收。① 装 ntfy（Google Play、F-Droid 都有）；② 在 ntfy 里点 ＋，主题名称填上面的主题，勾上「使用其他服务器」，地址填上面的服务器，点「订阅」；③ 回到这里点「打开并试推一条」。点主题或服务器就能复制。手机上的 Tailscale 要一直连着才收得到。"
        (ntfy?.optInt("listening") ?: 0) > 0 -> "对话做完时推到 ntfy App。正在用这台电脑、或手机正开着那个对话时不推。"
        else -> "现在没有手机连着：看看 ntfy 里订阅了上面的主题和服务器没有，手机上的 Tailscale 连着没有。" + (ntfy?.string("last_seen")?.takeIf { it.isNotBlank() }?.let { "上次连着是 $it。" } ?: "") + "没连着时做完的对话，连上后会补推（12 小时内的）。"
    }
    if (explain != null) Text(explain, style = MaterialTheme.typography.note, color = p.muted)
    val recent = state?.rows("recent") { it.string("time") + " " + it.string("text") }.orEmpty().take(3)
    if (recent.isNotEmpty()) Text("最近：" + recent.joinToString("\n"), style = MaterialTheme.typography.note, color = p.muted)
    note?.let { Text(it, style = MaterialTheme.typography.note, color = p.muted, modifier = Modifier.semantics { liveRegion = LiveRegionMode.Polite }) }
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
