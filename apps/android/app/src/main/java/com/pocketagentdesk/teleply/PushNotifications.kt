package com.pocketagentdesk.teleply

import android.Manifest
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.content.ContextCompat

/**
 * 遥应通知's three channels and its notifications (design-2 §3.4): conversation notices grouped by computer, the live
 * cards on the lock screen, and the foreground service's quiet line. All of them use this app's own single-colour mark,
 * never another app's.
 */
object PushChannels {
    const val Notice = "teleply_notice"
    const val Live = "teleply_live"
    const val Service = "teleply_service"

    /** Created at every service start; creating one that exists only updates its words. */
    fun ensure(context: Context) {
        val manager = context.getSystemService(NotificationManager::class.java)
        manager.createNotificationChannel(NotificationChannel(Notice, "对话通知", NotificationManager.IMPORTANCE_HIGH).apply {
            description = "对话结束、失败或等你处理时通知；同一台电脑的通知收在一组里"
            lockscreenVisibility = Notification.VISIBILITY_PUBLIC
            enableVibration(true)
        })
        manager.createNotificationChannel(NotificationChannel(Live, "进行中的对话", NotificationManager.IMPORTANCE_DEFAULT).apply {
            description = "正在干活或等你的对话，显示为锁屏上的实时卡片"
            lockscreenVisibility = Notification.VISIBILITY_PUBLIC
            setShowBadge(false)
        })
        manager.createNotificationChannel(NotificationChannel(Service, "后台连接", NotificationManager.IMPORTANCE_LOW).apply {
            description = "保持一条到你自己中转的连接；长按关掉这一类，服务照常运行"
            lockscreenVisibility = Notification.VISIBILITY_SECRET
            setShowBadge(false)
        })
    }

    fun allowed(context: Context): Boolean =
        (Build.VERSION.SDK_INT < 33 || ContextCompat.checkSelfPermission(context, Manifest.permission.POST_NOTIFICATIONS) == PackageManager.PERMISSION_GRANTED) &&
            NotificationManagerCompat.from(context).areNotificationsEnabled() &&
            context.getSystemService(NotificationManager::class.java).getNotificationChannel(Notice)?.importance != NotificationManager.IMPORTANCE_NONE
}

/** Extras the notification carries into MainActivity: which computer, which app, which conversation (design-2 §3.4.1). */
const val PushExtraDevice = "teleply.push.device"
const val PushExtraApp = "teleply.push.app"
const val PushExtraChat = "teleply.push.chat"

private const val NoticeId = 7201
private const val LiveId = 7301
private const val LiveOverflowId = 7302
private const val ServiceId = 7200
private const val TestId = 7202

/**
 * Draws what [PushModel] derived. It keeps no rules of its own: three cards at most, 电脑离线, gone and the group summary
 * words all come from the pure model, so the tests cover them without Android.
 */
class PushNotifier(private val context: Context) {
    private val manager = NotificationManagerCompat.from(context)
    private val noticesByDevice = mutableMapOf<String, MutableSet<String>>()
    private val shownCards = mutableSetOf<String>()
    private var overflowShown = false

    fun showNotice(notice: PushNotice) {
        val builder = NotificationCompat.Builder(context, PushChannels.Notice)
            .setSmallIcon(R.drawable.ic_push)
            .setContentTitle(notice.title)
            .setContentText(notice.body)
            .setStyle(NotificationCompat.BigTextStyle().bigText(notice.body))
            .setSubText(notice.subtitle.takeIf { it.isNotBlank() })
            .setContentIntent(open(notice.device, notice.app, notice.chat, notice.key))
            .setAutoCancel(true)
            .setVisibility(NotificationCompat.VISIBILITY_PUBLIC)
            .setGroup(notice.group.ifBlank { "teleply_test" })
            .setWhen(System.currentTimeMillis())
        if (!notice.loud) builder.setSilent(true)
        notify(notice.key, NoticeId, builder.build())
        if (notice.group.isNotBlank()) {
            val tags = noticesByDevice.getOrPut(notice.group) { mutableSetOf() }
            tags += notice.key
            if (tags.size >= 2) showGroupSummary(notice.group, tags.size) else cancelGroupSummary(notice.group)
        }
    }

    fun showTest(notice: PushNotice) {
        val builder = NotificationCompat.Builder(context, PushChannels.Notice)
            .setSmallIcon(R.drawable.ic_push)
            .setContentTitle(notice.title)
            .setContentText(notice.body)
            .setStyle(NotificationCompat.BigTextStyle().bigText(notice.body))
            .setSubText(notice.subtitle.takeIf { it.isNotBlank() })
            .setContentIntent(open("", "", "", "test"))
            .setAutoCancel(true)
            .setVisibility(NotificationCompat.VISIBILITY_PUBLIC)
        notify("test", TestId, builder.build())
    }

