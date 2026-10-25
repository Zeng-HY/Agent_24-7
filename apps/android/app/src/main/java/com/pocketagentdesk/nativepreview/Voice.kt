package com.pocketagentdesk.nativepreview

import android.Manifest
import android.annotation.SuppressLint
import android.content.Context
import android.content.pm.PackageManager
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaRecorder
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.gestures.awaitEachGesture
import androidx.compose.foundation.gestures.awaitFirstDown
import androidx.compose.foundation.gestures.waitForUpOrCancellation
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.minimumInteractiveComponentSize
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.Stable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.hapticfeedback.HapticFeedbackType
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalHapticFeedback
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.onClick
import androidx.compose.ui.semantics.role
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.core.content.ContextCompat
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import java.nio.ByteBuffer
import java.nio.ByteOrder
import kotlin.math.log10
import kotlin.math.max
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONObject

/** Where voice put its words in the draft: [at] and the [text] there now, the words as heard ([raw]), the new draft. */
data class VoicePlacement(val at: Int, val text: String, val raw: String, val draft: String)

/**
 * Puts recognised words where the cursor was, replacing a selection (web voice-ui.js insert): a space before them
 * after Latin text, nothing after Chinese, a line break when the words hold one.
 */
fun placeDictation(existing: String, text: String, start: Int, end: Int = start): VoicePlacement {
    val s = start.coerceIn(0, existing.length)
    val e = end.coerceIn(s, existing.length)
    val before = existing.substring(0, s)
    val after = existing.substring(e)
    val last = before.lastOrNull()
    val sep = when {
        last == null || last.isWhitespace() -> ""
        text.contains('\n') -> "\n"
        last.code in 0x3000..0x9FFF || last.code in 0xFF00..0xFFEF -> ""
        else -> " "
    }
    return VoicePlacement(before.length + sep.length, text, text, before + sep + text + after)
}

/** 16-bit little-endian mono PCM, as the computer's recogniser takes it. */
fun pcmBytes(samples: ShortArray): ByteArray = ByteBuffer.allocate(samples.size * 2).order(ByteOrder.LITTLE_ENDIAN).apply { asShortBuffer().put(samples) }.array()

/** A WAV file of 16 kHz mono PCM (web wav()). */
fun wavBytes(samples: ShortArray, rate: Int = VoiceRate): ByteArray {
    val data = samples.size * 2
    return ByteBuffer.allocate(44 + data).order(ByteOrder.LITTLE_ENDIAN).apply {
        put("RIFF".toByteArray()); putInt(36 + data); put("WAVE".toByteArray()); put("fmt ".toByteArray())
        putInt(16); putShort(1); putShort(1); putInt(rate); putInt(rate * 2); putShort(2); putShort(16)
        put("data".toByteArray()); putInt(data)
        samples.forEach { putShort(it) }
    }.array()
}

const val VoiceRate = 16000
private const val Piece = 4000              // a quarter second goes up at a time
private const val MaxPiece = 9 * VoiceRate  // the computer takes at most 10 s in one piece
private const val MaxSeconds = 300

enum class VoiceMode { Idle, Press, Hold, Recording, Finishing }

/** A line above the box about voice, with one thing to do: 换云端识别, 撤销, 填到这里. */
data class VoicePill(val text: String, val action: String? = null, val run: (() -> Unit)? = null, val error: Boolean = false, val hideAfter: Long = 0, val serial: Long = System.nanoTime())

/**
 * Voice input through the computer (web voice-ui.js): while you talk, pieces of audio go to the computer's recogniser
 * and the words show in the card as they come; ✓ (or letting go after holding) puts them where the cursor was, and with
 * 录音后自动整理 on the computer then tidies them, which 撤销 undoes. When the computer loses the recording, the whole
 * of it goes to its cloud recogniser instead. Nothing is ever sent by itself, and no audio is kept on the phone.
 */
