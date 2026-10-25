package com.pocketagentdesk.teleply

import android.content.Context
import androidx.compose.animation.core.Animatable
import androidx.compose.animation.core.CubicBezierEasing
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.spring
import androidx.compose.animation.core.tween
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyItemScope
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.clearAndSetSemantics
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.semantics.stateDescription
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.IntOffset
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlinx.coroutines.delay
import org.json.JSONObject

/*
 * The sidebar (spec 4.2, 0.9 as the web's static/sidebar-ui.js): each source behind its own mark, its projects behind
 * the rounded folder (其他对话 behind a speech bubble) with ＋ and a chevron that turns, the conversations indented with a
 * breathing dot while they run. Opening the drawer brings the sources in one after another; folding grows and fades.
 */

/** The one spring of the drawer and the chat (web E = cubic-bezier(.32,.72,0,1)). */
private val DrawerEase = CubicBezierEasing(0.32f, 0.72f, 0f, 1f)

@Composable
fun WorkspaceDrawer(s: ReaderState, vm: ReaderViewModel, onClose: () -> Unit, width: Dp, opening: Boolean = false) {
    val p = LocalTeleply.current
    val context = LocalContext.current
    var folds by remember { mutableStateOf(context.getSharedPreferences(FoldPrefs, Context.MODE_PRIVATE).getStringSet("folds", emptySet()).orEmpty()) }
    fun toggle(key: String) {
        folds = if (key in folds) folds - key else folds + key
        context.getSharedPreferences(FoldPrefs, Context.MODE_PRIVATE).edit().putStringSet("folds", folds).apply()
    }
    // Each opening plays the sources' arrival again (web lbrRowIn).
    var serial by remember { mutableIntStateOf(0) }
    LaunchedEffect(opening) { if (opening) serial++ }
    val tree = remember(s.tree) { runCatching { JSONObject(s.tree) }.getOrDefault(JSONObject()) }
    Column(Modifier.width(width).fillMaxSize().testTag("sidebar").windowInsetsPadding(WindowInsets.safeDrawing.only(WindowInsetsSides.Vertical + WindowInsetsSides.Start))) {
        Row(Modifier.fillMaxWidth().padding(start = 20.dp, end = 12.dp, top = 8.dp, bottom = 4.dp), verticalAlignment = Alignment.CenterVertically) {
            Text("电脑遥控", style = MaterialTheme.typography.sheetTitle, color = p.text, modifier = Modifier.weight(1f).semantics { heading() })
            TeleplyIconButton(TeleplyIcons.Close, "关闭导航", onClose)
        }
        LazyColumn(Modifier.weight(1f).fillMaxWidth().testTag("sidebar-tree"), contentPadding = PaddingValues(start = 8.dp, end = 8.dp, bottom = 12.dp)) {
            s.treeError?.let { error -> item(key = "error") { NoteBar(error, NoteTone.Error, Modifier.clip(TeleplyShape.Card), action = "重试", onAction = vm::retrySources) } }
            val apps = tree.rows("apps") { it }
            if (apps.isEmpty() && s.treeError == null) item(key = "loading") { Text(if (s.device == null) "先选择一台电脑" else "读取中…", style = MaterialTheme.typography.note, color = p.muted, modifier = Modifier.padding(12.dp)) }
            apps.forEachIndexed { n, group ->
                val app = group.string("app")
                val appKey = "app:$app"
                val appOpen = appKey !in folds
                item(key = appKey) {
                    Arrive(n + 1, serial, Modifier.drawerItem(this)) { TreeApp(app, group.string("name").ifBlank { sourceName(app) }, appOpen) { toggle(appKey) } }
                }
                if (appOpen) {
                    val projects = group.rows("projects") { it }
                    if (projects.isEmpty()) item(key = "$appKey:none") { Text("没有对话", style = MaterialTheme.typography.note, color = p.muted, modifier = Modifier.drawerItem(this).padding(start = 12.dp, top = 8.dp, bottom = 8.dp)) }
                    projects.forEach { project ->
                        // Sources start open, projects folded (web sidebar): a project is kept open once opened.
                        val key = "project:$app:${project.string("key")}"
                        val open = "open:$key" in folds
                        val name = project.string("name")
                        val projectless = project.optBoolean("projectless")
                        item(key = key) {
                            TreeProject(name, projectless, open, Modifier.drawerItem(this), onAdd = if (project.string("folder").isNotBlank() || projectless) ({
                                onClose()
                                vm.startNew(app, if (projectless) "" else project.string("folder"), projectless)
                            }) else null, addLabel = if (projectless) "新建不在项目里的${sourceName(app)}对话" else "在「$name」新建对话") { toggle("open:$key") }
                        }
                        if (open) {
                            val items = project.rows("items") { it }
                            items.forEach { row ->
                                val chat = Chat(row.string("id"), row.string("title").ifBlank { "未命名对话" }, row.string("folder"), "", row.string("status"), row.string("app").ifBlank { app }, row.optLong("updated"))
                                item(key = "$key:${chat.id}") {
                                    TreeChat(chat, row.string("place"), chat.id == s.chat?.id && chat.app == s.app, Modifier.drawerItem(this)) { onClose(); vm.open(chat) }
                                }
                            }
                            val left = project.optInt("count") - items.size
                            if (left > 0) item(key = "$key:more") {
                                Text(
                                    "显示更多（还有 $left 个）",
                                    style = MaterialTheme.typography.note,
                                    color = p.accent,
                                    modifier = Modifier.drawerItem(this).fillMaxWidth().heightIn(min = 40.dp).clip(RoundedCornerShape(12.dp))
                                        .clickable(role = Role.Button) { vm.moreTree(app, project.string("key")) }.padding(start = 43.dp, top = 10.dp, bottom = 10.dp),
                                )
                            }
                        }
                    }
                }
            }
        }
        Row(Modifier.fillMaxWidth().padding(start = 20.dp, end = 12.dp, top = 4.dp, bottom = 8.dp), verticalAlignment = Alignment.CenterVertically) {
            val (dot, text) = when {
                s.fixture -> p.amber to "本地示例，未连接真实服务"
                s.expired -> p.error to "登录已失效"
                s.device == null -> p.muted to "没有选择电脑"
                s.error != null -> p.amber to "${s.device.label} · 连接有问题"
                else -> p.success to "${s.device.label} · 已连接"
            }
            Box(Modifier.size(10.dp).clip(CircleShape).background(dot))
            Spacer(Modifier.width(10.dp))
            Text(text, style = MaterialTheme.typography.note, color = p.muted, modifier = Modifier.weight(1f), maxLines = 2)
            TeleplyIconButton(TeleplyIcons.Settings, "设置", { onClose(); vm.settings() })
        }
    }
}

