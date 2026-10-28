package com.pocketagentdesk.teleply

import android.content.Context
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.interaction.collectIsPressedAsState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.ui.Alignment
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.sp
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.PickVisualMediaRequest
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.layout.onSizeChanged
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject

fun operationLabel(value:String)=when(value) { "pending" -> "待回答";"answered" -> "已回答";"draft" -> "草稿";"submitting","creating","dispatching" -> "正在提交，结果可核对";"unconfirmed","unknown" -> "结果待确认";"accepted" -> "已接收";"failed" -> "失败";"current" -> "当前版本";"updated" -> "文件已更新";"missing" -> "文件缺失";else -> value }
fun sourceName(app:String)=when(app) { "codex" -> "Codex";"claude" -> "Claude";"deepseek" -> "DeepSeek";else -> app }
fun JSONObject.strings(name:String)=optJSONArray(name)?.let { a -> (0 until a.length()).map { a.getString(it) } }.orEmpty()

/**
 * The workspace panes, each as the sheet or page the spec gives it (spec 4.4, 4.5, 4.7): the new conversation is a
 * glass sheet that fits one screen; attachments, references, computer files and conversation files are opaque
 * sheets; a file and a diff are detail pages. Model, mode and permission are menus from the composer's chips
 * (spec 0.4 §4.3), and questions are answered in the timeline.
 */
@Composable fun WorkspacePanes(vm:ReaderViewModel) {
    val c=vm.workspace;val s by c.state.collectAsStateWithLifecycle()
    val reader by vm.state.collectAsStateWithLifecycle()
    // A source switch inside the new-conversation sheet rebinds the workspace; the sheet stays up meanwhile.
    if(s.pane=="new" || reader.pendingNew?.switching==true) NewChatSheet(vm,s,reader)
    val pane=s.pane ?: return
    val k=s.key ?: return
    val j=remember(s.saved) { JSONObject(s.saved) };val data=remember(s.data) { JSONObject(s.data) }
    // Panes opened from a new conversation go back to it instead of closing everything.
    val back:()->Unit=if(k.chat=="@new") ({ c.panel("new") }) else c::close
    when(pane) {
        "new" -> Unit
        "chat","skill" -> TeleplySheet(if(pane=="chat") "引用对话" else "引用技能",back) { PaneStatus(s,j,c);ReferencesPane(pane,k,data,c,s.busy,s.error!=null) }
        "remote" -> TeleplySheet("从电脑选择文件",back) { PaneStatus(s,j,c);RemotePane(k,data,c) }
        "files" -> TeleplySheet("对话文件",c::close) { PaneStatus(s,j,c);FilesPane(data,c) }
        "file" -> DetailPage(data.string("name").ifBlank { "文件" },fileBack(data,c)) { FilePage(vm,k,data,s) }
        "diff" -> DetailPage("本轮差异",c::close) { DiffPage(data,c,s) }
        else -> LaunchedEffect(pane) { c.close() }
    }
}

/** A file page goes back where it was opened: its list, or the conversation for a file an answer links to (10-27). */
private fun fileBack(data:JSONObject,c:WorkspaceController):()->Unit = if(data.optBoolean("linked")) c::close else ({ c.panel(if(data.has("reference")) "remote" else "files") })

@Composable private fun PaneStatus(s:WorkspaceState,j:JSONObject,c:WorkspaceController) {
    val p=LocalTeleply.current
    ProgressLine(s.busy,p.line)
    s.error?.let { Text(it,style=MaterialTheme.typography.note,color=p.error) }
    if(s.result.isNotBlank() && s.pane!="file") Text(s.result,style=MaterialTheme.typography.note,color=p.muted)
    if(j.optJSONObject("pending_action")?.string("status")=="unknown") PillButton("核对上次操作",c::checkAction,enabled=!s.busy && !s.checking,style=PillStyle.Text)
}

// --- New conversation (web new-chat sheet, spec 0.4 §4.4) -----------------------------------------------------

private fun JSONObject.json(name:String)=optJSONObject(name) ?: JSONObject()

/**
 * 新建对话: a glass sheet in the web's order that fits one screen without scrolling. Source, the first message with
 * ＋ and 创建并发送, then one row each for 项目 and 模型与推理强度 (DeepSeek also 权限); a row opens its menu where it
 * is. The server takes no mode for a new conversation, so plan mode is chosen in the conversation afterwards.
 */
