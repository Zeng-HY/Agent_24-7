package com.pocketagentdesk.teleply

import android.app.Service
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.net.ConnectivityManager
import android.net.Network
import android.os.Build
import android.os.IBinder
import androidx.core.app.ServiceCompat
import androidx.core.content.ContextCompat
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener

/**
 * 遥应通知's foreground service (design-2 §3.3): one WebSocket of this phone's own to the relay, running while the switch
 * is on, also after a reboot or an update. It keeps the phone's place in the stream (boot:seq), retries 5 s, 10 s, 20 s,
 * 40 s, 60 s, 120 s, then every 300 s, reconnects at once when the network comes back, and stops retrying on a 401 with
 * the one line the user can act on: 需要在设置里重新打开遥应通知.
 *
 * Everything the messages mean is in [PushModel] and [PushProtocol]; this class only carries it out.
 */
class PushService : Service() {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main.immediate)
    private lateinit var channel: PushChannel
    private lateinit var notifier: PushNotifier
    private var socket: WebSocket? = null
    private var api: RelayApi? = null
    private var retry: Job? = null
    private var offlineSweep: Job? = null
    private var attempt = 0
    private var generation = 0
    private var model = PushModel()
    private var origin = ""
    private var stopping = false
    private var foregroundStarted = false
    private var foregroundFailed = false
    private var networkCallback: ConnectivityManager.NetworkCallback? = null

    override fun onCreate() {
        super.onCreate()
        PushChannels.ensure(this)
        notifier = PushNotifier(this)
        channel = PushChannel(this, { serviceOrigin -> RelayApi(serviceOrigin, (application as NativeApplication).vault) }, BuildConfig.VERSION_NAME)
        watchNetwork()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == ActionStop) {
            stopping = true
            cancelRetry()
            closeSocket()
            // The conversation notices already in the shade stay; only the live cards and their overflow line go.
            notifier.clearCards()
            stopSelf()
            return START_NOT_STICKY
        }
        origin = intent?.getStringExtra(ExtraOrigin)?.takeIf { it.isNotBlank() } ?: channel.origin()
        if (origin.isBlank() || !channel.enabled.value || !isPushSecret(channel.secret())) {
            // Nothing to connect to, or the registration is gone: the switch is on but needs the settings page again.
            if (!startInForeground(PushPhase.NeedsRenew)) return START_NOT_STICKY
            needsRenew()
            return START_STICKY
        }
        if (foregroundStarted) {
            // The app came to the front again, or the boot receiver asked twice: the connection stays as it is.
            connect()
            return START_STICKY
        }
        if (!startInForeground(PushPhase.Connecting)) return START_NOT_STICKY
        connect()
        return START_STICKY
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onDestroy() {
        stopping = true
        cancelRetry()
        closeSocket()
        networkCallback?.let { runCatching { getSystemService(ConnectivityManager::class.java).unregisterNetworkCallback(it) } }
        networkCallback = null
        // Only the live cards go; the ordinary conversation notices stay in the shade (复核 2026-11-24).
        notifier.clearCards()
        scope.cancel()
        // A startForeground that was refused is the one state the user must act on: keep saying so after the service ends.
        if (foregroundFailed) PushRuntime.set(PushStatus(enabled = true, phase = PushPhase.Error, reason = PushForegroundFailedText))
        else PushRuntime.set(PushStatus(enabled = channel.enabled.value, phase = PushPhase.Stopped))
        super.onDestroy()
    }

    /** Returns false when the system refused the foreground service; the caller then stops instead of crashing. */
    private fun startInForeground(phase: PushPhase, text: String? = null): Boolean {
        PushRuntime.set(PushStatus(true, phase, online = model.onlineCount(), computers = model.computerCount()))
        val line = text ?: pushStatusText(PushRuntime.status.value)
        val notification = notifier.serviceNotification(line)
        return try {
            ServiceCompat.startForeground(
                this,
                notifier.serviceId,
                notification,
                if (Build.VERSION.SDK_INT >= 34) ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE else 0,
            )
            foregroundStarted = true
            true
        } catch (e: Exception) {
            // Android 12+ may refuse a foreground service started from the background: do not take the app down.
            foregroundFailed = true
            stopping = true
            cancelRetry()
            closeSocket()
            notifier.clearCards()
            PushRuntime.set(PushStatus(enabled = true, phase = PushPhase.Error, reason = PushForegroundFailedText))
            stopSelf()
            false
        }
    }

    private fun connect() {
        if (stopping || socket != null || origin.isBlank()) return
        if (!channel.enabled.value) return
        // A 401 is the one thing retrying cannot mend: the user has to open 遥应通知 again (design-2 §3.3).
        if (PushRuntime.status.value.phase == PushPhase.NeedsRenew) return
        val current = ++generation
        val relay = runCatching { RelayApi(origin, (application as NativeApplication).vault) }.getOrNull() ?: return
        api?.close()
        api = relay
        if (PushRuntime.status.value.phase != PushPhase.Receiving) {
            PushRuntime.set(PushStatus(true, PushPhase.Connecting, online = model.onlineCount(), computers = model.computerCount()))
            notifier.postService("正在连接中转…")
        }
        val since = channel.since()?.format()
        val created = runCatching { relay.pushWebSocket(channel.secret(), since, listener(current)) }.getOrNull()
        if (created == null) {
            api?.close()
            api = null
            scheduleRetry()
        } else {
            socket = created
        }
    }

    private fun listener(current: Int) = object : WebSocketListener() {
        override fun onOpen(webSocket: WebSocket, response: Response) {
            scope.launch {
                if (current != generation) return@launch
                attempt = 0
                cancelRetry()
                PushRuntime.set(PushStatus(true, PushPhase.Receiving, online = model.onlineCount(), computers = model.computerCount()))
                notifier.postService(pushStatusText(PushRuntime.status.value))
            }
        }

        override fun onMessage(webSocket: WebSocket, text: String) {
            scope.launch { if (current == generation) handle(text) }
        }

        override fun onClosing(webSocket: WebSocket, code: Int, reason: String) {
            webSocket.close(1000, null)
        }

        override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
            scope.launch { if (current == generation) lost(null) }
        }

        override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
            scope.launch { if (current == generation) lost(response?.code) }
        }
    }

    private fun handle(text: String) {
        val message = PushProtocol.parse(text) ?: return
        val now = System.currentTimeMillis()
        model = model.apply(message, now)
        channel.advanceSince(PushSince(message.boot, message.seq))
        when (message) {
            is PushMessage.Hello -> {
                notifier.showCards(model.liveCards(now))
                scheduleOfflineSweep()
                receiving()
            }
            is PushMessage.Conversation -> {
                notifier.showCards(model.liveCards(now))
                scheduleOfflineSweep()
                receiving()
            }
            is PushMessage.Computer -> {
                notifier.showCards(model.liveCards(now))
                scheduleOfflineSweep()
                receiving()
            }
            is PushMessage.Notice -> notifier.showNotice(message.notice)
            is PushMessage.Test -> notifier.showTest(pushTestNotice(message))
            is PushMessage.Unknown -> Unit
        }
    }

    /**
     * 电脑掉线 → its card says 电脑离线 and is taken away after 30 minutes even if nothing else arrives, so the phone
     * does not keep a card that will never change again (design-2 §3.4.2). With more than one computer offline, the
     * next one to expire is scheduled after this one.
     */
    private fun scheduleOfflineSweep() {
        val now = System.currentTimeMillis()
        val next = model.nextOfflineExpiry(now)
        offlineSweep?.cancel()
        offlineSweep = null
        if (next == null) return
        offlineSweep = scope.launch {
            delay(next - now)
            notifier.showCards(model.liveCards(System.currentTimeMillis()))
            scheduleOfflineSweep()
        }
    }

    private fun receiving() {
        if (PushRuntime.status.value.phase == PushPhase.Receiving && PushRuntime.status.value.online == model.onlineCount() && PushRuntime.status.value.computers == model.computerCount()) return
        PushRuntime.set(PushStatus(true, PushPhase.Receiving, online = model.onlineCount(), computers = model.computerCount()))
    }

    /** A socket that ended: a 401 needs the settings page, anything else is retried on the design's ladder. */
    private fun lost(code: Int?) {
        socket = null
        api?.close()
        api = null
        // No later callback of this socket may start another retry or another connection.
        generation += 1
        if (stopping) return
        if (code == 401) {
            needsRenew()
            return
        }
        scheduleRetry()
    }

    private fun needsRenew() {
        cancelRetry()
        PushRuntime.set(PushStatus(true, PushPhase.NeedsRenew, online = model.onlineCount(), computers = model.computerCount()))
        notifier.postService("需要在设置里重新打开遥应通知")
    }

    private fun scheduleRetry() {
        if (stopping) return
        val wait = pushRetryMillis(attempt)
        attempt += 1
        PushRuntime.set(PushStatus(true, PushPhase.Retrying, online = model.onlineCount(), computers = model.computerCount()))
        notifier.postService(pushStatusText(PushRuntime.status.value))
        cancelRetry()
        retry = scope.launch {
            delay(wait)
            if (isActive) connect()
        }
    }

    private fun cancelRetry() {
        retry?.cancel()
        retry = null
    }

    private fun closeSocket() {
        generation += 1
        socket?.close(1000, null)
        socket = null
        api?.close()
        api = null
    }

    /** 网络恢复: reconnect now and start the ladder over (design-2 §3.3). */
    private fun watchNetwork() {
        val manager = getSystemService(ConnectivityManager::class.java) ?: return
        val callback = object : ConnectivityManager.NetworkCallback() {
            override fun onAvailable(network: Network) {
                scope.launch {
                    if (stopping) return@launch
                    // A 401 needs the settings page, not another try when the network comes back.
                    if (PushRuntime.status.value.phase == PushPhase.NeedsRenew) return@launch
                    attempt = 0
                    if (socket == null) {
                        cancelRetry()
                        connect()
                    }
                }
            }
        }
        runCatching { manager.registerDefaultNetworkCallback(callback) }.onSuccess { networkCallback = callback }
    }

    companion object {
        const val ActionStart = "com.pocketagentdesk.teleply.push.START"
        const val ActionStop = "com.pocketagentdesk.teleply.push.STOP"
        const val ExtraOrigin = "teleply.push.origin"

        fun start(context: Context, origin: String) {
            val intent = Intent(context, PushService::class.java).setAction(ActionStart).putExtra(ExtraOrigin, origin)
            ContextCompat.startForegroundService(context, intent)
        }

        fun stop(context: Context) { context.stopService(Intent(context, PushService::class.java)) }
    }
}

