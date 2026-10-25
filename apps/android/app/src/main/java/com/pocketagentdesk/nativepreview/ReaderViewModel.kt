package com.pocketagentdesk.nativepreview

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import java.util.UUID
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.*

interface ReaderStore {
    suspend fun source(app:String) {}
    suspend fun detail(key:ChatKey,kind:String):String? = null
    suspend fun detail(key:ChatKey,kind:String,value:String) {}
    suspend fun positionFor(key:ChatKey):ReadingPosition? = if(key.app=="codex") position(key.scope,key.device,key.chat) else null
    suspend fun draft(key:ChatKey):String = ""
    suspend fun draft(key:ChatKey,text:String) {}
    suspend fun submissions(key:ChatKey):List<Submission> = emptyList()
    suspend fun submission(value:Submission) {}
    suspend fun begin(value:Submission) { submission(value); if(value.action=="send") draft(ChatKey(value.scope,value.device,value.chat,value.app),"") }
    suspend fun preferences(): Preferences
    suspend fun setOrigin(origin: String)
    suspend fun appearance(theme: String, dynamic: Boolean)
    suspend fun selection(scope: String, device: String, chat: String, title: String)
    suspend fun position(scope: String, device: String, chat: String): ReadingPosition?
    suspend fun save(position: ReadingPosition)
}
class NativeReaderStore(private val settings: SettingsStore, private val dao: ReadingDao) : ReaderStore {
    override suspend fun source(app:String)=settings.source(app)
    override suspend fun positionFor(key:ChatKey)=dao.find(key.scope,key.device,key.chat,key.app)
    override suspend fun detail(key:ChatKey,kind:String)=dao.detail(key.scope,key.device,key.app,key.chat,kind)
    override suspend fun detail(key:ChatKey,kind:String,value:String)=dao.detail(InteractionDraft(key.scope,key.device,key.app,key.chat,kind,value))
    override suspend fun draft(key:ChatKey)=dao.draft(key.scope,key.device,key.chat,key.app)?.text.orEmpty()
    override suspend fun draft(key:ChatKey,text:String)=dao.draft(ChatDraft(key.scope,key.device,app=key.app,chat=key.chat,text=text))
    override suspend fun submissions(key:ChatKey)=dao.submissions(key.scope,key.device,key.chat,key.app)
    override suspend fun submission(value:Submission)=dao.submission(value)
    override suspend fun begin(value:Submission)=dao.begin(value)
    override suspend fun preferences() = settings.flow.first()
    override suspend fun setOrigin(origin: String) = settings.origin(origin)
    override suspend fun appearance(theme: String, dynamic: Boolean) = settings.appearance(theme, dynamic)
    override suspend fun selection(scope: String, device: String, chat: String, title: String) = settings.selection(scope,device,chat,title)
    override suspend fun position(scope: String, device: String, chat: String) = dao.find(scope,device,chat)
    override suspend fun save(position: ReadingPosition) = dao.save(position)
}
/** [Launch]: the Teleply mark while the app finds out where it stands (0.9, web account page while booting). */
/** [Developer]: 开发者选项 under 设置 (0.9: the service address, the local demo and diagnostics, off the main pages). */
enum class Screen { Launch, Service, Login, Devices, Chats, Reading, Settings, Developer }
data class ReaderState(
    val screen: Screen = Screen.Launch, val settingsReturn: Screen = Screen.Service,
    /** Where 更改服务地址 goes back to; whether the server lets people register and reset passwords by email. */
    val serviceReturn: Screen = Screen.Login, val emailEnabled: Boolean = false,
    val app:String="codex", val origin: String = "", val scope: String = "", val device: Computer? = null,
    val account: Account? = null, val chats: List<Chat> = emptyList(), val query: String = "",
    val listCursor: String? = null, val listMore: Boolean = false,
    val chat: Chat? = null, val messages: List<Message> = emptyList(), val cursor: String? = null,
    val older: Boolean = false, val newer: Boolean = false, val searchQuery: String = "",
    val hits: List<Message> = emptyList(), val hitCursor: String? = null, val hitMore: Boolean = false, val searched: Boolean = false,
    val busy: Boolean = false, val error: String? = null, val expired: Boolean = false,
    val theme: String = "system", val dynamic: Boolean = false, val serverVersion: String = "",
    val anchor: ReadingPosition? = null, val scrollRevision: Int = 0, val fixture: Boolean = false,
    /** Web list display (spec 4.1): source "all" or one app; sort updated / created; status all / running / waiting / done; group none / project / app. */
    val listSource: String = "all", val listSort: String = "updated", val listStatus: String = "all", val listGroup: String = "none",
    /** Page meta of the open conversation (title, folder, status, runtime) for the context ring and 会话状态. */
    val runtime: String = "{}",
    /** Sidebar tree from /api/chat/projects (spec 4.2). */
    val tree: String = "{}", val treeError: String? = null,
    /** A new conversation waiting for its sheet: from a project's ＋ or the title bar (spec 4.2, 4.4). */
    val pendingNew: NewTarget? = null,
    /** Rows archived from here, kept off the list until 撤销 (a refresh would bring them back for a moment). */
    val hidden: Set<String> = emptySet(),
    /** The bar under the list after a swipe: 对话已归档 with 撤销; [ArchiveUndo.waiting] while Claude still reads it back. */
    val undo: ArchiveUndo? = null,
    /** One line shown at the bottom for a moment: why an archive or a restore did not happen. */
    val notice: String? = null,
    /** Children fetched past the first ones a row carries (再显示), by row key. */
    val moreKids: Map<String, List<Chat>> = emptyMap(),
    /** A new conversation just opened from its job: its first message shows until the record has it (web handoff). */
    val handoff: NewHandoff? = null,
    /** The job whose sheet is open (核对结果, 继续发送, 恢复草稿, 移除), by request id. */
    val jobSheet: String? = null,
    /** Which desktop apps the computer in use has (0.9.1): what the list chips, ⋯ 来源 and 新建对话 offer. */
    val sources: SourceInfo = SourceInfo(),
)

/**
 * The desktop apps a computer has (0.9.1), as its service reports them: remote.py keeps only the groups of the apps it
 * found there (machines.installed_apps, or "apps" in remote_config.json) in the sidebar tree, each with or without
 * conversations, so an app with no conversations yet is still there and an app that is not installed is not.
 * [apps] null: not known yet for [device]. [cached]: this phone's copy from an earlier visit, shown while the computer
 * is asked again. [failed]: why it could not be asked this time (a copy, if there is one, keeps showing).
 */
