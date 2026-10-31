package com.pocketagentdesk.teleply

import android.Manifest
import android.app.*
import android.app.job.*
import android.content.*
import android.content.pm.PackageManager
import android.os.Build
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.content.ContextCompat
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.*
import org.json.JSONObject
import java.util.UUID

data class WatchTarget(val origin:String,val key:ChatKey,val nonce:String)
data class WatchSignal(val running:Boolean,val questions:String,val turn:String,val status:String) {
    fun json()=JSONObject().put("running",running).put("questions",questions).put("turn",turn).put("status",status).toString()
    companion object {
        fun parse(raw:String):WatchSignal?=runCatching { JSONObject(raw).let { WatchSignal(it.optBoolean("running"),it.string("questions"),it.string("turn"),it.string("status")) } }.getOrNull()
        fun from(control:Control):WatchSignal {
            val raw=JSONObject(control.raw)
            val questions=raw.rows("questions") { it }.filter { it.string("status") !in setOf("answered","expired","completed") }.map { it.string("id").ifBlank { it.string("callId") } }+
                raw.rows("interactions") { it }.filter { it.string("event") in setOf("approval/request","user-questions/request") }.map { it.string("eventId") }+
                listOfNotNull(raw.optJSONObject("prompt")?.takeIf { it.length()>0 }?.let { raw.string("action_revision").ifBlank { "prompt" } })
            val last=control.turns.entries.lastOrNull()
            return WatchSignal(control.running,questions.filter { it.isNotBlank() }.sorted().joinToString("|"),last?.key ?: control.turn,last?.value.orEmpty())
        }
    }
}
fun notificationChange(old:WatchSignal?,now:WatchSignal):String?=when {
    old==null -> null
    now.questions.isNotBlank() && now.questions!=old.questions -> "关注的会话需要处理问题或批准，请打开核对。"
    !now.running && (old.running || now.turn.isNotBlank() && now.turn!=old.turn && now.status in setOf("completed","interrupted","failed")) -> when(now.status) {
        "completed" -> "关注的会话已完成当前轮次。";"interrupted" -> "关注的会话已停止当前轮次。";"failed" -> "关注的会话报告了失败，请打开核对。";else -> "关注的会话运行状态有变化，请打开核对。"
    }
    else -> null
}
/**
 * Whether [target] is still this phone's: the same service and sign-in. Nothing saved is the default service, which the
 * app shows as [DefaultOrigin] (10-31: compared as written, the check could not be switched on there at all).
 */
