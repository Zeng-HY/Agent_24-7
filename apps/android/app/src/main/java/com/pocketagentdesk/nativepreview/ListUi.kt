package com.pocketagentdesk.nativepreview

import android.content.Context
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.tween
import androidx.compose.foundation.ScrollState
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.wrapContentHeight
import androidx.compose.foundation.rememberScrollState
import androidx.compose.runtime.mutableStateMapOf
import androidx.compose.ui.layout.onPlaced
import androidx.compose.ui.layout.positionInParent
import androidx.compose.ui.composed
import androidx.compose.ui.draw.drawWithContent
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.BlendMode
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.CompositingStrategy
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.platform.LocalLayoutDirection
import androidx.compose.ui.unit.LayoutDirection
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.interaction.collectIsPressedAsState
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.IntrinsicSize
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.WindowInsetsSides
import androidx.compose.foundation.layout.asPaddingValues
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.navigationBars
import androidx.compose.foundation.layout.only
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawing
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.windowInsetsPadding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyListScope
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.selection.selectable
import androidx.compose.foundation.selection.selectableGroup
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.Icon
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.minimumInteractiveComponentSize
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.runtime.snapshotFlow
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.layout.onSizeChanged
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.semantics.stateDescription
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlinx.coroutines.FlowPreview
import kotlinx.coroutines.flow.debounce
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.drop
import org.json.JSONObject
import java.util.Calendar

/** Web list labels (remote.html STATUS). */
fun statusLabel(status: String) = when (status) {
    "running" -> "● 运行中"
    "waiting" -> "等待你处理"
    "idle" -> "空闲"
    "stopped" -> "已停止"
    "failed" -> "失败"
    else -> "状态不明"
}

/** Web ago(): 刚刚, N 分钟前, 今天 HH:MM, 昨天 HH:MM, M-D HH:MM. */
fun agoLabel(ms: Long, now: Long = System.currentTimeMillis()): String {
    if (ms <= 0) return ""
    val seconds = (now - ms) / 1000
    if (seconds < 60) return "刚刚"
    if (seconds < 3600) return "${seconds / 60} 分钟前"
    val t = Calendar.getInstance().apply { timeInMillis = ms }
    val today = Calendar.getInstance().apply { timeInMillis = now }
    val yesterday = Calendar.getInstance().apply { timeInMillis = now - 86_400_000L }
    fun same(a: Calendar, b: Calendar) = a.get(Calendar.YEAR) == b.get(Calendar.YEAR) && a.get(Calendar.DAY_OF_YEAR) == b.get(Calendar.DAY_OF_YEAR)
    val hhmm = "%02d:%02d".format(t.get(Calendar.HOUR_OF_DAY), t.get(Calendar.MINUTE))
    return when {
        same(t, today) -> "今天 $hhmm"
        same(t, yesterday) -> "昨天 $hhmm"
        else -> "${t.get(Calendar.MONTH) + 1}-${t.get(Calendar.DAY_OF_MONTH)} $hhmm"
    }
}

/** Source badge colours: each app's own brand colour (web .badge). */
fun badgeColor(app: String) = when (app) {
    "claude" -> Color(0xFFD97757)
    "deepseek" -> Color(0xFF4D6BFE)
    else -> Color(0xFF111111)
}

@Composable
fun SourceBadge(app: String) {
    Box(Modifier.clip(RoundedCornerShape(6.dp)).background(badgeColor(app)).padding(horizontal = 6.dp, vertical = 2.dp)) {
        Text(sourceName(app), style = MaterialTheme.typography.labelSmall.copy(fontSize = 11.sp, fontWeight = FontWeight.SemiBold), color = Color.White)
    }
}

/**
 * The conversation list (spec 4.1): a glass title bar with ☰, "对话" and the computer, ✎ on the right; the source
 * chips, the search box and the rows scroll under it (web header fixes only the title row).
 */