data class SourceInfo(val device: String = "", val apps: List<String>? = null, val loading: Boolean = false, val failed: String? = null, val cached: Boolean = false)

/** The desktop apps, in the order the web and the sidebar show them. */
val SourceOrder = listOf("codex", "claude", "deepseek")

/** What the computer in use offers; null while not known (never another computer's list). */
fun ReaderState.knownApps(): List<String>? = sources.apps?.takeIf { device != null && sources.device == device.id }

/** Where a new conversation starts: [wanted] when this computer has it, otherwise the first app it has. */
fun ReaderState.newApp(wanted: String): String = knownApps()?.let { apps -> if (wanted in apps) wanted else apps.firstOrNull() ?: wanted } ?: wanted

/** The apps of a sidebar tree (/api/chat/projects), each group one app this computer has. */
fun treeApps(tree: org.json.JSONObject): List<String> = tree.rows("apps") { it.string("app") }.filter { it in SourceOrder }.distinct().sortedBy { SourceOrder.indexOf(it) }
data class NewHandoff(val app: String, val id: String, val text: String)
/** A new conversation's page before it exists (web preview id new:…). */
fun isNewPage(chat: Chat?) = chat?.id?.startsWith("new:") == true
data class ArchiveUndo(val chat: Chat, val index: Int, val waiting: Boolean, val serial: Long)
/** A row's key in the list: its source and id. */
fun chatKey(chat: Chat) = chat.app + ":" + chat.id
/** [text] is the first message carried over when the source is switched inside the sheet ([switching]: keep it open). */
data class NewTarget(val app:String,val folder:String,val projectless:Boolean,val text:String="",val switching:Boolean=false,val restore:NewJob?=null)
/** The Teleply service every ordinary user signs in to (mobile/src/settings.mjs DEFAULT_ORIGIN, deploy/relay). */
const val DefaultOrigin = "https://8.166.15.235"

