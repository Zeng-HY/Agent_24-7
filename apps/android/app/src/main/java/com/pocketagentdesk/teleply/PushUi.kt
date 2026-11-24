package com.pocketagentdesk.teleply

import android.Manifest
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.PowerManager
import android.provider.Settings
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.semantics
import androidx.core.content.ContextCompat
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import kotlinx.coroutines.launch
import org.json.JSONObject

/**
 * 设置 → 手机通知 → 遥应通知 (design-2 §3.5): the switch, the line that says what the connection is doing, 试推一条,
 * 后台运行设置, and 定时任务's three choices. The demo shows the same group with fixed data and contacts nothing.
 */
@Composable
fun PushSettings(s: ReaderState, vm: ReaderViewModel, graph: NativeApplication?) {
    if (s.fixture) FixturePushSettings(s, vm) else if (graph != null) RealPushSettings(s, vm, graph)
}

@Composable
private fun FixturePushSettings(s: ReaderState, vm: ReaderViewModel) {
    val p = LocalTeleply.current
    var on by remember { mutableStateOf(false) }
    var background by remember { mutableStateOf(false) }
    SectionLabel("遥应通知")
    CardSection {
        SwitchRow("遥应通知", on, detail = if (on) "本地示例 · 不连接中转" else null) { on = it }
        CardDivider()
        CardRow("后台运行设置", { background = true }, detail = "按手机牌子告诉你怎样让它一直在后台", chevron = true)
    }
    if (on) Text("本地示例不连接中转，试推不可用；真机上打开后会先登记这台手机。", style = MaterialTheme.typography.note, color = p.muted)
    CodexAutomationSettings(s, vm)
    if (background) PushBackgroundSheet { background = false }
}

@Composable
private fun RealPushSettings(s: ReaderState, vm: ReaderViewModel, graph: NativeApplication) {
    val p = LocalTeleply.current
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val enabled by graph.push.channel.enabled.collectAsStateWithLifecycle()
    val status by PushRuntime.status.collectAsStateWithLifecycle()
    var busy by remember { mutableStateOf(false) }
    var testing by remember { mutableStateOf(false) }
    var failure by remember { mutableStateOf<String?>(null) }
    var testNote by remember { mutableStateOf<String?>(null) }
    var background by remember { mutableStateOf(false) }
    val line = when {
        !enabled -> "未开启"
        status.enabled -> pushStatusText(status)
        else -> "正在连接中转…"
    }
    fun start() {
        if (busy) return
        busy = true
        failure = null
        scope.launch {
            try {
                graph.push.enable(s.origin)
                requestIgnoreBattery(context)
            } catch (e: Exception) {
                failure = pushFailureText(e)
                runCatching { graph.push.channel.disable() }
            } finally { busy = false }
        }
    }
    val permission = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
        if (granted) start() else failure = "通知权限未开启，打开系统通知权限后再试。"
    }
    SectionLabel("遥应通知")
    CardSection {
        SwitchRow("遥应通知", enabled, enabled = !busy, detail = line) { want ->
            if (busy) return@SwitchRow
            if (!want) {
                busy = true
                scope.launch { try { graph.push.disable() } catch (e: Exception) { failure = pushFailureText(e) } finally { busy = false } }
                return@SwitchRow
            }
            if (Build.VERSION.SDK_INT >= 33 && ContextCompat.checkSelfPermission(context, Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
                permission.launch(Manifest.permission.POST_NOTIFICATIONS)
            } else start()
        }
        if (enabled) {
            CardDivider()
            CardRow("试推一条", {
                if (!testing) {
                    testing = true
                    testNote = null
                    failure = null
                    scope.launch {
                        try { graph.push.test(); testNote = pushTestText() } catch (e: Exception) { failure = pushFailureText(e) } finally { testing = false }
                    }
                }
            }, detail = if (testing) "正在请中转发…" else "经这条连接推一条，看看通知和锁屏", enabled = !testing)
        }
        CardDivider()
        CardRow("后台运行设置", { background = true }, detail = "按手机牌子告诉你怎样让它一直在后台", chevron = true)
    }
    if (enabled) Text("可以把电脑上的 ntfy 关掉，免得收两遍。", style = MaterialTheme.typography.note, color = p.muted)
    Text("「后台连接」那条通知可以长按关掉，服务照常运行。", style = MaterialTheme.typography.note, color = p.muted)
    testNote?.let { Text(it, style = MaterialTheme.typography.note, color = p.muted, modifier = Modifier.semantics { liveRegion = LiveRegionMode.Polite }) }
    failure?.let { Text(it, style = MaterialTheme.typography.note, color = p.error, modifier = Modifier.semantics { liveRegion = LiveRegionMode.Polite }) }
    CodexAutomationSettings(s, vm)
    if (background) PushBackgroundSheet { background = false }
}

/** 「Codex 定时任务」 (design-2 §3.5): the computer's own setting, shown only when this version of it has `automations`. */
@Composable
private fun CodexAutomationSettings(s: ReaderState, vm: ReaderViewModel) {
    val p = LocalTeleply.current
    val scope = rememberCoroutineScope()
    val device = s.device ?: return
    var state by remember(device.id) { mutableStateOf<JSONObject?>(null) }
    var mode by remember(device.id) { mutableStateOf("") }
    var failure by remember(device.id) { mutableStateOf<String?>(null) }
    LaunchedEffect(device.id) {
        state = runCatching { vm.deviceCall("notify") }.getOrElse { failure = it.message; null }
        mode = pushAutomationMode(state).orEmpty()
    }
    // The computer's first version sends a plain string; an object with mode is accepted too. No key at all: older
    // computer, the group is not shown.
    val current = pushAutomationMode(state) ?: return
    SectionLabel("Codex 定时任务")
    SegmentedChoice(PushAutomationChoices, mode.ifBlank { current }, { chosen ->
        mode = chosen
        failure = null
        scope.launch {
            try { vm.deviceCall("notify/automations", body = JSONObject().put("mode", chosen)) } catch (e: Exception) { failure = e.message ?: "电脑没有回应" }
        }
    })
    Text(pushAutomationExplanation(), style = MaterialTheme.typography.note, color = p.muted)
    failure?.let { Text(it, style = MaterialTheme.typography.note, color = p.error) }
}

/** 后台运行设置 (design-2 §3.5): one sentence for this phone's maker, and the app's system page every phone has. */
@Composable
private fun PushBackgroundSheet(onDismiss: () -> Unit) {
    val p = LocalTeleply.current
    val context = LocalContext.current
    TeleplySheet("后台运行设置", onDismiss) {
        Text(backgroundHint(Build.MANUFACTURER.orEmpty()), style = MaterialTheme.typography.bodyLarge, color = p.text)
        Text("系统省电会限制后台：按上面设好，遥应才能在屏幕关掉时也收到通知。", style = MaterialTheme.typography.note, color = p.muted)
        PillButton("打开遥应的系统设置", { openAppDetails(context) }, style = PillStyle.Primary, modifier = Modifier.fillMaxWidth())
    }
}

/** 忽略电池优化 (design-2 §3.5): asked once when the switch goes on, and only if it is not already allowed. */
fun requestIgnoreBattery(context: Context) {
    val power = context.getSystemService(PowerManager::class.java)
    if (power?.isIgnoringBatteryOptimizations(context.packageName) == true) return
    runCatching {
        context.startActivity(Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS, Uri.parse("package:${context.packageName}")))
    }.onFailure { openAppDetails(context) }
}

fun openAppDetails(context: Context) {
    runCatching {
        context.startActivity(Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.parse("package:${context.packageName}")))
    }
}