@Composable private fun NewChatSheet(vm:ReaderViewModel,s:WorkspaceState,reader:ReaderState) {
    val c=vm.workspace
    val target=reader.pendingNew
    val k=s.key
    val app=target?.app ?: k?.app ?: reader.app
    // Only the apps this computer has (0.9.1), as read when it was entered: nothing is read here while the sheet moves,
    // and while they are not known the sheet offers the source it opened with, not all three.
    val known=reader.knownApps()
    val apps=known ?: listOf(app)
    val ready=k!=null && k.chat=="@new" && k.app==app && s.ready && s.pane=="new"
    // A source the computer turns out not to have (chosen on another computer, or gone there): its first app instead,
    // with the words typed so far.
    LaunchedEffect(known,app,ready) {
        val first=known?.firstOrNull() ?: return@LaunchedEffect
        if(ready && app !in known) {
            val text=runCatching { JSONObject(s.saved).string("first_message") }.getOrDefault("")
            if(text.isNotBlank()) c.edit("first_message","")
            vm.startNew(first,text=text,switching=true)
        }
    }
    TeleplySheet("新建对话",{ c.close();vm.consumeNew() },style=SheetStyle.Glass) {
        // While another source binds, the sheet keeps its shape with the carried text and nothing to press.
        val j=remember(s.saved,ready,target) { if(ready) JSONObject(s.saved) else JSONObject().put("first_message",target?.text.orEmpty()) }
        val data=remember(s.newData,ready) { if(ready) JSONObject(s.newData) else JSONObject() }
        if(apps.size>1) SegmentedChoice(apps.map { it to sourceName(it) },app,{ next ->
            if(next!=app && ready) {
                val text=j.string("first_message")
                if(text.isNotBlank()) c.edit("first_message","")
                vm.startNew(next,text=text,switching=true)
            }
        })
        if(known==null) {
            val failed=reader.sources.failed!=null && !reader.sources.loading
            Text(if(failed) "读不到这台电脑上有哪些应用，先用 ${sourceName(app)}。点这里重试" else "正在读取这台电脑上的应用，先用 ${sourceName(app)}",style=MaterialTheme.typography.note,
                color=if(failed) LocalTeleply.current.accent else LocalTeleply.current.muted,
                modifier=if(failed) Modifier.clip(RoundedCornerShape(8.dp)).clickable(role=Role.Button,onClick=vm::retrySources) else Modifier)
        }
        // A first message under way no longer holds the sheet (0.8, web 10-16): it is followed on its own page.
        if(ready) { s.error?.let { Text(it,style=MaterialTheme.typography.note,color=LocalTeleply.current.error) } }
        NewChat(vm,app,data,j,s,ready,reader.fixture)
    }
}

@Composable private fun ColumnScope.NewChat(vm:ReaderViewModel,app:String,data:JSONObject,j:JSONObject,s:WorkspaceState,ready:Boolean,fixture:Boolean) {
    val c=vm.workspace;val p=LocalTeleply.current;val context=LocalContext.current
    var note by remember { mutableStateOf("") }
    var confirm by remember { mutableStateOf<JSONObject?>(null) }
    val pickers=rememberAttachPickers(vm) { note=it }
    val folders=remember(data,app) { recentFirst(context,app,data.json("folders").rows("items") { it }) }
    val folder=j.string("folder");val projectless=j.string("projectless")=="1"
    // Like the web: a project not yet chosen starts as the one used last here, or the first the computer lists.
    LaunchedEffect(folders,ready) { if(ready && folder.isBlank() && !projectless && folders.isNotEmpty()) c.chooseFolder(folders.first().string("path"),false) }
    val extras=j.rows("uploads") { it }.size+j.rows("references") { it }.size
    val uploading=j.rows("uploads") { it }.any { it.string("status")!="ready" }
    val canCreate=ready && !s.busy && (j.string("first_message").isNotBlank() || extras>0) && !uploading && (app!="deepseek" || folder.isNotBlank())
    NewComposer(vm,app,j,ready,s.busy,pickers,canCreate) { if(!fixture) rememberFolder(context,app,folder);c.create() }
    if(note.isNotBlank()) Text(note,style=MaterialTheme.typography.note,color=p.muted)
    s.newNote?.let { Text(it,style=MaterialTheme.typography.note,color=p.muted) }
    Column(Modifier.fillMaxWidth()) {
        val current=folders.find { it.string("path")==folder }
        val folderName=when {
            folder.isBlank() && app!="deepseek" -> "无项目"
            current!=null -> current.string("name").ifBlank { folder }
            folder.isNotBlank() -> folder.substringAfterLast('/').substringAfterLast('\\')
            else -> "选择工作区"
        }
        val folderDetail=when {
            folder.isBlank() && app!="deepseek" -> "不放进任何项目"
            folder.isNotBlank() -> folder
            data.has("folders") -> "DeepSeek 的工作区"
            else -> "读取电脑上的项目…"
        }
        NewChoiceRow(if(folder.isBlank() && app!="deepseek") TeleplyIcons.Loose else TeleplyIcons.Project,folderName,folderDetail,"项目",ready,"项目文件夹",420.dp,scrolls=false) { FolderMenu(vm) }
        val models=data.json("models").rows("models") { it }
        val modelId=j.string("new_model");val effortId=j.string("new_effort")
        val model=models.find { it.string("id")==modelId }
        val effortLabel=model?.rows("efforts") { it }?.find { it.string("id")==effortId }?.let { e -> if(app=="codex") effortName(e.string("id")) else e.string("label") }
        val modelName=if(modelId.isBlank()) "默认模型" else (model?.string("label")?.ifBlank { null } ?: j.string("new_model_label").ifBlank { modelId })+(effortLabel?.let { " · $it" } ?: "")
        NewChoiceRow(TeleplyIcons.Spark,modelName,if(modelId.isBlank()) "跟电脑当前设置走" else "新对话用这个模型","模型与推理强度",ready,"模型与推理强度",480.dp,scrolls=false) { NewModelMenu(vm) }
        if(app=="deepseek") {
            val options=data.json("permissions").rows("options") { it }
            val chosen=options.find { it.string("value")==j.string("new_permission") && j.string("new_permission").isNotBlank() }
            NewChoiceRow(TeleplyIcons.Settings,chosen?.string("name") ?: j.string("new_permission_name").ifBlank { "默认权限" },"首条消息发送前设置并核对","权限",ready,"权限",420.dp) { NewPermissionMenu(vm) { confirm=it } }
        }
    }
    confirm?.let { option -> AlertDialog(onDismissRequest={confirm=null},title={Text("确认改成「${option.string("name")}」？")},text={Text(option.string("description"))},confirmButton={TextButton(onClick={confirm=null;c.setNewPermission(option)}) { Text("确认选择此权限") }},dismissButton={TextButton(onClick={confirm=null}) { Text("取消") }}) }
}

