package com.pocketagentdesk.teleply

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import android.provider.Settings
import android.speech.*
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.semantics.*
import androidx.compose.ui.unit.dp
import androidx.core.content.ContextCompat
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import kotlinx.coroutines.launch

fun appendDictation(existing:String,recognized:String):String=if(recognized.isBlank()) existing else existing+if(existing.isBlank() || existing.last().isWhitespace()) recognized.trim() else "\n"+recognized.trim()
fun speechError(code:Int)=when(code) {
    SpeechRecognizer.ERROR_INSUFFICIENT_PERMISSIONS -> "麦克风权限未开启，可继续键盘输入。"
    SpeechRecognizer.ERROR_NO_MATCH,SpeechRecognizer.ERROR_SPEECH_TIMEOUT -> "没有识别到清晰内容，草稿未改变。"
    SpeechRecognizer.ERROR_NETWORK,SpeechRecognizer.ERROR_NETWORK_TIMEOUT -> "系统识别服务网络不可用，草稿未改变。"
    SpeechRecognizer.ERROR_RECOGNIZER_BUSY -> "系统识别服务正忙，请稍后再试。"
    else -> "系统语音识别未完成，草稿未改变。"
}

/**
 * Microphone for a computer whose voice service is off: the phone's own speech recogniser; the result is appended to
 * the draft and is never sent by itself. Status goes to [onNote], shown in the input area's note line.
 */
@Composable fun SystemMicButton(controller:ChatController,onNote:(String)->Unit) {
    val state by controller.state.collectAsStateWithLifecycle()
    val key=state.key ?: return
    val p=LocalTeleply.current
    val context=LocalContext.current;val owner=LocalLifecycleOwner.current
    val available=remember { runCatching { SpeechRecognizer.isRecognitionAvailable(context) }.getOrDefault(false) }
    var listening by remember(key) { mutableStateOf(false) }
    var explanation by remember(key) { mutableStateOf(false) }
    var permissionTarget by remember { mutableStateOf<ChatKey?>(null) }
    val gate=remember(key) { SpeechGate(key) }
    var recognizer by remember(key) { mutableStateOf<SpeechRecognizer?>(null) }
    val note by rememberUpdatedState(onNote)
    fun cancel() { gate.cancel();recognizer?.cancel();recognizer?.destroy();recognizer=null;listening=false }
    fun start() {
        if(!available || ContextCompat.checkSelfPermission(context,Manifest.permission.RECORD_AUDIO)!=PackageManager.PERMISSION_GRANTED) { note("麦克风权限或系统识别服务不可用。");return }
        cancel();val ticket=gate.start()
        try {
            val local=Build.VERSION.SDK_INT>=31 && SpeechRecognizer.isOnDeviceRecognitionAvailable(context)
            val sr=if(local && Build.VERSION.SDK_INT>=31) SpeechRecognizer.createOnDeviceSpeechRecognizer(context) else SpeechRecognizer.createSpeechRecognizer(context)
            recognizer=sr
            sr.setRecognitionListener(object:RecognitionListener {
                override fun onReadyForSpeech(params:Bundle?) { if(gate.accepts(ticket,key)) note("正在聆听；结果会追加到草稿末尾。") }
                override fun onBeginningOfSpeech()=Unit
                override fun onRmsChanged(rmsdB:Float)=Unit
                override fun onBufferReceived(buffer:ByteArray?)=Unit
                override fun onEndOfSpeech() { if(gate.accepts(ticket,key)) note("正在识别…") }
                override fun onError(error:Int) { if(gate.accepts(ticket,controller.state.value.key)) { note(speechError(error));cancel() } }
                override fun onResults(results:Bundle?) {
                    if(!gate.accepts(ticket,controller.state.value.key)) return
                    val text=results?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)?.firstOrNull().orEmpty()
                    controller.appendVoice(key,text)
                    note(if(text.isBlank()) "没有识别结果，草稿未改变。" else "识别结果已追加到草稿，尚未发送。")
                    cancel()
                }
                override fun onPartialResults(partialResults:Bundle?)=Unit
                override fun onEvent(eventType:Int,params:Bundle?)=Unit
            })
            listening=true;note(if(local) "使用设备上的语音识别。" else "使用系统语音识别，服务可能联网。")
            sr.startListening(Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH).putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL,RecognizerIntent.LANGUAGE_MODEL_FREE_FORM).putExtra(RecognizerIntent.EXTRA_PARTIAL_RESULTS,false).putExtra(RecognizerIntent.EXTRA_MAX_RESULTS,1))
        } catch(_:Exception) { cancel();note("无法启动系统语音识别，可继续键盘输入。") }
    }
    val permission=rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { granted -> val expected=permissionTarget;permissionTarget=null;if(granted && expected==key && gate.key==controller.state.value.key && owner.lifecycle.currentState.isAtLeast(Lifecycle.State.STARTED)) start() else note("语音未启动，草稿保留；可在系统应用设置中修改权限。") }
    DisposableEffect(key,owner) {
        val observer=LifecycleEventObserver { _,event -> if(event==Lifecycle.Event.ON_STOP) { if(listening) note("已停止语音输入，草稿保留。");cancel() } }
        owner.lifecycle.addObserver(observer)
        onDispose { owner.lifecycle.removeObserver(observer);gate.close();recognizer?.cancel();recognizer?.destroy() }
    }
    TeleplyIconButton(
        TeleplyIcons.Mic,
        if(listening) "取消语音输入" else "语音输入",
        { if(listening) { cancel();note("语音已取消，草稿保留。") } else explanation=true },
        style=IconButtonStyle.Plain,
        enabled=available && state.ready,
        tint=if(listening) p.accent else p.muted,
        disabledReason=if(!available) "此设备未提供系统语音识别" else null,
    )
    if(explanation) AlertDialog(onDismissRequest={explanation=false},title={Text("系统语音输入")},text={Text("识别服务可能联网。只在这次操作中使用麦克风，本应用不保存录音；结果追加到当前草稿，仍需手动发送。")},confirmButton={TextButton(onClick={explanation=false;if(ContextCompat.checkSelfPermission(context,Manifest.permission.RECORD_AUDIO)==PackageManager.PERMISSION_GRANTED) start() else {permissionTarget=key;permission.launch(Manifest.permission.RECORD_AUDIO)}}) { Text("开始识别") }},dismissButton={TextButton(onClick={explanation=false}) { Text("取消") }})
}
class SpeechGate(val key:ChatKey) {
    private var ticket=0;private var closed=false
    fun start():Int { ticket++;return ticket }
    fun cancel() { ticket++ }
    fun close() { closed=true;cancel() }
    fun accepts(value:Int,current:ChatKey?)=!closed && value==ticket && current==key
}