/**
 * 开机后、App 更新后，如果「遥应通知」开着就自动起 (design-2 §3.3). A specialUse foreground service may start from
 * BOOT_COMPLETED on Android 15; the receiver only starts it, the service decides whether it can connect.
 */
class PushBootReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent?) {
        if (intent?.action != Intent.ACTION_BOOT_COMPLETED && intent?.action != Intent.ACTION_MY_PACKAGE_REPLACED) return
        if (!pushEnabledIn(context)) return
        val origin = pushOriginIn(context)
        if (origin.isBlank()) return
        runCatching { PushService.start(context, origin) }
    }
}

/**
 * 设置页's side of 遥应通知 (design-2 §3.5): register, start or stop the service, keep the relay's place, and the one
 * 试推. It owns no Android layout; the page only calls it and reads [PushRuntime] for the status line.
 */
class PushController(private val context: Context, apiFactory: (String) -> ReadApi, version: String) {
    val channel = PushChannel(context, apiFactory, version)

    val enabled get() = channel.enabled.value

    /** 打开: register this phone, then keep one connection running. Throws in the service's words and leaves the switch off. */
    suspend fun enable(origin: String) {
        channel.register(origin)
        PushRuntime.set(PushStatus(true, PushPhase.Connecting))
        PushService.start(context, origin)
    }

    /** 关掉: the relay forgets this phone first, then the service stops; a relay that cannot be reached does not keep it on. */
    suspend fun disable() {
        runCatching { channel.unregister() }
        channel.disable()
        PushService.stop(context)
        PushRuntime.set(PushStatus(false))
    }

    suspend fun test() = channel.test()

    /** 退出登录: unregister, stop, and leave nothing of the account's notifications behind (design-2 §1.1). */
    suspend fun signedOut() {
        channel.signedOut()
        PushService.stop(context)
        PushRuntime.set(PushStatus(false))
    }

    fun moved(from: String, to: String) {
        channel.moved(from, to)
        if (channel.enabled.value) runCatching { PushService.start(context, to) }
    }

    /** The app came to the front: if the switch is on, the service should be running (it is idempotent). */
    fun ensureRunning() {
        if (channel.enabled.value && channel.origin().isNotBlank()) runCatching { PushService.start(context, channel.origin()) }
    }
}