/** The first message (web .new-composer): attachment tiles, the text, then ＋ and the round 创建并发送 button. */
@Composable private fun NewComposer(vm:ReaderViewModel,app:String,j:JSONObject,ready:Boolean,busy:Boolean,pickers:AttachPickers,canCreate:Boolean,onCreate:()->Unit) {
    val p=LocalTeleply.current;val menus=LocalMenuHost.current;val plus=remember { MenuAnchor() }
    val shape=RoundedCornerShape(20.dp)
    val text=j.string("first_message")
    val maxField=(LocalConfiguration.current.screenHeightDp*0.28f).dp
    Column(Modifier.fillMaxWidth().clip(shape).background(p.card).border(1.dp,p.line,shape).padding(start=6.dp,end=6.dp,top=6.dp,bottom=4.dp)) {
        Attachments(j,vm)
        Box(Modifier.fillMaxWidth().padding(horizontal=10.dp,vertical=8.dp)) {
            if(text.isEmpty()) Text("想做什么？",style=MaterialTheme.typography.bodyLarge,color=p.muted)
            BasicTextField(
                text,
                { vm.workspace.edit("first_message",it) },
                Modifier.fillMaxWidth().heightIn(min=48.dp,max=maxField).testTag("new-message").semantics { contentDescription="首条消息" },
                enabled=ready,
                textStyle=MaterialTheme.typography.bodyLarge.copy(color=p.text),
                cursorBrush=SolidColor(p.accent),
            )
        }
        Row(Modifier.fillMaxWidth(),verticalAlignment=Alignment.CenterVertically) {
            TeleplyIconButton(TeleplyIcons.Plus,"添加附件或引用",{
                menus?.show(MenuRequest(plus.bounds,MenuPlacement.BelowStart,"添加附件或引用",width=240.dp) { AttachMenu(app,ready,pickers,vm) })
            },modifier=Modifier.menuAnchor(plus),style=IconButtonStyle.Plain,tint=p.muted,enabled=ready)
            Spacer(Modifier.weight(1f))
            SendButton("创建并发送",canCreate,busy,onCreate)
        }
    }
}

/**
 * A choice row of the new conversation (web .new-folder): icon, the value with one small line under it, ⌄. A tap opens
 * the row's menu from the row, as wide as the row.
 */
@Composable private fun NewChoiceRow(icon:androidx.compose.ui.graphics.vector.ImageVector,title:String,detail:String,label:String,enabled:Boolean,menuLabel:String,maxHeight:androidx.compose.ui.unit.Dp,scrolls:Boolean=true,menu:@Composable MenuScope.()->Unit) {
    val p=LocalTeleply.current;val menus=LocalMenuHost.current;val density=LocalDensity.current
    val anchor=remember { MenuAnchor() }
    val interaction=remember { MutableInteractionSource() }
    val pressed by interaction.collectIsPressedAsState()
    Row(
        Modifier.fillMaxWidth().heightIn(min=60.dp).menuAnchor(anchor).clip(RoundedCornerShape(16.dp))
            .background(if(pressed) p.pressed else androidx.compose.ui.graphics.Color.Transparent)
            .clickable(interaction,indication=null,enabled=enabled,role=Role.Button) {
                val width=with(density) { anchor.bounds.width.toDp() }.coerceAtLeast(280.dp)
                menus?.show(MenuRequest(anchor.bounds,MenuPlacement.BelowStart,menuLabel,width=width,scrolls=scrolls,maxHeight=maxHeight,content=menu))
            }
            .semantics(mergeDescendants=true) { contentDescription="$label：$title，$detail" }
            .padding(horizontal=4.dp,vertical=10.dp),
        verticalAlignment=Alignment.CenterVertically,
        horizontalArrangement=Arrangement.spacedBy(12.dp),
    ) {
        Icon(icon,contentDescription=null,tint=p.muted,modifier=Modifier.size(22.dp))
        Column(Modifier.weight(1f)) {
            Text(title,style=MaterialTheme.typography.bodyLarge.copy(fontSize=15.sp,fontWeight=FontWeight.Medium),color=p.text.copy(alpha=if(enabled) 1f else 0.6f),maxLines=1,overflow=TextOverflow.Ellipsis)
            Text(detail,style=MaterialTheme.typography.bodySmall.copy(fontSize=12.sp),color=p.muted,maxLines=1,overflow=TextOverflow.Ellipsis,modifier=Modifier.padding(top=2.dp))
        }
        Icon(TeleplyIcons.ChevronDown,contentDescription=null,tint=p.muted,modifier=Modifier.size(18.dp))
    }
}