/** Rows that come and go as groups fold fade in or out while the rows below slide along (web .tree-kids). */
private fun Modifier.drawerItem(scope: LazyItemScope): Modifier = with(scope) {
    animateItem(fadeInSpec = tween(200), placementSpec = spring<IntOffset>(dampingRatio = 0.9f, stiffness = 500f), fadeOutSpec = tween(120))
}

/** A source arriving as the drawer opens (web lbrRowIn): 10dp from the left, 300 ms, 24 ms after the one above. */
@Composable
private fun Arrive(index: Int, serial: Int, modifier: Modifier = Modifier, content: @Composable () -> Unit) {
    val still = rememberReducedMotion()
    val progress = remember { Animatable(1f) }
    LaunchedEffect(serial) {
        if (serial > 0 && !still) { progress.snapTo(0f); delay(20L + index * 24L); progress.animateTo(1f, tween(300, easing = DrawerEase)) }
    }
    Box(modifier.graphicsLayer { alpha = progress.value; translationX = (1f - progress.value) * -10.dp.toPx() }) { content() }
}

/** The chevron of a group: points right when shut, turns down as it opens (web .tree-chev, 340 ms). */
@Composable
private fun Chevron(open: Boolean) {
    val p = LocalTeleply.current
    val turn by animateFloatAsState(if (open) 90f else 0f, tween(340, easing = DrawerEase), label = "chevron")
    Icon(TeleplyIcons.ChevronRight, contentDescription = null, tint = p.muted, modifier = Modifier.size(16.dp).graphicsLayer { rotationZ = turn })
}

