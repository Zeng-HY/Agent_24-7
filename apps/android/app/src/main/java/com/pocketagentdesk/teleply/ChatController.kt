package com.pocketagentdesk.teleply

import java.util.UUID
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.*
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import org.json.JSONObject

/** [focus] counts requests for the input to take the keyboard (继续修改 a Codex plan); [hint] then shows in the empty box. */
data class ComposerState(val key:ChatKey?=null,val draft:String="",val ready:Boolean=false,val submitting:Boolean=false,val control:Control=Control(),val connection:String="实时连接未启动",val submissions:List<Submission> = emptyList(),val error:String?=null,val revision:Int=0,val draftReset:Int=0,val focus:Int=0,val hint:String="")

/**
 * Kept in a send's local copy (its body), never sent: where Claude's record stood when the computer pressed Enter and
 * the words to look for there (web chat/check), and, for a send the computer turned away, what was in Claude's box and why.
 */
internal const val ClaudeOffset="_claude_offset"
internal const val ClaudeCheckText="_claude_check_text"
internal const val DesktopDraftKey="_desktop_draft"
internal const val SendErrorKey="_send_error"
private val LocalKeys=listOf(ClaudeOffset,ClaudeCheckText,DesktopDraftKey,SendErrorKey)
/** Labels of sends still to be settled, and of a send taken off the list by the user. */
private val Unsettled=listOf("提交中","送达状态待确认","已接收","已排队")
const val RemovedLabel="已移除"

