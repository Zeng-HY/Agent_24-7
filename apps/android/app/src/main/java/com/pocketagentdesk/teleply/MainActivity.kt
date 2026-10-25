package com.pocketagentdesk.teleply

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.BackHandler
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.foundation.background
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveableStateHolder
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.layout.onSizeChanged
import androidx.compose.ui.platform.*
import androidx.compose.ui.semantics.clearAndSetSemantics
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.min
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.room.Room
import kotlinx.coroutines.launch

fun useTwoPane(width:Float,height:Float,fontScale:Float)=width>=840f*fontScale.coerceIn(1f,1.6f) && height>=480f

class NativeApplication : android.app.Application() {
    override fun onCreate() { super.onCreate(); Diagnostics.load(this); prewarmGlass() }
    val database by lazy { Room.databaseBuilder(this,ReadingDatabase::class.java,"reading.db").addMigrations(CHAT_MIGRATION,INTERACTION_MIGRATION).build() }
    val store by lazy { NativeReaderStore(SettingsStore(this),database.positions()) }
    val vault by lazy { SecureCookieVault(this) }
    val watch by lazy { WatchManager(this,store) { origin -> RelayApi(origin,vault) } }
    val updater by lazy { AppUpdater(this) }
}
class MainActivity : ComponentActivity() {
    private var watchToken by mutableStateOf<String?>(null)
    override fun onNewIntent(intent:android.content.Intent) { super.onNewIntent(intent);setIntent(intent);watchToken=intent.getStringExtra(WatchManager.EXTRA) }
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        val graph=application as NativeApplication
        val store=graph.store
        val vault=graph.vault
        watchToken=intent.getStringExtra(WatchManager.EXTRA)
        setContent {
            val vm:ReaderViewModel=viewModel(factory=object:ViewModelProvider.Factory {
                @Suppress("UNCHECKED_CAST") override fun <T:ViewModel> create(modelClass:Class<T>):T = ReaderViewModel(store) { origin -> RelayApi(origin,vault) } as T
            })
            val state by vm.state.collectAsStateWithLifecycle()
            LaunchedEffect(watchToken,state.busy,state.account) {
                val token=watchToken
                if(token!=null && !state.busy && state.account!=null) {
                    watchToken=null;intent.removeExtra(WatchManager.EXTRA)
                    graph.watch.resolve(token)?.let { vm.openNotification(it) }
                }
            }
            val dark=state.theme=="dark" || state.theme=="system" && isSystemInDarkTheme()
            SideEffect {
                androidx.core.view.WindowCompat.getInsetsController(window,window.decorView).apply {
                    isAppearanceLightStatusBars=!dark
                    isAppearanceLightNavigationBars=!dark
                }
            }
            TeleplyTheme(state.theme,state.dynamic) { ReaderApp(state,vm) }
        }
    }
}

/**
 * The whole app (spec 4): glass menus over everything, in-window sheets, the sidebar drawer, and one page per screen.
 * Wide windows (840dp and 480dp high) show the list and the conversation side by side (spec 6.7).
 */
