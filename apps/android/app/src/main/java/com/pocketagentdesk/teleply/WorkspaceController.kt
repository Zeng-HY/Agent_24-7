package com.pocketagentdesk.teleply

import android.content.Context
import android.net.Uri
import android.provider.OpenableColumns
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
data class WorkspaceState(val key:ChatKey?=null,val ready:Boolean=false,val pane:String?=null,val busy:Boolean=false,val error:String?=null,val data:String="{}",val saved:String="{}",val result:String="",val preview:ByteArray?=null,val transfer:String="",val savingFile:Boolean=false,val savedUri:String?=null,val choices:String="{}",val choicesBusy:Boolean=false,val choicesError:String?=null,val cards:Map<String,String> = emptyMap(),val newData:String="{}",val newNote:String?=null,
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
                if(next.app=="claude" && !synthetic) listOf(catalogKey(next) to next,lastCatalogKey(next) to lastCatalog(next)).forEach { (name,owner) ->
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
    fun close() { saveJob?.cancel();read?.cancel();generation++;mutable.update { it.copy(pane=null,data="{}",preview=null,busy=false,error=null,result=if(it.pane=="file") "" else it.result,converting=false,previewNote="") } }
    fun panel(name:String) {
        saveJob?.cancel();read?.cancel();generation++
        mutable.update { it.copy(pane=name,data="{}",busy=false,error=null,preview=null,newNote=if(name=="new") null else it.newNote,result=if(it.pane=="file") "" else it.result,converting=false,previewNote="") }
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
        if(k.app=="codex") return
        choiceRead?.cancel()
        val synthetic=fixture
        val shown=remembered(k,model).apply { if(fresh) put("refreshing",true) }
        update(k) { it.copy(choices=shown.toString(),choicesBusy=true,choicesError=null) }
        choiceRead=launchSafe {
            try {
                val data=JSONObject(shown.toString()).apply { remove("refreshing") }
                if(k.app=="claude") {
                    val catalog=service.detail(k.device,"claude/catalog",body=JSONObject().put("id",k.chat).put("fresh",fresh))
                    keepCatalog(k,catalog,synthetic);data.put("source_catalog",catalog)
                }
                if(k.app=="deepseek") {
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
        if(k.app=="claude") {
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
        if(k.app=="deepseek") {
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
        if(k.app!="claude" || state.value.busy || !active.add(k)) return
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
        if(k.app!="claude" || k.chat=="@new") return
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
                val before=saved(k);val uploads=before.rows("uploads") { it }
                require(!image || uploads.count { it.optBoolean("image") }<5) { "最多5张图片" }
                persist(k,before.put("uploads",JSONArray(uploads+JSONObject().put("local",local).put("name",name).put("image",image).put("status","uploading"))),synthetic)
                withContext(Dispatchers.IO) {
                    context.contentResolver.openInputStream(uri)?.use { input ->
                        val limit=if(image) 20L*1024*1024 else 100L*1024*1024
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
                // No folder is 无项目, as the sheet shows it; DeepSeek always needs one of its workspaces.
                val folder=j.string("folder");val projectless=k.app!="deepseek" && (j.string("projectless")=="1" || folder.isBlank())
                require(folder.isNotBlank() || projectless) { "DeepSeek 要选一个工作区" }
                val body=JSONObject().put("request_id",rid).put("app",k.app).put("folder",if(projectless) "" else folder).put("text",text)
                    .put("attachments",extras.optJSONArray("attachments") ?: JSONArray()).put("references",references)
                if(projectless) body.put("projectless",true)
                val model=j.string("new_model");if(model.isNotBlank()) body.put("settings",JSONObject().put("model",model).put("effort",j.string("new_effort").ifBlank { null } ?: JSONObject.NULL))
                if(k.app=="deepseek" && j.string("new_permission").isNotBlank()) body.put("permission",j.string("new_permission")).put("permission_confirmed",j.optBoolean("permission_confirmed"))
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
                    "codex/answer" -> {
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
        if(!valid(k) || k.app!="claude" || !state.value.ready || state.value.checking || k in active) return
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
                val result=if(route=="codex/answer") service.command(k.device,"answer",payload) else service.detail(k.device,route,body=payload)
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
        if(k.app!="claude" || route !in setOf("claude/next","claude/task") || state.value.pressing) return
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
     * state is read again at once, so the chips and the send button follow (web: openOnPC, then refresh).
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
            catch(e:Exception) { update(k) { it.copy(error=e.message ?: "电脑上没有打开，请稍后再试") } }
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
    fun cancelSave() { saveJob?.cancel() }
    fun openSaved(context:Context,uri:String,name:String) {
        try { context.startActivity(android.content.Intent.createChooser(android.content.Intent(android.content.Intent.ACTION_VIEW).setDataAndType(Uri.parse(uri),shareMime(name)).addFlags(android.content.Intent.FLAG_GRANT_READ_URI_PERMISSION),"打开已保存的文件")) }
        catch(_:Exception) { key?.let { k -> update(k) { it.copy(transfer="文件已保存，手机上暂时没有可用的打开应用") } } }
    }
    /**
     * A file's page: its words, its picture or PDF drawn here. A Word or Excel file is drawn here from the file itself
     * (user 10-28: "Word 和 Excel 在手机上直接显示"; [phoneOffice], "preview": "phone"). PowerPoint, the old .doc and .ppt,
     * and a Word or Excel file over 20 MB show as the PDF the computer's Office makes when it offers one ("preview":
     * "pdf" in the list or meta, 10-27; kept as "pdf": true). 保存到手机, 系统分享 and 用其他应用打开 take the file
     * itself, and work while the PDF is being made.
     */
    fun file(file:JSONObject) {
        val k=key ?: return;val service=api ?: return;saveJob?.cancel();read?.cancel();val g=++generation
        update(k) { it.copy(pane="file",busy=true,data=file.toString(),error=null,preview=null,result="",transfer="",savedUri=null,savingFile=false,converting=false,previewNote="") }
        read=launchSafe { try {
            val q=mapOf("app" to k.app,"id" to k.chat,"file" to file.getString("id"))
            val meta=service.detail(k.device,"file/meta",q)
            val kind=meta.string("kind")
            val pdf=kind=="download" && (meta.string("preview")=="pdf" || file.string("preview")=="pdf")
            val phone=kind=="download" && phoneOffice(file.string("name").ifBlank { meta.string("name") })!=null && meta.optLong("size")<=PreviewLimit
            val data=JSONObject(file.toString()).put("kind",kind).put("meta",meta).apply {
                remove("preview");remove("pdf")
                if(pdf) put("pdf",true)
                if(phone) put("preview","phone") else if(pdf) put("preview","pdf")
            }.toString()
            if(pdf && !phone) {
                // The page and its buttons at once; the PDF when Office on the computer has made it (5-30 s the first time).
                if(g==generation) update(k) { it.copy(data=data,busy=false,converting=true) }
                convert(k,service,file.getString("id"),g)
                return@launchSafe
            }
            var text="";var bytes:ByteArray?=null;var note=""
            try {
                if(kind=="text") text=service.detail(k.device,"file/text",q).string("text")
                if((phone || kind in listOf("image","pdf")) && meta.optLong("size")<=PreviewLimit) bytes=service.download(k.device,k.chat,file.getString("id"))
            } catch(e:CancellationException) { throw e } catch(_:Exception) { note="预览未能加载，仍可尝试保存原文件。" }
            if(g==generation) update(k) { it.copy(data=data,result=text,preview=bytes,busy=false,transfer=note) }
        } catch(e:CancellationException) { throw e } catch(e:Exception) { if(g==generation) update(k) { it.copy(error=e.message,busy=false,converting=false) } } }
    }
    /** The computer's PDF of a file for the page of generation [g]; the computer's words when it gives none. */
    private suspend fun convert(k:ChatKey,service:ReadApi,id:String,g:Int) {
        val pdf=try { service.filePdf(k.device,k.chat,id,PreviewLimit) }
            catch(e:CancellationException) { throw e }
            catch(e:Exception) { if(g==generation) update(k) { it.copy(converting=false,previewNote=pdfFailure(e)) };null }
        if(pdf!=null && g==generation) update(k) { it.copy(converting=false,preview=pdf) }
    }
    /**
     * The phone could not draw the open Word or Excel file (a damaged or protected one): the computer's PDF when it offers
     * one, as before 10-28; otherwise a line saying so. Once per page; the buttons keep taking the file itself.
     */
    fun officeFailed() {
        val k=key ?: return;val service=api ?: return;val s=state.value;val g=generation
        val data=JSONObject(s.data)
        if(s.pane!="file" || data.string("preview")!="phone") return
        if(!data.optBoolean("pdf")) { update(k) { it.copy(preview=null,data=data.put("preview","failed").toString(),previewNote="手机上显示不了这个文件，可保存后使用系统应用打开。") };return }
        update(k) { it.copy(preview=null,data=data.put("preview","pdf").toString(),converting=true,previewNote="") }
        read=launchSafe { convert(k,service,data.getString("id"),g) }
    }
    @Volatile private var listing:Pair<ChatKey,JSONObject>?=null
    /**
     * A file an HTML preview names beside itself: only one this conversation lists, matched exactly by its path (web
     * artifact-preview resource), at most 4 MB. Null for anything else, so the page shows it as missing.
     */
    suspend fun previewResource(file:JSONObject,path:String):ByteArray? {
        val k=key ?: return null;val service=api ?: return null
        if(path.isBlank() || file.string("path").isBlank()) return null
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
        saveJob=scope.launch {
            try {
                withContext(Dispatchers.IO) {
                    context.contentResolver.openOutputStream(uri,"w")?.use { output ->
                        var count=0L;var last=-1L
                        val size=file.optJSONObject("meta")?.optLong("size") ?: file.optLong("size")
                        val guarded=object:java.io.FilterOutputStream(output) {
                            override fun write(buffer:ByteArray,offset:Int,length:Int) {
                                require(state.value.key==k && g==generation) { "会话已切换，保存已停止" }
                                out.write(buffer,offset,length);count+=length
                                val percent=if(size>0) (count*100/size).coerceAtMost(100) else count/1048576
                                if(percent!=last) { last=percent;update(k) { it.copy(transfer=if(size>0) "正在保存 $percent%" else "已接收 $percent MB") } }
                            }
                        }
                        service.downloadTo(k.device,k.chat,file.getString("id"),guarded)
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
        val job=launchSafe {
            try {
                val cached=PlatformFiles.prepare(context,service,k,file.getString("id"),file.string("name")) { state.value.key==k && generation==g }
                if(valid(k) && generation==g) { PlatformFiles.launch(context,cached,open);update(k) { it.copy(result="已打开系统选择器，请在所选应用中确认后续操作。") } }
            } catch(e:Exception) { update(k) { it.copy(error=e.message ?: "没有可用的接收应用") } }
            finally { update(k) { it.copy(busy=false) } }
        };jobs+=job
    }
}

fun actionIdentity(route:String,body:JSONObject)=route+":"+(listOf("question_id","event_id","call_id","token","tool_id","title").firstNotNullOfOrNull { body.string(it).ifBlank { null } } ?: body.string("kind"))
