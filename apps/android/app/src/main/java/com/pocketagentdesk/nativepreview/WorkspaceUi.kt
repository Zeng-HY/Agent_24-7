package com.pocketagentdesk.nativepreview

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
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
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

private val Sources = listOf("codex","claude","deepseek")

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
        "chat","skill" -> TeleplySheet(if(pane=="chat") "引用对话" else "引用技能",back) { PaneStatus(s,j,c);ReferencesPane(pane,k,data,c,s.busy) }
        "remote" -> TeleplySheet("电脑上的文件",back) { PaneStatus(s,j,c);RemotePane(k,data,c) }
        "files" -> TeleplySheet("对话文件",c::close) { PaneStatus(s,j,c);FilesPane(data,c) }
        "file" -> DetailPage(data.string("name").ifBlank { "文件" },{ c.panel("files") }) { FilePage(vm,k,data,s) }
        "diff" -> DetailPage("本轮差异",c::close) { DiffPage(data,c,s) }
        else -> LaunchedEffect(pane) { c.close() }
    }
}

@Composable private fun PaneStatus(s:WorkspaceState,j:JSONObject,c:WorkspaceController) {
    val p=LocalTeleply.current
    ProgressLine(s.busy,p.line)
    s.error?.let { Text(it,style=MaterialTheme.typography.note,color=p.error) }
    if(s.result.isNotBlank() && s.pane!="file") Text(s.result,style=MaterialTheme.typography.note,color=p.muted)
    if(j.optJSONObject("pending_action")?.string("status")=="unknown") PillButton("核对上次操作",c::checkAction,enabled=!s.busy,style=PillStyle.Text)
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
    LaunchedEffect(Unit) { vm.loadTree() }
    val apps=remember(reader.tree) { runCatching { JSONObject(reader.tree).rows("apps") { it.string("app") } }.getOrDefault(emptyList()).filter { it in Sources } }.ifEmpty { Sources }
    TeleplySheet("新建对话",{ c.close();vm.consumeNew() },style=SheetStyle.Glass) {
        val ready=k!=null && k.chat=="@new" && k.app==app && s.ready && s.pane=="new"
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

@Composable private fun ColumnScope.ReferencesPane(pane:String,k:ChatKey,data:JSONObject,c:WorkspaceController,busy:Boolean) {
    var query by remember(k,pane) { mutableStateOf("") }
    TeleplyTextField(query,{ query=it },"搜索${if(pane=="chat") "对话" else "技能"}")
    PillButton("搜索",{ c.refresh(pane,query) },enabled=!busy)
    val items=data.rows("items") { it }
    if(items.isNotEmpty()) CardSection {
        items.forEachIndexed { index,ref ->
            if(index>0) CardDivider()
            CardRow(ref.string("name").ifBlank { ref.string("title") },{ c.addReference(ref);if(k.chat=="@new") c.panel("new") else c.close() },detail=ref.string("description").ifBlank { null })
        }
    }
    if(data.optBoolean("has_more")) PillButton("下一页",{ c.refresh(pane,query,data.string("next_offset")) },style=PillStyle.Text)
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
            CardRow(row.string("name"),{ if(file) { c.addReference(row);if(k.chat=="@new") c.panel("new") else c.close() } else c.refresh("remote",row.string("path")) },icon=if(file) TeleplyIcons.File else TeleplyIcons.Folder,chevron=!file)
        }
    }
    if(data.optBoolean("has_more")) PillButton("下一页",{ c.refresh("remote",data.string("path"),data.string("next_offset")) },style=PillStyle.Text)
}

@Composable private fun ColumnScope.FilesPane(data:JSONObject,c:WorkspaceController) {
    val p=LocalTeleply.current
    InfoNote("这里打开的是文件现在的样子；某一轮改了什么，请从时间线里那一步的「本轮差异」进入。")
    val items=data.rows("items") { it }
    if(items.isEmpty()) Text("这个对话没有明确授权的文件引用。",style=MaterialTheme.typography.note,color=p.muted)
    else CardSection {
        items.forEachIndexed { index,f ->
            if(index>0) CardDivider()
            CardRow(f.string("name"),{ c.file(f) },detail="${operationLabel(f.string("state"))} · ${f.optLong("size")} 字节",icon=TeleplyIcons.File,chevron=true,enabled=f.string("state")!="missing")
        }
    }
}

// --- Detail pages: file preview and diff (spec 4.5) -----------------------------------------------------------