@OptIn(FlowPreview::class)
@Composable
fun ChatListScreen(s: ReaderState, vm: ReaderViewModel, onMenu: () -> Unit, modifier: Modifier = Modifier) {
    val p = LocalTeleply.current
    val density = LocalDensity.current
    var barHeight by remember { mutableStateOf(0.dp) }
    val list = rememberLazyListState()
    var query by rememberSaveable(s.scope, s.device?.id) { mutableStateOf(s.query) }
    LaunchedEffect(s.query) { if (s.query != query && s.query.isBlank()) query = "" }
    LaunchedEffect(s.scope, s.device?.id) {
        snapshotFlow { query }.drop(1).distinctUntilChanged().debounce(450).collect { if (it != vm.state.value.query) vm.searchChats(it) }
    }
    val bottom = WindowInsets.navigationBars.asPaddingValues().calculateBottomPadding()
    val context = LocalContext.current
    // Open folds of children are kept on this phone (web lbr_conv_folds).
    var folds by remember { mutableStateOf(context.getSharedPreferences(FoldPrefs, Context.MODE_PRIVATE).getStringSet("conv_folds", emptySet()).orEmpty()) }
    val toggleFold: (String) -> Unit = { key ->
        folds = if (key in folds) folds - key else folds + key
        context.getSharedPreferences(FoldPrefs, Context.MODE_PRIVATE).edit().putStringSet("conv_folds", folds).apply()
    }
    val swipe = remember { SwipeState() }
    LaunchedEffect(list.isScrollInProgress) { if (list.isScrollInProgress) swipe.open = null }
    GlassScreen(
        modifier.fillMaxSize().background(p.page),
        topEdge = barHeight + 12.dp,
        content = {
            LazyColumn(
                Modifier.fillMaxSize().testTag("chat-list"),
                state = list,
                contentPadding = PaddingValues(start = 16.dp, end = 16.dp, top = barHeight + 4.dp, bottom = bottom + 88.dp),
            ) {
                item(key = "jobs") { NewJobDock(s, vm) }
                item(key = "chips") { SourceChips(s, vm) }
                item(key = "search") { SearchLine(query, { query = it }, { vm.searchChats(query) }) }
                chatRows(s, vm, query, { query = "" }, folds, toggleFold, swipe)
            }
        },
        overlay = {
            Column(Modifier.fillMaxWidth().onSizeChanged { barHeight = with(density) { it.height.toDp() } }) {
                ListTopBar(s, vm, onMenu)
                ProgressLine(s.busy)
                if (s.fixture) NoteBar("本地示例 · 固定数据 · 未连接真实服务", NoteTone.Info)
                s.error?.let { NoteBar(it, NoteTone.Error, action = "重试", actionEnabled = !s.busy, onAction = vm::retry) }
            }
            Column(Modifier.align(Alignment.BottomCenter).fillMaxWidth().padding(bottom = bottom + 16.dp), horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(8.dp)) {
                NoticeToast(s.notice, { vm.notice(null) })
                UndoBar(s.undo, vm::undoArchive, vm::dropUndo)
            }
        },
    )
}