/**
 * 手机通知 and 语音输入 groups of the settings page (spec 4.6), plus the system accessibility settings. 手机通知 is the
 * web's ntfy group first, then this phone's own check of one conversation (a native addition).
 */
@Composable fun PlatformSettings(s:ReaderState,vm:ReaderViewModel) {
    val context=LocalContext.current
    SectionLabel("手机通知")
    if(!s.fixture || s.device!=null) NtfySettings(vm,s)
    (context.applicationContext as? NativeApplication)?.let { WatchSettings(s,it) }
    SectionLabel("语音输入")
    VoiceSettings(vm,s)
    // 读屏与字号 is gone (0.9): the app follows the system's settings by itself, nothing here to set.
}

/** This phone's own check of one conversation (a native addition beside ntfy): not real-time, at most every 15 minutes. */
@Composable private fun WatchSettings(s:ReaderState,graph:NativeApplication) {
    val context=LocalContext.current
    val p=LocalTeleply.current
    val target by graph.watch.state.collectAsStateWithLifecycle()
    val scope=rememberCoroutineScope();var note by remember { mutableStateOf("") };var busy by remember { mutableStateOf(false) }
    var pending by remember { mutableStateOf<WatchTarget?>(null) }
    fun enable(t:WatchTarget) { if(busy) return;busy=true;scope.launch { try { graph.watch.enable(t.origin,t.key);note="后台定期检查已开启。" } catch(e:Exception) { note=e.message ?: "未能开启" } finally { busy=false } } }
    val permission=rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { allowed -> val t=pending;pending=null;if(allowed && t!=null) enable(t) else note="通知未获授权，阅读和草稿不受影响。" }
    CardSection {
        CardRow("后台会话检查",null,detail="只看选中的一个会话，最快15分钟一次；省电、离线或强制停止时会更晚，不是实时推送。",value=if(target==null) "未开启" else "已开启")
        CardDivider()
        when {
            s.fixture -> CardRow("本地示例不会启用真实后台任务",null)
            s.device!=null && s.chat!=null -> CardRow("关注当前会话状态",{
                val t=WatchTarget(s.origin,ChatKey(s.scope,s.device.id,s.chat.id,s.app),"")
                if(Build.VERSION.SDK_INT>=33 && ContextCompat.checkSelfPermission(context,Manifest.permission.POST_NOTIFICATIONS)!=PackageManager.PERMISSION_GRANTED) {pending=t;permission.launch(Manifest.permission.POST_NOTIFICATIONS)}
                else enable(t)
            },icon=TeleplyIcons.Bell,enabled=!busy)
            else -> CardRow("进入需要关注的会话，再从这里或对话菜单开启",null)
        }
        if(target!=null && !s.fixture) {
            CardDivider()
            CardRow("关闭后台检查",{ graph.watch.disable();note="后台检查已关闭。" },enabled=!busy,danger=true)
            CardDivider()
            CardRow("立即核对一次",{ busy=true;scope.launch { try { note=graph.watch.checkOnce() } finally { busy=false } } },enabled=!busy)
        }
        CardDivider()
        CardRow("系统通知设置",{ context.startActivity(Intent(Settings.ACTION_APP_NOTIFICATION_SETTINGS).putExtra(Settings.EXTRA_APP_PACKAGE,context.packageName)) },chevron=true)
    }
    if(note.isNotBlank()) Text(note,Modifier.semantics { liveRegion=LiveRegionMode.Polite },style=MaterialTheme.typography.note,color=p.muted)
}