/** A source (web .tree-app): its mark, its name, the chevron; a tap folds it. */
@Composable
private fun TreeApp(app: String, name: String, open: Boolean, onToggle: () -> Unit) {
    val p = LocalTeleply.current
    Row(
        Modifier.fillMaxWidth().padding(top = 12.dp).heightIn(min = 42.dp).clip(RoundedCornerShape(12.dp))
            .clickable(role = Role.Button, onClick = onToggle)
            .semantics { stateDescription = if (open) "已展开" else "已收起" }
            .padding(start = 12.dp, end = 12.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(9.dp),
    ) {
        SourceMark(app)
        Text(name, style = MaterialTheme.typography.bodyMedium.copy(fontSize = 14.sp, fontWeight = FontWeight.SemiBold), color = p.text, maxLines = 1, overflow = TextOverflow.Ellipsis, modifier = Modifier.weight(1f))
        Chevron(open)
    }
}

/** A project (web .tree-proj): the rounded folder (or the bubble of 其他对话), its name, ＋ for a new conversation there, the chevron. */
@Composable
private fun TreeProject(name: String, projectless: Boolean, open: Boolean, modifier: Modifier, onAdd: (() -> Unit)?, addLabel: String, onToggle: () -> Unit) {
    val p = LocalTeleply.current
    Row(
        modifier.fillMaxWidth().heightIn(min = 44.dp).clip(RoundedCornerShape(12.dp))
            .clickable(role = Role.Button, onClick = onToggle)
            .semantics { stateDescription = if (open) "已展开" else "已收起" }
            .padding(start = 12.dp, end = 12.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(9.dp),
    ) {
        Icon(if (projectless) TeleplyIcons.Loose else TeleplyIcons.Project, contentDescription = null, tint = if (p.dark) p.muted else Color(0xFF606975), modifier = Modifier.size(24.dp))
        Text(name, style = MaterialTheme.typography.bodyLarge.copy(fontSize = 15.sp, fontWeight = FontWeight.Medium), color = p.text, maxLines = 1, overflow = TextOverflow.Ellipsis, modifier = Modifier.weight(1f))
        if (onAdd != null) {
            val interaction = remember { MutableInteractionSource() }
            Box(
                Modifier.size(36.dp).pressScale(interaction, 0.82f).clip(RoundedCornerShape(10.dp))
                    .clickable(interaction, indication = null, role = Role.Button, onClick = onAdd)
                    .semantics { contentDescription = addLabel },
                contentAlignment = Alignment.Center,
            ) { Icon(TeleplyIcons.Plus, contentDescription = null, tint = p.muted, modifier = Modifier.size(18.dp)) }
        }
        Chevron(open)
    }
}

/** A conversation (web .tree-item): indented, a breathing green dot while it runs (amber while it waits), its time. */
@Composable
private fun TreeChat(chat: Chat, place: String, current: Boolean, modifier: Modifier, onClick: () -> Unit) {
    val p = LocalTeleply.current
    Box(
        modifier.fillMaxWidth().heightIn(min = 40.dp).clip(RoundedCornerShape(12.dp))
            .background(if (current) p.selected else Color.Transparent)
            .clickable(role = Role.Button, onClick = onClick),
        contentAlignment = Alignment.CenterStart,
    ) {
        if (chat.status == "running" || chat.status == "waiting") StatusDot(chat.status == "running", Modifier.padding(start = 22.5.dp))
        Row(Modifier.fillMaxWidth().padding(start = 43.dp, end = 12.dp, top = 8.dp, bottom = 8.dp), verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Text(chat.title, style = MaterialTheme.typography.bodyMedium.copy(fontSize = 14.sp), color = if (current) p.onSelected else p.text, maxLines = 1, overflow = TextOverflow.Ellipsis)
                if (place.isNotBlank()) Text(place, style = MaterialTheme.typography.bodySmall.copy(fontSize = 12.sp), color = p.muted, maxLines = 1, overflow = TextOverflow.Ellipsis)
            }
            val ago = agoLabel(chat.updated)
            if (ago.isNotEmpty()) Text(ago, style = MaterialTheme.typography.bodySmall.copy(fontSize = 12.sp, fontFeatureSettings = "tnum"), color = p.muted, maxLines = 1, modifier = Modifier.padding(start = 8.dp))
        }
    }
}

/** 7dp; while running a ring breathes out of it every 1.8 s (web .tree-dot::after lbrPing). */
@Composable
private fun StatusDot(running: Boolean, modifier: Modifier = Modifier) {
    val p = LocalTeleply.current
    val color = if (running) p.success else p.amber
    val still = rememberReducedMotion()
    Box(modifier.size(7.dp).semantics { contentDescription = if (running) "运行中" else "等待你处理" }, contentAlignment = Alignment.Center) {
        if (running && !still) {
            val ping = rememberInfiniteTransition(label = "ping")
            val t by ping.animateFloat(0f, 1f, infiniteRepeatable(tween(1800, easing = DrawerEase), RepeatMode.Restart), label = "ping-t")
            Box(Modifier.size(7.dp).graphicsLayer { scaleX = 1f + 1.8f * t; scaleY = 1f + 1.8f * t; alpha = 0.55f * (1f - t) }.clip(CircleShape).background(color).clearAndSetSemantics { })
        }
        Box(Modifier.size(7.dp).clip(CircleShape).background(color))
    }
}
