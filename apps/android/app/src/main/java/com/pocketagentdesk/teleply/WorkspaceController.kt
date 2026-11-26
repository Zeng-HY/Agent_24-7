package com.pocketagentdesk.teleply

import android.content.Context
import android.net.Uri
import android.provider.OpenableColumns
import java.nio.charset.CharacterCodingException
import java.util.UUID
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.*
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import org.json.JSONArray
import org.json.JSONObject

/**
 * [choices] holds what the composer's model and mode menus list (spec 0.4 §4.3), read beside any open pane. [cards] is
 * where each Claude timeline button stands (next-step box, task card): pressing:label, done:what was done, error:why.
 * [newData] is what the new-conversation sheet lists (folders, models, permissions): what this phone had first, the
 * computer's lists when they come (0.8, web new-chat-ui.js); [newNote] a line under the sheet when a list did not come.
 */
data class WorkspaceState(val key:ChatKey?=null,val ready:Boolean=false,val pane:String?=null,val busy:Boolean=false,val error:String?=null,val data:String="{}",val saved:String="{}",val result:String="",val preview:ByteArray?=null,val previewFile:String?=null,val transfer:String="",val savingFile:Boolean=false,val savedUri:String?=null,val choices:String="{}",val choicesBusy:Boolean=false,val choicesError:String?=null,val cards:Map<String,String> = emptyMap(),val newData:String="{}",val newNote:String?=null,
                          /** 核对上次操作 reading the computer: the button waits; nothing else does. */
                          val checking:Boolean=false,
                          /** A file being turned into PDF on the computer (PowerPoint, the old .doc and .ppt), and why there is no preview ([previewNote]). */
                          val converting:Boolean=false,val previewNote:String="") {
    /** One Claude button at a time: its click waits for the computer's window. */
    val pressing:Boolean get() = cards.values.any { it.startsWith("pressing:") }
}

/**
 * How long the computer takes a Claude press after it gave its one-time token (claude_control _ticket and choose:
 * 120 s). A press whose reply was lost cannot land after that.
 */
const val ClaudePressLife=120_000L

/** The most a picture, PDF, Word or Excel file drawn on a file's page may be, the computer's PDF of an Office file too. */
const val PreviewLimit=20L*1024*1024
/** §5.8: a picture's original may be this large in the viewer (past it the 2048 thumb is shown). */
const val PicturePreviewLimit=30L*1024*1024
/** §5.8: a PDF may be this large and still open on its page, kept on disk rather than in memory. */
const val PdfPreviewLimit=100L*1024*1024
/** §5.8: a Word or Excel file may be this large to be drawn by the phone's own pages. */
const val OfficePreviewLimit=15L*1024*1024
/** 11-26: and its body (word/document.xml, or Excel's worksheets) may be this large: past it the page says so instead. */
const val OfficeBodyLimit=8L*1024*1024
/** 11-26: what the failure page says for a file the phone will not draw (design §6.1). */
const val OfficeTooLargeNote="文件太大，手机里不直接显示。"

/** Why the computer's Office gave no PDF: in its own words when it gave some (10-27). */
fun pdfFailure(e:Exception):String = when(e) {
    is PreviewTooLarge -> e.message.orEmpty()
    is ServiceFailure -> "没能转成 PDF："+e.detail.ifBlank { e.message.orEmpty() }
    is java.io.InterruptedIOException -> "没能转成 PDF：等了太久，电脑还没转好，请稍后再打开。"
    else -> "没能转成 PDF：连不上电脑，请稍后再打开。"
}

/** What a Claude press was, kept with it on this phone only (never sent): an option or button of its card ("choice"), 停止这一轮 ("stop"), or 立即补充 of a queued message ([item]). */
fun claudePress(what:String,item:String="")=JSONObject().put("what",what).apply { if(item.isNotBlank()) put("item",item) }

/**
 * What a Claude press whose reply was lost came to, by Claude's state read since (10-27): still waiting for it, so
 * press again; or nothing waiting any more, so it was dealt with. Nothing is sent again either way.
 */
