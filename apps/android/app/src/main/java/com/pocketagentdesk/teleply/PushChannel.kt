package com.pocketagentdesk.teleply

import android.content.Context
import android.os.Build
import java.security.MessageDigest
import java.security.SecureRandom
import java.util.Locale
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow

/**
 * 遥应通知 (安卓 1.0.10, design-2 §1.1): this phone's own key and its registration with the relay's account service.
 *
 * The key is 32 random bytes kept as 64 lower-case hex digits in app-private storage; the relay only ever sees
 * sha256(key) — the same thing it stores for an iPhone's APNs token. The key never leaves the phone in any other form,
 * and is never written to a log.
 */
const val PushSecretBytes = 32
private val PushSecretPattern = Regex("[0-9a-f]{64}")

fun newPushSecret(): String {
    val bytes = ByteArray(PushSecretBytes)
    SecureRandom().nextBytes(bytes)
    return bytes.joinToString("") { "%02x".format(it) }
}

fun isPushSecret(value: String): Boolean = PushSecretPattern.matches(value)

fun sha256Hex(value: String): String =
    MessageDigest.getInstance("SHA-256").digest(value.toByteArray(Charsets.UTF_8)).joinToString("") { "%02x".format(it) }

/** The fingerprint registered with the relay: sha256 of the key's 64 hex digits, never the key itself (design-2 §1.1). */
fun pushToken(secret: String): String = sha256Hex(secret)

/** The phone's name for the relay's list: maker and model, at most 40 characters as the relay takes. */
fun pushLabel(manufacturer: String, model: String): String = listOf(manufacturer.trim(), model.trim()).filter { it.isNotEmpty() }.joinToString(" ").take(40)

/** The words the relay writes notices in: simplified Chinese for a Chinese phone, English otherwise (design-2 §1.1). */
fun pushLanguage(languageTag: String): String = if (languageTag.lowercase(Locale.ROOT).startsWith("zh")) "zh-Hans" else "en"

/**
 * Where this phone's stream stood: the relay boot it was reading and the last message it handled (design-2 §1.3, §3.3).
 * Sent as `since=<boot>:<seq>`; empty or unreadable means "no since", and the relay starts from its hello.
 */
data class PushSince(val boot: String, val seq: Long) {
    fun format(): String = if (boot.isBlank()) "" else "$boot:$seq"
    companion object {
        fun parse(raw: String?): PushSince? {
            val text = raw?.trim().orEmpty()
            if (text.isEmpty()) return null
            val split = text.lastIndexOf(':')
            if (split <= 0 || split == text.length - 1) return null
            val boot = text.substring(0, split)
            val seq = text.substring(split + 1).toLongOrNull() ?: return null
            if (seq < 0) return null
            return PushSince(boot, seq)
        }
    }
}

/** What the connection is doing, for the settings page's status line (design-2 §3.5). */
enum class PushPhase { Stopped, Connecting, Receiving, Retrying, NeedsRenew, Error }

data class PushStatus(val enabled: Boolean = false, val phase: PushPhase = PushPhase.Stopped, val online: Int = 0, val computers: Int = 0, val reason: String? = null)

/** The service's live status, read by the settings page (memory only; the switch itself is kept in storage). */
object PushRuntime {
    private val mutable = MutableStateFlow(PushStatus())
    val status: StateFlow<PushStatus> = mutable
    fun set(value: PushStatus) { mutable.value = value }
}

/** 「在接收 · 2 台电脑在线」「连不上中转，正在重试」「需要重新打开」 (design-2 §3.5). */
fun pushStatusText(status: PushStatus): String = when {
    !status.enabled -> "未开启"
    status.phase == PushPhase.NeedsRenew -> "需要重新打开"
    status.phase == PushPhase.Receiving -> if (status.online > 0) "在接收 · ${status.online} 台电脑在线" else "在接收 · 没有电脑在线"
    status.phase == PushPhase.Connecting || status.phase == PushPhase.Retrying -> "连不上中转，正在重试"
    status.phase == PushPhase.Error -> status.reason?.takeIf { it.isNotBlank() } ?: "连接出错"
    else -> "未开启"
}

/**
 * Everything the phone keeps for 遥应通知: its key, the fingerprint, whether it is on, the service address it registered
 * with, and where its stream stood. Registration is a call to the existing account service with the existing cookie;
 * a phone that has not signed in cannot register and is told so in the service's own words.
 */
class PushChannel(private val context: Context, private val apiFactory: (String) -> ReadApi, private val version: String) {
    private val app = context.applicationContext
    private val prefs = app.getSharedPreferences("native_push", Context.MODE_PRIVATE)
    private val enabledFlow = MutableStateFlow(prefs.getBoolean(KeyEnabled, false))
    val enabled: StateFlow<Boolean> = enabledFlow

    fun secret(): String = prefs.getString(KeySecret, null)?.takeIf(::isPushSecret)
        ?: newPushSecret().also { check(prefs.edit().putString(KeySecret, it).commit()) }

    /** What the relay stores: sha256 of [secret]. */
    fun token(): String = pushToken(secret())

    fun origin(): String = prefs.getString(KeyOrigin, "").orEmpty()