/** [defaultOrigin] is used until another service address is set under 设置 → 更改服务地址 (0.9: none to type at first). */
class ReaderViewModel(private val store: ReaderStore, private val defaultOrigin: String = DefaultOrigin, private val apiFactory: (String) -> ReadApi) : ViewModel() {
    private val mutable = MutableStateFlow(ReaderState())
    val state: StateFlow<ReaderState> = mutable.asStateFlow()
    private var api: ReadApi? = null
    /** The local demo's computer, for tests: what it was asked. */
    internal val fixtureWorld get() = (api as? FixtureApi)?.world
    val composer=ChatController(viewModelScope,store)
    val workspace=WorkspaceController(viewModelScope,store)
    val jobs=NewChatJobs(viewModelScope,store)
    init {
        composer.extras={workspace.sendExtras()};composer.boundSettings={workspace.boundSettings()};composer.sentExtras={k,extra -> workspace.clearSent(k,extra)};composer.restoreExtras={k,extra -> workspace.restoreSent(k,extra)};workspace.changed={ composer.refreshControl() }
        // No state poll while a tap waits on the computer (web claude-ui.js `choosing`).
        composer.pollPaused={ workspace.state.value.busy || workspace.state.value.pressing || composer.state.value.submitting }
        workspace.stateRead={ k,raw -> composer.applyState(k,raw) }
        workspace.created={ job -> jobCreated(job) }
        workspace.adopted={ job -> jobs.adopt(job) }
        jobs.settle={ job -> if(isNewPage(state.value.chat) && state.value.chat?.id==job.preview) finishJob(job) }
    }
    fun switchSource(app:String) = operation { g ->
        pendingNotification=null
        require(app in SourceOrder)
        api=api?.forSource(app)
        if(!state.value.fixture) store.source(app)
        commit(g) { it.copy(app=app,chat=null,messages=emptyList(),chats=emptyList(),anchor=null,screen=if(it.device!=null) Screen.Chats else it.screen,query="",listCursor=null,listMore=false) }
        persistSelection(state.value.scope,state.value.device?.id.orEmpty(),"","")
        loadChats(g)
    }
    private var pendingNotification:WatchTarget?=null
    fun openNotification(target:WatchTarget) { pendingNotification=target;operation { g ->
        val s=state.value;val key=target.key
        require(s.origin==target.origin && s.scope==key.scope && s.account!=null) { "通知登录范围已变化，请重新选择会话" }
        api?.close();api=apiFactory(s.origin).forSource(key.app)
        val service=requireNotNull(api);val account=service.account()
        val device=account.devices.firstOrNull { it.id==key.device && it.connectable } ?: error("通知对应电脑不可用")
        currentCoroutineContext().ensureActive()
        store.source(key.app)
        val known=if(s.sources.device==device.id) s.sources.apps else cachedSources(s.scope,device.id)
        commit(g) { ReaderState(origin=s.origin,scope=s.scope,app=key.app,account=account,device=device,screen=Screen.Chats,theme=s.theme,dynamic=s.dynamic,serverVersion=s.serverVersion,busy=true,
            sources=SourceInfo(device.id,known,loading=true,cached=known!=null)) }
        service.select(device.id)
        loadTree(true)
        readChat(g,Chat(key.chat,"通知对应会话"),true)
        pendingNotification=null
    } }
    fun live(foreground:Boolean) {
        val s=state.value
        val key=if(s.screen==Screen.Reading && !s.expired && s.device!=null && s.chat!=null) ChatKey(s.scope,s.device.id,s.chat.id,s.app) else null
        val newPage=isNewPage(s.chat)
        workspace.bind(if(s.device!=null && !s.expired) ChatKey(s.scope,s.device.id,s.chat?.id ?: "@new",s.app) else null,api,s.fixture)
        jobs.bind(s.scope,if(s.expired) null else s.device?.id,api,s.fixture)
        jobs.foreground(foreground)
        jobs.onScreen=if(newPage && s.screen==Screen.Reading) s.chat?.id else null
        pollList(foreground && s.screen==Screen.Chats && s.device!=null && !s.expired)
        pollDevices(foreground && s.screen==Screen.Devices && s.account!=null && !s.fixture)
        // The live connection stays while the page reads (older messages, a search): it used to drop on every progress
        // bar and come back with a fresh read of the computer. A new conversation's page has no state yet: drafts only.
        composer.bind(key,api,foreground && !newPage,s.fixture) { frame ->
            mutable.update { current ->
                if(current.screen==Screen.Reading && current.app==key?.app && current.scope==key.scope && current.device?.id==key.device && current.chat?.id==key.chat)
                    current.copy(messages=mergeLive(current.messages,frame.messages)) else current
            }
        }
    }
    private var work: Job? = null
    private var generation = 0
    private var pendingRestore: Preferences? = null
    private val fixturePositions=mutableMapOf<ChatKey,ReadingPosition>()
    private suspend fun persistSelection(scope:String,device:String,chat:String,title:String) {
        if(!state.value.fixture) store.selection(scope,device,chat,title)
    }
    init { launch() }
    /** Starts as the app opens: the saved service, or the default one, with the mark shown meanwhile (web booting). */
    private fun launch() = operation { g -> begin(g) }
    /** From nothing held (leaving the local demo, another service): only what this phone saved carries over. */
    private suspend fun begin(g: Int) {
        val p = store.preferences(); pendingRestore = p
        val origin = p.origin.ifBlank { defaultOrigin }
        commit(g) { ReaderState(app=p.app, origin=origin, scope=p.scope, theme=p.theme, dynamic=p.dynamic, screen=if(origin.isBlank()) Screen.Service else Screen.Launch, busy=true) }
        if (origin.isNotBlank()) { api?.close(); api = apiFactory(origin).forSource(p.app); restore(g) }
    }
    private fun commit(g: Int, update: (ReaderState) -> ReaderState) { if (g == generation) mutable.update(update) }
    private fun operation(block: suspend (Int) -> Unit) {
        work?.cancel(); val g = ++generation
        mutable.update { it.copy(busy=true,error=null) }
        work = viewModelScope.launch {
            try { block(g) }
            catch (e: CancellationException) { throw e }
            catch (e: Exception) { commit(g) { s -> s.copy(error=when(e) { is ServiceFailure -> e.message; is IllegalArgumentException -> e.message; else -> "连接失败，请检查网络和服务地址后重试。" }, screen=if (e is ServiceFailure && e.status==401) Screen.Login else s.screen, expired=s.expired || (e is ServiceFailure && e.status==401)) } }
            finally { commit(g) { it.copy(busy=false) } }
        }
    }
    /**
     * Where the app stands at launch (web account page): not signed in → 登录; signed in → the computer used last when
     * it is online, the only computer when there is one, otherwise 我的电脑. A server out of reach leaves 登录 with why.
     */
    private suspend fun restore(g: Int) {
        val service = requireNotNull(api)
        val config = try { service.accountConfig() } catch (e: CancellationException) { throw e } catch (_: Exception) {
            commit(g) { it.copy(screen=Screen.Login,error="连不上服务器，请检查网络后重试。") }; return
        }
        commit(g) { it.copy(serverVersion=config.string("version"),emailEnabled=config.optBoolean("email_enabled"),screen=Screen.Login,
            device=pendingRestore?.device?.takeIf { d -> d.isNotBlank() }?.let { d -> Computer(d,"待核对电脑",false) },
            chat=pendingRestore?.chat?.takeIf { c -> c.isNotBlank() }?.let { c -> Chat(c,pendingRestore?.title.orEmpty()) }) }
        val account = try { service.account() } catch (e: ServiceFailure) {
            // Not signed in: 登录. Signed in before on this phone: the sign-in ran out, and the place is kept for after it.
            if (e.status == 401) { commit(g) { it.copy(screen=Screen.Login,expired=it.device!=null) }; return }
            throw e
        }
        currentCoroutineContext().ensureActive()
        val p = pendingRestore
        val device = account.devices.find { it.id == p?.device } ?: account.devices.singleOrNull()?.takeIf { p?.device.isNullOrBlank() }
        val scope = p?.scope?.ifBlank { null } ?: UUID.randomUUID().toString()
        commit(g) { it.copy(account=account,scope=scope,device=null,chat=null,screen=Screen.Devices,expired=false) }
        if (device != null && device.connectable) {
            service.select(device.id)
            val known = cachedSources(scope, device.id)
            commit(g) { it.copy(device=device,screen=Screen.Chats,sources=SourceInfo(device.id,known,loading=true,cached=known!=null)) }
            loadTree(true)
            if (device.id == p?.device && !p.chat.isNullOrBlank()) readChat(g, Chat(p.chat,p.title.ifBlank { "对话" }), restorePosition=true) else loadChats(g)
            if (device.id != p?.device) persistSelection(scope,device.id,"","")
        }
        pendingRestore = null
    }
    /**
     * 连接这个服务 (开发者选项 → 服务地址): only a service that answers replaces the one in use, and the app then starts on
     * it as at launch (signed in there: straight to the computers). One out of reach keeps this page with why.
     */
    fun connect(value: String) = operation { g ->
        pendingNotification=null
        val origin = serviceOrigin(value).toString()
        val next = apiFactory(origin)
        try { next.accountConfig() }
        catch (e: CancellationException) { throw e }
        catch (_: Exception) { throw IllegalArgumentException("连不上这个服务，请检查地址和网络后重试。") }
        finally { next.close() }
        currentCoroutineContext().ensureActive()
        // Another service starts with no place: the saved computer and conversation belong to the old one. The local
        // demo saves nothing, so leaving it for the saved service keeps the place there.
        val saved = store.preferences().origin.ifBlank { defaultOrigin }
        if (runCatching { serviceOrigin(saved).toString() }.getOrNull() != origin) store.setOrigin(origin)
        begin(g)
    }
    /** 退出登录 (web account menu): the service forgets the sign-in, this phone its cookie and where it was. */
    fun logout() = operation { g ->
        pendingNotification=null
        val s=state.value
        try { api?.logout() } catch (e: CancellationException) { throw e } catch (_: Exception) { /* the cookie is gone here either way */ }
        persistSelection(s.scope,"","","")
        commit(g) { ReaderState(app=s.app,origin=s.origin,screen=Screen.Login,theme=s.theme,dynamic=s.dynamic,serverVersion=s.serverVersion,emailEnabled=s.emailEnabled,fixture=s.fixture) }
    }
    /** 重命名 a computer (web device menu); the list is read again. */
    fun renameDevice(device: Computer, label: String) = operation { g ->
        require(label.isNotBlank()) { "请输入电脑名称。" }
        val service = requireNotNull(api)
        service.renameDevice(device.id, label.trim())
        val account = service.account()
        commit(g) { it.copy(account=account,device=it.device?.let { d -> account.devices.find { a -> a.id==d.id } ?: d }) }
    }
    /** 移除: the computer loses remote access (its files stay); the list is read again. */
    fun removeDevice(device: Computer) = operation { g ->
        val service = requireNotNull(api)
        service.revokeDevice(device.id)
        val account = service.account()
        commit(g) { it.copy(account=account,device=if(it.device?.id==device.id) null else it.device,chats=if(it.device?.id==device.id) emptyList() else it.chats) }
    }
    // --- 我的电脑 is read again every 15 s while it is shown (web account page), quietly.
    private var devicePoll: Job? = null
    private fun pollDevices(on: Boolean) {
        if (!on) { devicePoll?.cancel(); devicePoll = null; return }
        if (devicePoll?.isActive == true) return
        devicePoll = viewModelScope.launch {
            while (isActive) {
                delay(15_000)
                val s = state.value
                if (s.busy || s.screen != Screen.Devices || s.account == null) continue
                val account = try { api?.account() } catch (e: CancellationException) { throw e } catch (_: Exception) { null } ?: continue
                mutable.update { if (it.screen == Screen.Devices && it.origin == s.origin) it.copy(account=account) else it }
            }
        }
    }
    /** The sign-in or connection check again, as at launch (登录's 重试). */
    fun relaunch() = launch()
    fun login(name: String, password: String) = operation { g ->
        require(name.isNotBlank() && password.isNotBlank()) { "请输入账号与密码。" }
        val service = requireNotNull(api)
        service.login(name.trim(),password)
        val account = service.account()
        currentCoroutineContext().ensureActive()
        val previous = state.value
        // A device ID is owned by exactly one account. Never trust an email/display name as an immutable identity.
        val sameOwner = previous.expired && previous.device != null && account.devices.any { it.id == previous.device.id }
        val scope = if(sameOwner) previous.scope else UUID.randomUUID().toString()
        if (sameOwner) {
            val verified = account.devices.first { it.id == previous.device!!.id }
            commit(g) { it.copy(account=account,device=verified,expired=false,screen=if(it.chat != null) Screen.Reading else Screen.Chats) }
            if(previous.messages.isEmpty() && verified.connectable) {
                service.select(verified.id)
                if(state.value.sources.device!=verified.id) { val known=cachedSources(scope,verified.id);commit(g) { it.copy(sources=SourceInfo(verified.id,known,loading=true,cached=known!=null)) } }
                if(state.value.knownApps()==null || state.value.sources.failed!=null) loadTree(true)
                if(previous.chat!=null) readChat(g,previous.chat,true) else loadChats(g)
            }
        } else {
            commit(g) { ReaderState(app=previous.app,origin=previous.origin,scope=scope,account=account,screen=Screen.Devices,theme=previous.theme,dynamic=previous.dynamic,serverVersion=previous.serverVersion,busy=true,fixture=previous.fixture) }
        }
        persistSelection(scope,if(sameOwner) previous.device!!.id else "",if(sameOwner) previous.chat?.id.orEmpty() else "",if(sameOwner) previous.chat?.title.orEmpty() else "")
        val destination=pendingNotification
        if(destination!=null && destination.key.scope==scope && account.devices.any { it.id==destination.key.device }) viewModelScope.launch { yield();openNotification(destination) } else pendingNotification=null
    }
    fun computers() = operation { g ->
        commit(g) { it.copy(screen=Screen.Devices) }
        val account = requireNotNull(api).account()
        commit(g) { s ->
            if(s.device!=null && account.devices.none { it.id==s.device.id }) s.copy(account=account,device=null,chat=null,messages=emptyList(),chats=emptyList(),anchor=null)
            else s.copy(account=account)
        }
    }
    fun select(device: Computer) = operation { g ->
        pendingNotification=null
        require(device.connectable) { "电脑已离线，请稍后刷新。" }
        val s=state.value
        // Another computer starts from its own apps (this phone's copy, else unknown), never the last one's (0.9.1). A
        // list filter on an app it is not known to have falls back to 全部 rather than an empty list.
        val same=s.sources.device==device.id
        val known=if(same) s.sources.apps else cachedSources(s.scope,device.id)
        val filter=if(s.listSource=="all" || known?.contains(s.listSource)==true) s.listSource else "all"
        // Drop old displayed content before selecting, even if the new selection fails.
        commit(g) { it.copy(device=null,chat=null,messages=emptyList(),chats=emptyList(),hits=emptyList(),anchor=null,query="",cursor=null,listCursor=null,older=false,listMore=false,tree="{}",treeError=null,runtime="{}",
            listSource=filter,sources=SourceInfo(device.id,known,loading=true,cached=known!=null && !same)) }
        treeJob?.cancel();treeMore.clear();treeAt=0L
        requireNotNull(api).select(device.id)
        currentCoroutineContext().ensureActive()
        commit(g) { it.copy(device=device,screen=Screen.Chats) }
        loadTree(true)
        persistSelection(state.value.scope,device.id,"","")
        loadChats(g)
    }
    private suspend fun loadChats(g: Int, more: Boolean = false) {
        val s = state.value; val device = s.device ?: return
        val page = requireNotNull(api).chatList(device.id,s.listSource,s.query,if(more) s.listCursor else null,s.listSort,s.listStatus)
        // Rows of another filter (it changed while they came, e.g. the computer turned out not to have that app) stay out.
        commit(g) { if(it.device?.id!=device.id || it.listSource!=s.listSource) it else it.copy(chats=(if(more) (it.chats+page.items).distinctBy { c -> chatKey(c) } else page.items).filter { c -> chatKey(c) !in it.hidden },listCursor=page.cursor,listMore=page.hasMore,moreKids=if(more) it.moreKids else emptyMap()) }
    }
    // --- What the computer has (0.9.1): this phone's copy first, then the computer's answer (the sidebar tree, loadTree).
    private fun sourcesKey(scope:String,device:String)=ChatKey(scope,device,"@sources","codex")
    /** The apps [device] had when this phone last asked, under this sign-in; null when never asked (or the local demo). */
    private suspend fun cachedSources(scope:String,device:String):List<String>? {
        if(state.value.fixture || scope.isBlank()) return null
        val saved=try { store.detail(sourcesKey(scope,device),"sources") } catch(e:CancellationException) { throw e } catch(_:Exception) { null } ?: return null
        return saved.split(',').filter { it in SourceOrder }
    }
    /** Asks the computer again (the chips' and the sheet's 重试). */
    fun retrySources() { mutable.update { if(it.device!=null && it.sources.device==it.device.id) it.copy(sources=it.sources.copy(loading=true,failed=null)) else it };loadTree(true) }
    /**
     * The computer answered with its apps: a list filter on one it does not have goes back to 全部 (the list is read
     * again when it shows), instead of an empty list under a chip that is no longer there.
     */
    private fun fitSources(apps:List<String>) {
        var reread=false
        mutable.update { s ->
            if(s.listSource=="all" || s.listSource in apps) s
            else { reread=s.screen==Screen.Chats;s.copy(listSource="all",chats=emptyList(),listCursor=null,listMore=false) }
        }
        if(reread) operation { g -> loadChats(g) }
    }
    fun searchChats(query: String) = operation { g ->
        commit(g) { it.copy(query=query,chats=emptyList(),listCursor=null,listMore=false) }; loadChats(g)
    }
    fun moreChats() = operation { g -> loadChats(g,true) }
    fun open(chat: Chat) = operation { g ->
        pendingNotification=null
        // Opened from the list: a job that made it is done with (web route).
        jobs.jobs.value.find { it.accepted && it.createdId==chat.id && (it.pendingJson().string("app").ifBlank { it.app })==chat.app }?.let(jobs::drop)
        useSource(chat.app);readChat(g,chat,true)
    }
    /** The "all" list and the sidebar mix sources: opening a row of another source switches source, not the list. */
    private suspend fun useSource(app:String) {
        if(!pointSource(app)) return
        if(!state.value.fixture) store.source(app)
    }
    /**
     * Points the service at [app]; true when it changed. The old instance is not closed (0.9.1): instances of one
     * service share their connections, so closing it cancelled every request under way, the sidebar's and the
     * new-conversation sheet's included. Their own owners cancel what they no longer need.
     */
    private fun pointSource(app:String):Boolean {
        if(app.isBlank() || app==state.value.app) return false
        require(app in SourceOrder) { "来源应用无效" }
        api=api?.forSource(app)
        mutable.update { it.copy(app=app,chat=null,messages=emptyList(),anchor=null,runtime="{}") }
        return true
    }
    fun listDisplay(source:String=state.value.listSource,sort:String=state.value.listSort,status:String=state.value.listStatus,group:String=state.value.listGroup) = operation { g ->
        require(source=="all" || source in setOf("codex","claude","deepseek"))
        val reload=source!=state.value.listSource || sort!=state.value.listSort || status!=state.value.listStatus
        commit(g) { it.copy(listSource=source,listSort=sort,listStatus=status,listGroup=group,chats=if(reload) emptyList() else it.chats,listCursor=if(reload) null else it.listCursor,listMore=if(reload) false else it.listMore) }
        if(reload) loadChats(g)
    }
    /** 清除筛选: back to every source, newest first, every state, and no search words. */
    fun clearListFilters() = operation { g ->
        commit(g) { it.copy(listSource="all",listSort="updated",listStatus="all",query="",chats=emptyList(),listCursor=null,listMore=false) }
        loadChats(g)
    }
    /**
     * Opens the new-conversation sheet for [app], with the project filled in when it came from a project's ＋. A computer
     * without [app] starts in an app it has (0.9.1). Nothing here waits or shows a progress line: the sheet opens at
     * once (0.9.1: this used to run as a page operation, which cancelled a list read under way and redrew the page twice).
     */
    fun startNew(app:String=state.value.app,folder:String="",projectless:Boolean=false,text:String="",switching:Boolean=false,restore:NewJob?=null) {
        pendingNotification=null
        val target=state.value.newApp(app)
        val fromReading=state.value.screen==Screen.Reading
        // From a conversation: a read of it still under way must not bring its page back over the list.
        if(fromReading) { work?.cancel();generation++ }
        val switched=pointSource(target)
        val keepFolder=target==app
        // The list's ✎ with the sheet's draft already bound: open it in this frame, not after a round through pendingNew.
        val ws=workspace.state.value
        if(!fromReading && !switched && folder.isBlank() && !projectless && text.isBlank() && restore==null && ws.ready && ws.key?.chat=="@new" && ws.key.app==target) {
            workspace.panel("new");return
        }
        mutable.update { it.copy(screen=if(fromReading) Screen.Chats else it.screen,chat=if(fromReading) null else it.chat,busy=if(fromReading) false else it.busy,
            pendingNew=NewTarget(target,if(keepFolder) folder else "",keepFolder && projectless,text,switching,restore)) }
        val s=state.value
        viewModelScope.launch {
            if(switched && !s.fixture) store.source(target)
            if(fromReading) persistSelection(s.scope,s.device?.id.orEmpty(),"","")
        }
        if(fromReading && s.chats.isEmpty()) operation { g -> loadChats(g) }
    }
    fun consumeNew() { mutable.update { it.copy(pendingNew=null) } }