fun claudePressFound(pending:JSONObject,state:Control):String {
    val raw=runCatching { JSONObject(state.raw) }.getOrDefault(JSONObject())
    val press=pending.optJSONObject("local") ?: JSONObject()
    return when(press.string("what")) {
        "stop" -> if(state.running) "电脑上的 Claude 还在运行；上次的停止可能没送到，需要的话请再点一次。" else "电脑上的 Claude 已经停下了。"
        "steer" -> if(press.string("item").isNotBlank() && press.string("item") in raw.rows("queued") { it.string("id") }) "这条消息还在电脑上排队；上次的立即补充可能没送到，可以再点一次。"
            else "这条消息已经不在电脑上排队了，上次的立即补充已处理。"
        else -> if(pendingCards("claude",raw).isNotEmpty()) "电脑上的 Claude 还在等你选；上次那一下可能没送到，请再选一次。" else "电脑上已经没有在等的选项，上次的选择已处理。"
    }
}
class WorkspaceController(private val scope:CoroutineScope,private val store:ReaderStore) {
    private val mutable=MutableStateFlow(WorkspaceState());val state=mutable.asStateFlow()
    private var api:ReadApi?=null;private var key:ChatKey?=null;private var fixture=false
    /** Where this phone keeps answer thumbs and originals (§7); set by the app, absent in tests. */
    var mediaDir:java.io.File?=null
    private var saveJob:Job?=null
    private var generation=0;private var read:Job?=null;private var choiceRead:Job?=null
    private val mutex=Mutex();private val demo=mutableMapOf<ChatKey,String>()
    private val newIds=Mutex()
    private val active=mutableSetOf<ChatKey>()
    private val jobs=mutableListOf<Job>()
    private val uploadJobs=mutableMapOf<String,Job>()
    private val cache=mutableMapOf<ChatKey,String>()
    private val modes=mutableMapOf<ChatKey,Boolean>()
    /** Lists kept on this phone (0.8): Claude's model lists by conversation, DeepSeek's by computer, the sheet's lists. */
    private val catalogs=mutableMapOf<String,JSONObject>()
    private val lists=mutableMapOf<ChatKey,JSONObject>()
    private val newReads=mutableMapOf<String,Job>()
    /** Called after an action reached the source, so the composer can re-read questions and state. */
    var changed:()->Unit = {}
    /** A state the computer sent back with an action (Claude settings): shown at once, no second read. */
    var stateRead:(ChatKey,JSONObject)->Unit = { _,_ -> }
    /** A first message sent: becomes a creation job (web 10-16) and the sheet is free again at once. */
    var created:(NewJob)->Unit = {}
    /** A first message 0.7 left under way in the sheet: followed as a job, without opening it. */
    var adopted:(NewJob)->Unit = {}
    /** Active computer's assistant manifest snapshot (plan §6.1). */
    var catalog:()->AgentCatalogSnapshot = { AgentCatalogSnapshot.Builtin }
    private fun launchSafe(block:suspend ()->Unit):Job {
        val owner=key
        return scope.launch { try { block() } catch(e:CancellationException) { throw e } catch(e:Exception) { owner?.let { k -> update(k) { it.copy(ready=false,busy=false,error=e.message ?: "本地保存失败，操作已暂停") } } } }
    }
    private fun saved(k:ChatKey=key ?: error("没有活动会话"))=JSONObject(cache[k] ?: "{}")
    private fun valid(k:ChatKey)=key==k
    private fun update(k:ChatKey,f:(WorkspaceState)->WorkspaceState) { if(valid(k)) mutable.update(f) }
    fun bind(next:ChatKey?,service:ReadApi?,synthetic:Boolean) {
        if(key==next && api===service) return
        read?.cancel();choiceRead?.cancel();newReads.values.forEach { it.cancel() };newReads.clear();jobs.forEach { it.cancel() };jobs.clear();val g=++generation
        key=next;api=service;fixture=synthetic;mutable.value=WorkspaceState(key=next,newData=next?.let { lists[it]?.toString() } ?: "{}")
        if(next==null) return
        modes[next]=synthetic
        read=launchSafe {
            try {
                val value=mutex.withLock { if(synthetic) demo[next] else store.detail(next,"workspace") } ?: "{}"
                val j=JSONObject(value)
                j.rows("uploads") { it }.forEach { if(it.string("status") in listOf("uploading","checking")) it.put("status","failed").put("error","上传中断，请重新选择文件") }
                // 0.7 kept a first message under way in the sheet's draft (new_status): it becomes a job, the draft starts afresh.
                if(next.chat=="@new" && j.string("new_status") !in listOf("","draft")) {
                    legacyJob(next,j)?.let(adopted)
                    listOf("new_id","new_status","new_result","new_body","first_message","uploads","references").forEach { j.remove(it) }
                    mutex.withLock { if(synthetic) demo[next]=j.toString() else store.detail(next,"workspace",j.toString()) }
                }
                // The sheet's lists of last time, so it opens with them (0.8); the computer's come in behind.
                val kept=if(next.chat=="@new" && lists[next]==null && !synthetic) store.detail(next,"new_lists")?.let { runCatching { JSONObject(it) }.getOrNull() } else null
                // Claude's model lists of last time, this conversation's and the computer's latest, for the model menu.
                if(catalog().cardLayout(next.app)=="claude.v1" && !synthetic) listOf(catalogKey(next) to next,lastCatalogKey(next) to lastCatalog(next)).forEach { (name,owner) ->
                    if(catalogs[name]==null) store.detail(owner,"claude_catalog")?.let { runCatching { JSONObject(it) }.getOrNull() }?.let { catalogs[name]=it }
                }
                if(g==generation) { cache[next]=j.toString();kept?.let { lists[next]=it };update(next) { it.copy(saved=j.toString(),ready=true,newData=(lists[next] ?: JSONObject()).toString()) } }
            } catch(_:Exception) { if(g==generation) update(next) { it.copy(error="无法恢复附件和交互草稿，暂不能发送") } }
        }
    }
    private fun legacyJob(k:ChatKey,j:JSONObject):NewJob? {
        val rid=j.string("new_id");if(!Regex("[a-f0-9]{32}").matches(rid)) return null
        val result=j.optJSONObject("new_result") ?: JSONObject().put("state","unconfirmed").put("message","提交结果未确认，请核对")
        return NewJob(rid,k.app,j.string("folder"),j.string("projectless")=="1",j.string("folder").substringAfterLast('/').substringAfterLast('\\'),j.string("first_message"),
            body=(j.optJSONObject("new_body") ?: JSONObject().put("request_id",rid)).toString(),pending=result.toString())
    }
    private suspend fun persist(k:ChatKey,j:JSONObject,synthetic:Boolean=modes[k]==true) {
        cache[k]=j.toString()
        update(k) { it.copy(saved=j.toString()) }
        mutex.withLock { if(synthetic) demo[k]=j.toString() else store.detail(k,"workspace",j.toString()) }
    }
    /** Drafts stay editable while a pane reads its lists; only a create or action in flight holds them. */
    fun edit(field:String,value:String) {
        val k=key ?: return;if(!state.value.ready || state.value.busy && k in active) return
        val j=saved(k).put(field,value);cache[k]=j.toString();update(k) { it.copy(saved=j.toString()) }
        val synthetic=fixture
        launchSafe { try { mutex.withLock { if(synthetic) demo[k]=j.toString() else store.detail(k,"workspace",j.toString()) } } catch(_:Exception) { update(k) { it.copy(ready=false,error="交互草稿保存失败") } } }
    }
    /** A file page keeps the file's text in [WorkspaceState.result]: it goes with the page, not into the status line. */
    fun close() { saveJob?.cancel();read?.cancel();generation++;mutable.update { it.copy(pane=null,data="{}",preview=null,previewFile=null,busy=false,error=null,result=if(it.pane=="file") "" else it.result,converting=false,previewNote="") } }
    fun panel(name:String) {
        saveJob?.cancel();read?.cancel();generation++
        mutable.update { it.copy(pane=name,data="{}",busy=false,error=null,preview=null,previewFile=null,newNote=if(name=="new") null else it.newNote,result=if(it.pane=="file") "" else it.result,converting=false,previewNote="") }
        if(name=="new") openNew() else refresh(name)
    }
    /**
     * 新建对话 opens at once (0.8, web openNewSheet): the folders and models of last time are already there, the
     * computer's folder list comes in behind and replaces them, and the draft's request id is asked for meanwhile.
     * Models and DeepSeek's permissions are read when their menu opens. Nothing here shows a progress bar.
     */
    private fun openNew() {
        val k=key ?: return;val service=api ?: return
        if(k.chat!="@new") return
        loadNewFolders()
        launchSafe { try { ensureNewId(k,service) } catch(e:CancellationException) { throw e } catch(_:Exception) { /* asked again on 创建并发送 */ } }
    }
    fun loadNewFolders() = loadNewList("folders") { k,service -> service.detail(k.device,"chat/folders",mapOf("app" to k.app)) }
    /** The models a new conversation may start on; the computer answers from what its menus showed before (cheap). */
    fun loadNewModels() = loadNewList("models") { k,service -> service.detail(k.device,"chat/new/options",mapOf("app" to k.app)) }
    fun loadNewPermissions() = loadNewList("permissions") { k,service -> service.detail(k.device,"deepseek/permissions") }
    private fun loadNewList(name:String,read:suspend (ChatKey,ReadApi)->JSONObject) {
        val k=key ?: return;val service=api ?: return
        if(k.chat!="@new" || newReads[name]?.isActive==true) return
        val synthetic=fixture
        newReads[name]=launchSafe {
            try {
                val value=read(k,service)
                if(!valid(k)) return@launchSafe
                val next=JSONObject((lists[k] ?: JSONObject()).toString()).put(name,value)
                lists[k]=next
                update(k) { it.copy(newData=next.toString(),newNote=if(name=="folders") null else it.newNote) }
                if(!synthetic) mutex.withLock { store.detail(k,"new_lists",next.toString()) }
            } catch(e:CancellationException) { throw e }
            catch(e:Exception) {
                val what=when(name) { "folders" -> "项目文件夹";"models" -> "模型列表";else -> "权限选项" }
                if(valid(k)) update(k) { it.copy(newNote="电脑上的${what}这次没读到：${e.message ?: "没有回应"}，先用手机上记着的") }
            }
        }
    }
    fun refresh(name:String=state.value.pane.orEmpty(),query:String="",offset:String="0",fresh:Boolean=false) {
        if(name=="new") { loadNewFolders();return }
        val k=key ?: return;val service=api ?: return;read?.cancel();val g=++generation
        update(k) { it.copy(busy=true,error=null) }
        read=launchSafe {
            try {
                val q=mapOf("app" to k.app,"id" to k.chat)
                val data=when(name) {
                    "files" -> service.detail(k.device,"chat/files",q+mapOf("message" to query.ifBlank { null }))
                    "remote" -> if(query.isBlank()) service.detail(k.device,"files/places",q) else service.detail(k.device,"files/list",q+mapOf("path" to query,"offset" to offset))
                    "chat","skill" -> service.detail(k.device,if(k.chat=="@new") "chat/new/references" else "composer/references",q+mapOf("kind" to name,"query" to query,"offset" to if(fresh) "0" else offset,"fresh" to if(fresh) "1" else "0","scan_id" to if(offset!="0" && !fresh) JSONObject(state.value.data).string("scan_id") else "","projectless" to if(saved(k).string("folder").isBlank()) "1" else "0","folder" to saved(k).string("folder")))
                    else -> JSONObject()
                }
                if(g==generation && state.value.pane==name) update(k) { it.copy(data=data.toString(),busy=false) }
            } catch(e:CancellationException) { throw e }
            catch(e:Exception) { if(g==generation) update(k) { it.copy(error=if(name=="skill") "技能读取失败，请重试。若仍失败，请检查电脑端连接。" else e.message ?: "读取失败",busy=false) } }
        }
    }
    /**
     * The lists the composer's menus need (spec 0.4 §4.3), shown at once from this phone and checked behind (0.8, web
     * claude-ui.js savedCatalog/loadCatalog). Claude's come from the catalog the computer keeps, without opening the
     * desktop's menus; [fresh] (刷新) reads them on the desktop again. A conversation never opened shows the list of
     * another one on the same [model], its own choices unknown. DeepSeek's models and permissions likewise. Codex needs
     * none: its catalog comes with the conversation state. Does not touch the open pane.
     */
    fun loadChoices(fresh:Boolean=false,model:String="") {
        val k=key ?: return;val service=api ?: return
        val layout=catalog().cardLayout(k.app)
        if(layout!="claude.v1" && layout!="deepseek.v1") return
        choiceRead?.cancel()
        val synthetic=fixture
        val shown=remembered(k,model).apply { if(fresh) put("refreshing",true) }
        update(k) { it.copy(choices=shown.toString(),choicesBusy=true,choicesError=null) }
        choiceRead=launchSafe {
            try {
                val data=JSONObject(shown.toString()).apply { remove("refreshing") }
                if(layout=="claude.v1") {
                    val catalog=service.detail(k.device,"claude/catalog",body=JSONObject().put("id",k.chat).put("fresh",fresh))
                    keepCatalog(k,catalog,synthetic);data.put("source_catalog",catalog)
                }
                if(layout=="deepseek.v1") {
                    val models=service.detail(k.device,"deepseek/models");catalogs["deepseek-models|${k.device}"]=models
                    val permissions=service.detail(k.device,"deepseek/permissions",mapOf("app" to k.app,"id" to k.chat));catalogs["deepseek-permissions|${k.device}|${k.chat}"]=permissions
                    data.put("source_catalog",models).put("permissions",permissions)
                }
                update(k) { it.copy(choices=data.toString(),choicesBusy=false) }
            } catch(e:CancellationException) { throw e }
            catch(e:Exception) { update(k) { it.copy(choicesError=e.message ?: "读不到电脑上的选项",choicesBusy=false) } }
        }
    }
    private fun catalogKey(k:ChatKey)="claude|${k.scope}|${k.device}|${k.chat}"
    private fun lastCatalogKey(k:ChatKey)="claude-last|${k.scope}|${k.device}"
    private fun lastCatalog(k:ChatKey)=ChatKey(k.scope,k.device,"@catalog","claude")
    /** What the menus showed last (web savedCatalog): this conversation's, or the latest on the same model, its picks unknown. */
    private fun remembered(k:ChatKey,model:String):JSONObject = JSONObject().apply {
        val layout=catalog().cardLayout(k.app)
        if(layout=="claude.v1") {
            val own=catalogs[catalogKey(k)]
            val last=catalogs[lastCatalogKey(k)]?.takeIf { own==null && model.isNotBlank() && it.string("model_id")==model }
            when {
                own!=null -> put("source_catalog",own)
                last!=null -> put("source_catalog",JSONObject(last.toString()).apply {
                    rows("fast") { it }.forEach { it.put("selected",JSONObject.NULL) }
                    rows("effort") { it }.forEach { it.put("selected",false);it.optJSONObject("range")?.put("value",JSONObject.NULL) }
                    put("borrowed",true)
                })
            }
        }
        if(layout=="deepseek.v1") {
            catalogs["deepseek-models|${k.device}"]?.let { put("source_catalog",it) }
            catalogs["deepseek-permissions|${k.device}|${k.chat}"]?.let { put("permissions",it) }
        }
    }
    private suspend fun keepCatalog(k:ChatKey,catalog:JSONObject,synthetic:Boolean) {
        val own=JSONObject(catalog.toString()).apply { remove("borrowed");remove("cached") }
        catalogs[catalogKey(k)]=own;catalogs[lastCatalogKey(k)]=own
        if(!synthetic) mutex.withLock { store.detail(k,"claude_catalog",own.toString());store.detail(lastCatalog(k),"claude_catalog",own.toString()) }
    }
    /**
     * A model, effort, speed or mode picked from a Claude chip (web claude-ui.js change, pickMode): applied on the
     * computer, which sends back the state and, mostly, the updated list. Only without a list is the desktop read again.
     */
    fun claudeSetting(kind:String,name:String,value:Any?=null,expected:String="") {
        val k=key ?: return;val service=api ?: return
        if(catalog().cardLayout(k.app)!="claude.v1" || state.value.busy || !active.add(k)) return
        val synthetic=fixture
        update(k) { it.copy(busy=true,error=null,result="") }
        launchSafe {
            var again=false
            try {
                val body=JSONObject().put("id",k.chat).put("kind",kind).put("name",name).put("value",value ?: JSONObject.NULL).apply { if(expected.isNotBlank()) put("expected_model",expected) }
                val r=service.detail(k.device,"claude/setting",body=body)
                val read=r.optJSONObject("state")
                if(read!=null) stateRead(k,read) else changed()
                val catalog=r.optJSONObject("catalog")
                if(catalog!=null) { keepCatalog(k,catalog,synthetic);update(k) { it.copy(choices=JSONObject(it.choices).put("source_catalog",catalog).toString()) } }
                else again=kind!="mode"
                update(k) { it.copy(result=r.string("text").ifBlank { if(kind=="mode") "已切换到「$name」" else "已应用到这个 Claude 对话" }) }
            } catch(e:CancellationException) { throw e }
            catch(e:Exception) { update(k) { it.copy(error=e.message ?: "没有应用，请看电脑上的 Claude") } }
            finally { active.remove(k);update(k) { it.copy(busy=false) } }
            if(again) loadChoices(fresh=true)
        }
    }
    /** Leaves no menu open on the computer once the phone's model menu closed (web claude-ui.js closeMenu). */
    fun closeClaudeMenu() {
        val k=key ?: return;val service=api ?: return
        if(catalog().cardLayout(k.app)!="claude.v1" || k.chat=="@new") return
        scope.launch { try { service.detail(k.device,"claude/close-menu",body=JSONObject().put("id",k.chat)) } catch(e:CancellationException) { throw e } catch(_:Exception) { } }
    }
    fun addReference(reference:JSONObject) {
        val k=key ?: return
        launchSafe { val j=saved(k);val refs=j.rows("references") { it };if(refs.none { it.string("id")==reference.string("id") && it.string("kind")==reference.string("kind") }) persist(k,j.put("references",JSONArray(refs+reference))) }
    }
    fun removeReference(id:String) { val k=key ?: return;val j=saved(k);launchSafe { persist(k,j.put("references",JSONArray(j.rows("references") { it }.filter { it.string("id")!=id }))) } }
    fun sendExtras():JSONObject {
        val k=key ?: error("没有活动会话")
        require(state.value.ready) { "附件和设置仍在恢复，请稍候" }
        val j=saved(k);val uploads=j.rows("uploads") { it }
        require(uploads.filter { it.optBoolean("image") }.sumOf { it.optJSONObject("meta")?.optLong("original_size") ?: 0 } <= 50L*1024*1024) { "图片合计不能超过50MB" }
        require(uploads.none { it.string("status")!="ready" }) { "存在未完成或失败的附件，请重选或移除后再发送" }
        return JSONObject().put("attachments",JSONArray(uploads.filter { it.optBoolean("image") }.map { it.getJSONObject("meta").getString("id") }))
            .put("references",JSONArray(j.rows("references") { it }+uploads.filter { !it.optBoolean("image") }.map { it.getJSONObject("meta") }))
            .apply { j.optJSONObject("settings")?.let { put("settings",it) };j.optJSONObject("expected_settings")?.let { put("expected_settings",it) } }
    }
    fun clearSent(k:ChatKey,extras:JSONObject) {
        val j=saved(k)
        val images=extras.optJSONArray("attachments")?.let { a -> (0 until a.length()).map { a.getString(it) }.toSet() }.orEmpty()
        val refs=extras.rows("references") { it.string("id") }.toSet()
        val (sent,kept)=j.rows("uploads") { it }.partition { it.optJSONObject("meta")?.string("id") in images+refs }
        sent.forEach { dropPhotoPreview(it.string("preview")) }
        j.put("uploads",JSONArray(kept))
        j.put("references",JSONArray(j.rows("references") { it }.filter { it.string("id") !in refs }))
        // Settings bind to the next message only (web: d.settings and d.base go with the send); the chip then shows
        // what the computer has, and a later message is not checked against the settings from before this one.
        if(extras.has("settings")) { j.remove("settings");j.remove("expected_settings") }
        // A send supersedes the one-line result above the box (设置已绑定…): its receipt shows there now.
        update(k) { it.copy(result="") }
        launchSafe { persist(k,j) }
    }
    /** The model, effort and mode bound to the next message, and what they were chosen against (Codex). */
    fun boundSettings():JSONObject {
        val k=key ?: return JSONObject();val j=saved(k)
        return JSONObject().apply { j.optJSONObject("settings")?.let { put("settings",it) };j.optJSONObject("expected_settings")?.let { put("expected_settings",it) } }
    }
    fun restoreSent(k:ChatKey,body:JSONObject) {
        require(valid(k) && state.value.ready) { "当前会话已变化，未恢复附件" }
        val j=saved(k)
        require(j.rows("uploads") { it }.isEmpty() && j.rows("references") { it }.isEmpty()) { "已有新附件或引用，请先处理它们，再恢复提交快照" }
        val service=api ?: error("服务未连接")
        val images=body.strings("attachments")
        j.put("references",body.optJSONArray("references") ?: JSONArray())
        j.put("uploads",JSONArray(images.map { id -> JSONObject().put("local",UUID.randomUUID().toString()).put("name","恢复的图片").put("image",true).put("status","checking").put("meta",JSONObject().put("id",id)) }))
        body.optJSONObject("settings")?.let { j.put("settings",it) };body.optJSONObject("expected_settings")?.let { j.put("expected_settings",it) }
        cache[k]=j.toString();update(k) { it.copy(saved=j.toString()) }
        launchSafe {
            persist(k,j)
            if(images.isNotEmpty()) {
                val found=runCatching { service.detail(k.device,"codex/attachments",mapOf("id" to k.chat,"ids" to images.joinToString(","))).rows("items") { it } }.getOrDefault(emptyList())
                if(valid(k)) { val current=saved(k);current.rows("uploads") { it }.forEach { row -> val meta=found.find { it.string("id")==row.optJSONObject("meta")?.string("id") };if(meta!=null) row.put("status","ready").put("meta",meta).put("name",meta.string("name")) else row.put("status","failed").put("error","原图片无法恢复，请重选或移除；不会省略附件发送") };persist(k,current) }
            }
        }
    }
    fun importUri(context:Context,uri:Uri,image:Boolean) {
        val k=key ?: return;val service=api ?: return;val synthetic=fixture
        if(!state.value.ready) return
        val local=UUID.randomUUID().toString()
        val job=launchSafe {
            val temp=java.io.File.createTempFile("selected-",".upload",context.cacheDir)
            try {
                val name=withContext(Dispatchers.IO) { context.contentResolver.query(uri,arrayOf(OpenableColumns.DISPLAY_NAME),null,null,null)?.use { if(it.moveToFirst()) it.getString(0) else null } ?: "文件" }
                val params=catalog().params(k.app)
                val before=saved(k);val uploads=before.rows("uploads") { it }
                require(!image || uploads.count { it.optBoolean("image") }<params.maxImages) { "最多${params.maxImages}张图片" }
                persist(k,before.put("uploads",JSONArray(uploads+JSONObject().put("local",local).put("name",name).put("image",image).put("status","uploading"))),synthetic)
                withContext(Dispatchers.IO) {
                    context.contentResolver.openInputStream(uri)?.use { input ->
                        val limit=if(image) params.maxImageBytes else 100L*1024*1024
                        temp.outputStream().use { out -> val buffer=ByteArray(65536);var count=0L
                            while(true) { currentCoroutineContext().ensureActive();val n=input.read(buffer);if(n<0) break;count+=n;require(count<=limit) { "文件超过上传上限" };out.write(buffer,0,n) }
                        }
                    } ?: error("无法读取所选文件，请重新选择")
                }
                // A picture shows itself in its tile (10-27): its preview is made before the upload and goes with the row.
                if(image) withContext(Dispatchers.IO) { photoPreview(context,temp) }?.let { preview ->
                    val j=saved(k);val row=j.rows("uploads") { it }.firstOrNull { it.string("local")==local }
                    if(valid(k) && row!=null) { row.put("preview",preview);persist(k,j,synthetic) } else dropPhotoPreview(preview)
                }
                val target=if(k.chat=="@new") ensureNewId(k,service) else k.chat
                val meta=service.uploadStream(k.device,target,name,temp.length(),image,k.chat=="@new") { temp.inputStream() }
                if(valid(k)) { val j=saved(k);j.rows("uploads") { it }.firstOrNull { it.string("local")==local }?.put("status","ready")?.put("meta",meta);persist(k,j,synthetic) }
            } catch(e:CancellationException) { throw e }
            catch(e:Exception) { if(valid(k)) { val j=saved(k);j.rows("uploads") { it }.firstOrNull { it.string("local")==local }?.put("status","failed")?.put("error",e.message ?: "上传失败");persist(k,j,synthetic);update(k) { it.copy(error=e.message) } } }
            finally { temp.delete() }
        };jobs+=job;uploadJobs[local]=job
    }
    fun removeUpload(local:String) {
        uploadJobs.remove(local)?.cancel()
        val k=key ?: return;val j=saved(k)
        j.rows("uploads") { it }.filter { it.string("local")==local }.forEach { dropPhotoPreview(it.string("preview")) }
        // Removing a pending local row never silently removes other attachments.
        launchSafe { persist(k,j.put("uploads",JSONArray(j.rows("uploads") { it }.filter { it.string("local")!=local }))) }
    }
    private suspend fun ensureNewId(k:ChatKey,service:ReadApi):String = newIds.withLock {
        val old=saved(k).string("new_id");if(old.isNotBlank()) return@withLock old
        val id=service.detail(k.device,"chat/new/draft",body=JSONObject()).getString("request_id")
        require(Regex("[a-f0-9]{32}").matches(id));persist(k,saved(k).put("new_id",id));id
    }
    /**
     * 创建并发送 (0.8, web new-chat-ui.js send, 10-16): the draft becomes a job of its own and the sheet starts afresh at
     * once, keeping the source, project and picks; the job is sent and followed outside the sheet, so nothing here waits
     * on the computer but the draft's request id (asked for when the sheet opened).
     */
    fun create() {
        val k=key ?: return;val service=api ?: return
        if(!state.value.ready || k.chat!="@new" || !active.add(k)) return
        update(k) { it.copy(busy=true,error=null) }
        launchSafe {
            try {
                val rid=ensureNewId(k,service);val j=saved(k);require(valid(k)) { "来源已切换，未提交" }
                val extras=sendExtras()
                val text=j.string("first_message").trim()
                val references=extras.optJSONArray("references") ?: JSONArray()
                val images=j.rows("uploads") { it }.filter { it.optBoolean("image") }.mapNotNull { it.optJSONObject("meta") }
                require(text.isNotBlank() || images.isNotEmpty() || references.length()>0) { "请输入首条消息" }
                // No folder is 无项目, as the sheet shows it; sources without new_projectless need a workspace.
                val snap=catalog();val caps=snap.info(k.app).caps
                val folder=j.string("folder");val projectless=caps.newProjectless && (j.string("projectless")=="1" || folder.isBlank())
                require(folder.isNotBlank() || projectless) { "${snap.name(k.app)} 要选一个工作区" }
                val body=JSONObject().put("request_id",rid).put("app",k.app).put("folder",if(projectless) "" else folder).put("text",text)
                    .put("attachments",extras.optJSONArray("attachments") ?: JSONArray()).put("references",references)
                if(projectless) body.put("projectless",true)
                val model=j.string("new_model");if(model.isNotBlank()) body.put("settings",JSONObject().put("model",model).put("effort",j.string("new_effort").ifBlank { null } ?: JSONObject.NULL))
                if(caps.newPermission && j.string("new_permission").isNotBlank()) body.put("permission",j.string("new_permission")).put("permission_confirmed",j.optBoolean("permission_confirmed"))
                val name=JSONObject(state.value.newData).optJSONObject("folders")?.rows("items") { it }?.find { it.string("path")==folder }?.string("name")
                val job=NewJob(rid,k.app,if(projectless) "" else folder,projectless,if(projectless) "" else name?.ifBlank { null } ?: folder.substringAfterLast('/').substringAfterLast('\\'),text,
                    references=references.toString(),images=JSONArray(images).toString(),body=body.toString(),pending=JSONObject().put("state","creating").put("message","正在创建对话…").toString())
                // The sheet starts afresh: same source, project and picks; the words, files and request id go with the job.
                j.rows("uploads") { it }.forEach { dropPhotoPreview(it.string("preview")) }
                persist(k,JSONObject(j.toString()).apply { listOf("new_id","first_message","uploads","references").forEach { remove(it) } })
                created(job)
            } catch(e:CancellationException) { throw e }
            catch(e:Exception) { update(k) { it.copy(error="还没发出，草稿还在："+(e.message ?: "请稍后再试")) } }
            finally { active.remove(k);update(k) { it.copy(busy=false) } }
        }
    }
    /**
     * 恢复草稿 (web restore): a first message that was not sent goes back into the sheet to change and send again. Its
     * pictures went up under the old request and cannot follow; the sheet says so.
     */
    fun restoreNew(job:NewJob) {
        val k=key ?: return
        if(k.chat!="@new" || k.app!=job.app) return
        launchSafe {
            saved(k).rows("uploads") { it }.forEach { dropPhotoPreview(it.string("preview")) }
            val j=saved(k).put("first_message",job.text).put("folder",job.folder).put("projectless",if(job.projectless) "1" else "")
                .put("references",JSONArray(job.references)).put("uploads",JSONArray())
            j.remove("new_id")
            persist(k,j)
            if(JSONArray(job.images).length()>0) update(k) { it.copy(newNote="照片没有跟着恢复，请重新添加") }
        }
    }
    fun selectSettings(settings:JSONObject,expected:JSONObject) {
        val k=key ?: return;launchSafe { persist(k,saved(k).put("settings",settings).put("expected_settings",expected));update(k) { it.copy(result="设置已绑定下一条消息，尚未发送") } }
    }
    /** 项目 of a new conversation: a folder, or 无项目. Chosen skills belong to the old folder and are dropped (web). */
    fun chooseFolder(path:String,projectless:Boolean) {
        val k=key ?: return;if(!state.value.ready || k in active) return
        val j=saved(k)
        if(j.string("folder")==path && (j.string("projectless")=="1")==projectless) return
        read?.cancel();generation++
        update(k) { it.copy(data="{}",busy=false,error=null) }
        j.put("folder",path).put("projectless",if(projectless) "1" else "")
        j.put("references",JSONArray(j.rows("references") { it }.filter { it.string("kind")!="skill" }))
        launchSafe { persist(k,j) }
    }
    fun setNewPermission(option:JSONObject) { val k=key ?: return;launchSafe { persist(k,saved(k).put("new_permission",option.string("value")).put("new_permission_name",option.string("name")).put("permission_confirmed",option.optBoolean("confirm"))) } }
    /**
     * 核对上次操作: what became of an action whose reply was lost, read back from the computer; nothing is sent again.
     * A Codex answer has a receipt, DeepSeek's model and permission are read back. A Claude press has neither, and the
     * computer takes its token for 2 minutes only (10-27: the line stayed for ever and a tap changed nothing): Claude's
     * state is read again, shown, and the press settled, with what that state shows ([claudePressFound]).
     */
    fun checkAction() {
        val k=key ?: return;val service=api ?: return
        val pending=saved(k).optJSONObject("pending_action")?.takeIf { it.string("status")=="unknown" } ?: return
        if(state.value.busy || state.value.checking) return
        update(k) { it.copy(checking=true,error=null,result="") }
        launchSafe {
            var checked=false
            try {
                val result=when(pending.string("route")) {
                    // 通用布局的答复（第二批 A3）和 Codex 一样有自己的回执。
                    "codex/answer", "generic/answer" -> {
                        val receipt=service.receipt(k.device,k.chat,pending.getJSONObject("body").getString("request_id"))
                        if(receipt.string("state") in listOf("accepted","rejected")) settle(k,pending,"receipt")
                        "回答回执：${receipt.string("state")}"
                    }
                    "claude/choose" -> {
                        val read=service.control(k.device,k.chat)
                        stateRead(k,JSONObject(read.raw))
                        settle(k,pending,"checked")
                        claudePressFound(pending,read)
                    }
                    else -> {
                        val actual=JSONObject(service.control(k.device,k.chat).raw);val body=pending.getJSONObject("body")
                        val confirmed=when(pending.string("route")) {
                            "deepseek/permission" -> actual.string("permission")==body.string("preset")
                            "deepseek/model" -> body.optJSONObject("settings")?.let { wanted -> val current=actual.optJSONObject("settings") ?: JSONObject();wanted.keys().asSequence().all { wanted.opt(it)==current.opt(it) } }==true
                            else -> false
                        }
                        if(confirmed) settle(k,pending,"read")
                        if(confirmed) "已读回所选设置" else "此来源没有独立动作回执，请核对刷新后的实际状态；不会自动重试。"
                    }
                }
                update(k) { it.copy(result=result) }
                checked=true
            } catch(e:CancellationException) { throw e }
            catch(e:Exception) { update(k) { it.copy(error=e.message ?: "没读到电脑上的状态，请稍后再核对") } }
            finally { update(k) { it.copy(checking=false) } }
            // The pane and the cards follow what was found. (A plain refresh() here, with no pane open, left the page
            // busy for good: every later action and state poll waited on it.)
            if(checked && valid(k)) {
                state.value.pane?.let { refresh(it) }
                if(pending.string("route")!="claude/choose") changed()
            }
        }
    }
    /**
     * Claude's state was read (entering the conversation, a poll, after a send or a press): a press still unknown past
     * the 2 minutes the computer takes its token, or kept before 10-27 without a time, can no longer land. It is
     * settled quietly and its line goes (10-27: 「上次操作的结果还没确认」 stayed for ever). Nothing is sent again.
     */
    fun claudeStateRead(k:ChatKey) {
        if(!valid(k) || catalog().cardLayout(k.app)!="claude.v1" || !state.value.ready || state.value.checking || k in active) return
        val pending=saved(k).optJSONObject("pending_action")?.takeIf { it.string("route")=="claude/choose" && it.string("status")=="unknown" } ?: return
        val at=pending.optLong("at")
        if(at>0 && System.currentTimeMillis()-at<ClaudePressLife) return
        launchSafe { settle(k,pending,"expired") }
    }
    /**
     * [pending] done, kept as the last action (the next one moves it to action_history), when it is still the one
     * waiting there; and the words its lost reply left in the status line go with it.
     */
    private suspend fun settle(k:ChatKey,pending:JSONObject,how:String) {
        if(!valid(k)) return
        val j=saved(k);val now=j.optJSONObject("pending_action") ?: return
        if(now.string("status")!="unknown" || now.optJSONObject("body")?.string("request_id")!=pending.optJSONObject("body")?.string("request_id")) return
        persist(k,j.put("pending_action",JSONObject(now.toString()).put("status","done").put("settled",how)))
        update(k) { it.copy(error=if(it.error!=null && it.error==lostReply) null else it.error) }
    }
    /** What a lost reply left in the status line ([action]), cleared when that action is settled. */
    private var lostReply:String?=null
    /**
     * An answer, approval or desktop choice, posted at once as the web does (0.8): the computer checks it still waits
     * there (question revision, event, token) and turns a stale one away, so the phone no longer reads the state first.
     * [question] stays for the call sites; its revision travels in the body. The copy kept on this phone has when it was
     * posted ("at", 10-27) and [local] (what a Claude press was, [claudePress]), neither of which is sent.
     */
    fun action(route:String,body:JSONObject,@Suppress("UNUSED_PARAMETER") question:JSONObject?=null,local:JSONObject?=null) {
        val k=key ?: return;val service=api ?: return;if(state.value.busy || !active.add(k)) return
        val synthetic=fixture;update(k) { it.copy(busy=true,error=null,result="") }
        launchSafe {
            var posted=false
            try {
                require(route!="claude/choose" || body.string("token").isNotBlank()) { "桌面选项已变化，请刷新" }
                require(valid(k)) { "来源或会话已切换，未提交" }
                val payload=JSONObject(body.toString()).put("id",k.chat)
                val rid=UUID.randomUUID().toString();payload.put("request_id",rid)
                val previous=saved(k).optJSONObject("pending_action")
                require(previous==null || previous.string("status")=="done" || actionIdentity(previous.string("route"),previous.optJSONObject("body") ?: JSONObject())!=actionIdentity(route,payload)) { "上次操作结果仍待核对，请刷新来源状态后处理" }
                val next=saved(k)
                if(previous!=null) next.put("action_history",JSONArray(next.rows("action_history") { it }+previous))
                val at=System.currentTimeMillis()
                fun kept(status:String)=JSONObject().put("route",route).put("body",payload).put("status",status).put("at",at).apply { if(local!=null) put("local",JSONObject(local.toString())) }
                persist(k,next.put("pending_action",kept("unknown")),synthetic)
                posted=true
                val result=when {
                    route=="codex/answer" || route=="generic/answer" -> service.command(k.device,"answer",payload)
                    route=="claude/choose" && local?.string("what")=="stop" -> service.command(k.device,"stop",payload)
                    else -> service.detail(k.device,route,body=payload)
                }
                persist(k,saved(k).put("pending_action",kept("done")),synthetic)
                update(k) { it.copy(result=result.string("text").ifBlank { "操作已返回，请刷新核对实际状态" }) }
                if(state.value.pane!=null) refresh(state.value.pane.orEmpty())
                changed()
            } catch(e:CancellationException) { throw e }
            catch(e:Exception) {
                // Turned away by the computer (4xx: answered elsewhere, expired, changed): nothing happened there, so it
                // is not left to be checked. A lost reply (network) stays "unknown" and is never sent again by itself;
                // it says so in words, not the system's ("timeout").
                val turnedAway=posted && e is ServiceFailure && e.status in 400..499
                if(turnedAway) persist(k,saved(k).apply { remove("pending_action") },synthetic)
                val why=if(posted && e !is ServiceFailure) "没收到电脑的回复，上次操作的结果还没确认；不会自动重试。" else e.message ?: "操作结果待确认；不会自动重试"
                lostReply=if(posted && !turnedAway) why else null
                update(k) { it.copy(error=why) }
                if(turnedAway) changed()
            }
            finally { active.remove(k);update(k) { it.copy(busy=false) } }
        }
    }
    /**
     * A button of Claude's next-step box or of a task card, pressed on the computer as if clicked there (web pressNext,
     * pressTask). The computer checks the box or card still waits with that very button, so a press that comes too
     * late is refused there instead of landing elsewhere; a refusal leaves the buttons for another try.
     */
    fun claudeButton(card:String,route:String,body:JSONObject,label:String) {
        val k=key ?: return;val service=api ?: return
        if(catalog().cardLayout(k.app)!="claude.v1" || route !in setOf("claude/next","claude/task") || state.value.pressing) return
        update(k) { it.copy(cards=it.cards+(card to "pressing:$label"),error=null) }
        launchSafe {
            try {
                val r=service.detail(k.device,route,body=JSONObject(body.toString()).put("id",k.chat))
                update(k) { it.copy(cards=it.cards+(card to "done:"+r.string("text").ifBlank { "已在电脑上点了「$label」" })) }
                changed()
            } catch(e:CancellationException) { throw e }
            catch(e:Exception) { update(k) { it.copy(cards=it.cards+(card to "error:"+(e.message ?: "没有点上，请在电脑上处理"))) } }
        }
    }
    /**
     * 电脑上打开: asks the computer to show this conversation in its desktop app. Not a message, nothing is sent. The
     * state is read again at once, so the chips and the send button follow (web: openOnPC, then refresh). 11-17: when
     * Codex did not take the conversation it says why in that state, so that reason is shown instead of a red error.
     */
    fun openOnComputer() {
        val k=key ?: return;val service=api ?: return
        if(k.chat=="@new" || state.value.busy) return
        update(k) { it.copy(busy=true,error=null,result="") }
        launchSafe {
            try {
                val r=service.detail(k.device,"chat/open",body=JSONObject().put("app",k.app).put("id",k.chat))
                update(k) { it.copy(result=r.string("text").ifBlank { "已在电脑上打开" }) }
                if(valid(k)) changed()
            }
            catch(e:Exception) {
                if(e is ServiceFailure && e.code=="codex_not_taken") { if(valid(k)) changed() }
                else update(k) { it.copy(error=e.message ?: "电脑上没有打开，请稍后再试") }
            }
            finally { update(k) { it.copy(busy=false) } }
        }
    }
    /** Clears the one-line result after the UI showed it. */
    fun clearResult() { mutable.update { it.copy(result="") } }
    fun computerFile(reference:JSONObject) {
        if(reference.string("download_id").isBlank()) { key?.let { k -> update(k) { it.copy(error="请更新电脑端后下载文件") } };return }
        file(JSONObject(reference.toString()).put("id",reference.string("download_id")).put("reference",reference))
    }
    private var linkRead:Job?=null
    /**
     * A file an answer links to (web reading-ui.js referencedFile; user 10-27, as on the iPhone): its page, to look at,
     * save or share, found by its path among the files the computer lists for this conversation (the files its
     * answers name). One that is not listed says why; it used to read （链接未开放）.
     */
    fun openLinkedFile(path:String) {
        val k=key ?: return;val service=api ?: return
        update(k) { it.copy(error=null) }
        linkRead?.cancel()
        linkRead=launchSafe {
            try {
                val listed=service.detail(k.device,"chat/files",mapOf("app" to k.app,"id" to k.chat))
                if(!valid(k)) return@launchSafe
                listing=k to listed
                val items=listed.rows("items") { it }
                val match=items.find { normalizePath(it.string("path"))==normalizePath(path) } ?: items.find { looseFilePath(it.string("path"))==looseFilePath(path) }
                when {
                    match==null || match.string("id").isBlank() -> update(k) { it.copy(error="这个文件不在电脑列出的对话文件里，现在打不开；电脑端更新后再试") }
                    match.string("state")=="missing" -> update(k) { it.copy(error="文件已移动或删除") }
                    // Its page goes back to the conversation, not to the list of files.
                    else -> file(JSONObject(match.toString()).put("linked",true))
                }
            } catch(e:CancellationException) { throw e }
            catch(e:Exception) { if(valid(k)) update(k) { it.copy(error=e.message ?: "没读到电脑上的对话文件，请稍后再试") } }
        }
    }
    /**
     * A picture sent with a message (state `images`; web codex-ui.js renderImages and previewImage): its small copy for
     * the bubble, or the whole one to look at, fetched from the computer once and kept in [caches] by the picture's id
     * (iPhone sentPicture). Its path, or null when it cannot be had; for the whole one the page says why.
     */
    suspend fun sentPicture(caches:java.io.File,picture:SentPicture,whole:Boolean):String? {
        val k=key ?: return null;val service=api ?: return null
        val folder=java.io.File(java.io.File(caches,SentPictureFolder),picture.id)
        val kept=java.io.File(folder,if(whole) "whole.png" else "small.png")
        if(kept.isFile) return kept.path
        return try {
            withContext(Dispatchers.IO) {
                folder.mkdirs()
                // Written aside first: a fetch cut short never passes for the picture.
                val part=java.io.File.createTempFile(kept.name,".part",folder)
                try { part.outputStream().use { service.sentPicture(k.device,picture.id,!whole,it) };check(part.renameTo(kept) || kept.isFile) { "图片没能存到手机上" } }
                finally { part.delete() }
            }
            kept.path
        } catch(e:CancellationException) { throw e }
        catch(e:Exception) { if(whole) update(k) { it.copy(error=if(e is ServiceFailure && e.status==404) "电脑上已经没有这张图片了" else e.message ?: "没取到这张图片，请稍后再试") };null }
    }
    /**
     * A file the answer listed with it (`files`, §5.1) opens its page directly, carrying that very entry: no read of
     * the conversation's whole file list first, and the page goes back to the conversation. The page still reads the
     * file's meta and bytes as before.
     */
    fun openAnswerFile(file: FileRef) {
        if (file.id.isBlank()) return
        file(file.toJson().put("linked", true))
    }
    /**
     * A picture in an answer (§6.1): the computer's thumb at [width] (320 for a strip, 640 or 1280 in the text, 2048 or
     * 4096 for the viewer), kept on this phone by (computer, file id, `v`, width) (§7). Null when it cannot be had; the
     * page offers 重试.
     */
    suspend fun answerThumb(caches:java.io.File, file:FileRef, width:Int):android.graphics.Bitmap? {
        val k=key ?: return null;val service=api ?: return null
        if(file.id.isBlank()) return null
        val bucket=when { width<=320 -> 320; width<=640 -> 640; width<=1280 -> 1280; width<=2048 -> 2048; else -> 4096 }
        val version=file.stableVersion()
        val cache=ThumbCache(java.io.File(caches,ThumbCacheFolder),ThumbCacheLimit)
        val kept=if(version!=null) withContext(Dispatchers.IO) { cache.read(k.device,file.id,version,bucket) } else null
        val bytes=kept ?: try {
            val fetched=service.thumb(k.device,k.chat,file.id,bucket,version.orEmpty())
            // No version means no safe cache key: the computer is asked every time (an older computer).
            if(version!=null) withContext(Dispatchers.IO) { cache.write(k.device,file.id,version,bucket,fetched) }
            fetched
        } catch(e:CancellationException) { throw e }
        catch(_:Exception) { return null }
        return withContext(Dispatchers.IO) { decodeThumb(bytes,bucket) }
    }
    /**
     * The original of a file the answer listed, kept under `answer-files` per computer (§7): the same file is not
     * downloaded twice for its page, the viewer, saving or sharing. Null when this phone has no cache or the fetch fails.
     */
    suspend fun cachedAnswerFile(file:FileRef):java.io.File? {
        val k=key ?: return null;val service=api ?: return null;val dir=mediaDir ?: return null
        if(file.id.isBlank()) return null
        // No `v` and no size+modified: nothing to tell one version from the next, so nothing is kept.
        val version=file.stableVersion() ?: return null
        val cache=FileCache(java.io.File(dir,FileCacheFolder),FileCacheLimit)
        val ext=FileCache.safeExt(file.name)
        cache.read(k.device,file.id,version,ext)?.let { return it }
        return withContext(Dispatchers.IO) {
            cache.writeStream(k.device,file.id,version,ext) { output -> service.downloadTo(k.device,k.chat,file.id,output) }
        }
    }
    /** The kept original of an open file, when there is one already: saving and sharing then copy it, no second fetch. */
    fun cachedFileFor(file:JSONObject):java.io.File? {
        val k=key ?: return null;val dir=mediaDir ?: return null
        val id=file.string("id");if(id.isBlank()) return null
        val meta=file.optJSONObject("meta") ?: JSONObject()
        val version=fileVersion(file.string("v"), file.optLong("size").takeIf { it>0 } ?: meta.optLong("size"), file.optLong("modified").takeIf { it>0 } ?: meta.optLong("modified")) ?: return null
        return FileCache(java.io.File(dir,FileCacheFolder),FileCacheLimit).read(k.device,id,version,FileCache.safeExt(file.string("name")))
    }
    /** The pictures of one answer, in the order it shows them, in the viewer (§6.2): a full-screen page of its own. */
    fun openPictures(files:List<FileRef>, index:Int) {
        val k=key ?: return
        val pictures=files.filter { it.picture }
        if(pictures.isEmpty()) return
        val items=JSONArray(pictures.map { it.toJson() })
        update(k) { it.copy(pane="picture",busy=false,error=null,data=JSONObject().put("items",items).put("index",index.coerceIn(0,pictures.lastIndex)).toString(),result="",transfer="",savedUri=null,preview=null,previewFile=null) }
    }
    /** The address and headers for MediaPlayer/VideoView to stream a file (§6.2); null when it cannot be played. */
    suspend fun mediaSource(file:FileRef):MediaSource? {
        val k=key ?: return null;val service=api ?: return null
        // The local demo has no stream of its own: its made-up clip is played from a file on this phone.
        if(service is FixtureApi) {
            val dir=mediaDir
            if(dir!=null) {
                val bytes=runCatching { withContext(Dispatchers.IO) { service.download(k.device,k.chat,file.id) } }.getOrNull()
                if(bytes!=null && bytes.isNotEmpty()) {
                    val kept=java.io.File(dir,"fixture-${file.id}.${FileCache.safeExt(file.name)}")
                    withContext(Dispatchers.IO) { kept.writeBytes(bytes) }
                    return MediaSource(android.net.Uri.fromFile(kept).toString(), emptyMap())
                }
            }
        }
        return try { service.mediaSource(k.device,k.chat,file.id,file.version) }
        catch(e:CancellationException) { throw e }
        catch(_:Exception) { null }
    }
    /** A zip's listing (§5.7); null when the computer cannot read it. */
    suspend fun zipListing(file:FileRef):JSONObject? {
        val k=key ?: return null;val service=api ?: return null
        return try { service.fileZip(k.device,k.chat,file.id) }
        catch(e:CancellationException) { throw e }
        catch(_:Exception) { null }
    }
    fun cancelSave() { saveJob?.cancel() }
    fun openSaved(context:Context,uri:String,name:String) {
        try { context.startActivity(android.content.Intent.createChooser(android.content.Intent(android.content.Intent.ACTION_VIEW).setDataAndType(Uri.parse(uri),shareMime(name)).addFlags(android.content.Intent.FLAG_GRANT_READ_URI_PERMISSION),"打开已保存的文件")) }
        catch(_:Exception) { key?.let { k -> update(k) { it.copy(transfer="文件已保存，手机上暂时没有可用的打开应用") } } }
    }
    /**
     * A file's page: its words, its picture or PDF drawn here. A Word or Excel file is drawn here from the file itself
     * (user 10-28: "Word 和 Excel 在手机上直接显示"; [phoneOffice], "preview": "phone"). A CSV or TSV is drawn as a table
     * from the file itself too, whatever kind the computer gives it (11-16), its bytes read here as UTF-8 or GB18030
     * ([decodeCsvText]) because the computer's text preview knows only UTF-8 and UTF-16. PowerPoint, the old .doc and
     * .ppt show as the PDF the computer's Office makes when it offers one ("preview": "pdf" in the list or meta, 10-27;
     * kept as "pdf": true). 保存到手机, 系统分享 and 用其他应用打开 take the file itself, and work while the PDF is made.
     *
     * 11-26: a Word or Excel file is no longer read whole into the page's state. Its kept copy on this phone is what the
     * page streams from ([WorkspaceState.previewFile]); only a plain JVM without a cache still gets bytes. A file whose
     * body is too big (or that is too big itself) is shown as the computer's PDF when it offers one (1.0.11 kept), and
     * only without it as the failure page, which can still offer the answer's same-named PDF.
     */
    fun file(file:JSONObject) {
        val k=key ?: return;val service=api ?: return;saveJob?.cancel();read?.cancel();val g=++generation
        update(k) { it.copy(pane="file",busy=true,data=file.toString(),error=null,preview=null,previewFile=null,result="",transfer="",savedUri=null,savingFile=false,converting=false,previewNote="") }
        read=launchSafe { try {
            val q=mapOf("app" to k.app,"id" to k.chat,"file" to file.getString("id"))
            val meta=service.detail(k.device,"file/meta",q)
            val kind=meta.string("kind")
            val name=file.string("name").ifBlank { meta.string("name") }
            val size=meta.optLong("size")
            val version=file.string("v").ifBlank { meta.string("v") }
            // New limits (§5.8) when the app's cache is here; a plain JVM (tests) keeps 1.0.10's 20 MB.
            val cached = mediaDir!=null
            val pictureLimit = if(cached) PicturePreviewLimit else PreviewLimit
            val pdfLimit = if(cached) PdfPreviewLimit else PreviewLimit
            // A CSV or TSV is read here as text, whatever the computer calls it; it never goes through a PDF.
            val sheet=sheetKind(name)
            // The page that draws a Word or Excel file here (11-26: a CSV has a table page, not this one).
            val page=phoneOffice(name)?.takeIf { sheet==null }
            val pdf=kind=="download" && sheet==null && (meta.string("preview")=="pdf" || file.string("preview")=="pdf")
            val phone=phoneOffice(name)!=null && (kind=="download" || sheet!=null)
            val data=JSONObject(file.toString()).put("kind",kind).put("name",name).put("meta",meta).apply {
                remove("preview");remove("pdf")
                if(pdf) put("pdf",true)
                if(phone) put("preview","phone") else if(pdf) put("preview","pdf")
                if(version.isNotBlank()) put("v",version)
            }
            if(pdf && !phone) {
                // The page and its buttons at once; the PDF when Office on the computer has made it (5-30 s the first time).
                if(g==generation) update(k) { it.copy(data=data.toString(),busy=false,converting=true) }
                convert(k,service,FileRef(id=file.getString("id"),name=name,version=version,size=size,modified=meta.optLong("modified")),g)
                return@launchSafe
            }
            // A zip lists what is inside (§5.7); audio and video stream from the file route themselves (§6.2).
            if(data.string("view")=="archive" && zipFile(name)) {
                val zipped=zipListing(FileRef(id=file.getString("id"),name=name,version=version,size=size))
                val why=if(zipped!=null) { data.put("zip",zipped.toString());"" } else "这个压缩包读不了，可以保存后用其他应用打开。"
                if(g==generation) update(k) { it.copy(data=data.toString(),busy=false,previewNote=why) }
                return@launchSafe
            }
            if(data.string("view") in setOf("audio","video")) {
                if(g==generation) update(k) { it.copy(data=data.toString(),busy=false) }
                return@launchSafe
            }
            var text="";var bytes:ByteArray?=null;var keptFile:String?=null;var note="";var unshown=""
            val newComputer=data.string("view").isNotBlank()
            try {
                if(sheet!=null) {
                    // A newer computer's CSV/TSV comes already decoded by it (§5.4); an older one is read here as before.
                    if(csvSource(newComputer)==CsvSource.TEXT && size<=5L*1024*1024) {
                        val reply=service.detail(k.device,"file/text",q)
                        text=reply.string("text")
                        val (limited,more)=limitCsvRows(text)
                        if(more) { text=limited;data.put("rowsTruncated",true) }
                        if(text.isNotBlank()) { bytes=text.toByteArray(Charsets.UTF_8);data.put("sheet",sheet) }
                    } else if(size<=PreviewLimit) try {
                        text=decodeCsvText(service.download(k.device,k.chat,file.getString("id")))
                        // The table page reads UTF-8, as the phone's own text (3.3); the page is told the separator.
                        if(text.isNotBlank()) { bytes=text.toByteArray(Charsets.UTF_8);data.put("sheet",sheet) }
                    } catch(e:CharacterCodingException) { unshown="手机上显示不了这个文件，可保存后使用系统应用打开。" }
                } else {
                    if(kind=="text") {
                        val reply=service.detail(k.device,"file/text",q)
                        text=reply.string("text")
                        if(newComputer) {
                            data.put("truncated",reply.optBoolean("truncated"))
                            if(reply.optLong("total_size")>0) data.put("total_size",reply.optLong("total_size"))
                            if(data.string("lang").isBlank() && reply.string("lang").isNotBlank()) data.put("lang",reply.string("lang"))
                            if(data.optInt("line")<=0 && reply.optInt("line")>0) data.put("line",reply.optInt("line"))
                            if(reply.string("encoding").isNotBlank()) data.put("encoding",reply.string("encoding"))
                        }
                    }
                    // Pictures, PDFs and Word/Excel are kept on disk (§7), not read whole into memory first.
                    val picture=kind=="image" && (size<=0 || size<=pictureLimit)
                    val document=(kind=="pdf" || pdf) && (size<=0 || size<=pdfLimit)
                    // 11-26: a Word or Excel file past the file limit is not fetched at all; the failure page says so.
                    val overLimit=page!=null && size>OfficePreviewLimit
                    if(!overLimit && (picture || document || phone)) {
                        val ref=FileRef(id=file.getString("id"),name=name,version=version,size=size,modified=meta.optLong("modified"))
                        // With the app's cache, the file goes to disk; a plain JVM (tests) keeps the old in-memory way.
                        if(cached) {
                            val kept=cachedAnswerFile(ref)
                            // The file stays on disk and is streamed from there (11-26): a Word or Excel file is never
                            // read back into the page. A computer that gives no version to keep it by (or a cache that
                            // could not be written) leaves no file to stream, so its bytes are read as before — the
                            // size limits below keep that bounded, and a file past them is dropped at once.
                            if(kept!=null) keptFile=kept.path
                            else if(size<=PreviewLimit) bytes=service.download(k.device,k.chat,file.getString("id"))
                            else if(page!=null) note="预览未能加载，仍可尝试保存原文件。"
                        } else if(size<=PreviewLimit) bytes=service.download(k.device,k.chat,file.getString("id"))
                    }
                }
            } catch(e:CancellationException) { throw e } catch(_:Exception) { note="预览未能加载，仍可尝试保存原文件。" }
            // A CSV that could not be read, or is empty, says why instead of showing an empty table.
            if(sheet!=null && bytes==null) data.put("preview","failed")
            // 11-26: a Word or Excel file is drawn only when its body (word/document.xml, Excel's worksheets) and the
            // file itself are small enough. Only the zip's directory is read for that, never its body. Past the limit
            // the computer's Office can still turn it into a PDF (1.0.11, kept: for many computers that shows the whole
            // file); only without that does the failure page say the phone cannot draw it.
            if(page!=null) {
                val stored=keptFile?.let { java.io.File(it) }
                val total=when { size>0 -> size; stored!=null -> stored.length(); bytes!=null -> bytes!!.size.toLong(); else -> 0L }
                if(total>OfficePreviewLimit) unshown=OfficeTooLargeNote
                else if(stored!=null || bytes!=null) officeTooLarge(page,total,if(stored!=null) zipEntrySizes(stored) else zipEntrySizes(bytes!!))?.let { unshown=it }
                if(unshown.isNotBlank() && pdf) {
                    // Not fetched at all when the file itself is past the limit; the computer's PDF is shown instead.
                    data.put("preview","pdf")
                    if(g==generation) update(k) { it.copy(data=data.toString(),busy=false,converting=true,preview=null,previewFile=null,previewNote="",transfer=note) }
                    convert(k,service,FileRef(id=file.getString("id"),name=name,version=version,size=size,modified=meta.optLong("modified")),g)
                    return@launchSafe
                }
                if(unshown.isNotBlank()) {
                    data.put("preview","failed")
                    bytes=null
                    // The same-named PDF the answer listed, when there is one (design §4.1 third point).
                    if(file.optBoolean("linked")) siblingPdf(k,service,name)?.let { data.put("pdf_file",it) }
                }
            }
            if(g==generation) update(k) { it.copy(data=data.toString(),result=text,preview=bytes,previewFile=keptFile,busy=false,transfer=note,previewNote=unshown) }
        } catch(e:CancellationException) { throw e } catch(e:Exception) { if(g==generation) update(k) { it.copy(error=e.message,busy=false,converting=false) } } }
    }
    /**
     * A PDF the answer lists beside a file of the same name (11-26, design §4.1 third point), for the failure page's
     * 看 PDF 版: the conversation's file list, matched by name without its extension, in any case. Null when there is
     * none, or the list cannot be read; a file opened from the computer's browser has no answer, so none is looked for.
     */
    private suspend fun siblingPdf(k:ChatKey,service:ReadApi,name:String):JSONObject? {
        val stem=name.substringBeforeLast('.',"").trim()
        if(stem.isBlank()) return null
        val listed=runCatching {
            listing?.takeIf { it.first==k }?.second ?: service.detail(k.device,"chat/files",mapOf("app" to k.app,"id" to k.chat)).also { listing=k to it }
        }.getOrNull() ?: return null
        return listed.rows("items") { it }.firstOrNull { item ->
            item.string("id").isNotBlank() && item.string("state")!="missing" && fileExtension(item.string("name"))=="pdf" &&
                item.string("name").substringBeforeLast('.',"").equals(stem,ignoreCase=true)
        }
    }
    /**
     * The computer's PDF of a file for the page of generation [g]; kept on disk like any other original (§7). 11-26: a
     * Word or Excel file whose conversion fails gives the failure page (and the answer's same-named PDF, if listed);
     * anything else keeps saying why there is no preview.
     */
    private suspend fun convert(k:ChatKey,service:ReadApi,file:FileRef,g:Int) {
        var note=""
        val pdf=try { service.filePdf(k.device,k.chat,file.id,if(mediaDir!=null) PdfPreviewLimit else PreviewLimit) }
            catch(e:CancellationException) { throw e }
            catch(e:Exception) { note=pdfFailure(e);null }
        if(pdf==null) {
            if(g!=generation) return
            val data=JSONObject(state.value.data)
            val page=data.string("name").let { phoneOffice(it)!=null && sheetKind(it)==null }
            if(!page) { update(k) { it.copy(converting=false,previewNote=note) };return }
            if(data.optBoolean("linked")) siblingPdf(k,service,data.string("name"))?.let { data.put("pdf_file",it) }
            update(k) { it.copy(converting=false,preview=null,previewFile=null,data=data.put("preview","failed").toString(),previewNote=note) }
            return
        }
        val dir=mediaDir
        val kept=if(dir==null) null else withContext(Dispatchers.IO) {
            FileCache(java.io.File(dir,FileCacheFolder),FileCacheLimit).writeStream(k.device,file.id,file.stableVersion() ?: "pdf","pdf") { it.write(pdf) }
        }
        if(g==generation) update(k) { it.copy(converting=false,preview=if(kept==null) pdf else null,previewFile=kept?.path) }
    }
    /**
     * The phone could not draw the open Word or Excel file (a damaged or protected one, or the web view's renderer was
     * ended), or the table of a CSV or TSV. 11-26: the computer's own PDF comes first (1.0.11: the computer's Office can
     * often show the whole file), and only when it does not offer one, or the conversion fails, the failure page
     * (design §6.1), which offers the same-named PDF from the answer when there is one. A CSV has no PDF: its source,
     * already read, is shown instead (11-16). Once per page; saving and sharing still take the file itself.
     */
    fun officeFailed() {
        val k=key ?: return;val service=api ?: return;val s=state.value;val g=generation
        val data=JSONObject(s.data)
        if(s.pane!="file" || data.string("preview")!="phone") return
        // A CSV or TSV is read here and the computer has no PDF of it: show the source that is already here.
        if(data.string("sheet").isNotBlank() || sheetKind(data.string("name"))!=null) {
            update(k) { it.copy(preview=null,previewFile=null,data=data.put("preview","failed").toString(),previewNote="表格显示不了，下面是原文") }
            return
        }
        if(data.optBoolean("pdf")) {
            // 1.0.11 kept: the computer's Office turns it into a PDF; a conversion that fails lands on the failure page.
            update(k) { it.copy(preview=null,previewFile=null,data=data.put("preview","pdf").toString(),converting=true,previewNote="") }
            read=launchSafe { convert(k,service,FileRef(id=data.getString("id"),name=data.string("name"),version=data.string("v")),g) }
            return
        }
        update(k) { it.copy(preview=null,previewFile=null,data=data.put("preview","failed").toString(),previewNote="") }
        // The same-named PDF the answer listed, when it came from an answer: found after the page says it failed.
        if(!data.optBoolean("linked")) return
        read=launchSafe {
            val pdf=siblingPdf(k,service,data.string("name")) ?: return@launchSafe
            if(g==generation) update(k) { it.copy(data=JSONObject(it.data).put("pdf_file",pdf).toString()) }
        }
    }
    @Volatile private var listing:Pair<ChatKey,JSONObject>?=null
    /**
     * A file an HTML preview names beside itself: only one this conversation lists, matched exactly by its path (web
     * artifact-preview resource), at most 4 MB. Null for anything else, so the page shows it as missing.
     */
    suspend fun previewResource(file:JSONObject,path:String):ByteArray? {
        val k=key ?: return null;val service=api ?: return null
        if(path.isBlank() || file.string("path").isBlank()) return null
        val id=file.string("id")
        // A newer computer checks and reads the file beside the page itself (§5.6); an older one still goes through the
        // conversation's file list below.
        if(file.string("view").isNotBlank() && id.isNotBlank()) {
            try { return service.fileResource(k.device,k.chat,id,path) }
            catch(e:CancellationException) { throw e }
            catch(e:ServiceFailure) { if(e.status!=404) return null }
            catch(_:Exception) { return null }
        }
        val items=(listing?.takeIf { it.first==k }?.second ?: service.detail(k.device,"chat/files",mapOf("app" to k.app,"id" to k.chat)).also { listing=k to it }).rows("items") { it }
        val target=normalizePath(path)
        val match=items.find { it.string("id").isNotBlank() && it.string("path").isNotBlank() && normalizePath(it.string("path"))==target } ?: return null
        if(match.optLong("size")>4L*1024*1024 || match.string("state")=="missing") return null
        return service.download(k.device,k.chat,match.getString("id"))
    }
    fun diff(ref:String,offset:Int=0) {
        val k=key ?: return;val service=api ?: return;read?.cancel();val g=++generation
        update(k) { it.copy(pane="diff",busy=true,error=null,preview=null,converting=false,previewNote="") }
        read=launchSafe { try { val r=service.detail(k.device,"chat/diff",mapOf("app" to k.app,"id" to k.chat,"ref" to ref,"offset" to "$offset"));if(g==generation) update(k) { it.copy(data=r.toString(),busy=false) } } catch(e:CancellationException) { throw e } catch(e:Exception) { if(g==generation) update(k) { it.copy(error=e.message,busy=false) } } }
    }
    fun saveFile(context:Context,uri:Uri,file:JSONObject) {
        val k=key ?: return;val service=api ?: return;val g=generation
        if(saveJob?.isActive==true) return
        update(k) { it.copy(savingFile=true,transfer="正在保存…",savedUri=null) }
        val kept=cachedFileFor(file)
        saveJob=scope.launch {
            try {
                withContext(Dispatchers.IO) {
                    context.contentResolver.openOutputStream(uri,"w")?.use { output ->
                        var count=0L;var last=-1L
                        val size=kept?.length()?.takeIf { it>0 } ?: file.optJSONObject("meta")?.optLong("size") ?: file.optLong("size")
                        val guarded=object:java.io.FilterOutputStream(output) {
                            override fun write(buffer:ByteArray,offset:Int,length:Int) {
                                require(state.value.key==k && g==generation) { "会话已切换，保存已停止" }
                                out.write(buffer,offset,length);count+=length
                                val percent=if(size>0) (count*100/size).coerceAtMost(100) else count/1048576
                                if(percent!=last) { last=percent;update(k) { it.copy(transfer=if(size>0) "正在保存 $percent%" else "已接收 $percent MB") } }
                            }
                        }
                        // A kept original is copied, not fetched a second time (§7).
                        if(kept!=null) kept.inputStream().use { input ->
                            val buffer=ByteArray(65536)
                            while(true) { val n=input.read(buffer);if(n<0) break;guarded.write(buffer,0,n) }
                        }
                        else service.downloadTo(k.device,k.chat,file.getString("id"),guarded)
                        require(size<0 || count==size) { "文件接收不完整，请重试" }
                    } ?: error("无法保存到所选位置")
                }
                require(valid(k) && g==generation) { "会话已切换，保存已停止" }
                update(k) { it.copy(transfer="已保存到所选位置：${file.string("name")}",savedUri=uri.toString()) }
            } catch(e:Exception) {
                withContext(NonCancellable) {
                    val removed=withContext(Dispatchers.IO) { runCatching { android.provider.DocumentsContract.deleteDocument(context.contentResolver,uri) }.getOrDefault(false) }
                    if(valid(k) && g==generation) update(k) { it.copy(transfer=(if(e is CancellationException) "已取消保存" else "保存失败：${e.message ?: "请重试"}")+(if(removed) "" else "。请检查所选位置并删除未完成的文件。")) }
                }
            } finally { if(valid(k) && g==generation) update(k) { it.copy(savingFile=false) } }
        }
        jobs+=saveJob!!
    }
    fun shareFile(context:Context,file:JSONObject,open:Boolean) {
        val k=key ?: return;val service=api ?: return;val g=generation
        if(state.value.busy) return
        update(k) { it.copy(busy=true,error=null) }
        val kept=cachedFileFor(file)
        val job=launchSafe {
            try {
                val shared=PlatformFiles.prepare(context,service,k,file.getString("id"),file.string("name"),{ state.value.key==k && generation==g },kept)
                if(valid(k) && generation==g) { PlatformFiles.launch(context,shared,open);update(k) { it.copy(result="已打开系统选择器，请在所选应用中确认后续操作。") } }
            } catch(e:Exception) { update(k) { it.copy(error=e.message ?: "没有可用的接收应用") } }
            finally { update(k) { it.copy(busy=false) } }
        };jobs+=job
    }
}