/** 项目 menu: 无项目 first (not for DeepSeek), then the projects, recently used first; a search box over 8 of them. */
@Composable private fun MenuScope.FolderMenu(vm:ReaderViewModel) {
    val ws by vm.workspace.state.collectAsStateWithLifecycle()
    val k=ws.key ?: return
    val c=vm.workspace;val context=LocalContext.current
    // The list of last time at once; the computer's comes in behind and replaces it (0.8: it used to read first).
    LaunchedEffect(Unit) { c.loadNewFolders() }
    val data=remember(ws.newData) { runCatching { JSONObject(ws.newData) }.getOrDefault(JSONObject()) }
    val j=remember(ws.saved) { runCatching { JSONObject(ws.saved) }.getOrDefault(JSONObject()) }
    val folders=remember(data,k.app) { recentFirst(context,k.app,data.json("folders").rows("items") { it }) }
    var query by remember { mutableStateOf("") }
    val projectless=j.string("folder").isBlank()
    Column(Modifier.fillMaxWidth()) {
        if(folders.size>8) MenuSearch(query,{ query=it },"搜索项目名称或路径")
        Column(Modifier.weight(1f,fill=false).verticalScroll(rememberScrollState())) {
            if(k.app!="deepseek" && (query.isBlank() || "无项目".contains(query.trim()))) {
                MenuRow("无项目",{ c.chooseFolder("",true) },detail=if(k.app=="claude") "Claude 不选文件夹，电脑上显示 No folder" else "在「文档\\Codex」下新建一个文件夹",trailing=if(projectless) MenuTrailing.Checked else MenuTrailing.None)
            }
            val words=query.trim()
            val hits=folders.filter { f -> words.isBlank() || (f.string("name")+" "+f.string("path")+" "+f.strings("sources").joinToString(" ")).contains(words,ignoreCase=true) }
            hits.forEach { f ->
                val path=f.string("path")
                MenuRow(f.string("name").ifBlank { path },{ c.chooseFolder(path,false) },detail=path,trailing=if(!projectless && j.string("folder")==path) MenuTrailing.Checked else MenuTrailing.None)
            }
            when {
                !data.has("folders") -> MenuLoading("首次读取电脑上的项目…")
                hits.isEmpty() && words.isNotBlank() -> MenuHint("没有匹配的项目文件夹")
                folders.isEmpty() -> MenuHint(if(k.app=="deepseek") "电脑上的 DeepSeek 还没有工作区" else "电脑上还没有项目文件夹")
            }
        }
    }
}

/** 模型与推理强度 menu: 默认 first, the models, then the chosen model's effort steps (默认 included). */
@Composable private fun MenuScope.NewModelMenu(vm:ReaderViewModel) {
    val ws by vm.workspace.state.collectAsStateWithLifecycle()
    val k=ws.key ?: return
    val c=vm.workspace
    // The models of last time at once; the computer's list (from what its menus showed before) comes in behind.
    LaunchedEffect(Unit) { c.loadNewModels() }
    val data=remember(ws.newData) { runCatching { JSONObject(ws.newData) }.getOrDefault(JSONObject()) }
    val j=remember(ws.saved) { runCatching { JSONObject(ws.saved) }.getOrDefault(JSONObject()) }
    val options=data.json("models")
    val models=options.rows("models") { it }
    val modelId=j.string("new_model")
    val model=models.find { it.string("id")==modelId }
    val efforts=model?.rows("efforts") { it }.orEmpty().map { e -> e.string("id") to if(k.app=="codex") effortName(e.string("id")) else e.string("label").ifBlank { e.string("id") } }
    ChoiceList(if(efforts.isEmpty()) emptyList() else listOf("" to "默认")+efforts,j.string("new_effort"),true,{ e -> c.edit("new_effort",e) }) {
        MenuRow("默认（电脑当前设置）",{ c.edit("new_model","");c.edit("new_model_label","");c.edit("new_effort","") },trailing=if(modelId.isBlank()) MenuTrailing.Checked else MenuTrailing.None)
        models.forEach { m ->
            val id=m.string("id")
            MenuRow(m.string("label").ifBlank { id },{ if(id!=modelId) { c.edit("new_model",id);c.edit("new_model_label",m.string("label").ifBlank { id });c.edit("new_effort","") } },trailing=if(id==modelId) MenuTrailing.Checked else MenuTrailing.None)
        }
        when {
            !data.has("models") -> MenuLoading("首次读取电脑上的模型…")
            options.string("note").isNotBlank() -> MenuHint(options.string("note"))
            model==null && modelId.isNotBlank() && models.isNotEmpty() -> MenuHint("之前选的模型不在电脑现在的列表里，请重新选。")
        }
    }
}

/** DeepSeek 权限 menu for the new conversation; options that need it are confirmed first. */
@Composable private fun MenuScope.NewPermissionMenu(vm:ReaderViewModel,onConfirm:(JSONObject)->Unit) {
    val ws by vm.workspace.state.collectAsStateWithLifecycle()
    val c=vm.workspace
    LaunchedEffect(Unit) { c.loadNewPermissions() }
    val data=remember(ws.newData) { runCatching { JSONObject(ws.newData) }.getOrDefault(JSONObject()) }
    val j=remember(ws.saved) { runCatching { JSONObject(ws.saved) }.getOrDefault(JSONObject()) }
    val current=j.string("new_permission")
    MenuRow("默认权限",{ c.setNewPermission(JSONObject()) },detail="用 DeepSeek 当前的设置",trailing=if(current.isBlank()) MenuTrailing.Checked else MenuTrailing.None)
    data.json("permissions").rows("options") { it }.forEach { option ->
        val on=current==option.string("value")
        MenuRow(option.string("name"),{ if(!on) { if(option.optBoolean("confirm")) onConfirm(option) else c.setNewPermission(option) } },detail=option.string("description").ifBlank { null },trailing=if(on) MenuTrailing.Checked else MenuTrailing.None)
    }
    if(!data.has("permissions")) MenuLoading("首次读取电脑上的权限…")
}