    // --- New conversations under way (0.8, web new-chat-ui.js jobs): the sheet closes at once, the first message shows
    // on the conversation's page with a line under it, and the page becomes the conversation when the computer made it.
    private fun jobCreated(job:NewJob) {
        workspace.close()
        jobs.submit(job)
        openPreview(job)
    }
    /** A row above the list, or a job's page: the conversation when ready, the sheet for a problem, else its page. */
    fun openJob(job:NewJob) {
        when {
            job.accepted -> finishJob(job)
            job.problem -> mutable.update { it.copy(jobSheet=job.request) }
            else -> openPreview(job)
        }
    }
    private fun openPreview(job:NewJob) = operation { g ->
        pendingNotification=null
        useSource(job.app)
        commit(g) { it.copy(screen=Screen.Reading,chat=Chat(job.preview,job.text.replace(Regex("\\s+")," ").trim().take(50).ifBlank { "新对话" },job.label,"","creating",job.app),
            messages=emptyList(),cursor=null,older=false,newer=false,anchor=null,hits=emptyList(),searched=false,runtime="{}",handoff=null) }
    }
    /** The computer made it: its page becomes the conversation, words written there go along (web finish). */
    fun finishJob(job:NewJob) = operation { g ->
        val r=job.pendingJson();val id=r.string("id");if(id.isBlank()) return@operation
        val app=r.string("app").ifBlank { job.app }
        val s=state.value;val device=s.device ?: return@operation
        composer.moveDraft(ChatKey(s.scope,device.id,job.preview,job.app),ChatKey(s.scope,device.id,id,app))
        jobs.drop(job)
        useSource(app)
        commit(g) { it.copy(jobSheet=null,handoff=NewHandoff(app,id,job.text)) }
        readChat(g,Chat(id,r.string("title").ifBlank { job.text.replace(Regex("\\s+")," ").trim().take(50).ifBlank { "新对话" } },r.string("folder").ifBlank { job.label },"","running",app),false)
    }
    fun closeJobSheet() { mutable.update { it.copy(jobSheet=null) } }
    fun checkJob(job:NewJob) { jobs.current(job.request)?.let { jobs.check(it.copy(note="")) } }
    fun retryJob(job:NewJob) { jobs.current(job.request)?.let(jobs::retry) }
    /** 打开对话: the conversation the computer reported, even before it was confirmed (web newOpen). */
    fun openJobChat(job:NewJob) {
        val r=job.pendingJson();if(r.string("id").isBlank()) return
        if(job.accepted) { finishJob(job);return }
        mutable.update { it.copy(jobSheet=null) }
        open(Chat(r.string("id"),r.string("title").ifBlank { job.text.take(50).ifBlank { "新对话" } },r.string("folder").ifBlank { job.label },"","idle",job.app))
    }
    /** 移除: the phone stops following it; a conversation the computer made still shows in the list. */
    fun removeJob(job:NewJob) {
        jobs.drop(job)
        mutable.update { it.copy(jobSheet=null) }
        if(state.value.chat?.id==job.preview) back()
    }
    /** 恢复草稿: a first message that did not go back into the sheet, to change and send again (web restore). */
    fun restoreJob(job:NewJob) {
        if(job.state!="failed") return
        jobs.drop(job)
        mutable.update { it.copy(jobSheet=null) }
        if(state.value.chat?.id==job.preview) back()
        startNew(job.app,restore=job)
    }