@Composable
private fun ListTopBar(s: ReaderState, vm: ReaderViewModel, onMenu: () -> Unit) {
    val p = LocalTeleply.current
    val menus = LocalMenuHost.current
    val machine = remember { MenuAnchor() }
    Row(
        Modifier.fillMaxWidth()
            .windowInsetsPadding(WindowInsets.safeDrawing.only(WindowInsetsSides.Top + WindowInsetsSides.Horizontal))
            .padding(start = 16.dp, end = 16.dp, top = 8.dp, bottom = 8.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        TeleplyIconButton(TeleplyIcons.Menu, "打开导航", onMenu)
        Column(Modifier.weight(1f)) {
            Text("对话", style = MaterialTheme.typography.titleLarge, color = p.text, modifier = Modifier.semantics { heading() })
            val devices = s.account?.devices.orEmpty()
            val canSwitch = devices.size > 1
            Text(
                (s.device?.label ?: "电脑上的工作，随时继续") + if (canSwitch) " ⌄" else "",
                style = MaterialTheme.typography.labelMedium,
                color = p.muted,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
                modifier = Modifier
                    .menuAnchor(machine)
                    .then(
                        if (canSwitch && menus != null) Modifier.clickable(role = Role.Button) {
                            menus.show(MenuRequest(machine.bounds, MenuPlacement.BelowStart, "切换电脑") {
                                devices.forEach { device ->
                                    MenuRow(
                                        device.label,
                                        { vm.select(device) },
                                        icon = TeleplyIcons.Window,
                                        detail = if (device.connectable) null else "电脑离线",
                                        trailing = if (device.id == s.device?.id) MenuTrailing.Checked else MenuTrailing.None,
                                        enabled = device.connectable && !s.busy,
                                    )
                                }
                                MenuDivider()
                                MenuRow("账号与电脑", { vm.computers() }, icon = TeleplyIcons.Settings)
                            })
                        }.semantics { contentDescription = "切换电脑，当前是${s.device?.label ?: "未选择"}" } else Modifier,
                    )
                    .padding(vertical = 2.dp),
            )
        }
        // A computer with none of the apps has nothing to start a conversation in; a list being read does not hold it.
        val noApps = s.knownApps()?.isEmpty() == true
        TeleplyIconButton(TeleplyIcons.New, "新建对话", { vm.startNew(if (s.listSource == "all") s.app else s.listSource) }, enabled = s.device != null && !noApps,
            disabledReason = if (noApps) "这台电脑上没有找到可用的桌面应用" else null)
    }
}

/**
 * 全部 and a chip for each app this computer has, then the ⋯ "列表显示" menu (spec 4.1). Only the computer's own apps
 * (0.9.1, as the web hides the others): while they are not known yet, only 全部 (and a filter already chosen) with a
 * short note, never all three. The chips keep their full width and scroll sideways when they do not fit; the edge they
 * pass under fades a little while there is more that way. The ⋯ stays put outside the scrolling. Content layer: not glass.
 */
@Composable
private fun SourceChips(s: ReaderState, vm: ReaderViewModel) {
    val menus = LocalMenuHost.current
    val anchor = remember { MenuAnchor() }
    val known = s.knownApps()
    val options = listOf("all" to "全部") + (known ?: listOf(s.listSource).filter { it != "all" }).map { it to sourceName(it) }
    val scroll = rememberScrollState()
    // Where each chip sits in the row: the chosen one is scrolled fully into view, clear of the faded edge, also when it
    // was only partly showing. Only this row scrolls; the list around it never moves for it.
    val spans = remember { mutableStateMapOf<String, IntRange>() }
    val margin = with(LocalDensity.current) { 24.dp.roundToPx() }
    LaunchedEffect(s.listSource, spans[s.listSource], scroll.viewportSize) {
        val span = spans[s.listSource] ?: return@LaunchedEffect
        val viewport = scroll.viewportSize
        if (viewport <= 0) return@LaunchedEffect
        val target = when {
            span.first < scroll.value -> span.first - margin
            span.last > scroll.value + viewport -> span.last + margin - viewport
            else -> return@LaunchedEffect
        }
        scroll.animateScrollTo(target.coerceIn(0, scroll.maxValue))
    }
    Row(Modifier.fillMaxWidth().padding(top = 8.dp, bottom = 12.dp), verticalAlignment = Alignment.CenterVertically) {
        Row(
            Modifier.weight(1f).edgeFade(scroll).horizontalScroll(scroll).selectableGroup().testTag("source-chips"),
            horizontalArrangement = Arrangement.spacedBy(8.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            options.forEach { (value, label) ->
                SourceChip(label, s.listSource == value, !s.busy, Modifier.onPlaced { spans[value] = it.positionInParent().x.toInt().let { x -> x..x + it.size.width } }) { vm.listDisplay(source = value) }
            }
            if (known == null && s.device != null) {
                if (s.sources.failed != null && !s.sources.loading) SourceNote("读不到这台电脑的应用 · 重试", vm::retrySources) else SourceNote("正在读取这台电脑的应用…", null)
            }
        }
        Spacer(Modifier.width(8.dp))
        TeleplyIconButton(
            TeleplyIcons.More,
            "列表显示选项",
            {
                menus?.show(MenuRequest(anchor.bounds, MenuPlacement.BelowEnd, "列表显示") { ListDisplayMenu(s, vm) })
            },
            modifier = Modifier.menuAnchor(anchor),
            style = IconButtonStyle.Solid,
        )
    }
}

/** A source chip at its full width (0.9.1: chips no longer share the row's width, which cut "DeepSeek" to "Deep"). */
@Composable
private fun SourceChip(label: String, selected: Boolean, enabled: Boolean, modifier: Modifier = Modifier, onClick: () -> Unit) {
    val p = LocalTeleply.current
    val interaction = remember { MutableInteractionSource() }
    Box(
        modifier
            .minimumInteractiveComponentSize()
            .heightIn(min = 40.dp)
            .pressScale(interaction)
            .clip(CircleShape)
            .background(if (selected) p.accent else p.control)
            .then(if (p.dark && !selected) Modifier.border(1.dp, p.edge, CircleShape) else Modifier)
            .selectable(selected, interactionSource = interaction, indication = null, enabled = enabled, role = Role.Tab, onClick = onClick)
            .padding(horizontal = 14.dp),
        contentAlignment = Alignment.Center,
    ) {
        Text(label, style = MaterialTheme.typography.labelLarge, color = if (selected) p.onAccent else p.text, maxLines = 1, softWrap = false)
    }
}

/** A line beside the chips while the computer's apps are not known: reading, or why not with 重试 ([onRetry]). */
@Composable
private fun SourceNote(text: String, onRetry: (() -> Unit)?) {
    val p = LocalTeleply.current
    Text(
        text,
        style = MaterialTheme.typography.note,
        color = if (onRetry != null) p.accent else p.muted,
        maxLines = 1,
        softWrap = false,
        modifier = Modifier.clip(CircleShape)
            .then(if (onRetry != null) Modifier.clickable(role = Role.Button, onClick = onRetry) else Modifier)
            .heightIn(min = 40.dp).wrapContentHeight().padding(horizontal = 8.dp),
    )
}

/**
 * Fades the content out towards an edge it runs past, only while it can still scroll that way (0.9.1): the chips seem
 * to go on past the edge instead of being cut. It is a mask on this box's own drawing, so it takes no touches and
 * covers nothing beside the box.
 */
fun Modifier.edgeFade(scroll: ScrollState, width: Dp = 24.dp): Modifier = composed {
    val start by animateFloatAsState(if (scroll.canScrollBackward) 1f else 0f, tween(150), label = "fade-start")
    val end by animateFloatAsState(if (scroll.canScrollForward) 1f else 0f, tween(150), label = "fade-end")
    val rtl = LocalLayoutDirection.current == LayoutDirection.Rtl
    graphicsLayer { compositingStrategy = CompositingStrategy.Offscreen }
        .drawWithContent {
            drawContent()
            val w = width.toPx().coerceAtMost(size.width / 3f)
            val left = if (rtl) end else start
            val right = if (rtl) start else end
            if (left > 0f) drawRect(Brush.horizontalGradient(0f to Color.Black.copy(alpha = 1f - left), 1f to Color.Black, startX = 0f, endX = w), size = Size(w, size.height), blendMode = BlendMode.DstIn)
            if (right > 0f) drawRect(Brush.horizontalGradient(0f to Color.Black, 1f to Color.Black.copy(alpha = 1f - right), startX = size.width - w, endX = size.width), topLeft = Offset(size.width - w, 0f), size = Size(w, size.height), blendMode = BlendMode.DstIn)
        }
}

/** 分组 / 排序 / 状态 / 来源, each with its current value; a row opens its options in the same menu (web). */
@Composable
private fun MenuScope.ListDisplayMenu(s: ReaderState, vm: ReaderViewModel) {
    var page by remember { mutableStateOf<String?>(null) }
    val groups = listOf("none" to "不分组", "project" to "按项目", "app" to "按来源应用")
    val sorts = listOf("updated" to "最近活动", "created" to "创建时间")
    val states = listOf("all" to "全部", "running" to "运行中", "waiting" to "等待处理", "done" to "已结束")
    // The same apps as the chips (0.9.1): this computer's, or while not known only a filter already chosen.
    val known = s.knownApps()
    val sources = listOf("all" to "全部应用") + (known ?: listOf(s.listSource).filter { it != "all" }).map { it to sourceName(it) }
    fun label(options: List<Pair<String, String>>, value: String) = options.firstOrNull { it.first == value }?.second ?: value
    when (page) {
        null -> {
            MenuRow("分组", { page = "group" }, detail = label(groups, s.listGroup), trailing = MenuTrailing.Chevron, dismissOnClick = false)
            MenuRow("排序", { page = "sort" }, detail = label(sorts, s.listSort), trailing = MenuTrailing.Chevron, dismissOnClick = false)
            MenuRow("状态", { page = "status" }, detail = label(states, s.listStatus), trailing = MenuTrailing.Chevron, dismissOnClick = false)
            MenuRow("来源", { page = "source" }, detail = label(sources, s.listSource), trailing = MenuTrailing.Chevron, dismissOnClick = false)
        }
        else -> {
            MenuRow("‹ 返回", { page = null }, dismissOnClick = false)
            MenuDivider()
            val (options, current) = when (page) {
                "group" -> groups to s.listGroup
                "sort" -> sorts to s.listSort
                "status" -> states to s.listStatus
                else -> sources to s.listSource
            }
            options.forEach { (value, text) ->
                MenuRow(text, {
                    when (page) {
                        "group" -> vm.listDisplay(group = value)
                        "sort" -> vm.listDisplay(sort = value)
                        "status" -> vm.listDisplay(status = value)
                        else -> vm.listDisplay(source = value)
                    }
                }, trailing = if (value == current) MenuTrailing.Checked else MenuTrailing.None)
            }
            if (page == "source" && known == null) MenuHint(if (s.sources.failed != null && !s.sources.loading) "读不到这台电脑上有哪些应用，可在列表上方重试" else "正在读取这台电脑上的应用…")
        }
    }
}

/** Search box under the chips (web placeholder). Searches as you stop typing, or on the keyboard's search key. */
@Composable
private fun SearchLine(value: String, onValue: (String) -> Unit, onSearch: () -> Unit) {
    val p = LocalTeleply.current
    Row(
        Modifier.fillMaxWidth().padding(bottom = 8.dp).heightIn(min = 44.dp).clip(CircleShape).background(p.control)
            .then(if (p.dark) Modifier.border(1.dp, p.edge, CircleShape) else Modifier)
            .padding(horizontal = 14.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Icon(TeleplyIcons.Search, contentDescription = null, tint = p.muted, modifier = Modifier.size(18.dp))
        Spacer(Modifier.width(10.dp))
        Box(Modifier.weight(1f).padding(vertical = 10.dp)) {
            if (value.isEmpty()) Text("搜索对话标题或文件夹", style = MaterialTheme.typography.bodyLarge, color = p.muted, maxLines = 1)
            BasicTextField(
                value,
                onValue,
                Modifier.fillMaxWidth().testTag("chat-search").semantics { contentDescription = "搜索对话标题或文件夹" },
                textStyle = MaterialTheme.typography.bodyLarge.copy(color = p.text),
                singleLine = true,
                cursorBrush = SolidColor(p.accent),
                keyboardOptions = KeyboardOptions(imeAction = ImeAction.Search),
                keyboardActions = KeyboardActions(onSearch = { onSearch() }),
            )
        }
        if (value.isNotEmpty()) TeleplyIconButton(TeleplyIcons.Close, "清除搜索", { onValue(""); onSearch() }, style = IconButtonStyle.Plain, tint = p.muted)
    }
}

/** Sources whose conversations can be archived from the list (web: Codex, DeepSeek, and Claude where the computer has it). */
private val Archivable = setOf("codex", "claude", "deepseek")

private fun LazyListScope.chatRows(s: ReaderState, vm: ReaderViewModel, query: String, clearQuery: () -> Unit, folds: Set<String>, toggleFold: (String) -> Unit, swipe: SwipeState) {
    if (s.chats.isEmpty()) {
        if (!s.busy) item(key = "empty") { EmptyList(s, vm, query.isNotBlank(), clearQuery) }
        return
    }
    val groupName: (Chat) -> String = when (s.listGroup) {
        "project" -> { c -> c.folder.ifBlank { "未分组" } }
        "app" -> { c -> sourceName(c.app) }
        else -> { _ -> "" }
    }
    val rows = if (s.listGroup == "none") s.chats else s.chats.sortedBy(groupName)
    var previous: String? = null
    rows.forEachIndexed { index, chat ->
        val heading = groupName(chat)
        if (heading.isNotEmpty() && heading != previous) {
            val key = "group:$heading"
            item(key = key) { Text(heading, style = MaterialTheme.typography.note, color = LocalTeleply.current.muted, modifier = Modifier.padding(start = 8.dp, top = 16.dp, bottom = 4.dp).semantics { heading() }) }
        }
        previous = heading
        val key = chatKey(chat)
        val open = key in folds
        item(key = "chat:$key") {
            when {
                // 未分组的会话: a row that only folds its sessions.
                chat.group -> ChatRow(chat, first = index == 0, enabled = !s.busy, open = open, modifier = Modifier.animateItem()) { toggleFold(key) }
                // A search hit that is a child: it says whose it is, and a subagent opens the conversation that shows its card.
                chat.kind.isNotBlank() -> ChatRow(chat, first = index == 0, enabled = !s.busy, modifier = Modifier.animateItem()) { vm.openChild(chat, null) }
                else -> Box(Modifier.animateItem()) {
                    SwipeArchive(key, swipe, chat.status == "running", !s.busy && chat.app in Archivable, { vm.archive(chat) }, { vm.notice("这个对话正在运行，先停止这一轮再归档") }) {
                        ChatRow(chat, first = index == 0, enabled = !s.busy) { vm.open(chat) }
                    }
                }
            }
        }
        if (chat.childCount > 0 && !chat.group) item(key = "fold:$key") {
            FoldRow(open, chat.childCount, chat.childRunning, Modifier.animateItem()) { toggleFold(key) }
        }
        if (open && chat.childCount > 0) {
            val kids = (chat.children + s.moreKids[key].orEmpty()).distinctBy { it.id }
            kids.forEach { child -> item(key = "child:$key:${child.id}") { ChildRow(child, enabled = !s.busy, modifier = Modifier.animateItem()) { vm.openChild(child, chat) } } }
            if (chat.childCount > kids.size) item(key = "more:$key") {
                Text(
                    "再显示 ${minOf(50, chat.childCount - kids.size)} 个（共 ${chat.childCount} 个）",
                    style = MaterialTheme.typography.note,
                    color = LocalTeleply.current.accent,
                    modifier = Modifier.animateItem().fillMaxWidth().clip(RoundedCornerShape(8.dp)).clickable(role = Role.Button) { vm.moreChildren(chat) }.padding(start = 24.dp, top = 6.dp, bottom = 14.dp),
                )
            }
        }
    }
    if (s.listMore) item(key = "more") {
        Box(Modifier.fillMaxWidth().padding(top = 12.dp), contentAlignment = Alignment.Center) {
            PillButton("加载更多对话", vm::moreChats, enabled = !s.busy)
        }
    }
}

/**
 * Web .conv row: source badge, title, time; status and folder; one line of preview. A group row (未分组的会话) says
 * how many sessions it holds and folds them ([open]); a child found by search says whose it is.
 */
@Composable
fun ChatRow(chat: Chat, first: Boolean = false, enabled: Boolean = true, selected: Boolean = false, open: Boolean? = null, modifier: Modifier = Modifier, onClick: () -> Unit) {
    val p = LocalTeleply.current
    val interaction = remember { MutableInteractionSource() }
    val pressed by interaction.collectIsPressedAsState()
    Column(modifier.fillMaxWidth().then(if (open != null) Modifier.semantics { stateDescription = if (open) "已展开" else "已收起" } else Modifier)) {
        if (!first) Box(Modifier.fillMaxWidth().height(1.dp).background(if (p.dark) p.line else p.panel))
        Column(
            Modifier.fillMaxWidth()
                .clip(RoundedCornerShape(8.dp))
                .background(if (pressed) p.pressed else if (selected) p.selected else Color.Transparent)
                .clickable(interaction, indication = null, enabled = enabled, role = Role.Button, onClick = onClick)
                .padding(horizontal = 4.dp, vertical = 14.dp),
        ) {
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                if (chat.app.isNotBlank()) SourceBadge(chat.app)
                Text(chat.title + when (open) { true -> " ▾"; false -> " ▸"; null -> "" }, style = MaterialTheme.typography.bodyLarge.copy(fontWeight = FontWeight.SemiBold), color = p.text, maxLines = 1, overflow = TextOverflow.Ellipsis, modifier = Modifier.weight(1f))
                val ago = agoLabel(chat.updated)
                if (ago.isNotEmpty()) Text(ago, style = MaterialTheme.typography.bodySmall, color = p.muted, maxLines = 1)
            }
            Row(Modifier.padding(top = 6.dp)) {
                val status = statusLabel(chat.status)
                Text(
                    status,
                    style = MaterialTheme.typography.note,
                    color = when (chat.status) { "running" -> p.success; "waiting" -> p.askGo; "failed" -> p.error; "unknown", "" -> p.amber; else -> p.muted },
                    fontWeight = if (chat.status == "running" || chat.status == "waiting") FontWeight.SemiBold else null,
                )
                val detail = when {
                    chat.group -> " · ${chat.childCount} 个" + if (chat.childRunning > 0) "，${chat.childRunning} 个运行中" else ""
                    chat.kind == "subagent" -> " · 子智能体"
                    chat.folder.isNotBlank() -> " · ${chat.folder}"
                    else -> ""
                } + if (chat.kind.isNotBlank()) (if (chat.parentTitle.isNotBlank()) " · 属于「${chat.parentTitle}」" else " · 未分组") else ""
                if (detail.isNotBlank()) Text(detail, style = MaterialTheme.typography.note, color = p.muted, maxLines = 1, overflow = TextOverflow.Ellipsis)
            }
            if (chat.preview.isNotBlank()) Text(chat.preview, style = MaterialTheme.typography.bodyMedium, color = p.muted, maxLines = 1, overflow = TextOverflow.Ellipsis, modifier = Modifier.padding(top = 6.dp))
        }
    }
}

/** 子对话 N 个 · M 个运行中, or 收起子对话 (web .conv-fold): folds a row's children under it. */
@Composable
private fun FoldRow(open: Boolean, count: Int, running: Int, modifier: Modifier = Modifier, onClick: () -> Unit) {
    val p = LocalTeleply.current
    Text(
        (if (open) "▾ 收起子对话" else "▸ 子对话 $count 个") + if (running > 0) " · $running 个运行中" else "",
        style = MaterialTheme.typography.note.copy(fontWeight = FontWeight.Medium),
        color = p.accent,
        modifier = modifier.fillMaxWidth().clip(RoundedCornerShape(8.dp)).clickable(role = Role.Button, onClick = onClick)
            .semantics { stateDescription = if (open) "已展开" else "已收起" }
            .padding(start = 16.dp, top = 2.dp, bottom = 12.dp),
    )
}

/** A child under its conversation (web .conv-child): a line on the left, its title, state and time. */
@Composable
private fun ChildRow(chat: Chat, enabled: Boolean, modifier: Modifier = Modifier, onClick: () -> Unit) {
    val p = LocalTeleply.current
    val interaction = remember { MutableInteractionSource() }
    val pressed by interaction.collectIsPressedAsState()
    Row(
        modifier.fillMaxWidth().height(IntrinsicSize.Min).clip(RoundedCornerShape(8.dp))
            .background(if (pressed) p.pressed else Color.Transparent)
            .clickable(interaction, indication = null, enabled = enabled, role = Role.Button, onClick = onClick),
    ) {
        Box(Modifier.padding(start = 11.dp, top = 8.dp, bottom = 8.dp).width(2.dp).fillMaxHeight().clip(RoundedCornerShape(1.dp)).background(p.line))
        Column(Modifier.weight(1f).padding(start = 11.dp, end = 4.dp, top = 9.dp, bottom = 9.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(chat.title, style = MaterialTheme.typography.bodyLarge.copy(fontSize = 15.sp, fontWeight = FontWeight.Medium), color = p.text, maxLines = 1, overflow = TextOverflow.Ellipsis, modifier = Modifier.weight(1f))
                val ago = agoLabel(chat.updated)
                if (ago.isNotEmpty()) Text(ago, style = MaterialTheme.typography.bodySmall, color = p.muted, maxLines = 1, modifier = Modifier.padding(start = 8.dp))
            }
            Row(Modifier.padding(top = 2.dp)) {
                Text(statusLabel(chat.status), style = MaterialTheme.typography.bodySmall.copy(fontSize = 12.sp), color = when (chat.status) { "running" -> p.success; "waiting" -> p.askGo; "failed" -> p.error; else -> p.muted })
                if (chat.kind == "subagent") Text(" · 子智能体", style = MaterialTheme.typography.bodySmall.copy(fontSize = 12.sp), color = p.muted)
            }
        }
    }
}

/** No rows: say which filters apply, offer 清除筛选 and 新建对话 (spec 8.2). */
@Composable
private fun EmptyList(s: ReaderState, vm: ReaderViewModel, searching: Boolean, clearQuery: () -> Unit) {
    val p = LocalTeleply.current
    val filtered = searching || s.listSource != "all" || s.listStatus != "all"
    // None of the desktop apps on this computer (web NO_APPS): say so, with 重试, instead of an empty list.
    if (s.knownApps()?.isEmpty() == true) {
        Column(Modifier.fillMaxWidth().padding(vertical = 32.dp), horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Text("这台电脑上没有找到桌面应用", style = MaterialTheme.typography.titleMedium, color = p.text)
            Text("没找到 Codex、Claude 或 DeepSeek 桌面版。装好后点重试；也可以在电脑的 remote_config.json 里用 \"apps\" 指定。", style = MaterialTheme.typography.note, color = p.muted)
            PillButton("重试", vm::retrySources)
        }
        return
    }
    Column(Modifier.fillMaxWidth().padding(vertical = 32.dp), horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(10.dp)) {
        Text(if (s.error == null) "没有找到对话" else "暂时无法读取对话", style = MaterialTheme.typography.titleMedium, color = p.text)
        val conditions = buildList {
            if (s.listSource != "all") add("来源：${sourceName(s.listSource)}")
            if (s.listStatus != "all") add("状态：" + mapOf("running" to "运行中", "waiting" to "等待处理", "done" to "已结束")[s.listStatus].orEmpty())
            if (searching) add("搜索：${s.query}")
        }
        if (conditions.isNotEmpty()) Text("当前条件：" + conditions.joinToString("，"), style = MaterialTheme.typography.note, color = p.muted)
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            if (filtered) PillButton("清除筛选", { clearQuery(); vm.clearListFilters() })
            if (s.device != null) PillButton("新建对话", { vm.startNew(if (s.listSource == "all") s.app else s.listSource) }, style = PillStyle.Primary)
        }
    }
}

// Sidebar (spec 4.2): in DrawerUi.kt since 0.9. Folds of the list and the sidebar are kept here.
internal const val FoldPrefs = "teleply_ui"