    fun label(): String = pushLabel(Build.MANUFACTURER.orEmpty(), Build.MODEL.orEmpty())

    fun language(): String = pushLanguage(Locale.getDefault().toLanguageTag())

    fun since(): PushSince? = PushSince.parse(prefs.getString(KeySince, null))

    fun saveSince(value: PushSince) { prefs.edit().putString(KeySince, value.format()).apply() }

    fun clearSince() { prefs.edit().remove(KeySince).apply() }

    /** Keep the stream where it stood, if [value] belongs to the same relay boot; a new boot starts from hello. */
    fun advanceSince(value: PushSince) {
        val old = since()
        if (old != null && old.boot == value.boot && old.seq >= value.seq) return
        saveSince(value)
    }

    /** 打开: register this phone for [origin]. Throws in the service's words (no sign-in, offline…) and keeps the switch off. */
    suspend fun register(origin: String) {
        val service = apiFactory(origin)
        try { service.pushRegister(token(), label(), version, language()) } finally { service.close() }
        check(prefs.edit().putBoolean(KeyEnabled, true).putString(KeyOrigin, origin).commit())
        enabledFlow.value = true
    }

    /** 关闭/退出登录前: the relay forgets this fingerprint. */
    suspend fun unregister() {
        val service = apiFactory(origin().ifBlank { return })
        try { service.pushUnregister(token()) } finally { service.close() }
    }

    /** 试推一条: the relay pushes one notice through the WebSocket to this phone. */
    suspend fun test() {
        val service = apiFactory(origin().ifBlank { error("还没有登记遥应通知") })
        try { service.pushTest(token()) } finally { service.close() }
    }

    /** The switch and the saved place go; the key stays so registering again is the same phone to the relay. */
    fun disable() {
        prefs.edit().putBoolean(KeyEnabled, false).remove(KeySince).apply()
        enabledFlow.value = false
    }

    /** 退出登录: nothing of the account's notifications is left (best effort: the sign-out goes on either way). */
    suspend fun signedOut() {
        if (enabledFlow.value) runCatching { unregister() }
        disable()
    }

    /** The service address moved (10-31 [moveService]): the same service, so the registration goes along. */
    fun moved(from: String, to: String) {
        if (sameService(origin(), from)) prefs.edit().putString(KeyOrigin, to).apply()
    }

    private companion object {
        const val KeySecret = "secret"
        const val KeyEnabled = "enabled"
        const val KeyOrigin = "origin"
        const val KeySince = "since"
    }
}

/** 「后台没起来」: a foreground service the system refused (Android 12+ from the background). Opening the app tries again. */
const val PushForegroundFailedText = "后台没起来：打开遥应一次就好"

/** `POST /account/push/<action>` answers; a phone that is not signed in gets 401 and the page says so. */
fun pushFailureText(error: Exception): String = when {
    error is ServiceFailure && error.status == 401 -> "登录已失效，请重新登录后再打开遥应通知"
    error is ServiceFailure && error.status == 404 -> "这个服务还没有安卓通知，请稍后再试"
    error.message?.isNotBlank() == true -> error.message.orEmpty()
    else -> "连不上中转，请检查网络后重试"
}

/** A line for 试推一条 after the relay accepted it. */
fun pushTestText(): String = "已请中转发一条，稍等就到"

/**
 * The saved switch, for the boot receiver and the app's start: true when 遥应通知 was on and a key exists. Reading this
 * starts nothing; [PushService] decides whether it can connect.
 */
fun pushEnabledIn(context: Context): Boolean =
    context.getSharedPreferences("native_push", Context.MODE_PRIVATE).let { it.getBoolean("enabled", false) && isPushSecret(it.getString("secret", null).orEmpty()) }

fun pushOriginIn(context: Context): String = context.getSharedPreferences("native_push", Context.MODE_PRIVATE).getString("origin", "").orEmpty()

/**
 * 后台运行设置's one line for this phone's maker (design-2 §3.5): a Chinese sentence naming the exact page, or the
 * general one for a maker without a special page. Pure, so the words are unit-tested.
 */
fun backgroundHint(manufacturer: String): String {
    val name = manufacturer.lowercase()
    return when {
        name.contains("xiaomi") || name.contains("redmi") || name.contains("poco") ->
            "小米/红米：设置 → 应用设置 → 遥应 → 省电策略，选「无限制」；再到最近任务里给遥应加锁。"
        name.contains("huawei") || name.contains("honor") ->
            "华为/荣耀：设置 → 应用 → 遥应 → 耗电详情，关掉「自动管理」，允许后台活动。"
        name.contains("oppo") || name.contains("oneplus") || name.contains("realme") ->
            "OPPO/一加/真我：设置 → 电池 → 应用耗电管理 → 遥应，允许「允许后台运行」。"
        name.contains("vivo") || name.contains("iqoo") ->
            "vivo/iQOO：设置 → 电池 → 后台耗电管理 → 遥应，选「允许后台高耗电」。"
        name.contains("samsung") ->
            "三星：设置 → 电池 → 后台使用限制，把遥应放进「从不休眠的应用」。"
        else -> "在系统设置里允许遥应后台运行，并关掉对它的省电限制；有的手机还要在最近任务里加锁。"
    }
}