    // --- The list is read again every 10 s while it is in front (web loadConvs): rows merge, nothing is reset.
    private var listPoll:Job?=null
    private fun pollList(on:Boolean) {
        if(!on) { listPoll?.cancel();listPoll=null;return }
        if(listPoll?.isActive==true) return
        listPoll=viewModelScope.launch { while(isActive) { delay(10_000);refreshList() } }
    }
    private suspend fun refreshList() {
        val s=state.value
        if(s.busy || s.screen!=Screen.Chats || s.expired) return
        try { mergeFirstPage() } catch(e:CancellationException) { throw e } catch(_:Exception) { }
    }
    /** The list's first page again, merged into what shows (web loadList): its rows first, the others kept below. */
    private suspend fun mergeFirstPage(g:Int?=null) {
        val s=state.value;val device=s.device ?: return;val service=api ?: return
        val page=service.chatList(device.id,s.listSource,s.query,null,s.listSort,s.listStatus)
        val merge:(ReaderState)->ReaderState={ now ->
            if(now.device?.id!=device.id || listOf(now.listSource,now.query,now.listSort,now.listStatus)!=listOf(s.listSource,s.query,s.listSort,s.listStatus)) now
            else {
                // Pages read past the first stay as they were, with where the next one starts.
                val fresh=page.items.map(::chatKey).toSet()
                val beyond=now.chats.any { chatKey(it) !in fresh }
                now.copy(chats=(page.items+now.chats.filter { chatKey(it) !in fresh }).filter { chatKey(it) !in now.hidden },listCursor=if(beyond) now.listCursor else page.cursor,listMore=if(beyond) now.listMore else page.hasMore)
            }
        }
        if(g!=null) commit(g,merge) else mutable.update(merge)
    }