@OptIn(ExperimentalLayoutApi::class)
@Composable fun ReaderApp(s:ReaderState,vm:ReaderViewModel) {
    val p=LocalTeleply.current
    val graph=LocalContext.current.applicationContext as? NativeApplication
    val keyboard=LocalSoftwareKeyboardController.current
    val imeVisible=WindowInsets.isImeVisible
    val owner=LocalLifecycleOwner.current
    val fontScale=LocalDensity.current.fontScale
    DisposableEffect(s.scope,s.origin) { onDispose { clearMarkdownCache() } }
    DisposableEffect(owner,s.screen,s.scope,s.app,s.device?.id,s.chat?.id,s.expired,s.fixture) {
        fun syncLifecycle() {
            val active=owner.lifecycle.currentState.isAtLeast(Lifecycle.State.STARTED)
            vm.live(active)
            graph?.watch?.foreground=if(active && s.screen==Screen.Reading && s.device!=null && s.chat!=null) ChatKey(s.scope,s.device.id,s.chat.id,s.app) else null
        }
        val observer=LifecycleEventObserver { _,event ->
            if(event==Lifecycle.Event.ON_STOP) Diagnostics.background()
            // An update is looked for when the app comes to the front, once a day at most (old app: daily on entering).
            if(event==Lifecycle.Event.ON_START) graph?.updater?.check(manual=false)
            syncLifecycle()
        }
        owner.lifecycle.addObserver(observer)
        syncLifecycle()
        onDispose { owner.lifecycle.removeObserver(observer);vm.live(false);graph?.watch?.foreground=null }
    }
    MenuHost(Modifier.fillMaxSize()) {
        SheetHost {
            val drawer=rememberDrawerState(DrawerValue.Closed)
            val scope=rememberCoroutineScope()
            LaunchedEffect(drawer.currentValue) { if(drawer.currentValue==DrawerValue.Open) vm.loadTree() }
            BackHandler(drawer.isOpen) { scope.launch { drawer.close() } }
            // 登录 is the first page (0.9): back leaves the app there, except from the local demo, which goes back to it.
            val canBack=s.screen in listOf(Screen.Settings,Screen.Developer,Screen.Reading,Screen.Service) || s.screen==Screen.Login && s.fixture || s.screen==Screen.Devices && s.device!=null
            BackHandler(canBack && !drawer.isOpen && !imeVisible) { vm.back() }
            BackHandler(imeVisible) { keyboard?.hide() }
            val savedPages=rememberSaveableStateHolder()
            val openMenu:()->Unit={ scope.launch { drawer.open() } }
            BoxWithConstraints(Modifier.fillMaxSize()) {
                val drawerWidth=min(320.dp,maxWidth*0.88f)
                val twoPane=useTwoPane(maxWidth.value,maxHeight.value,fontScale)
                val listWidth=if(maxWidth>=1200.dp) 412.dp else 360.dp
                ModalNavigationDrawer(
                    drawerState=drawer,
                    gesturesEnabled=drawer.isOpen || s.screen==Screen.Chats || twoPane && s.screen==Screen.Reading,
                    scrimColor=p.scrim,
                    drawerContent={
                        // A closed drawer stays composed for the swipe; TalkBack and tests must not reach its buttons.
                        val hidden=drawer.currentValue==DrawerValue.Closed && drawer.targetValue==DrawerValue.Closed
                        ModalDrawerSheet(drawerShape=TeleplyShape.Drawer,drawerContainerColor=p.panel,drawerContentColor=p.text,drawerTonalElevation=0.dp,windowInsets=WindowInsets(0),modifier=Modifier.width(drawerWidth).then(if(hidden) Modifier.clearAndSetSemantics { } else Modifier)) {
                            WorkspaceDrawer(s,vm,{ scope.launch { drawer.close() } },drawerWidth,opening=drawer.targetValue==DrawerValue.Open)
                        }
                    },
                ) {
                    Box(Modifier.fillMaxSize().background(p.page)) {
                        when(s.screen) {
                            Screen.Launch -> LaunchPage()
                            Screen.Service -> ServiceScreen(s,vm)
                            Screen.Login -> LoginPage(s,vm)
                            Screen.Devices -> DevicesPage(s,vm)
                            Screen.Chats -> savedPages.SaveableStateProvider("list/${s.scope}/${s.device?.id}") { ChatListScreen(s,vm,openMenu) }
                            Screen.Reading -> if(twoPane) {
                                Row(Modifier.fillMaxSize().testTag("two-pane")) {
                                    Box(Modifier.width(listWidth).fillMaxHeight()) { savedPages.SaveableStateProvider("list/${s.scope}/${s.device?.id}") { ChatListScreen(s,vm,openMenu) } }
                                    Spacer(Modifier.width(24.dp))
                                    Box(Modifier.weight(1f).fillMaxHeight()) { ChatScreen(s,vm,null) }
                                }
                            } else ChatScreen(s,vm,vm::back)
                            Screen.Settings -> SettingsScreen(s,vm)
                            Screen.Developer -> DeveloperScreen(s,vm)
                        }
                    }
                }
            }
            WorkspacePanes(vm)
            PendingNewSheet(s,vm)
            NewJobSheet(s,vm)
        }
        // Under the title bar: at the bottom it would cover the question bar and the input card.
        Box(Modifier.fillMaxSize().windowInsetsPadding(WindowInsets.statusBars).padding(top=76.dp),contentAlignment=Alignment.TopCenter) { DiagnosticToast() }
    }
    graph?.updater?.let { UpdateDialogs(it) }
}