@Stable
class PcVoice internal constructor(private val vm: ReaderViewModel, private val context: Context, private val scope: CoroutineScope) {
    var mode by mutableStateOf(VoiceMode.Idle); private set
    var heard by mutableStateOf(""); private set
    var partial by mutableStateOf(""); private set
    var seconds by mutableIntStateOf(0); private set
    var cancelArmed by mutableStateOf(false)
    var pill by mutableStateOf<VoicePill?>(null)
    val levels = mutableStateListOf<Float>()
    val active: Boolean get() = mode != VoiceMode.Idle
    private var busy = false
    private var session: Session? = null

    private class Session(val chat: ChatKey, val app: String, val title: String, val folder: String, val start: Int, val end: Int) {
        val lock = Any()
        val all = ArrayList<ShortArray>()
        val queue = ArrayList<ShortArray>()
        var total = 0
        var queued = 0
        @Volatile var sid: String? = null
        @Volatile var local = true
        @Volatile var stopping = false
        var capture: Job? = null
        var sender: Job? = null
        fun recording(): ShortArray = synchronized(lock) { join(all) }
    }

    fun begin(chat: ChatKey, app: String, title: String, folder: String, start: Int, end: Int) {
        if (active || busy) return
        val s = Session(chat, app, title, folder, start, end)
        session = s
        mode = VoiceMode.Press; heard = ""; partial = ""; seconds = 0; levels.clear(); cancelArmed = false; pill = null
        // The computer starts listening while the phone does; without it, the cloud gets the whole recording at the end.
        scope.launch {
            try {
                val j = vm.voiceCall("voice/stream/start", mapOf("tidy" to if (voiceTidy(context)) "1" else "0"))
                s.sid = j.string("sid").ifBlank { null }
                if (s.sid == null) s.local = false else if (session === s) send(s) else cancelOnComputer(s)
            } catch (e: CancellationException) { throw e } catch (_: Exception) { s.local = false }
        }
        s.capture = scope.launch(Dispatchers.IO) { capture(s) }
    }
    /** A short tap: it keeps listening until ✓. */
    fun toTap() { if (mode == VoiceMode.Press) mode = VoiceMode.Recording }
    fun toHold() { if (mode == VoiceMode.Press) mode = VoiceMode.Hold }

    @SuppressLint("MissingPermission")
    private suspend fun capture(s: Session) {
        val min = AudioRecord.getMinBufferSize(VoiceRate, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT)
        val record = runCatching { AudioRecord(MediaRecorder.AudioSource.VOICE_RECOGNITION, VoiceRate, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT, max(min, 8192)) }.getOrNull()
        if (record == null || record.state != AudioRecord.STATE_INITIALIZED) {
            record?.release()
            withContext(Dispatchers.Main) { if (session === s) { drop(s); pill = VoicePill("没拿到麦克风，可以继续打字", error = true, hideAfter = 6000) } }
            return
        }
        try {
            record.startRecording()
            val buffer = ShortArray(2048)
            while (currentCoroutineContext().isActive && !s.stopping) {
                val n = record.read(buffer, 0, buffer.size)
                if (n < 0) break
                if (n == 0) continue
                val piece = buffer.copyOf(n)
                val level = level(piece)
                val total = synchronized(s.lock) { s.all.add(piece); s.queue.add(piece); s.total += n; s.queued += n; s.total }
                withContext(Dispatchers.Main) {
                    if (session === s) { levels.add(level); if (levels.size > 160) levels.removeRange(0, levels.size - 160); seconds = total / VoiceRate }
                }
                if (total >= MaxSeconds * VoiceRate) { withContext(Dispatchers.Main) { finish() }; break }
            }
        } finally { runCatching { record.stop() }; record.release() }
    }