    // --- 左滑归档 and 撤销 (web archive-ui.js): the archive is made on the computer; the row leaves the list at once.
    private val archiving = mutableMapOf<String,Deferred<Boolean>>()
    private var undoSerial = 0L
    fun archive(chat:Chat) {
        val s=state.value;val device=s.device ?: return;val service=api ?: return
        if(chat.group || chat.kind.isNotBlank() || chat.app !in setOf("codex","claude","deepseek")) return
        if(chat.status=="running") { notice("这个对话正在运行，先停止这一轮再归档");return }
        val key=chatKey(chat);val index=s.chats.indexOfFirst { chatKey(it)==key }.coerceAtLeast(0);val serial=++undoSerial
        mutable.update { it.copy(hidden=it.hidden+key,chats=it.chats.filter { c -> chatKey(c)!=key },undo=ArchiveUndo(chat,index,chat.app=="claude",serial)) }
        val job=viewModelScope.async {
            try {
                service.detail(device.id,"chat/archive",body=org.json.JSONObject().put("app",chat.app).put("id",chat.id))
                mutable.update { if(it.undo?.serial==serial) it.copy(undo=it.undo.copy(waiting=false)) else it }
                loadTree(true);true
            } catch(e:CancellationException) { throw e }
            catch(e:Exception) {
                comeBack(chat,index)
                mutable.update { it.copy(undo=if(it.undo?.serial==serial) null else it.undo,notice=(if(chat.app=="claude") "Claude：" else "没归档：")+(e.message ?: "电脑没有回应")) };false
            } finally { archiving.remove(key) }
        }
        archiving[key]=job
    }
    private fun comeBack(chat:Chat,index:Int) {
        val key=chatKey(chat)
        mutable.update { s -> s.copy(hidden=s.hidden-key,chats=if(s.chats.any { chatKey(it)==key }) s.chats else s.chats.toMutableList().apply { add(index.coerceIn(0,size),chat) }) }
    }
    /** 撤销: back on the list at once, then restored on the computer once its archive is done. */
    fun undoArchive() {
        val u=state.value.undo ?: return;val device=state.value.device ?: return;val service=api ?: return
        if(u.waiting) return
        mutable.update { it.copy(undo=null) }
        comeBack(u.chat,u.index)
        val key=chatKey(u.chat)
        viewModelScope.launch {
            if(archiving[key]?.await()==false) return@launch
            try { service.detail(device.id,"chat/unarchive",body=org.json.JSONObject().put("app",u.chat.app).put("id",u.chat.id));loadTree(true);notice("已恢复") }
            catch(e:CancellationException) { throw e }
            catch(e:Exception) { mutable.update { it.copy(hidden=it.hidden+key,chats=it.chats.filter { c -> chatKey(c)!=key },notice=(if(u.chat.app=="claude") "Claude：" else "没恢复：")+(e.message ?: "电脑没有回应")) } }
        }
    }
    fun dropUndo(serial:Long) { mutable.update { if(it.undo?.serial==serial && !it.undo.waiting) it.copy(undo=null) else it } }
    fun notice(text:String?) { mutable.update { it.copy(notice=text) } }
    /** A conversation restored from 已归档对话: back on the list. */
    fun restored(app:String,id:String) {
        mutable.update { it.copy(hidden=it.hidden-"$app:$id") }
        loadTree(true)
        if(state.value.screen==Screen.Chats) searchChats(state.value.query)
    }
    /** 再显示 N 个: the next children of a row, past the ones it carries. */
    fun moreChildren(chat:Chat) {
        val s=state.value;val device=s.device ?: return;val service=api ?: return
        val key=chatKey(chat);val have=chat.children.size+(s.moreKids[key]?.size ?: 0)
        viewModelScope.launch {
            try {
                val items=service.detail(device.id,"chats/children",mapOf("app" to chat.app,"id" to chat.id,"offset" to "$have","limit" to "50")).rows("items",::parseChat)
                mutable.update { it.copy(moreKids=it.moreKids+(key to ((it.moreKids[key] ?: emptyList())+items).distinctBy { c -> c.id })) }
            } catch(e:CancellationException) { throw e }
            catch(e:Exception) { notice(e.message ?: "读不到更多子对话") }
        }
    }
    /** A subagent's own record is not readable here: its row opens the conversation that shows its card (web openChild). */
    fun openChild(child:Chat,parent:Chat?) {
        if(child.kind!="subagent") open(child) else open(parent ?: Chat(child.parent,child.parentTitle.ifBlank { "对话" },app=child.app))
    }