private const val RecentKey="new_folders_"

private fun recentFolders(context:Context,app:String):List<String> = runCatching {
    val array=JSONArray(context.getSharedPreferences("teleply_ui",Context.MODE_PRIVATE).getString(RecentKey+app,"[]"))
    (0 until array.length()).map { array.getString(it) }
}.getOrDefault(emptyList())

/** Remembers the project a new conversation went to, so the next one starts there (web lbr_new_folder). */
private fun rememberFolder(context:Context,app:String,path:String) {
    if(path.isBlank()) return
    val list=(listOf(path)+recentFolders(context,app).filter { it!=path }).take(8)
    context.getSharedPreferences("teleply_ui",Context.MODE_PRIVATE).edit().putString(RecentKey+app,JSONArray(list).toString()).apply()
}

/** Projects used recently from this phone first, the rest in the computer's order. */
private fun recentFirst(context:Context,app:String,folders:List<JSONObject>):List<JSONObject> {
    val recent=recentFolders(context,app)
    return folders.sortedBy { f -> recent.indexOf(f.string("path")).let { if(it<0) Int.MAX_VALUE else it } }
}

// --- Attachments, references and computer files ---------------------------------------------------------------

@Composable private fun ColumnScope.ReferencesPane(pane:String,k:ChatKey,data:JSONObject,c:WorkspaceController,busy:Boolean,failed:Boolean) {
    var query by remember(k,pane) { mutableStateOf("") }
    TeleplyTextField(query,{ query=it },"搜索${if(pane=="chat") "对话" else "技能"}")
    PillButton("搜索",{ c.refresh(pane,query) },enabled=!busy)
    val items=data.rows("items") { it }
    if(pane=="skill") {
        PillButton("重新读取",{ c.refresh(pane,query,fresh=true) },enabled=!busy,style=PillStyle.Text)
        val status=data.string("scan_status")
        val note=when {
            failed && items.isNotEmpty() -> "刷新失败，以下仍是上次读取的结果。"
            busy -> if(items.isEmpty()) "正在读取技能…" else "正在读取，以下暂为上次结果。"
            status=="failed" -> "技能读取失败，请重试；若仍失败，请检查电脑端技能配置。"
            status=="partial" -> if(items.isEmpty()) "已加载的技能中没有匹配项，部分来源未能读取。" else "部分技能未能读取，其余技能仍可选择。"
            !failed && data.has("items") && items.isEmpty() -> "未找到匹配技能。"
            else -> ""
        }
        if(note.isNotBlank()) Text(note,style=MaterialTheme.typography.note)
        if(data.optBoolean("page_reset")) Text("技能列表已变化，已返回第一页。",style=MaterialTheme.typography.note)
    }
    if(items.isNotEmpty()) CardSection {
        items.forEachIndexed { index,ref ->
            if(index>0) CardDivider()
            CardRow(ref.string("name").ifBlank { ref.string("title") },{ c.addReference(ref);if(k.chat=="@new") c.panel("new") else c.close() },detail=ref.string("description").ifBlank { null })
        }
    }
    if(data.optBoolean("has_more")) PillButton("下一页",{ c.refresh(pane,query,data.string("next_offset")) },style=PillStyle.Text,enabled=!busy)
}

@Composable private fun ColumnScope.RemotePane(k:ChatKey,data:JSONObject,c:WorkspaceController) {
    if(data.string("path").isNotBlank()) Text(data.string("path"),style=MaterialTheme.typography.note,color=LocalTeleply.current.muted)
    Row(horizontalArrangement=Arrangement.spacedBy(8.dp)) {
        if(data.string("parent").isNotBlank()) PillButton("上一级",{ c.refresh("remote",data.string("parent")) })
        data.optJSONObject("folder")?.let { folder -> PillButton("引用此文件夹",{ c.addReference(folder);if(k.chat=="@new") c.panel("new") else c.close() }) }
    }
    val items=data.rows("items") { it }
    if(items.isNotEmpty()) CardSection {
        items.forEachIndexed { index,row ->
            if(index>0) CardDivider()
            val file=row.string("kind")=="file"
            CardRow(row.string("name"),{ if(file) { c.computerFile(row) } else c.refresh("remote",row.string("path")) },icon=if(file) TeleplyIcons.File else TeleplyIcons.Folder,chevron=!file)
        }
    }
    if(data.optBoolean("has_more")) PillButton("下一页",{ c.refresh("remote",data.string("path"),data.string("next_offset")) },style=PillStyle.Text)
}