    /** Pieces go to the computer one request at a time; whatever piles up meanwhile goes in the next one. */
    private fun send(s: Session) {
        s.sender = scope.launch {
            while (true) {
                val piece = synchronized(s.lock) {
                    if (s.queued >= Piece || s.stopping && s.queued > 0) {
                        val all = join(s.queue)
                        val take = all.copyOfRange(0, minOf(all.size, MaxPiece))
                        s.queue.clear()
                        if (all.size > take.size) s.queue.add(all.copyOfRange(take.size, all.size))
                        s.queued = all.size - take.size
                        take
                    } else null
                }
                if (piece == null) { if (s.stopping && s.capture?.isActive != true) break; delay(60); continue }
                try {
                    val j = vm.voiceCall("voice/stream/chunk", mapOf("sid" to s.sid), pcmBytes(piece))
                    if (session === s) { heard = j.string("final"); partial = j.string("partial") }
                } catch (e: CancellationException) { throw e }
                catch (_: Exception) { s.local = false; break }  // the computer lost this recording: the cloud gets all of it
            }
        }
    }

    fun finish() {
        val s = session ?: return
        if (mode == VoiceMode.Finishing || mode == VoiceMode.Idle) return
        s.stopping = true
        mode = VoiceMode.Finishing
        busy = true
        scope.launch {
            try {
                s.capture?.join()
                val total = synchronized(s.lock) { s.total }
                if (total < VoiceRate / 2) { cancelOnComputer(s); end(); pill = VoicePill("太短了，没听到", hideAfter = 2000); return@launch }
                var text: String
                var source = "local"
                var raw = ""
                var tidied = false
                if (s.local && s.sid != null) s.sender?.join()
                if (s.local && s.sid != null) {
                    text = vm.voiceCall("voice/stream/end", mapOf("sid" to s.sid)).string("text").trim()
                } else {
                    source = "cloud"
                    val j = vm.voiceCall("voice", query(s), wavBytes(s.recording()), "audio/wav")
                    text = j.string("text").trim(); raw = j.string("raw").trim(); tidied = j.optBoolean("tidied")
                }
                end()
                if (text.isBlank()) {
                    pill = if (source == "local") VoicePill("没听清", "换云端识别", { cloudAgain(s) }, hideAfter = 7000) else VoicePill("没听清", hideAfter = 4000)
                    return@launch
                }
                place(s, text, raw, tidied, source)
            } catch (e: CancellationException) { throw e }
            catch (_: Exception) {
                end()
                pill = VoicePill("没转成文字", if (synchronized(s.lock) { s.all.isNotEmpty() }) "换云端识别" else null, { cloudAgain(s) }, error = true, hideAfter = 10000)
            } finally { busy = false }
        }
    }

    fun cancel() {
        val s = session ?: return
        drop(s)
        cancelOnComputer(s)
    }
    private fun drop(s: Session) { s.stopping = true; s.capture?.cancel(); s.sender?.cancel(); end(); session = null }
    private fun end() { mode = VoiceMode.Idle; heard = ""; partial = ""; levels.clear(); cancelArmed = false }
    private fun cancelOnComputer(s: Session) { val sid = s.sid ?: return; scope.launch { runCatching { vm.voiceCall("voice/stream/cancel", mapOf("sid" to sid)) } } }
    private fun query(s: Session) = mapOf("tidy" to if (voiceTidy(context)) "1" else "0", "app" to s.app, "title" to s.title.take(120), "folder" to s.folder.take(120))