fun watchBelongs(target:WatchTarget,prefs:Preferences)=sameService(target.origin,prefs.origin.ifBlank { DefaultOrigin }) && target.key.scope==prefs.scope && prefs.scope.isNotBlank()
class WatchManager(private val context:Context,private val store:ReaderStore,private val apiFactory:(String)->ReadApi) {
    private val prefs=context.getSharedPreferences("native_watch",Context.MODE_PRIVATE)
    private val mutable=MutableStateFlow(readTarget());val state=mutable.asStateFlow()
    @Volatile var foreground:ChatKey?=null
    private fun readTarget():WatchTarget?=runCatching {
        val j=JSONObject(prefs.getString("target",null) ?: error("No target"))
        val app=j.getString("app");require(app in setOf("codex","claude","deepseek"))
        WatchTarget(serviceOrigin(j.getString("origin")).toString(),ChatKey(j.getString("scope"),j.getString("device"),j.getString("chat"),app),j.getString("nonce"))
    }.getOrNull()
    fun allowed()=(Build.VERSION.SDK_INT<33 || ContextCompat.checkSelfPermission(context,Manifest.permission.POST_NOTIFICATIONS)==PackageManager.PERMISSION_GRANTED) && NotificationManagerCompat.from(context).areNotificationsEnabled() && context.getSystemService(NotificationManager::class.java).getNotificationChannel(CHANNEL)?.importance!=NotificationManager.IMPORTANCE_NONE
    fun channel() { context.getSystemService(NotificationManager::class.java).createNotificationChannel(NotificationChannel(CHANNEL,"会话状态更新",NotificationManager.IMPORTANCE_DEFAULT).apply { description="用户选择会话的后台定期检查，可能因系统省电而延迟";lockscreenVisibility=Notification.VISIBILITY_PRIVATE }) }
    suspend fun enable(origin:String,key:ChatKey) {
        check(allowed()) { "通知权限尚未开启" }
        val candidate=WatchTarget(origin,key,UUID.randomUUID().toString());check(watchBelongs(candidate,store.preferences())) { "登录范围已变化，请重新选择会话" }
        val api=apiFactory(origin).forSource(key.app)
        val control=try { check(api.account().devices.any { it.id==key.device && it.connectable }) { "电脑不可用，尚未开启检查" };api.control(key.device,key.chat).also { check(it.available) { "来源状态不可读取，尚未开启检查" } } } finally { api.close() }
        check(watchBelongs(candidate,store.preferences())) { "账号已变化，未开启检查" }
        channel()
        check(allowed()) { "通知权限或通知渠道已关闭，未开启后台检查" }
        val j=JSONObject().put("origin",origin).put("scope",key.scope).put("device",key.device).put("app",key.app).put("chat",key.chat).put("nonce",candidate.nonce)
        check(prefs.edit().putString("target",j.toString()).putString("signal",WatchSignal.from(control).json()).commit())
        mutable.value=candidate
        val result=context.getSystemService(JobScheduler::class.java).schedule(JobInfo.Builder(JOB,ComponentName(context,WatchJobService::class.java)).setRequiredNetworkType(JobInfo.NETWORK_TYPE_ANY).setRequiresBatteryNotLow(true).setPeriodic(JobInfo.getMinPeriodMillis()).setPersisted(true).build())
        if(result!=JobScheduler.RESULT_SUCCESS) { disable();error("系统未接受后台检查任务") }
    }
    fun disable() { context.getSystemService(JobScheduler::class.java).cancel(JOB);NotificationManagerCompat.from(context).cancel(NOTICE);prefs.edit().clear().commit();mutable.value=null }
    /**
     * 10-31 ([moveService]): the service's address changed from [from] to [to], the same service. The conversation
     * checked there goes along with its token, so a notice already shown still opens it.
     */
    fun moved(from:String,to:String) {
        val t=state.value ?: return
        if(!sameService(t.origin,from)) return
        val j=runCatching { JSONObject(prefs.getString("target",null)!!) }.getOrNull() ?: return
        if(prefs.edit().putString("target",j.put("origin",to).toString()).commit()) mutable.value=t.copy(origin=to)
    }
    suspend fun resolve(nonce:String):WatchTarget?=state.value?.takeIf { it.nonce==nonce && watchBelongs(it,store.preferences()) }
    suspend fun checkOnce():String {
        val target=state.value ?: return "未开启"
        if(!allowed()) return "通知权限未开启"
        if(!watchBelongs(target,store.preferences())) { disable();return "登录范围已变化，已停止检查" }
        val api=apiFactory(target.origin).forSource(target.key.app)
        try {
            val account=api.account()
            if(account.devices.none { it.id==target.key.device }) { disable();return "电脑归属已变化，已停止检查" }
            if(account.devices.none { it.id==target.key.device && it.connectable }) return "电脑离线，保留原状态"
            val control=api.control(target.key.device,target.key.chat)
            if(!control.available) return "来源不可读取，保留原状态"
            if(state.value?.nonce!=target.nonce || !watchBelongs(target,store.preferences())) return "检查对象已变化"
            val signal=WatchSignal.from(control)
            val text=notificationChange(WatchSignal.parse(prefs.getString("signal","").orEmpty()),signal)
            if(text!=null && foreground!=target.key && allowed()) {
                channel()
                val intent=Intent(context,MainActivity::class.java).putExtra(EXTRA,target.nonce).setAction("teleply.watch.${target.nonce}").addFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP or Intent.FLAG_ACTIVITY_SINGLE_TOP)
                val pending=PendingIntent.getActivity(context,NOTICE,intent,PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
                val public=NotificationCompat.Builder(context,CHANNEL).setSmallIcon(android.R.drawable.ic_dialog_info).setContentTitle("遥应有一条状态更新").build()
                val notification=NotificationCompat.Builder(context,CHANNEL).setSmallIcon(android.R.drawable.ic_dialog_info).setContentTitle("遥应 · 会话状态更新").setContentText(text).setContentIntent(pending).setAutoCancel(true).setVisibility(NotificationCompat.VISIBILITY_PRIVATE).setPublicVersion(public).build()
                // Permission is rechecked immediately before posting; revocation is handled below.
                @Suppress("MissingPermission")
                NotificationManagerCompat.from(context).notify(NOTICE,notification)
            }
            if(state.value?.nonce==target.nonce) prefs.edit().putString("signal",signal.json()).commit()
            return "已核对当前状态"
        } catch(e:ServiceFailure) { return if(e.status==401) "登录失效，请重新登录后核对" else "暂时无法读取，保留原状态" }
        catch(_:Exception) { return "暂时无法读取，保留原状态" }
        finally { api.close() }
    }
    companion object { const val JOB=4104;const val NOTICE=4105;const val CHANNEL="native_chat_status";const val EXTRA="teleply_watch_token" }
}
class WatchJobService:JobService() {
    private val scope=CoroutineScope(SupervisorJob()+Dispatchers.Main.immediate);private var work:Job?=null
    override fun onStartJob(params:JobParameters):Boolean { work=scope.launch { try { (application as NativeApplication).watch.checkOnce() } finally { if(isActive) jobFinished(params,false) } };return true }
    override fun onStopJob(params:JobParameters):Boolean { work?.cancel();return true }
    override fun onDestroy() { scope.cancel();super.onDestroy() }
}