fun actionIdentity(route:String,body:JSONObject)=route+":"+(listOf("question_id","event_id","call_id","token","tool_id","title").firstNotNullOfOrNull { body.string(it).ifBlank { null } } ?: body.string("kind"))

/**
 * A zip's entries and their uncompressed sizes, read from its central directory: what is left of the file is not
 * decompressed, so a huge Word or Excel file can be judged before it is drawn (11-26). Empty for something that is
 * not a readable zip (the page then tries, and its own failure page says it could not).
 */
fun zipEntrySizes(file:java.io.File):Map<String,Long> = runCatching {
    java.util.zip.ZipFile(file).use { zip ->
        zip.entries().asSequence().filter { !it.isDirectory }.associate { it.name to it.size.coerceAtLeast(0) }
    }
}.getOrDefault(emptyMap())

/** [zipEntrySizes] for a zip held in memory (a plain JVM without the phone's cache): its central directory, too. */
fun zipEntrySizes(zip:ByteArray):Map<String,Long> {
    fun u16(at:Int)= (zip[at].toInt() and 0xff) or ((zip[at+1].toInt() and 0xff) shl 8)
    fun u32(at:Int)= u16(at).toLong() or (u16(at+2).toLong() shl 16)
    var end=-1
    // The end of the central directory is the last 22 bytes, plus a comment of at most 64 KB.
    for(at in maxOf(0,zip.size-22-65535)..zip.size-22) if(u32(at)==0x06054b50L) { end=at;break }
    if(end<0) return emptyMap()
    var at=u32(end+16).toInt()
    val sizes=mutableMapOf<String,Long>()
    repeat(u16(end+10)) {
        if(at<0 || at+46>zip.size || u32(at)!=0x02014b50L) return sizes
        val size=u32(at+24)
        val nameLength=u16(at+28);val extra=u16(at+30);val comment=u16(at+32)
        if(at+46+nameLength>zip.size) return sizes
        val name=String(zip,at+46,nameLength,Charsets.UTF_8)
        // 0xFFFFFFFF means the real size is in a zip64 extra field: too big to draw either way.
        if(!name.endsWith("/")) sizes[name]=if(size==0xFFFFFFFFL) Long.MAX_VALUE else size
        at+=46+nameLength+extra+comment
    }
    return sizes
}

/**
 * Why the phone does not draw a Word or Excel file (11-26, design §6.1), or null when it may: the file is past
 * [OfficePreviewLimit], or its body is past [OfficeBodyLimit] — word/document.xml for Word, the worksheets' XML added up
 * for Excel. [entries] is [zipEntrySizes] of the file, read before anything is drawn.
 */
fun officeTooLarge(page:String,size:Long,entries:Map<String,Long>):String? {
    if(size>OfficePreviewLimit) return OfficeTooLargeNote
    val body=when(page) {
        "word" -> entries["word/document.xml"] ?: 0L
        "sheet" -> entries.entries.sumOf { (name,bytes) -> if(name.startsWith("xl/worksheets/") && name.endsWith(".xml")) bytes else 0L }
        else -> 0L
    }
    return if(body>OfficeBodyLimit) OfficeTooLargeNote else null
}