    private fun place(s: Session, text: String, raw: String, tidied: Boolean, source: String) {
        val composer = vm.composer
        if (composer.state.value.key != s.chat) {
            pill = VoicePill("对话已经换了", "填到这里", {
                val now = composer.state.value
                now.key?.let { composer.insertVoice(it, text, now.draft.length, now.draft.length) }
                pill = null
            }, hideAfter = 12000)
            return
        }
        val placed = composer.insertVoice(s.chat, text, s.start, s.end) ?: return
        if (source == "cloud") { if (tidied && raw.isNotBlank() && raw != text) tidiedPill(s.chat, placed.copy(raw = raw)) else pill = null; return }
        if (voiceTidy(context)) tidyIn(s, placed)
    }
    private fun tidyIn(s: Session, placed: VoicePlacement) {
        pill = VoicePill("整理中…")
        scope.launch {
            try {
                val draft = vm.composer.state.value.draft
                val existing = draft.substring(max(0, placed.at - 400), placed.at.coerceAtMost(draft.length))
                val j = vm.deviceCall("voice/tidy", body = JSONObject().put("text", placed.raw).put("app", s.app).put("title", s.title).put("folder", s.folder).put("existing", existing))
                val text = j.string("text").trim()
                if (active) return@launch  // a new recording is on screen; this text stays as it is
                if (text.isBlank() || text == placed.text) { pill = null; return@launch }
                val swapped = vm.composer.swapVoice(s.chat, placed, text)
                if (swapped == null) { pill = null; return@launch }  // already being edited
                tidiedPill(s.chat, swapped.copy(raw = placed.raw))
            } catch (e: CancellationException) { throw e }
            catch (_: Exception) { if (!active) pill = VoicePill("整理没成功，保留原话", error = true, hideAfter = 3500) }
        }
    }
    private fun tidiedPill(chat: ChatKey, placed: VoicePlacement) {
        pill = VoicePill("已整理", "撤销", { vm.composer.swapVoice(chat, placed, placed.raw); pill = null }, hideAfter = 5000)
    }
    /** The phone still has the recording: the computer's cloud recogniser tries it. */
    private fun cloudAgain(s: Session) {
        if (busy || active) return
        busy = true
        pill = VoicePill("云端识别中…")
        scope.launch {
            try {
                val j = vm.voiceCall("voice", query(s), wavBytes(s.recording()), "audio/wav")
                val text = j.string("text").trim()
                if (text.isBlank()) { pill = VoicePill("云端也没听清", hideAfter = 4000); return@launch }
                val composer = vm.composer
                val now = composer.state.value
                val key = now.key
                val placed = if (key == s.chat) composer.insertVoice(key, text, now.draft.length, now.draft.length) else null
                if (placed == null) { pill = VoicePill("对话已经换了", hideAfter = 4000); return@launch }
                val raw = j.string("raw").trim()
                if (j.optBoolean("tidied") && raw.isNotBlank() && raw != text) tidiedPill(s.chat, placed.copy(raw = raw)) else pill = null
            } catch (e: CancellationException) { throw e }
            catch (_: Exception) { pill = VoicePill("云端识别没成功", error = true, hideAfter = 5000) }
            finally { busy = false }
        }
    }

    private companion object {
        fun join(parts: List<ShortArray>): ShortArray {
            val all = ShortArray(parts.sumOf { it.size })
            var at = 0
            parts.forEach { System.arraycopy(it, 0, all, at, it.size); at += it.size }
            return all
        }
        /** Loudness 0..1 of a piece (web pushLevel: dB of every fourth sample, -55 to -15). */
        fun level(samples: ShortArray): Float {
            var sum = 0.0
            var n = 0
            var i = 0
            while (i < samples.size) { val v = samples[i] / 32768.0; sum += v * v; n++; i += 4 }
            val db = 10 * log10(sum / max(1, n) + 1e-9)
            return ((db + 55) / 40).toFloat().coerceIn(0f, 1f)
        }
    }
}

@Composable
fun rememberPcVoice(vm: ReaderViewModel): PcVoice {
    val context = LocalContext.current.applicationContext
    val scope = rememberCoroutineScope()
    return remember(vm) { PcVoice(vm, context, scope) }
}

/** What has been heard so far, in the card in place of the text box (web .rec-text): settled words, then the guess. */
@Composable
fun VoiceLive(voice: PcVoice, modifier: Modifier = Modifier) {
    val p = LocalTeleply.current
    val scroll = rememberScrollState()
    LaunchedEffect(voice.heard, voice.partial) { scroll.scrollTo(scroll.maxValue) }
    Box(modifier.fillMaxWidth().heightIn(min = 28.dp, max = 180.dp).verticalScroll(scroll).semantics { liveRegion = LiveRegionMode.Polite }) {
        if (voice.heard.isEmpty() && voice.partial.isEmpty()) Text(if (voice.mode == VoiceMode.Finishing) "正在出字…" else "正在听…", style = MaterialTheme.typography.bodyLarge, color = p.muted)
        else Text(buildAnnotatedString { append(voice.heard); withStyle(SpanStyle(color = p.muted)) { append(voice.partial) } }, style = MaterialTheme.typography.bodyLarge, color = p.text)
    }
}