    private fun showGroupSummary(device: String, count: Int) {
        val builder = NotificationCompat.Builder(context, PushChannels.Notice)
            .setSmallIcon(R.drawable.ic_push)
            .setContentTitle(pushGroupSummary(count))
            .setContentIntent(open("", "", "", "summary:$device"))
            .setGroup(device)
            .setGroupSummary(true)
            .setAutoCancel(true)
            .setOnlyAlertOnce(true)
            .setSilent(true)
            .setVisibility(NotificationCompat.VISIBILITY_PUBLIC)
        notify("summary:$device", NoticeId, builder.build())
    }

    private fun cancelGroupSummary(device: String) {
        manager.cancel("summary:$device", NoticeId)
        noticesByDevice[device]?.let { if (it.isEmpty()) noticesByDevice.remove(device) }
    }

    /** The lock-screen cards: one per working or waiting conversation, the overflow line, and nothing for what ended. */
    fun showCards(cards: PushLiveCards) {
        val wanted = cards.cards.map { it.key }.toSet()
        (shownCards - wanted).forEach { manager.cancel(it, LiveId) }
        shownCards.clear()
        shownCards += wanted
        cards.cards.forEach { card ->
            val builder = NotificationCompat.Builder(context, PushChannels.Live)
                .setSmallIcon(R.drawable.ic_push)
                .setContentTitle(card.title)
                .setContentText(card.body)
                .setStyle(NotificationCompat.BigTextStyle().bigText(card.body))
                .setSubText(card.subText.takeIf { it.isNotBlank() })
                .setWhen(if (card.startedAt > 0) card.startedAt else System.currentTimeMillis())
                .setUsesChronometer(card.startedAt > 0)
                .setShowWhen(true)
                .setContentIntent(open(card.device, card.app, card.chat, card.key))
                .setOngoing(true)
                .setOnlyAlertOnce(true)
                .setSilent(true)
                .setVisibility(NotificationCompat.VISIBILITY_PUBLIC)
                .setRequestPromotedOngoing(true)
            notify(card.key, LiveId, builder.build())
        }
        if (cards.overflow > 0) {
            val builder = NotificationCompat.Builder(context, PushChannels.Live)
                .setSmallIcon(R.drawable.ic_push)
                .setContentTitle(pushOverflowTitle(cards.overflow))
                .setContentText("打开遥应查看")
                .setContentIntent(open("", "", "", "overflow"))
                .setOngoing(true)
                .setOnlyAlertOnce(true)
                .setSilent(true)
                .setVisibility(NotificationCompat.VISIBILITY_PUBLIC)
                .setRequestPromotedOngoing(true)
            notify("overflow", LiveOverflowId, builder.build())
            overflowShown = true
        } else if (overflowShown) {
            manager.cancel("overflow", LiveOverflowId)
            overflowShown = false
        }
    }

    /** 关掉 or 退出登录: the cards and the notices this phone posted go; the relay's stream has stopped anyway. */
    fun clear() {
        shownCards.forEach { manager.cancel(it, LiveId) }
        shownCards.clear()
        if (overflowShown) manager.cancel("overflow", LiveOverflowId)
        overflowShown = false
        noticesByDevice.forEach { (device, tags) ->
            tags.forEach { manager.cancel(it, NoticeId) }
            manager.cancel("summary:$device", NoticeId)
        }
        noticesByDevice.clear()
        manager.cancel("test", TestId)
    }

    /** The foreground service's own line; its words say what the connection is doing (design-2 §3.4.3). */
    fun serviceNotification(text: String): Notification =
        NotificationCompat.Builder(context, PushChannels.Service)
            .setSmallIcon(R.drawable.ic_push)
            .setContentTitle("遥应在接收通知")
            .setContentText(text)
            .setContentIntent(open("", "", "", "service"))
            .setOngoing(true)
            .setOnlyAlertOnce(true)
            .setSilent(true)
            .setShowWhen(false)
            .setVisibility(NotificationCompat.VISIBILITY_SECRET)
            .build()

    fun postService(text: String) { notify(null, ServiceId, serviceNotification(text)) }

    val serviceId: Int get() = ServiceId

    private fun notify(tag: String?, id: Int, notification: Notification) {
        // Permission is the settings page's business; the service still runs with the channel hidden, as the design says.
        @Suppress("MissingPermission")
        if (tag == null) manager.notify(id, notification) else manager.notify(tag, id, notification)
    }

    private fun open(device: String, app: String, chat: String, tag: String): PendingIntent {
        val intent = Intent(context, MainActivity::class.java)
            .setAction("teleply.push.$tag")
            .addFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP or Intent.FLAG_ACTIVITY_SINGLE_TOP)
        if (device.isNotBlank()) intent.putExtra(PushExtraDevice, device)
        if (app.isNotBlank()) intent.putExtra(PushExtraApp, app)
        if (chat.isNotBlank()) intent.putExtra(PushExtraChat, chat)
        return PendingIntent.getActivity(context, tag.hashCode(), intent, PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
    }
}