@Composable private fun ColumnScope.FilesPane(data:JSONObject,c:WorkspaceController) {
    val p=LocalTeleply.current
    InfoNote("这里打开的是文件现在的样子；某一轮改了什么，请从时间线里那一步的「本轮差异」进入。")
    val items=data.rows("items") { it }
    if(items.isEmpty()) Column { Text("暂未识别到本对话的成果文件，可从电脑目录选择并保存到手机。",style=MaterialTheme.typography.note,color=p.muted);PillButton("从电脑选择文件",{ c.panel("remote") },style=PillStyle.Text) }
    else CardSection {
        items.forEachIndexed { index,f ->
            if(index>0) CardDivider()
            CardRow(f.string("name"),{ c.file(f) },detail="${operationLabel(f.string("state"))} · ${f.optLong("size")} 字节",icon=TeleplyIcons.File,chevron=true,enabled=f.string("state")!="missing")
        }
    }
}

// --- Detail pages: file preview and diff (spec 4.5) -----------------------------------------------------------

/**
 * A file's page, as WeChat shows a file (user 10-28: "无用边框太多了，不需要什么说明文字你就参考微信的这种设计，占全部
 * 位置，右上角放三个点"): back, the name, and ⋯ with what can be done with the file; the file itself fills the rest.
 * Word and Excel drawn here (10-28), a PDF and the computer's PDF of PowerPoint page under page, a picture fitted, HTML
 * as a page; Markdown to read and other text in a code panel scroll as before. A file it does not show says what it is.
 * Saving shows how far it got at the bottom.
 */
@Composable private fun FilePage(vm:ReaderViewModel,k:ChatKey,data:JSONObject,s:WorkspaceState) {
    val c=vm.workspace;val context=LocalContext.current;val p=LocalTeleply.current
    var pickerKey by remember { mutableStateOf<ChatKey?>(null) }
    var saving by remember { mutableStateOf<JSONObject?>(null) }
    val save=rememberLauncherForActivityResult(ActivityResultContracts.CreateDocument("application/octet-stream")) { uri -> if(uri!=null && c.state.value.key==pickerKey) saving?.let { c.saveFile(context,uri,it) } }
    val name=data.string("name").ifBlank { "文件" }
    val lower=name.lowercase()
    val html=lower.endsWith(".html") || lower.endsWith(".htm")
    val markdown=lower.endsWith(".md") || lower.endsWith(".markdown")
    var rendered by remember(data.string("id")) { mutableStateOf(true) }
    // How the file shows: "phone", Word or Excel drawn here from the file itself (10-28); "pdf", the PDF the computer's
    // Office makes (PowerPoint, the old .doc and .ppt; 10-27); "failed", neither.
    val shown=data.string("preview");val kind=data.string("kind");val bytes=s.preview
    val meta=data.optJSONObject("meta") ?: JSONObject()
    val ready=!s.busy && s.error==null
    val fill=s.converting || (bytes!=null && (shown=="phone" || shown=="pdf" || kind=="pdf" || kind=="image")) || (html && rendered && s.result.isNotBlank())
    val menus=LocalMenuHost.current;val more=remember { MenuAnchor() }
    PageFrame(name,null,fileBack(data,c),fill=fill,actions={
        CapsuleToolbar(Modifier.menuAnchor(more)) {
            TeleplyIconButton(TeleplyIcons.More,"文件菜单",{
                menus?.show(MenuRequest(more.bounds,MenuPlacement.BelowEnd,"文件菜单") {
                    if((html || markdown) && s.result.isNotBlank()) MenuRow(if(rendered) "查看源码" else if(html) "查看页面" else "阅读视图",{ rendered=!rendered },icon=TeleplyIcons.Text)
                    MenuRow("保存到手机",{ pickerKey=k;saving=JSONObject(s.data);save.launch(name) },icon=TeleplyIcons.Save,enabled=ready && !s.savingFile)
                    MenuRow("系统分享",{ c.shareFile(context,JSONObject(s.data),false) },icon=TeleplyIcons.Share,enabled=ready && !s.savingFile)
                    MenuRow("用其他应用打开",{ c.shareFile(context,JSONObject(s.data),true) },icon=TeleplyIcons.Open,enabled=ready && !s.savingFile)
                    data.optJSONObject("reference")?.let { ref -> MenuRow("添加到消息",{ c.addReference(ref);if(k.chat=="@new") c.panel("new") else c.close() },icon=TeleplyIcons.Plus,enabled=!s.savingFile) }
                    MenuDivider()
                    MenuHint(listOf(operationLabel(meta.string("state")),if(meta.has("size")) fileSize(meta.optLong("size")) else "").filter { it.isNotBlank() }.joinToString(" · "))
                })
            },style=IconButtonStyle.Plain)
        }
    }) {
        if(fill) {
            ProgressLine(s.busy,p.line)
            Box(Modifier.weight(1f).fillMaxWidth()) {
                when {
                    s.converting -> Row(Modifier.align(Alignment.Center).semantics { liveRegion=LiveRegionMode.Polite },verticalAlignment=Alignment.CenterVertically) {
                        CircularProgressIndicator(Modifier.size(16.dp),color=p.accent,strokeWidth=2.dp)
                        Spacer(Modifier.width(8.dp))
                        Text("正在用电脑上的 Office 转成 PDF…",style=MaterialTheme.typography.note,color=p.muted)
                    }
                    bytes!=null && shown=="phone" -> OfficePreview(bytes,data,c::officeFailed,Modifier.fillMaxSize())
                    bytes!=null && (shown=="pdf" || kind=="pdf") -> PdfPages(bytes)
                    bytes!=null && kind=="image" -> PicturePreview(bytes)
                    else -> HtmlPreview(s.result,data,vm,Modifier.fillMaxSize())
                }
            }
            FileStatus(s,c,context,data,Modifier.padding(horizontal=16.dp,vertical=8.dp))
        } else {
            ProgressLine(s.busy,p.line)
            s.error?.let { Text(it,style=MaterialTheme.typography.note,color=p.error) }
            if(s.result.isNotBlank()) {
                if(markdown && rendered) Markdown(s.result,Modifier.fillMaxWidth(),reader=true)
                else CodePanel(name,s.result,"复制文件内容")
            } else if(ready) UnshownFile(data,s,c,context)
            FileStatus(s,c,context,data)
        }
    }
}