/** ✕, the sound wave and the time while recording (web .rec-bar); holding says 松开放入 · 上滑取消. */
@Composable
fun VoiceBar(voice: PcVoice, modifier: Modifier = Modifier) {
    val p = LocalTeleply.current
    Row(modifier.heightIn(min = 44.dp), verticalAlignment = Alignment.CenterVertically) {
        if (voice.mode == VoiceMode.Recording) TeleplyIconButton(TeleplyIcons.Close, "不要这段录音", voice::cancel, style = IconButtonStyle.Plain)
        else Spacer(Modifier.width(8.dp))
        val ink = p.text
        val faint = if (voice.cancelArmed || voice.mode == VoiceMode.Finishing) 0.35f else 1f
        Canvas(Modifier.weight(1f).height(28.dp).padding(horizontal = 4.dp)) {
            val step = 5.dp.toPx()
            val bar = 3.dp.toPx()
            val count = (size.width / step).toInt()
            val shown = voice.levels.takeLast(count)
            var x = size.width - shown.size * step
            shown.forEach { v ->
                val h = max(3.dp.toPx(), v * size.height)
                drawRoundRect(ink.copy(alpha = (0.35f + 0.65f * minOf(1f, v * 1.6f)) * faint), Offset(x, (size.height - h) / 2), Size(bar, h), CornerRadius(1.5.dp.toPx()))
                x += step
            }
            var dot = size.width - shown.size * step - step
            while (dot >= 0) { drawRect(ink.copy(alpha = 0.25f * faint), Offset(dot, size.height / 2 - 1.dp.toPx()), Size(bar, 2.dp.toPx())); dot -= step }
        }
        val time = "%d:%02d".format(voice.seconds / 60, voice.seconds % 60)
        Text(time, style = MaterialTheme.typography.bodySmall.copy(fontSize = 13.sp), color = p.muted, modifier = Modifier.padding(horizontal = 6.dp))
        if (voice.mode == VoiceMode.Hold) Text(if (voice.cancelArmed) "松开取消" else "松开放入 · 上滑取消", style = MaterialTheme.typography.bodySmall.copy(fontSize = 12.sp), color = if (voice.cancelArmed) p.error else p.muted, modifier = Modifier.padding(end = 4.dp))
    }
}

/**
 * The microphone (web voice-ui.js): tap to talk as long as you like and tap ✓; or hold, talk, let go to keep the words,
 * slide up and let go to drop them. Uses the computer's voice service; a computer with voice turned off leaves the
 * phone's own recogniser ([SystemMicButton]).
 */