    /** A request to the selected computer from a settings page or a menu: notifications, voice, archived conversations. */
    suspend fun deviceCall(route:String,query:Map<String,String?> = emptyMap(),body:org.json.JSONObject?=null):org.json.JSONObject {
        val device=state.value.device ?: throw IllegalStateException("先选择一台电脑");val service=api ?: throw IllegalStateException("服务未连接")
        return service.detail(device.id,route,query,body)
    }
    suspend fun voiceCall(route:String,query:Map<String,String?> = emptyMap(),bytes:ByteArray?=null,type:String="application/octet-stream"):org.json.JSONObject {
        val device=state.value.device ?: throw IllegalStateException("先选择一台电脑");val service=api ?: throw IllegalStateException("服务未连接")
        return service.voice(device.id,route,query,bytes,type)
    }
    private val voiceOn=mutableMapOf<String,Boolean>()
    /** Whether this computer has its voice service on (web window.MACHINE.voice); asked once per computer. */
    suspend fun voiceAvailable():Boolean {
        val id=state.value.device?.id ?: return false
        voiceOn[id]?.let { return it }
        val on=try { deviceCall("voice/status");true } catch(e:ServiceFailure) { if(e.status==404) false else return true }
        voiceOn[id]=on
        return on
    }
    private var treeJob: Job? = null
    private val treeMore = mutableMapOf<Pair<String,String>,Int>()
    private var treeAt = 0L
    /**
     * Sidebar tree, read when the drawer opens and at most every 15 s (spec 4.2), and on entering a computer (0.9.1):
     * its groups are the apps that computer has ([SourceInfo]). Runs beside the page's own work; a read already under
     * way is not started again unless [force]d.
     */
    fun loadTree(force:Boolean=false) {
        val s=state.value;val device=s.device ?: return;val service=api ?: return
        if(!force && (treeJob?.isActive==true || System.currentTimeMillis()-treeAt<15_000 && s.tree!="{}")) return
        treeJob?.cancel()
        val owner=Triple(s.origin,s.scope,device.id)
        val synthetic=s.fixture
        treeJob=viewModelScope.launch {
            try {
                val more=org.json.JSONArray(treeMore.map { (k,n) -> org.json.JSONArray().put(k.first).put(k.second).put(n) }).toString()
                val tree=service.detail(device.id,"chat/projects",mapOf("more" to more))
                val apps=treeApps(tree)
                treeAt=System.currentTimeMillis()
                var mine=false
                mutable.update { if(Triple(it.origin,it.scope,it.device?.id)==owner) { mine=true;it.copy(tree=tree.toString(),treeError=null,sources=SourceInfo(device.id,apps)) } else it }
                if(mine) {
                    fitSources(apps)
                    if(!synthetic) try { store.detail(sourcesKey(owner.second,device.id),"sources",apps.joinToString(",")) } catch(e:CancellationException) { throw e } catch(_:Exception) { }
                }
            } catch(e:CancellationException) { throw e }
            catch(e:Exception) {
                val why=if(e is ServiceFailure) e.message else "暂时读不到电脑上的分组，可稍后再打开侧栏。"
                mutable.update { if(Triple(it.origin,it.scope,it.device?.id)==owner) it.copy(treeError=why,sources=if(it.sources.device==device.id) it.sources.copy(loading=false,failed=why) else it.sources) else it }
            }
        }
    }
    /** "显示更多": 30 more rows of one project (spec 4.2). */
    fun moreTree(app:String,key:String) { treeMore[app to key]=(treeMore[app to key] ?: 10)+30;loadTree(true) }
    private suspend fun readChat(g: Int, chat: Chat, restorePosition: Boolean) {
        val s = state.value; val device = requireNotNull(s.device)
        commit(g) { it.copy(screen=Screen.Reading,chat=chat,messages=if(it.chat?.id==chat.id) it.messages else emptyList(),cursor=if(it.chat?.id==chat.id) it.cursor else null,older=it.chat?.id==chat.id && it.older,newer=it.chat?.id==chat.id && it.newer,anchor=if(it.chat?.id==chat.id) it.anchor else null,hits=emptyList(),searched=false,searchQuery="",handoff=it.handoff?.takeIf { h -> h.id==chat.id && h.app==chat.app }) }
        val pos = if(!restorePosition) null else if(s.fixture) fixturePositions[ChatKey(s.scope,device.id,chat.id,s.app)] else store.positionFor(ChatKey(s.scope,device.id,chat.id,s.app))
        val page = requireNotNull(api).history(device.id,chat.id,around=pos?.message)
        currentCoroutineContext().ensureActive()
        commit(g) { it.copy(messages=page.items,cursor=page.cursor,older=page.hasMore,newer=page.hasNewer,anchor=pos,scrollRevision=it.scrollRevision+1,runtime=page.meta,chat=it.chat?.let { c -> pageTitle(page.meta)?.let { t -> c.copy(title=t) } ?: c }) }
        persistSelection(s.scope,device.id,chat.id,state.value.chat?.title ?: chat.title)
    }
    fun older() = operation { g ->
        val s = state.value; val cursor = s.cursor ?: return@operation
        val page = requireNotNull(api).history(requireNotNull(s.device).id,requireNotNull(s.chat).id,before=cursor)
        if(page.reset) { commit(g) { it.copy(error="历史位置已变化，请回到最新消息后重试。") }; return@operation }
        commit(g) { it.copy(messages=mergeMessages(it.messages,page.items,true),cursor=page.cursor,older=page.hasMore) }
    }
    fun latest() = operation { g -> state.value.chat?.let { readChat(g,it,false) } }
    fun expand(message: Message) = operation { g ->
        val s=state.value
        val full=requireNotNull(api).message(requireNotNull(s.device).id,requireNotNull(s.chat).id,message.id)
        commit(g) { it.copy(messages=mergeMessages(it.messages,listOf(full),false)) }
    }
    fun searchHistory(query: String, more: Boolean = false) = operation { g ->
        val s=state.value; require(query.isNotBlank()) { "请输入要查找的内容。" }
        if(!more) commit(g) { it.copy(hits=emptyList(),hitCursor=null,hitMore=false,searched=false,searchQuery=query) }
        val page=requireNotNull(api).search(requireNotNull(s.device).id,requireNotNull(s.chat).id,query,if(more) s.hitCursor else null)
        commit(g) { it.copy(searchQuery=query,hits=if(more) (it.hits+page.items).distinctBy { m -> m.id } else page.items,hitCursor=page.cursor,hitMore=page.hasMore,searched=true) }
    }
    fun jump(message: Message) = operation { g ->
        val s=state.value
        val page=requireNotNull(api).history(requireNotNull(s.device).id,requireNotNull(s.chat).id,around=message.id)
        commit(g) { it.copy(messages=page.items,cursor=page.cursor,older=page.hasMore,newer=page.hasNewer,anchor=ReadingPosition(s.scope,s.device.id,app=s.app,chat=s.chat.id,message=message.id,offset=0),scrollRevision=it.scrollRevision+1,hits=emptyList(),searched=false,runtime=page.meta) }
    }
    fun saveAnchor(message: String, offset: Int, expectedScope: String = state.value.scope, expectedDevice: String? = state.value.device?.id, expectedChat: String? = state.value.chat?.id,expectedApp:String=state.value.app) {
        val s=state.value
        if(expectedScope.isBlank() || expectedDevice==null || expectedChat==null) return
        val position=ReadingPosition(expectedScope,expectedDevice,app=expectedApp,chat=expectedChat,message=message,offset=offset)
        if(s.app==expectedApp && s.scope==expectedScope && s.device?.id==expectedDevice && s.chat?.id==expectedChat && s.messages.any { it.id==message }) mutable.update { it.copy(anchor=position) }
        if(s.fixture) fixturePositions[ChatKey(expectedScope,expectedDevice,expectedChat,expectedApp)]=position else viewModelScope.launch { store.save(position) }
    }