class ChatController(private val scope:CoroutineScope,private val persistent:ReaderStore) {
    var extras:()->JSONObject = { JSONObject() }
    /** The settings bound to the next message (Codex), without attachments: what a plan is carried out with. */
    var boundSettings:()->JSONObject = { JSONObject() }
    var sentExtras:(ChatKey,JSONObject)->Unit = { _,_ -> }
    var restoreExtras:(ChatKey,JSONObject)->Unit = { _,_ -> }
    /** True while a tap waits on the computer: no state poll then (web claude-ui.js: a read holds Claude ~1.4 s). */
    var pollPaused:()->Boolean = { false }
    private val mutable=MutableStateFlow(ComposerState())
    val state=mutable.asStateFlow()
    private var key:ChatKey?=null
    private var api:ReadApi?=null
    private var foreground=false
    private var job:Job?=null
    private var token=0
    private val writes=Mutex()
    private val memory=mutableMapOf<ChatKey,String>()
    private val demo=mutableMapOf<String,Submission>()
    private var fixture=false
    private val inFlight=mutableSetOf<ChatKey>()
    private val draftVersions=mutableMapOf<ChatKey,Long>()
    private val confirming=mutableSetOf<String>()
    private fun update(k:ChatKey,f:(ComposerState)->ComposerState) { if(key==k) mutable.update(f) }
    fun bind(next:ChatKey?,service:ReadApi?,active:Boolean,synthetic:Boolean,onFrame:(LiveFrame)->Unit) {
        if(key==next && api===service && foreground==active && fixture==synthetic) return
        job?.cancel(); val t=++token
        val changed=key!=next || api!==service
        key=next;api=service;foreground=active;fixture=synthetic
        if(changed) mutable.value=ComposerState(key=next,draft=memory[next].orEmpty(),submitting=next in inFlight)
        if(next==null || service==null) return
        job=scope.launch {
            try {
                if(changed || !state.value.ready) {
                    val draft=if(synthetic) memory[next].orEmpty() else writes.withLock { persistent.draft(next) }
                    val records=if(synthetic) demo.values.filter { it.scope==next.scope && it.device==next.device && it.chat==next.chat && it.app==next.app } else persistent.submissions(next)
                    if(t!=token) return@launch
                    memory[next]=draft
                    update(next) { it.copy(draft=draft,draftReset=it.draftReset+1,ready=true,submissions=records.map { r -> if(r.label=="提交中") r.copy(label="送达状态待确认") else r }) }
                }
                if(!active) { update(next) { it.copy(connection="已暂停实时连接",control=it.control.copy(available=false)) };return@launch }
                var retry=1000L
                while(isActive && t==token) {
                    try {
                        update(next) { it.copy(connection="正在核对实时状态",control=it.control.copy(available=false)) }
                        val control=service.control(next.device,next.chat)
                        if(t!=token) return@launch
                        update(next) { it.copy(control=mergeControl(it.control,control)) }
                        // Recovery reads receipts only. No mutation is replayed.
                        state.value.submissions.filter { it.label in Unsettled || it.action=="stop" }.forEach { reconcile(it,service,synthetic) }
                        coroutineScope {
                            // As the web: Claude every 5 s and DeepSeek every 2.5 s, from the computer's last read when it is
                            // under 4 s old (no fresh=1, which made the computer read Claude's window on every poll); a
                            // fresh read is only taken on entering and after an action. None while a tap waits there.
                            val every=if(next.app=="claude") 5000L else 2500L
                            val polling=if(next.app!="codex" && !synthetic) launch {
                                while(isActive) {
                                    delay(every)
                                    if(pollPaused()) continue
                                    val fresh=service.control(next.device,next.chat,fresh=false)
                                    if(t==token) update(next) { it.copy(control=mergeControl(it.control,fresh)) }
                                    // Claude has no receipts: its queued and unconfirmed sends are looked for in its record (web pollReceipts).
                                    if(next.app=="claude") claudePending(next).forEach { runCatching { reconcile(it,service,synthetic) } }
                                }
                            } else null
                            try { service.events(next.device,next.chat).collect { frame ->
                            if(t==token) {
                                onFrame(frame)
                                update(next) { it.copy(connection="实时连接正常",control=frame.control?.let { c -> mergeControl(it.control,c) } ?: it.control,revision=it.revision+if(frame.messages.isNotEmpty()) 1 else 0) }
                                if(frame.control!=null) state.value.submissions.filter { r ->
                                    r.action=="stop" && r.label.contains("等待") || r.label=="已排队" && frame.control.queued.none { it.id==r.request }
                                }.forEach { reconcile(it,service,synthetic) }
                                retry=1000L
                            }
                            } } finally { polling?.cancel() }
                        }
                        // Fixtures with no stream do not spin forever in tests.
                        update(next) { it.copy(connection=if(synthetic) "本地固定场景" else "实时连接已结束") }
                        return@launch
                    } catch(e:CancellationException) { throw e }
                    catch(e:Exception) {
                        if(t!=token) return@launch
                        update(next) { it.copy(connection=if(e is ServiceFailure && e.status==401) "登录失效，请返回账号页重新登录" else "连接中断，正在重连",control=it.control.copy(available=false)) }
                        if(e is ServiceFailure && e.status in listOf(401,403,404)) return@launch
                        delay(retry);retry=(retry*2).coerceAtMost(15000)
                    }
                }
            } catch(e:CancellationException) { throw e }
            catch(_:Exception) { update(next) { it.copy(ready=false,error="无法恢复草稿或提交记录，请重新进入会话。") } }
        }
    }
    /** Claude sends of the last half hour still queued or unconfirmed, newest eight. */
    private fun claudePending(k:ChatKey)=state.value.submissions.filter { r ->
        r.app=="claude" && r.chat==k.chat && r.action=="send" && r.label in listOf("已排队","送达状态待确认") && r.request !in confirming &&
            System.currentTimeMillis()-r.created<30*60_000 && runCatching { JSONObject(r.body).has(ClaudeOffset) }.getOrDefault(false)
    }.take(8)
    fun edit(text:String) {
        val k=key ?: return
        if(!state.value.ready) return
        memory[k]=text
        draftVersions[k]=(draftVersions[k] ?: 0)+1
        update(k) { it.copy(draft=text,hint=if(text.isBlank()) it.hint else "") }
        val synthetic=fixture
        scope.launch { try { writes.withLock { if(!synthetic) persistent.draft(k,text) } } catch(_:Exception) { update(k) { it.copy(error="草稿保存失败，请保留输入内容。",ready=false) } } }
    }
    /** Replaces the draft and pushes it into the text field (prompt library). */
    fun replaceDraft(text:String) { if(state.value.ready) { edit(text);mutable.update { it.copy(draftReset=it.draftReset+1) } } }
    fun appendVoice(expected:ChatKey,text:String) { if(key==expected && foreground && state.value.ready && text.isNotBlank()) { edit(appendDictation(state.value.draft,text));mutable.update { it.copy(draftReset=it.draftReset+1) } } }
    /** Voice text put in where the cursor was (web voice-ui.js insert); null when the conversation changed meanwhile. */
    fun insertVoice(expected:ChatKey,text:String,start:Int,end:Int=start):VoicePlacement? {
        if(key!=expected || !state.value.ready || text.isBlank()) return null
        val placed=placeDictation(state.value.draft,text,start,end)
        edit(placed.draft);mutable.update { it.copy(draftReset=it.draftReset+1) }
        return placed
    }
    /** Swaps the words voice put in for others (整理, or its 撤销), only while they are still there as they were. */
    fun swapVoice(expected:ChatKey,placed:VoicePlacement,text:String):VoicePlacement? {
        val draft=state.value.draft
        if(key!=expected || !state.value.ready || draft.length<placed.at+placed.text.length || draft.substring(placed.at,placed.at+placed.text.length)!=placed.text) return null
        val next=draft.substring(0,placed.at)+text+draft.substring(placed.at+placed.text.length)
        edit(next);mutable.update { it.copy(draftReset=it.draftReset+1) }
        return placed.copy(text=text,draft=next)
    }
    fun focusInput(hint:String) { mutable.update { it.copy(focus=it.focus+1,hint=hint) } }
    fun restore(record:Submission) {
        val k=key ?: return
        if(k!=ChatKey(record.scope,record.device,record.chat,record.app)) return
        if(state.value.draft.isBlank()) {
            try { restoreExtras(k,JSONObject(record.body));edit(record.text);mutable.update { it.copy(draftReset=it.draftReset+1) } }
            catch(e:Exception) { update(k) { it.copy(error=e.message ?: "提交快照未恢复") } }
        }
    }
    fun send(queue:Boolean=false) = submit("send",queue=queue)
    /** 执行计划: Codex carries out the plan it made, in normal mode (web codex-ui.js send(planId)); the draft is left alone. */
    fun executePlan(plan:String) = submit("send",plan=plan)
    fun stop() = submit("stop")
    fun cancel(message:String) = submit("queue-action",message=message)
    /** 立即补充: hand a queued message to the running turn (B05). Claude does this with a desktop token instead. */
    fun promote(message:String) = submit("queue-action",message=message,promote=true)
    /** A state the computer sent back with an action (Claude settings): shown as read, no second request. */
    fun applyState(k:ChatKey,raw:JSONObject) { if(key==k) update(k) { it.copy(control=mergeControl(it.control,parseControl(raw))) } }
    /**
     * Words written on a new conversation's page before it existed go on to the conversation (web writeDraft): added
     * under a draft already there, never over it.
     */
    suspend fun moveDraft(from:ChatKey,to:ChatKey) {
        val synthetic=fixture
        val text=(memory[from] ?: if(synthetic) "" else writes.withLock { persistent.draft(from) }).trim()
        if(text.isBlank()) return
        val there=memory[to] ?: if(synthetic) "" else writes.withLock { persistent.draft(to) }
        val next=if(there.isBlank()) text else there.trimEnd()+"\n"+text
        memory[to]=next;memory.remove(from)
        if(!synthetic) writes.withLock { persistent.draft(to,next);persistent.draft(from,"") }
    }
    /** Re-reads the source state once, e.g. after a question card was answered or Codex's "刷新 ›". */
    fun refreshControl() {
        val k=key ?: return;val service=api ?: return;val t=token
        scope.launch {
            try { val fresh=service.control(k.device,k.chat);if(t==token) update(k) { it.copy(control=mergeControl(it.control,fresh)) } }
            catch(e:CancellationException) { throw e } catch(_:Exception) { }
        }
    }
    /** 移除: takes a send that went nowhere off the list (web: the outbox card's 移除); the computer is not asked anything. */
    fun dismiss(record:Submission) {
        if(record.label in listOf("提交中")) return
        scope.launch { save(record.copy(label=RemovedLabel),fixture) }
    }
    /**
     * 换掉电脑上的「…」再发 (web resendReplacing): Claude turned the message away because its box on the computer held
     * other text. The same message goes again, naming exactly that text to replace; nothing else in the box is touched.
     */
    fun resendReplacing(record:Submission) {
        val k=key ?: return;val service=api ?: return
        val old=runCatching { JSONObject(record.body) }.getOrNull() ?: return
        val draft=old.string(DesktopDraftKey)
        if(k.app!="claude" || k!=ChatKey(record.scope,record.device,record.chat,record.app) || draft.isBlank() || record.label!="未接收") return
        if(!foreground || !state.value.ready || !state.value.control.available || !inFlight.add(k)) return
        val rid=UUID.randomUUID().toString()
        val body=JSONObject(old.toString()).apply { LocalKeys.forEach { remove(it) } }.put("request_id",rid).put("replace_draft",draft.take(2000))
        val next=Submission(rid,k.scope,k.device,app=k.app,chat=k.chat,text=record.text,action="send",turn=state.value.control.turn,body=body.toString())
        update(k) { it.copy(submitting=true,error=null) }
        val synthetic=fixture
        val binding=token;val version=draftVersions[k] ?: 0
        scope.launch {
            save(record.copy(label=RemovedLabel),synthetic)
            dispatch(k,service,"send",body,next,synthetic,binding,version,clearDraft=false)
        }
    }
    private fun submit(action:String,queue:Boolean=false,message:String="",promote:Boolean=false,plan:String?=null) {
        val k=key ?: return;val service=api ?: return;val s=state.value
        val planned=plan!=null
        if(action=="send" && !planned && s.submissions.any { it.action=="send" && it.text.trim()==s.draft.trim() && it.label in listOf("提交中","送达状态待确认") }) {
            update(k) { it.copy(error="相同内容的原提交尚待确认，请先核对状态，不能重复发送。") };return
        }
        val extra=try { if(action=="send" && !planned) extras() else JSONObject() } catch(e:Exception) { update(k) { it.copy(error=e.message) };return }
        val hasExtras=extra.optJSONArray("attachments")?.length()?.let { it>0 }==true || extra.optJSONArray("references")?.length()?.let { it>0 }==true
        if(!foreground || !s.ready || !s.control.available || !inFlight.add(k)) return
        if(action=="send" && !planned && ((s.draft.isBlank() && !hasExtras) || s.draft.trim().length>20000 || queue && !s.control.queueAvailable) || action=="stop" && !s.control.running || promote && !s.control.running || planned && (k.app!="codex" || s.control.running)) { inFlight.remove(k);return }
        val rid=UUID.randomUUID().toString()
        val body=JSONObject().put("id",k.chat)
        when(action) {
            "send" -> if(planned) {
                // The settings bound to the next message, or the conversation's own, in normal mode; Codex checks the plan is still its latest.
                val raw=runCatching { JSONObject(s.control.raw) }.getOrDefault(JSONObject())
                val bound=boundSettings()
                val current=raw.optJSONObject("settings") ?: JSONObject()
                val settings=JSONObject((bound.optJSONObject("settings") ?: current).toString()).put("mode","default")
                body.put("request_id",rid).put("text","请执行这份计划。").put("intent","auto").put("plan_id",plan).put("attachments",org.json.JSONArray())
                    .put("settings",settings).put("expected_settings",bound.optJSONObject("expected_settings") ?: current)
            } else { body.put("request_id",rid).put("text",s.draft.trim()).put("intent",if(queue) "queue" else if(s.control.running) "steer" else "auto");if(s.control.running) body.put("expected_turn",s.control.turn) }
            "stop" -> body.put("operation_id",rid).put("turn_id",s.control.turn)
            "queue-action" -> { body.put("request_id",rid).put("message_id",message).put("action",if(promote) "promote" else "cancel");if(promote) body.put("expected_turn",s.control.turn) }
        }
        if(action=="send" && !planned) extra.keys().forEach { body.put(it,extra.get(it)) }
        val text=when { planned -> "执行计划";action=="send" -> s.draft;action=="stop" -> "停止当前轮次";promote -> "立即补充";else -> "取消排队" }
        val record=Submission(rid,k.scope,k.device,app=k.app,chat=k.chat,text=text,action=action,turn=s.control.turn,body=body.toString())
        val synthetic=fixture
        // The draft version and the binding are taken now: edits made while the request starts are newer than it.
        val binding=token;val version=draftVersions[k] ?: 0
        update(k) { it.copy(submitting=true,error=null) }
        // A plan carried out uses up the settings bound to the next message, as a send does (web: d.settings goes).
        if(planned) mutable.update { it.copy(hint="") }
        scope.launch {
            if(action=="send" && !planned) dispatch(k,service,action,body,record,synthetic,binding,version,clearDraft=true,extra=extra)
            else dispatch(k,service,action,body,record,synthetic,binding,version,clearDraft=false,extra=if(planned) JSONObject().put("settings",JSONObject()) else null)
        }
    }
    /** Keeps the copy first, then posts once; never posts again by itself (B03, B04). */
    private suspend fun dispatch(k:ChatKey,service:ReadApi,action:String,body:JSONObject,record:Submission,synthetic:Boolean,binding:Int,version:Long,clearDraft:Boolean,extra:JSONObject?=null) {
        var began=false
        try {
            writes.withLock { if(synthetic) demo[record.request]=record else persistent.begin(record) }
            began=true
            if(extra!=null) sentExtras(k,extra)
            // Only clear the exact submitted draft; newer edits survive even a slow database.
            if(clearDraft && (draftVersions[k] ?: 0)==version) { memory[k]="" }
            update(k) {
                val clear=clearDraft && (draftVersions[k] ?: 0)==version
                it.copy(draft=if(clear) "" else it.draft,draftReset=it.draftReset+if(clear) 1 else 0,submissions=listOf(record)+it.submissions)
            }
            val result=service.command(k.device,action,body)
            if(action!="stop" && k.app=="codex") { require(result.string("request_id")==record.request) { "回执身份不匹配" } }
            if(action=="send" && k.app=="claude" && result.optBoolean("pressed")) {
                // The computer pressed Enter in Claude's box. Whether Claude read it is then looked for in its record (web chat/check).
                val pressed=record.copy(label="已接收",body=JSONObject(record.body).put(ClaudeOffset,result.optLong("offset")).put(ClaudeCheckText,result.string("check_text").ifBlank { body.string("text") }).toString())
                save(pressed,synthetic)
                scope.launch { confirmClaude(pressed,service,synthetic) }
            } else {
                val label=if(action=="stop" && result.optBoolean("ended")) "该轮已结束" else receiptLabel(result.string("delivery_state").ifBlank { if(result.optBoolean("accepted")) "accepted" else "unknown" },result,action)
                save(record.copy(label=label),synthetic)
            }
            val control=runCatching { service.control(k.device,k.chat) }.getOrNull()
            if(control!=null && binding==token && foreground) { update(k) { it.copy(control=mergeControl(it.control,control)) } }
        } catch(e:Exception) {
            if(began) {
                val failure=e as? ServiceFailure
                val kept=if(failure?.notSubmitted==true) JSONObject(record.body).put(SendErrorKey,failure.message.orEmpty()).apply { if(failure.draft.isNotBlank()) put(DesktopDraftKey,failure.draft) }.toString() else record.body
                save(record.copy(label=if(failure?.notSubmitted==true) "未接收" else "送达状态待确认",body=kept),synthetic)
            }
            else update(k) { it.copy(error="无法保存提交快照，尚未发送。") }
        } finally { inFlight.remove(k);update(k) { it.copy(submitting=false) } }
    }
    /** Looks for a Claude send in its record for up to 25 s, as the web does after Enter: read, queued, or still unconfirmed. */
    private suspend fun confirmClaude(record:Submission,service:ReadApi,synthetic:Boolean) {
        if(!confirming.add(record.request)) return
        try {
            val until=System.currentTimeMillis()+25_000
            var queued=false
            while(System.currentTimeMillis()<until) {
                // The fixture answers at once; a real computer is asked every 1.5 s, as the web does.
                if(!synthetic) delay(1500)
                val r=runCatching { claudeCheck(record,service) }.getOrNull() ?: continue
                if(r.optBoolean("delivered")) { save(record.copy(label="已送达"),synthetic);return }
                if(r.optBoolean("queued") && !queued) { queued=true;save(record.copy(label="已排队"),synthetic) }
            }
            save(record.copy(label=if(queued) "已排队" else "送达状态待确认"),synthetic)
        } finally { confirming.remove(record.request) }
    }
    private suspend fun claudeCheck(record:Submission,service:ReadApi):JSONObject? {
        val body=JSONObject(record.body)
        if(!body.has(ClaudeOffset)) return null
        return service.detail(record.device,"chat/check",body=JSONObject().put("app","claude").put("id",record.chat).put("offset",body.optLong(ClaudeOffset)).put("text",body.string(ClaudeCheckText)))
    }
    private suspend fun save(record:Submission,synthetic:Boolean) {
        try {
            writes.withLock { if(synthetic) demo[record.request]=record else persistent.submission(record) }
            update(ChatKey(record.scope,record.device,record.chat,record.app)) { s -> s.copy(submissions=(listOf(record)+s.submissions.filter { it.request!=record.request }).sortedByDescending { it.created }) }
        } catch(_:Exception) { update(ChatKey(record.scope,record.device,record.chat,record.app)) { it.copy(error="回执保存失败，请保留原请求并核对。") } }
    }
    fun check(record:Submission) {
        val service=api ?: return;val synthetic=fixture
        if(key!=ChatKey(record.scope,record.device,record.chat,record.app)) return
        scope.launch { try { reconcile(record,service,synthetic) } catch(_:Exception) { update(ChatKey(record.scope,record.device,record.chat,record.app)) { it.copy(error="核对失败，原提交仍保留；不会自动重发。") } } }
    }
    private suspend fun reconcile(record:Submission,service:ReadApi,synthetic:Boolean) {
        if(record.app=="claude" && record.action=="send") {
            // No receipts for Claude: what its record shows decides, and nothing is sent again.
            val r=claudeCheck(record,service) ?: return
            val label=when { r.optBoolean("delivered") -> "已送达";r.optBoolean("queued") -> "已排队";else -> record.label }
            if(label!=record.label) save(record.copy(label=label),synthetic)
            return
        }
        val response=service.receipt(record.device,record.chat,record.request)
        require(response.string("request_id").let { it==record.request || it.isBlank() && response.string("state")=="unknown" })
        var label=receiptLabel(response.string("state"),response.optJSONObject("result") ?: JSONObject(),record.action)
        if(record.action=="stop") {
            val control=service.control(record.device,record.chat)
            label=when(control.turns[record.turn]) { "interrupted" -> "已停止"; "completed" -> "该轮已完成"; "failed" -> "该轮失败"; else -> label }
        }
        save(record.copy(label=label),synthetic)
    }
}