@Composable
fun MicButton(vm: ReaderViewModel, voice: PcVoice, s: ReaderState, selection: () -> Pair<Int, Int>, onNote: (String) -> Unit) {
    val p = LocalTeleply.current
    val context = LocalContext.current
    val owner = LocalLifecycleOwner.current
    val haptic = LocalHapticFeedback.current
    val chat by vm.composer.state.collectAsStateWithLifecycle()
    val key = chat.key ?: return
    var computer by remember(s.device?.id) { mutableStateOf<Boolean?>(null) }
    LaunchedEffect(s.device?.id) { computer = runCatching { vm.voiceAvailable() }.getOrDefault(true) }
    if (computer == false) { SystemMicButton(vm.composer, onNote); return }
    val where by rememberUpdatedState(selection)
    val start: () -> Unit = {
        val (a, b) = where()
        haptic.performHapticFeedback(HapticFeedbackType.LongPress)
        voice.begin(key, s.app, s.chat?.title.orEmpty(), s.chat?.folder.orEmpty(), a, b)
    }
    val permission = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
        if (granted && owner.lifecycle.currentState.isAtLeast(Lifecycle.State.STARTED) && vm.composer.state.value.key == key) { start(); voice.toTap() }
        else if (!granted) onNote("没有麦克风权限：到系统设置 → 应用 → 遥应 原生预览 → 权限里打开麦克风；可以继续打字。")
    }
    fun permitted() = ContextCompat.checkSelfPermission(context, Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED
    // Leaving the app ends the recording and keeps what was said; leaving the conversation drops it.
    DisposableEffect(owner, key) {
        val observer = LifecycleEventObserver { _, event -> if (event == Lifecycle.Event.ON_STOP && voice.active) voice.finish() }
        owner.lifecycle.addObserver(observer)
        onDispose { owner.lifecycle.removeObserver(observer); if (voice.active) voice.cancel() }
    }
    val enabled = chat.ready && computer != null
    val mode = voice.mode
    val label = when (mode) { VoiceMode.Idle -> "语音输入"; VoiceMode.Recording -> "完成，把文字放进输入框"; VoiceMode.Finishing -> "正在出字"; else -> "松开放进输入框" }
    val (fill, ink) = when (mode) {
        VoiceMode.Recording -> p.text to p.page
        VoiceMode.Press, VoiceMode.Hold -> p.error to androidx.compose.ui.graphics.Color.White
        else -> androidx.compose.ui.graphics.Color.Transparent to p.muted
    }
    Box(
        Modifier.minimumInteractiveComponentSize().size(40.dp).clip(CircleShape).background(fill)
            .semantics {
                role = Role.Button; contentDescription = label
                onClick(label) {
                    when (voice.mode) {
                        VoiceMode.Idle -> if (enabled) { if (permitted()) { start(); voice.toTap() } else permission.launch(Manifest.permission.RECORD_AUDIO) }
                        VoiceMode.Recording -> voice.finish()
                        else -> Unit
                    }
                    true
                }
            }
            .pointerInput(enabled, key) {
                if (!enabled) return@pointerInput
                awaitEachGesture {
                    val down = awaitFirstDown()
                    down.consume()
                    when (voice.mode) {
                        VoiceMode.Recording -> { waitForUpOrCancellation(); voice.finish(); return@awaitEachGesture }
                        VoiceMode.Finishing, VoiceMode.Press, VoiceMode.Hold -> { waitForUpOrCancellation(); return@awaitEachGesture }
                        VoiceMode.Idle -> Unit
                    }
                    if (!permitted()) { waitForUpOrCancellation(); permission.launch(Manifest.permission.RECORD_AUDIO); return@awaitEachGesture }
                    start()
                    val up = withTimeoutOrNull(350) { waitForUpOrCancellation() }
                    if (up != null || voice.mode == VoiceMode.Idle) { voice.toTap(); return@awaitEachGesture }  // a tap: keep listening until ✓
                    voice.toHold()
                    val far = 70.dp.toPx()
                    while (true) {
                        val event = awaitPointerEvent()
                        val change = event.changes.firstOrNull { it.id == down.id } ?: break
                        voice.cancelArmed = down.position.y - change.position.y > far
                        change.consume()
                        if (!change.pressed) break
                    }
                    if (voice.cancelArmed) voice.cancel() else voice.finish()
                }
            },
        contentAlignment = Alignment.Center,
    ) {
        when (mode) {
            VoiceMode.Finishing -> CircularProgressIndicator(Modifier.size(20.dp), color = p.muted, strokeWidth = 2.dp)
            VoiceMode.Recording -> Icon(TeleplyIcons.Check, contentDescription = null, tint = ink, modifier = Modifier.size(20.dp))
            else -> Icon(TeleplyIcons.Mic, contentDescription = null, tint = if (enabled) ink else ink.copy(alpha = 0.35f), modifier = Modifier.size(22.dp))
        }
    }
}