/**
 * A project's ＋, the title bar's ✎ or a source switch inside the sheet: opens the new-conversation sheet once the
 * workspace has bound "@new". A switch brings the first message along; it is added to a draft already there.
 */
@Composable private fun PendingNewSheet(s:ReaderState,vm:ReaderViewModel) {
    val ws by vm.workspace.state.collectAsStateWithLifecycle()
    LaunchedEffect(s.pendingNew,ws.key,ws.ready) {
        val target=s.pendingNew ?: return@LaunchedEffect
        val key=ws.key ?: return@LaunchedEffect
        if(key.app==target.app && key.chat=="@new" && ws.ready) {
            target.restore?.let { vm.workspace.restoreNew(it) }
            if(target.folder.isNotBlank() || target.projectless) vm.workspace.chooseFolder(target.folder,target.projectless && target.app!="deepseek")
            if(target.text.isNotBlank()) {
                val draft=runCatching { org.json.JSONObject(vm.workspace.state.value.saved).string("first_message") }.getOrDefault("")
                vm.workspace.edit("first_message",if(draft.isBlank()) target.text else draft.trimEnd()+"\n"+target.text)
            }
            vm.workspace.panel("new")
            vm.consumeNew()
        }
    }
}

/**
 * A page with a glass title bar (spec 4.5): the content scrolls under the bar; the scroll edge keeps the title readable.
 */
@Composable fun PageFrame(title:String,subtitle:String?,onBack:(()->Unit)?,actions:@Composable RowScope.()->Unit={},notes:@Composable ColumnScope.()->Unit={},content:@Composable ColumnScope.()->Unit) {
    val p=LocalTeleply.current;val density=LocalDensity.current
    var bar by remember { mutableStateOf(0.dp) }
    GlassScreen(Modifier.fillMaxSize().background(p.page),topEdge=bar+12.dp,content={
        Column(
            Modifier.fillMaxSize().verticalScroll(rememberScrollState()).imePadding()
                .windowInsetsPadding(WindowInsets.safeDrawing.only(WindowInsetsSides.Horizontal+WindowInsetsSides.Bottom))
                .padding(start=16.dp,end=16.dp,top=bar+8.dp,bottom=24.dp),
            verticalArrangement=Arrangement.spacedBy(12.dp),
            content=content,
        )
    },overlay={
        Column(Modifier.fillMaxWidth().onSizeChanged { bar=with(density) { it.height.toDp() } }) {
            DetailTopBar(title,subtitle,onBack,actions=actions)
            notes()
        }
    })
}

@Composable private fun ColumnScope.ScreenNotes(s:ReaderState,vm:ReaderViewModel) {
    ProgressLine(s.busy)
    if(s.fixture && s.screen!=Screen.Service) NoteBar("本地示例 · 固定数据 · 未连接真实服务",NoteTone.Info)
    s.error?.let { NoteBar(it,NoteTone.Error,action=if(s.screen in listOf(Screen.Devices,Screen.Chats,Screen.Reading)) "重试" else null,actionEnabled=!s.busy,onAction=vm::retry) }
}

/**
 * 服务地址 (0.9, under 设置 → 开发者选项): the default service needs nothing typed. Another HTTPS service, or back to
 * the default one.
 */
@Composable private fun ServiceScreen(s:ReaderState,vm:ReaderViewModel) {
    val p=LocalTeleply.current
    var address by remember(s.origin) { mutableStateOf(if(s.fixture) "" else s.origin) }
    PageFrame("服务地址",null,vm::back,notes={ ScreenNotes(s,vm) }) {
        Text("一般不用改：默认连接 Teleply 的服务。自己部署了账号服务时，在这里填它的 HTTPS 根地址。",style=MaterialTheme.typography.bodyLarge,color=p.muted)
        TeleplyTextField(address,{ address=it },"服务地址",placeholder=DefaultOrigin,keyboardType=KeyboardType.Uri)
        PillButton("连接这个服务",{ vm.connect(address) },style=PillStyle.Primary,enabled=!s.busy && address.isNotBlank(),modifier=Modifier.fillMaxWidth())
        if(s.origin.removeSuffix("/")!=DefaultOrigin) PillButton("恢复默认服务",{ vm.connect(DefaultOrigin) },enabled=!s.busy,modifier=Modifier.fillMaxWidth())
    }
}