/** 1.7 KB for 1,757 bytes, as the iPhone writes sizes. */
fun fileSize(bytes:Long):String = when {
    bytes<1024 -> "$bytes 字节"
    bytes<1024L*1024 -> String.format(java.util.Locale.ROOT,"%.1f KB",bytes/1024.0)
    else -> String.format(java.util.Locale.ROOT,"%.1f MB",bytes/1048576.0)
}

/** A file the page does not show: what it is and why, and the apps that may show it. */
@Composable private fun UnshownFile(data:JSONObject,s:WorkspaceState,c:WorkspaceController,context:Context) {
    val p=LocalTeleply.current
    val size=data.optJSONObject("meta")?.optLong("size") ?: 0L
    val why=s.previewNote.ifBlank { s.transfer.takeIf { !s.savingFile && s.savedUri==null && it.startsWith("预览未能加载") }
        ?: if(size>PreviewLimit) "超过 20MB，不直接显示" else if(data.string("kind")=="text") "文件是空的" else "手机上看不了这类文件" }
    Column(Modifier.fillMaxWidth().padding(top=72.dp),horizontalAlignment=Alignment.CenterHorizontally,verticalArrangement=Arrangement.spacedBy(12.dp)) {
        Icon(TeleplyIcons.File,contentDescription=null,tint=p.muted,modifier=Modifier.size(48.dp))
        Text(data.string("name").ifBlank { "文件" },style=MaterialTheme.typography.bodyLarge,textAlign=androidx.compose.ui.text.style.TextAlign.Center)
        Text("${fileSize(size)} · $why",style=MaterialTheme.typography.note,color=p.muted,textAlign=androidx.compose.ui.text.style.TextAlign.Center)
        PillButton("用其他应用打开",{ c.shareFile(context,JSONObject(s.data),true) },enabled=!s.busy && !s.savingFile,style=PillStyle.Primary,leading=TeleplyIcons.Open)
    }
}

/** At the bottom: a save under way with 取消保存, how it went with 打开已保存的文件, and what went wrong. */
@Composable private fun FileStatus(s:WorkspaceState,c:WorkspaceController,context:Context,data:JSONObject,modifier:Modifier=Modifier) {
    val p=LocalTeleply.current
    val saved=s.transfer.takeIf { s.savingFile || s.savedUri!=null || it.startsWith("保存失败") || it.startsWith("已取消保存") }
    if(saved==null && s.error==null) return
    Row(modifier.fillMaxWidth().semantics { liveRegion=LiveRegionMode.Polite },verticalAlignment=Alignment.CenterVertically,horizontalArrangement=Arrangement.spacedBy(8.dp)) {
        Text(saved ?: s.error.orEmpty(),style=MaterialTheme.typography.note,color=if(saved==null) p.error else p.text,modifier=Modifier.weight(1f))
        if(s.savingFile) PillButton("取消保存",c::cancelSave,style=PillStyle.Text)
        else s.savedUri?.let { uri -> PillButton("打开",{ c.openSaved(context,uri,data.string("name")) },style=PillStyle.Text) }
    }
}

/** One open PDF for [PdfPages]: how many pages, and one page drawn at a time (PdfRenderer opens one page at a time). */
private class OpenPdf(private val file:java.io.File,private val renderer:android.graphics.pdf.PdfRenderer):java.io.Closeable {
    val count=renderer.pageCount
    private var closed=false
    /** Page [index], [width] pixels wide on white; null once the page has gone. */
    fun draw(index:Int,width:Int):android.graphics.Bitmap? = synchronized(this) {
        if(closed) return null
        renderer.openPage(index).use { page ->
            android.graphics.Bitmap.createBitmap(width,(width.toFloat()*page.height/page.width).toInt().coerceIn(1,width*4),android.graphics.Bitmap.Config.ARGB_8888).also {
                it.eraseColor(android.graphics.Color.WHITE);page.render(it,null,null,android.graphics.pdf.PdfRenderer.Page.RENDER_MODE_FOR_DISPLAY)
            }
        }
    }
    override fun close() = synchronized(this) { if(!closed) { closed=true;runCatching { renderer.close() };file.delete() } }
    companion object {
        fun open(folder:java.io.File,bytes:ByteArray):OpenPdf {
            val file=java.io.File.createTempFile("preview-",".pdf",folder)
            try { file.writeBytes(bytes);return OpenPdf(file,android.graphics.pdf.PdfRenderer(android.os.ParcelFileDescriptor.open(file,android.os.ParcelFileDescriptor.MODE_READ_ONLY))) }
            catch(e:Throwable) { file.delete();throw e }
        }
    }
}