    fun settings() { work?.cancel(); generation++; mutable.update { it.copy(settingsReturn=if(it.screen in listOf(Screen.Settings,Screen.Developer,Screen.Service)) it.settingsReturn else it.screen,screen=Screen.Settings,busy=false,error=null) } }
    fun developer() { work?.cancel(); generation++; mutable.update { it.copy(screen=Screen.Developer,busy=false,error=null) } }
    fun appearance(theme: String, dynamic: Boolean) { mutable.update { it.copy(theme=theme,dynamic=dynamic) }; viewModelScope.launch { store.appearance(theme,dynamic) } }
    /** 更改服务地址, from 设置 or 登录's ⋯; back returns where it was opened from. */
    fun serviceSettings() { work?.cancel(); generation++; mutable.update { it.copy(serviceReturn=if(it.screen==Screen.Service) it.serviceReturn else it.screen,screen=Screen.Service,busy=false,error=null) } }
    fun back() {
        pendingNotification=null
        val s=state.value
        if(s.screen==Screen.Settings) { mutable.update { it.copy(screen=it.settingsReturn) }; return }
        if(s.screen==Screen.Developer) { mutable.update { it.copy(screen=Screen.Settings) }; return }
        if(s.screen==Screen.Service) { mutable.update { it.copy(screen=if(it.serviceReturn in listOf(Screen.Service,Screen.Launch)) Screen.Login else it.serviceReturn) }; return }
        // Leaving the local demo goes back to the real sign-in, as the app opens.
        if(s.screen==Screen.Login && s.fixture) { relaunch(); return }
        if(s.screen==Screen.Reading) {
            // Back in the list it is read again (web closeConv → loadConvs): a conversation made meanwhile shows.
            operation { g ->
                commit(g) { it.copy(screen=Screen.Chats,chat=null,hits=emptyList(),searched=false) }; persistSelection(s.scope,s.device?.id.orEmpty(),"","")
                if(state.value.chats.isEmpty()) loadChats(g) else try { mergeFirstPage(g) } catch(e:CancellationException) { throw e } catch(_:Exception) { }
            }
        } else if(s.screen==Screen.Chats) computers()
        else if(s.screen==Screen.Devices && s.device!=null) { work?.cancel(); generation++; mutable.update { it.copy(screen=Screen.Chats,busy=false,error=null) } }
    }
    fun retry() { when(state.value.screen) { Screen.Devices -> computers(); Screen.Chats -> searchChats(state.value.query); Screen.Reading -> state.value.chat?.let(::open); Screen.Login -> if(state.value.account==null && !state.value.fixture) relaunch(); else -> Unit } }
    fun fixture() {
        api?.close(); work?.cancel(); generation++
        api=FixtureApi()
        mutable.value=ReaderState(screen=Screen.Login,origin="fixture://local",scope="fixture",theme=state.value.theme,dynamic=state.value.dynamic,fixture=true)
    }
    override fun onCleared() { api?.close() }
}
/** The server's own title for an opened conversation, when it gives one (notifications open with a placeholder). */
private fun pageTitle(meta:String)=runCatching { org.json.JSONObject(meta).string("title").ifBlank { null } }.getOrNull()