@Composable private fun FilePage(vm:ReaderViewModel,k:ChatKey,data:JSONObject,s:WorkspaceState) {
    val c=vm.workspace;val context=LocalContext.current;val p=LocalTeleply.current
    var pickerKey by remember { mutableStateOf<ChatKey?>(null) }
    var saving by remember { mutableStateOf<JSONObject?>(null) }
    val save=rememberLauncherForActivityResult(ActivityResultContracts.CreateDocument("application/octet-stream")) { uri -> if(uri!=null && c.state.value.key==pickerKey) saving?.let { c.saveFile(context,uri,it) } }
    PageFrame(data.string("name").ifBlank { "文件" },"当前文件 · ${operationLabel(data.optJSONObject("meta")?.string("state").orEmpty())}",{ c.panel("files") }) {
        ProgressLine(s.busy,p.line)
        s.error?.let { Text(it,style=MaterialTheme.typography.note,color=p.error) }
        val lower=data.string("name").lowercase()
        val html=lower.endsWith(".html") || lower.endsWith(".htm")
        val markdown=lower.endsWith(".md") || lower.endsWith(".markdown")
        if(s.result.isNotBlank()) {
            // HTML shows as a page and Markdown as text to read, with 查看源码 beside (web artifact-preview).
            if(html || markdown) {
                var rendered by remember(data.string("id")) { mutableStateOf(true) }
                SegmentedChoice(listOf("page" to if(html) "查看页面" else "阅读视图","source" to "查看源码"),if(rendered) "page" else "source",{ rendered=it=="page" })
                if(!rendered) CodePanel(data.string("name").ifBlank { "文本" },s.result,"复制文件内容")
                else if(html) HtmlPreview(s.result,data,vm)
                else Markdown(s.result,Modifier.fillMaxWidth(),reader=true)
            } else CodePanel(data.string("name").ifBlank { "文本" },s.result,"复制文件内容")
        }
        s.preview?.let { bytes -> NativePreview(bytes,data.string("kind")) }
        if((data.optJSONObject("meta")?.optLong("size") ?: 0)>20L*1024*1024) InfoNote("文件超过20MB预览上限，可保存后使用系统应用打开。")
        if(!s.busy && s.error==null) PillButton("保存到手机",{ pickerKey=k;saving=JSONObject(s.data);save.launch(data.string("name").ifBlank { "download" }) },style=PillStyle.Primary,leading=TeleplyIcons.Save,modifier=Modifier.fillMaxWidth())
        Row(Modifier.fillMaxWidth(),horizontalArrangement=Arrangement.spacedBy(8.dp)) {
            PillButton("系统分享",{ c.shareFile(context,JSONObject(s.data),false) },enabled=!s.busy && s.error==null,leading=TeleplyIcons.Share,modifier=Modifier.weight(1f))
            PillButton("用其他应用打开",{ c.shareFile(context,JSONObject(s.data),true) },enabled=!s.busy && s.error==null,leading=TeleplyIcons.Open,modifier=Modifier.weight(1f))
        }
        if(data.string("kind")=="download") InfoNote("这类文件不提供内嵌预览，可保存后使用系统应用打开。")
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

@Composable private fun NativePreview(bytes:ByteArray,kind:String) {
    var page by remember(bytes) { mutableIntStateOf(0) };var pages by remember(bytes) { mutableIntStateOf(1) }
    var bitmap by remember(bytes) { mutableStateOf<android.graphics.Bitmap?>(null) };var error by remember(bytes) { mutableStateOf<String?>(null) }
    val context=LocalContext.current
    LaunchedEffect(bytes,page) {
        try { bitmap=withContext(Dispatchers.IO) {
            if(kind=="pdf") {
                val temp=java.io.File.createTempFile("preview-",".pdf",context.cacheDir)
                try { temp.writeBytes(bytes);android.graphics.pdf.PdfRenderer(android.os.ParcelFileDescriptor.open(temp,android.os.ParcelFileDescriptor.MODE_READ_ONLY)).use { renderer -> pages=renderer.pageCount;renderer.openPage(page.coerceIn(0,renderer.pageCount-1)).use { pg -> android.graphics.Bitmap.createBitmap(1000,(1000f*pg.height/pg.width).toInt().coerceIn(1,4096),android.graphics.Bitmap.Config.ARGB_8888).also { it.eraseColor(android.graphics.Color.WHITE);pg.render(it,null,null,android.graphics.pdf.PdfRenderer.Page.RENDER_MODE_FOR_DISPLAY) } } } } finally { temp.delete() }
            } else { val info=android.graphics.BitmapFactory.Options().apply { inJustDecodeBounds=true };android.graphics.BitmapFactory.decodeByteArray(bytes,0,bytes.size,info);require(info.outWidth>0 && info.outHeight>0);val opts=android.graphics.BitmapFactory.Options().apply { inSampleSize=maxOf(1,maxOf(info.outWidth,info.outHeight)/2048) };android.graphics.BitmapFactory.decodeByteArray(bytes,0,bytes.size,opts) ?: throw IllegalArgumentException("图片格式不支持") }
        } } catch(e:Exception) { error="无法原生预览，可保存后使用系统应用打开。" }
    }
    bitmap?.let { Image(it.asImageBitmap(),contentDescription="文件预览",modifier=Modifier.fillMaxWidth()) }
    error?.let { Text(it,style=MaterialTheme.typography.note,color=LocalTeleply.current.muted) }
    if(kind=="pdf") Row(verticalAlignment=androidx.compose.ui.Alignment.CenterVertically) { PillButton("上一页",{ page-- },enabled=page>0,style=PillStyle.Text);Text("${page+1}/$pages",style=MaterialTheme.typography.note);PillButton("下一页",{ page++ },enabled=page+1<pages,style=PillStyle.Text) }
}