/**
 * Settings page (spec 4.6). Only what users set (0.9): conversations, appearance, notifications, voice, the account and
 * about; the service address, the local demo and diagnostics are under 开发者选项 at the bottom.
 */
@Composable private fun SettingsScreen(s:ReaderState,vm:ReaderViewModel) {
    var archived by remember { mutableStateOf(false) }
    var licences by remember { mutableStateOf(false) }
    PageFrame("设置",null,vm::back) {
        if(s.device!=null) {
            SectionLabel("对话")
            CardSection { CardRow("已归档对话",{ archived=true },chevron=true) }
        }
        SectionLabel("外观")
        SegmentedChoice(listOf("system" to "跟随系统","light" to "浅色","dark" to "深色"),s.theme,{ vm.appearance(it,false) })
        if(s.device!=null) PlatformSettings(s,vm)
        if(s.account!=null) {
            SectionLabel("账号")
            CardSection {
                CardRow("我的电脑",vm::computers,chevron=true)
                if(!s.fixture) { CardDivider();CardRow("退出登录",vm::logout,danger=true) }
            }
        }
        SectionLabel("关于遥应")
        val updater=rememberUpdater()
        CardSection {
            CardRow(if(updater?.enabled==false) "遥应 开发版" else "遥应",null,value=BuildConfig.VERSION_NAME.substringBefore('-'))
            CardDivider()
            CardRow("检查更新",{ updater?.check(manual=true) },detail=if(updater?.enabled==false) "开发版不检查更新" else "每天自动看一次，有新版本时提示",chevron=updater?.enabled==true,enabled=updater?.enabled==true)
            CardDivider()
            CardRow("开源组件",{ licences=true },chevron=true)
        }
        CardSection { CardRow("开发者选项",vm::developer,chevron=true) }
    }
    if(archived) ArchivedSheet(vm) { archived=false }
    if(licences) TeleplySheet("开源组件",{ licences=false }) {
        Text("液态玻璃移植自 Kyant0/AndroidLiquidGlass（Backdrop，Apache-2.0）；CommonMark Java 0.24.0（BSD-2-Clause）；AndroidX、Kotlin、OkHttp（Apache-2.0）；Claude、DeepSeek 图形来自 Simple Icons（CC0），Codex 图形来自 SVG Logos（CC0）；这些标志归各自公司所有。",style=MaterialTheme.typography.bodyMedium,color=LocalTeleply.current.text)
    }
}

/**
 * 开发者选项 (0.9, user decision): for building and looking into problems, out of users' way. Where the app connects
 * (服务地址), the local demo with fixed data, 诊断测速, and what this build is.
 */
@Composable private fun DeveloperScreen(s:ReaderState,vm:ReaderViewModel) {
    val p=LocalTeleply.current
    PageFrame("开发者选项",null,vm::back) {
        Text("给开发和排查问题用，平常用不到。",style=MaterialTheme.typography.note,color=p.muted)
        SectionLabel("服务")
        CardSection {
            CardRow("服务地址",vm::serviceSettings,detail=if(s.fixture) "本地示例" else s.origin.removePrefix("https://").removeSuffix("/"),chevron=true)
            if(s.serverVersion.isNotBlank()) { CardDivider();CardRow("服务版本",null,value=s.serverVersion) }
        }
        SectionLabel("本地示例")
        CardSection {
            if(s.fixture) CardRow("正在使用本地示例",null,detail="固定数据，不连接真实服务")
            else CardRow("打开本地示例",vm::fixture,detail="固定数据，不连接真实服务",chevron=true)
        }
        // 0.9.1: how fast the demo computer answers, to see the app on a slow or broken connection.
        if(s.fixture) vm.fixtureWorld?.let { world ->
            var network by remember(world) { mutableStateOf(world.network) }
            Text("示例网络",style=MaterialTheme.typography.note,color=p.muted)
            SegmentedChoice(FixtureNetwork.entries.map { it to it.label },network,{ network=it;world.network=it })
        }
        SectionLabel("诊断测速")
        DiagnosticsSettings(vm,s)
        SectionLabel("这个版本")
        CardSection {
            CardRow("版本",null,value=BuildConfig.VERSION_NAME)
            CardDivider()
            CardRow("包名",null,value=BuildConfig.APPLICATION_ID)
        }
        Text("新版本从 GitHub 发布页下载，核对签名后交给系统安装。",style=MaterialTheme.typography.note,color=p.muted)
    }
}