/**
 * A PDF's pages one under another on grey, each as wide as the screen, drawn as it comes into view (WeChat, 10-28; was
 * one page at a time with 上一页 and 下一页). The open file goes with the page.
 */
@Composable private fun PdfPages(bytes:ByteArray) {
    val context=LocalContext.current;val p=LocalTeleply.current
    var pdf by remember(bytes) { mutableStateOf<OpenPdf?>(null) }
    var failed by remember(bytes) { mutableStateOf(false) }
    LaunchedEffect(bytes) {
        val opened=withContext(Dispatchers.IO+kotlinx.coroutines.NonCancellable) { runCatching { OpenPdf.open(context.cacheDir,bytes) }.getOrNull() }
        if(opened==null) { failed=true;return@LaunchedEffect }
        pdf=opened
        try { kotlinx.coroutines.awaitCancellation() } finally { pdf=null;opened.close() }
    }
    val open=pdf
    if(failed) Text("无法原生预览，可保存后使用系统应用打开。",style=MaterialTheme.typography.note,color=p.muted,modifier=Modifier.padding(16.dp))
    else if(open!=null) BoxWithConstraints(Modifier.fillMaxSize().background(androidx.compose.ui.graphics.Color(if(p.dark) 0xFF2C2C2E else 0xFFE9E9EC))) {
        val width=constraints.maxWidth.coerceIn(1,1440)
        androidx.compose.foundation.lazy.LazyColumn(Modifier.fillMaxSize(),contentPadding=PaddingValues(vertical=8.dp),verticalArrangement=Arrangement.spacedBy(8.dp)) {
            items(open.count) { index -> PdfPage(open,index,width) }
        }
    }
}

@Composable private fun PdfPage(pdf:OpenPdf,index:Int,width:Int) {
    var drawn by remember(pdf,index,width) { mutableStateOf<android.graphics.Bitmap?>(null) }
    LaunchedEffect(pdf,index,width) { drawn=withContext(Dispatchers.IO) { runCatching { pdf.draw(index,width) }.getOrNull() } }
    val page=drawn
    if(page!=null) Image(page.asImageBitmap(),contentDescription="第 ${index+1} 页，共 ${pdf.count} 页",modifier=Modifier.fillMaxWidth().aspectRatio(page.width.toFloat()/page.height))
    else Box(Modifier.fillMaxWidth().aspectRatio(0.707f).background(androidx.compose.ui.graphics.Color.White))
}

/** A picture fitted to the page, at most 2048 px on its longer side. */
@Composable private fun PicturePreview(bytes:ByteArray) {
    var bitmap by remember(bytes) { mutableStateOf<android.graphics.Bitmap?>(null) };var failed by remember(bytes) { mutableStateOf(false) }
    LaunchedEffect(bytes) {
        val decoded=withContext(Dispatchers.IO) { runCatching {
            val info=android.graphics.BitmapFactory.Options().apply { inJustDecodeBounds=true };android.graphics.BitmapFactory.decodeByteArray(bytes,0,bytes.size,info)
            require(info.outWidth>0 && info.outHeight>0)
            android.graphics.BitmapFactory.decodeByteArray(bytes,0,bytes.size,android.graphics.BitmapFactory.Options().apply { inSampleSize=maxOf(1,maxOf(info.outWidth,info.outHeight)/2048) })
        }.getOrNull() }
        if(decoded==null) failed=true else bitmap=decoded
    }
    Box(Modifier.fillMaxSize(),contentAlignment=Alignment.Center) {
        bitmap?.let { Image(it.asImageBitmap(),contentDescription="文件预览",modifier=Modifier.fillMaxSize(),contentScale=androidx.compose.ui.layout.ContentScale.Fit) }
        if(failed) Text("无法原生预览，可保存后使用系统应用打开。",style=MaterialTheme.typography.note,color=LocalTeleply.current.muted)
    }
}

@Composable private fun DiffPage(data:JSONObject,c:WorkspaceController,s:WorkspaceState) {
    val p=LocalTeleply.current
    PageFrame("本轮差异",data.string("path").ifBlank { null },c::close) {
        ProgressLine(s.busy,p.line)
        s.error?.let { Text(it,style=MaterialTheme.typography.note,color=p.error) }
        InfoNote("来源记录提供的本轮差异；不根据当前文件猜测旧版本。")
        data.strings("hunks").forEach { hunk ->
            SelectionContainer {
                Column(Modifier.fillMaxWidth().background(p.codeFill,TeleplyShape.Code).horizontalScroll(rememberScrollState()).padding(12.dp)) {
                    hunk.lines().forEach { line ->
                        val (fill,ink)=when {
                            line.startsWith("+") -> p.success.copy(alpha=0.12f) to p.success
                            line.startsWith("-") -> p.error.copy(alpha=0.10f) to p.error
                            line.startsWith("@@") -> androidx.compose.ui.graphics.Color.Transparent to p.muted
                            else -> androidx.compose.ui.graphics.Color.Transparent to p.text
                        }
                        Text(line.ifEmpty { " " },style=MaterialTheme.typography.code,color=ink,softWrap=false,modifier=Modifier.background(fill))
                    }
                }
            }
        }
        if(data.has("next") && !data.isNull("next")) PillButton("下一页差异",{ c.diff(data.string("ref"),data.getInt("next")) })
    }
}
