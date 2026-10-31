package com.pocketagentdesk.teleply

import android.content.Intent
import android.net.Uri
import android.os.Build
import androidx.compose.animation.animateColorAsState
import androidx.compose.animation.core.Animatable
import androidx.compose.animation.core.CubicBezierEasing
import androidx.compose.animation.core.animateDpAsState
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.tween
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.interaction.collectIsPressedAsState
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.focus.onFocusChanged
import androidx.compose.ui.graphics.BlurEffect
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.graphics.TileMode
import androidx.compose.ui.graphics.TransformOrigin
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.max
import androidx.compose.ui.unit.sp
import kotlinx.coroutines.delay

/*
 * The opening pages as the web's account page (0.9, relay_account.html/.css/.js): the Teleply mark and name, then 登录
 * with only the account and password (the service is the default one, deploy/relay), or 我的电脑 once signed in. Their
 * parts rise into place one after another, fields lift their label and light up when typed in, the button gives a
 * little under the finger and spins while it waits.
 */

/** relay_account.css :root and its dark theme (static/theme.css). */
@Immutable
data class AccountColors(val page: Color, val ink: Color, val onInk: Color, val soft: Color, val muted: Color, val danger: Color, val edge: Color, val online: Color)

@Composable
fun accountColors(): AccountColors {
    val p = LocalTeleply.current
    return if (p.dark) AccountColors(Color.Black, Color(0xFFEEEEEE), Color(0xFF111113), Color(0xFF1E1E1E), Color(0xFFA8A8A8), Color(0xFFFF9A9A), Color(0xFF767676), Color(0xFF66D997))
    else AccountColors(Color.White, Color(0xFF111113), Color.White, Color(0xFFF4F4F6), Color(0xFF86868B), Color(0xFFC4352D), Color.Transparent, Color(0xFF34A76D))
}

/** --ease: cubic-bezier(.2,.8,.2,1). */
private val AccountEase = CubicBezierEasing(0.2f, 0.8f, 0.2f, 1f)

/** True when the system's animations are off (developer options or accessibility): parts then just appear. */
@Composable
fun rememberReducedMotion(): Boolean {
    val context = LocalContext.current
    return remember(context) { runCatching { android.provider.Settings.Global.getFloat(context.contentResolver, android.provider.Settings.Global.ANIMATOR_DURATION_SCALE, 1f) == 0f }.getOrDefault(false) }
}

/**
 * The account page's entrance (.rise): 14dp up out of a 6dp blur over 700 ms, [index] × 70 ms after the first. A new
 * [key] plays it again (a form switched, a computer added).
 */
@Composable
fun Rise(index: Int, modifier: Modifier = Modifier, key: Any? = Unit, content: @Composable () -> Unit) {
    val still = rememberReducedMotion()
    val progress = remember(key) { Animatable(if (still) 1f else 0f) }
    LaunchedEffect(key) { if (progress.value < 1f) { delay(index * 70L); progress.animateTo(1f, tween(700, easing = AccountEase)) } }
    Box(modifier.graphicsLayer {
        val left = 1f - progress.value
        alpha = progress.value
        translationY = left * 14.dp.toPx()
        renderEffect = if (left > 0.01f && Build.VERSION.SDK_INT >= 31) BlurEffect(6.dp.toPx() * left, 6.dp.toPx() * left, TileMode.Decal) else null
    }) { content() }
}

/** The mark and Teleply: centred above 登录, larger and to the left on 我的电脑 (web .brand). */
@Composable
fun BrandHeader(home: Boolean, modifier: Modifier = Modifier) {
    val c = accountColors()
    Row(modifier.semantics(mergeDescendants = true) { heading() }, verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(if (home) 12.dp else 10.dp)) {
        TeleplyLogo(width = if (home) 36.dp else 30.dp)
        Text(
            "Teleply",
            style = MaterialTheme.typography.titleMedium.copy(fontSize = if (home) 26.sp else 17.sp, lineHeight = if (home) 31.sp else 22.sp, fontWeight = if (home) FontWeight(650) else FontWeight.SemiBold, letterSpacing = if (home) (-0.7).sp else (-0.3).sp),
            color = c.ink,
        )
    }
}

/** While the app opens: only the mark and the name, where 登录 will keep them (web: nothing shows until it knows). */
@Composable
fun LaunchPage() {
    val c = accountColors()
    BoxWithConstraints(Modifier.fillMaxSize().background(c.page)) {
        Column(Modifier.fillMaxWidth().windowInsetsPadding(WindowInsets.safeDrawing).padding(top = max(48.dp, maxHeight * 0.11f)), horizontalAlignment = Alignment.CenterHorizontally) {
            Rise(0) { BrandHeader(home = false) }
        }
    }
}

/**
 * A field with its label inside that lifts and shrinks when typed in (web .field): 60dp, 18dp corners, grey; white with
 * a soft shadow while typed in. The password field has 显示／隐藏 at its end.
 */
@Composable
fun AccountField(
    value: String,
    onValue: (String) -> Unit,
    label: String,
    modifier: Modifier = Modifier,
    password: Boolean = false,
    keyboardType: KeyboardType = KeyboardType.Text,
    imeAction: ImeAction = ImeAction.Next,
    onDone: () -> Unit = {},
) {
    val c = accountColors()
    val p = LocalTeleply.current
    var focused by remember { mutableStateOf(false) }
    var shown by rememberSaveable { mutableStateOf(false) }
    val lift by animateFloatAsState(if (focused || value.isNotEmpty()) 1f else 0f, tween(300, easing = AccountEase), label = "label-lift")
    val fill by animateColorAsState(if (focused && !p.dark) Color.White else c.soft, tween(300, easing = AccountEase), label = "field-fill")
    val raise by animateDpAsState(if (focused && !p.dark) 12.dp else 0.dp, tween(350, easing = AccountEase), label = "field-shadow")
    val labelColor by animateColorAsState(if (focused) c.ink else c.muted, tween(300, easing = AccountEase), label = "label-colour")
    val shape = RoundedCornerShape(18.dp)
    Box(
        modifier.fillMaxWidth().height(60.dp)
            .shadow(raise, shape, ambientColor = Color.Black.copy(alpha = 0.08f), spotColor = Color.Black.copy(alpha = 0.24f))
            .clip(shape).background(fill)
            .then(if (p.dark) Modifier.border(1.dp, c.edge, shape) else Modifier),
    ) {
        Text(
            label,
            style = MaterialTheme.typography.bodyLarge.copy(fontSize = 16.sp, lineHeight = 22.sp),
            color = labelColor,
            modifier = Modifier.padding(start = 18.dp, top = 19.dp).graphicsLayer {
                transformOrigin = TransformOrigin(0f, 0f)
                val scale = 1f - 0.25f * lift
                scaleX = scale; scaleY = scale
                translationY = -11.dp.toPx() * lift
            },
        )
        BasicTextField(
            value,
            onValue,
            Modifier.fillMaxSize().padding(start = 18.dp, end = if (password) 72.dp else 18.dp, top = 25.dp, bottom = 9.dp)
                .onFocusChanged { focused = it.isFocused }.semantics { contentDescription = label },
            singleLine = true,
            textStyle = MaterialTheme.typography.bodyLarge.copy(fontSize = 16.sp, color = c.ink),
            cursorBrush = SolidColor(c.ink),
            visualTransformation = if (password && !shown) PasswordVisualTransformation() else VisualTransformation.None,
            keyboardOptions = KeyboardOptions(keyboardType = if (password) KeyboardType.Password else keyboardType, imeAction = imeAction, autoCorrectEnabled = false),
            keyboardActions = KeyboardActions(onDone = { onDone() }, onGo = { onDone() }),
        )
        if (password) Text(
            if (shown) "隐藏" else "显示",
            style = MaterialTheme.typography.bodySmall.copy(fontSize = 13.sp),
            color = c.muted,
            modifier = Modifier.align(Alignment.CenterEnd).padding(end = 8.dp).clip(RoundedCornerShape(12.dp))
                .clickable(role = Role.Button) { shown = !shown }
                .semantics { contentDescription = if (shown) "隐藏密码" else "显示密码" }
                .padding(horizontal = 12.dp, vertical = 12.dp),
        )
    }
}

/** The page's one strong button (web .primary): ink, 56dp, 18dp corners, a shadow; gives to 0.98 when pressed, spins while busy. */
@Composable
fun AccountButton(text: String, onClick: () -> Unit, modifier: Modifier = Modifier, busy: Boolean = false, enabled: Boolean = true) {
    val c = accountColors()
    val p = LocalTeleply.current
    val interaction = remember { MutableInteractionSource() }
    val pressed by interaction.collectIsPressedAsState()
    val scale by animateFloatAsState(if (pressed) 0.98f else 1f, tween(250, easing = AccountEase), label = "press")
    val raise by animateDpAsState(if (p.dark || !enabled) 0.dp else if (pressed) 6.dp else 14.dp, tween(300, easing = AccountEase), label = "button-shadow")
    val shape = RoundedCornerShape(18.dp)
    Box(
        modifier.fillMaxWidth().height(56.dp).graphicsLayer { scaleX = scale; scaleY = scale }
            .shadow(raise, shape, ambientColor = Color.Black.copy(alpha = 0.1f), spotColor = Color.Black.copy(alpha = 0.5f))
            .clip(shape).background(c.ink.copy(alpha = if (enabled || busy) 1f else 0.45f))
            .clickable(interaction, indication = null, enabled = enabled && !busy, role = Role.Button, onClick = onClick),
        contentAlignment = Alignment.Center,
    ) {
        if (busy) CircularProgressIndicator(Modifier.size(18.dp).semantics { contentDescription = "$text，请稍候" }, color = c.onInk, strokeWidth = 2.dp, trackColor = c.onInk.copy(alpha = 0.3f))
        else Text(text, style = MaterialTheme.typography.labelLarge.copy(fontSize = 16.sp, fontWeight = FontWeight.SemiBold, letterSpacing = 0.2.sp), color = c.onInk)
    }
}

/** A small grey button under the form (web .text-button). */
@Composable
private fun AccountTextButton(text: String, onClick: () -> Unit) {
    val c = accountColors()
    Text(text, style = MaterialTheme.typography.bodyMedium.copy(fontSize = 14.sp), color = c.muted,
        modifier = Modifier.clip(RoundedCornerShape(12.dp)).clickable(role = Role.Button, onClick = onClick).padding(horizontal = 12.dp, vertical = 10.dp))
}

/** The line under a page (web #message): errors in red; a change comes up out of a blur. */
@Composable
private fun AccountMessage(text: String?, error: Boolean, action: String? = null, onAction: () -> Unit = {}) {
    val c = accountColors()
    if (text.isNullOrBlank()) return
    Rise(0, Modifier.fillMaxWidth().padding(top = 24.dp), key = text) {
        Column(Modifier.fillMaxWidth(), horizontalAlignment = Alignment.CenterHorizontally) {
            Text(text, style = MaterialTheme.typography.bodyMedium.copy(fontSize = 14.sp, lineHeight = 24.sp), color = if (error) c.danger else c.muted, textAlign = TextAlign.Center,
                modifier = Modifier.padding(horizontal = 8.dp).semantics { liveRegion = LiveRegionMode.Polite })
            if (action != null) AccountTextButton(action, onAction)
        }
    }
}

/**
 * 登录 (web #auth): the mark and name, 登录, 邮箱或账号, 密码 and the button; the service is the default one, so there is
 * nothing else to fill in. The gear opens 设置 (服务地址 and 本地示例 are under its 开发者选项).
 */
@Composable
fun LoginPage(s: ReaderState, vm: ReaderViewModel) {
    val c = accountColors()
    val context = LocalContext.current
    var name by rememberSaveable(s.origin) { mutableStateOf("") }
    var password by remember { mutableStateOf("") } // never saved
    DisposableEffect(Unit) { onDispose { password = "" } }
    val ready = s.fixture || name.isNotBlank() && password.isNotBlank()
    val submit = { if (ready && !s.busy) { val typed = password; password = ""; vm.login(if (s.fixture) "fixture" else name, if (s.fixture) "fixture" else typed) } }
    BoxWithConstraints(Modifier.fillMaxSize().background(c.page)) {
        val top = max(48.dp, maxHeight * 0.11f)
        Column(
            Modifier.fillMaxSize().verticalScroll(rememberScrollState()).imePadding().windowInsetsPadding(WindowInsets.safeDrawing).padding(horizontal = 24.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            Column(Modifier.widthIn(max = 380.dp).fillMaxWidth().padding(top = top, bottom = 32.dp)) {
                Rise(0, Modifier.fillMaxWidth()) { BrandHeader(home = false, Modifier.fillMaxWidth().wrapContentWidth()) }
                Spacer(Modifier.height(44.dp))
                Rise(1, key = s.fixture) {
                    Text(if (s.fixture) "本地示例" else "登录", style = MaterialTheme.typography.headlineMedium.copy(fontSize = 30.sp, lineHeight = 38.sp, fontWeight = FontWeight.SemiBold, letterSpacing = (-0.8).sp), color = c.ink, modifier = Modifier.semantics { heading() })
                }
                Spacer(Modifier.height(30.dp))
                if (s.fixture) {
                    Rise(2, key = s.fixture) { Text("示例无需真实账号或密码，数据都是固定的，不连接真实服务。", style = MaterialTheme.typography.bodyLarge.copy(fontSize = 15.sp, lineHeight = 24.sp), color = c.muted) }
                } else {
                    Rise(2) { AccountField(name, { name = it }, "邮箱或账号", keyboardType = KeyboardType.Email) }
                    Spacer(Modifier.height(12.dp))
                    Rise(3) { AccountField(password, { password = it }, "密码", password = true, imeAction = ImeAction.Go, onDone = submit) }
                }
                Spacer(Modifier.height(22.dp))
                Rise(4, key = s.fixture) { AccountButton(if (s.fixture) "进入示例" else "登录", submit, busy = s.busy && s.screen == Screen.Login, enabled = ready) }
                Rise(5, Modifier.fillMaxWidth().padding(top = 16.dp), key = s.fixture) {
                    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.Center) {
                        when {
                            s.fixture -> AccountTextButton("返回登录") { vm.back() }
                            // Signing up and resetting by email belong to the web page; the phone hands over to it.
                            s.emailEnabled -> {
                                AccountTextButton("忘记密码？") { openAccountPage(context, s.origin) }
                                Spacer(Modifier.width(28.dp))
                                AccountTextButton("创建账号") { openAccountPage(context, s.origin) }
                            }
                            else -> Text("暂未开放注册", style = MaterialTheme.typography.bodyMedium.copy(fontSize = 14.sp), color = Color(0xFFB4B4B9), modifier = Modifier.padding(horizontal = 12.dp, vertical = 10.dp))
                        }
                    }
                }
                val offline = s.error?.startsWith("连不上服务器") == true && s.account == null
                AccountMessage(
                    s.error ?: s.accountNote ?: if (s.expired) "登录已失效，请重新登录；回到原来的位置。" else null,
                    error = s.error != null,
                    action = if (offline) "重试" else null,
                    onAction = vm::retry,
                )
            }
        }
        // 设置 only (0.9): the service address and the local demo are under 设置 → 开发者选项.
        if (!s.fixture) Box(Modifier.align(Alignment.TopEnd).windowInsetsPadding(WindowInsets.safeDrawing).padding(8.dp)) {
            TeleplyIconButton(TeleplyIcons.Settings, "设置", vm::settings, style = IconButtonStyle.Plain, tint = c.muted)
        }
    }
}

private fun openAccountPage(context: android.content.Context, origin: String) = openInBrowser(context, origin.removeSuffix("/") + "/account")

/** A web page in the phone's browser (登录's 忘记密码？ and 创建账号, 设置's 隐私政策); nothing happens when there is none. */
fun openInBrowser(context: android.content.Context, url: String) {
    runCatching { context.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url)).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) }
}

/**
 * 删除账号 (设置 → 账号; the web account menu's dialog): what goes and what stays, the password again, 取消 and 删除. A
 * sheet in the page's own window, as 管理电脑, so the field types like every other one. When the service turns the
 * password down or asks to wait, its words show under the field and the sheet stays; done, the app is on 登录.
 */
@Composable
fun DeleteAccountSheet(s: ReaderState, vm: ReaderViewModel, onDismiss: () -> Unit) {
    val p = LocalTeleply.current
    var password by remember { mutableStateOf("") } // never saved
    var refused by remember { mutableStateOf<String?>(null) }
    val delete = { if (password.isNotEmpty() && !s.busy) { refused = null; vm.deleteAccount(password) { refused = it } } }
    TeleplySheet("删除账号？", onDismiss) {
        if (s.busy) LinearProgressIndicator(Modifier.fillMaxWidth().height(2.dp), color = p.accent, trackColor = p.line)
        Text("账号、关联的邮箱、绑定的电脑和通知设置都会删除，不能恢复。电脑上的文件和对话不受影响。", style = MaterialTheme.typography.bodyMedium.copy(fontSize = 14.sp, lineHeight = 22.sp), color = p.muted)
        AccountField(password, { password = it }, "当前密码", password = true, imeAction = ImeAction.Done, onDone = delete)
        refused?.let { Text(it, Modifier.semantics { liveRegion = LiveRegionMode.Polite }, style = MaterialTheme.typography.note, color = p.error) }
        Row(Modifier.fillMaxWidth().padding(top = 8.dp), horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            PillButton("取消", onDismiss, modifier = Modifier.weight(1f))
            PillButton("删除", delete, style = PillStyle.Danger, enabled = password.isNotEmpty() && !s.busy, modifier = Modifier.weight(1f))
        }
    }
}

/**
 * 我的电脑 (web #signed): the mark and name on the left, then the computers, each with 在线 or 离线, 连接 and ⋯ (重命名,
 * 移除). The heading's ⋯ has 刷新, 设置 and 退出登录. Read again every 15 s while shown.
 */
@Composable
fun DevicesPage(s: ReaderState, vm: ReaderViewModel) {
    val c = accountColors()
    val menus = LocalMenuHost.current
    val head = remember { MenuAnchor() }
    var renaming by remember { mutableStateOf<Computer?>(null) }
    var removing by remember { mutableStateOf<Computer?>(null) }
    var connecting by remember { mutableStateOf<String?>(null) }
    LaunchedEffect(s.busy) { if (!s.busy) connecting = null }
    val devices = s.account?.devices.orEmpty()
    Column(
        Modifier.fillMaxSize().background(c.page).verticalScroll(rememberScrollState())
            .windowInsetsPadding(WindowInsets.safeDrawing).padding(start = 24.dp, end = 24.dp, top = 28.dp, bottom = 32.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Column(Modifier.widthIn(max = 440.dp).fillMaxWidth()) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                if (s.device != null) TeleplyIconButton(TeleplyIcons.Back, "返回", vm::back, style = IconButtonStyle.Plain, tint = c.ink)
                Rise(0) { BrandHeader(home = true) }
            }
            if (s.fixture) Text("本地示例 · 固定数据 · 未连接真实服务", style = MaterialTheme.typography.bodySmall.copy(fontSize = 13.sp), color = c.muted, modifier = Modifier.padding(top = 8.dp))
            Spacer(Modifier.height(32.dp))
            Rise(1) {
                Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                    Text("我的电脑", style = MaterialTheme.typography.titleLarge.copy(fontSize = 24.sp, lineHeight = 30.sp, fontWeight = FontWeight.SemiBold, letterSpacing = (-0.5).sp), color = c.ink, modifier = Modifier.weight(1f).semantics { heading() })
                    TeleplyIconButton(TeleplyIcons.More, "账号菜单", {
                        menus?.show(MenuRequest(head.bounds, MenuPlacement.BelowEnd, "账号菜单", width = 240.dp) {
                            MenuRow("刷新", vm::computers, icon = TeleplyIcons.Refresh)
                            MenuRow("设置", vm::settings, icon = TeleplyIcons.Settings)
                            MenuRow("退出登录", vm::logout, icon = TeleplyIcons.Logout, danger = true)
                        })
                    }, modifier = Modifier.menuAnchor(head), style = IconButtonStyle.Plain, tint = c.ink)
                }
            }
            Spacer(Modifier.height(20.dp))
            devices.forEachIndexed { index, device ->
                Rise(2 + index.coerceAtMost(8), Modifier.padding(bottom = 10.dp), key = device.id) {
                    DeviceRow(device, current = device.id == s.device?.id, busy = connecting == device.id && s.busy,
                        onConnect = { connecting = device.id; vm.select(device) }, onRename = { renaming = device }, onRemove = { removing = device })
                }
            }
            if (devices.isEmpty() && !s.busy) Text("暂无电脑", style = MaterialTheme.typography.bodyLarge.copy(fontSize = 15.sp), color = c.muted, textAlign = TextAlign.Center, modifier = Modifier.fillMaxWidth().padding(vertical = 28.dp))
            AccountMessage(s.error, error = true)
        }
    }
    // 管理电脑 (web dialog): a sheet in the page's own window, so the field types like every other one.
    renaming?.let { device ->
        var label by remember(device.id) { mutableStateOf(device.label) }
        val save = { if (label.isNotBlank()) { renaming = null; vm.renameDevice(device, label) } }
        TeleplySheet("管理电脑", { renaming = null }) {
            AccountField(label, { label = it }, "电脑名称", imeAction = ImeAction.Done, onDone = save)
            Row(Modifier.fillMaxWidth().padding(top = 8.dp), horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                PillButton("取消", { renaming = null }, modifier = Modifier.weight(1f))
                PillButton("确定", save, style = PillStyle.Primary, enabled = label.isNotBlank(), modifier = Modifier.weight(1f))
            }
        }
    }
    removing?.let { device ->
        AlertDialog(
            onDismissRequest = { removing = null },
            title = { Text("移除这台电脑？") },
            text = { Text("撤销「${device.label}」的远程访问，不删除电脑上的文件。") },
            confirmButton = { TextButton({ removing = null; vm.removeDevice(device) }) { Text("移除", color = c.danger) } },
            dismissButton = { TextButton({ removing = null }) { Text("取消") } },
        )
    }
}

/** One computer (web #devices li): its name, 在线 with a green dot or 离线, 连接 (or a greyed 离线) and ⋯. */
@Composable
private fun DeviceRow(device: Computer, current: Boolean, busy: Boolean, onConnect: () -> Unit, onRename: () -> Unit, onRemove: () -> Unit) {
    val c = accountColors()
    val menus = LocalMenuHost.current
    val anchor = remember { MenuAnchor() }
    val online = device.connectable
    Row(
        Modifier.fillMaxWidth().clip(RoundedCornerShape(22.dp)).background(c.soft)
            .clickable(enabled = online && !busy, role = Role.Button, onClick = onConnect)
            .padding(start = 20.dp, end = 8.dp, top = 14.dp, bottom = 14.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        Column(Modifier.weight(1f)) {
            Text(device.label, style = MaterialTheme.typography.bodyLarge.copy(fontSize = 16.sp, fontWeight = FontWeight.SemiBold), color = c.ink, maxLines = 2, overflow = TextOverflow.Ellipsis)
            Row(Modifier.padding(top = 4.dp), verticalAlignment = Alignment.CenterVertically) {
                if (online) { Box(Modifier.size(7.dp).clip(CircleShape).background(c.online)); Spacer(Modifier.width(7.dp)) }
                Text((if (online) "在线" else "离线") + if (current) " · 当前" else "", style = MaterialTheme.typography.bodySmall.copy(fontSize = 13.sp), color = c.muted)
            }
        }
        val interaction = remember { MutableInteractionSource() }
        Box(
            Modifier.heightIn(min = 40.dp).pressScale(interaction).clip(CircleShape)
                .then(if (online) Modifier.background(c.ink) else Modifier.background(c.soft).border(1.dp, LocalTeleply.current.line, CircleShape))
                .clickable(interaction, indication = null, enabled = online && !busy, role = Role.Button, onClick = onConnect)
                .semantics { contentDescription = if (online) "连接${device.label}" else "${device.label}离线" }
                .padding(horizontal = 18.dp, vertical = 10.dp),
            contentAlignment = Alignment.Center,
        ) {
            if (busy) CircularProgressIndicator(Modifier.size(16.dp), color = c.onInk, strokeWidth = 2.dp, trackColor = c.onInk.copy(alpha = 0.3f))
            else Text(if (online) "连接" else "离线", style = MaterialTheme.typography.labelLarge.copy(fontSize = 14.sp, fontWeight = FontWeight.Medium), color = if (online) c.onInk else c.muted)
        }
        TeleplyIconButton(TeleplyIcons.More, "管理电脑", {
            menus?.show(MenuRequest(anchor.bounds, MenuPlacement.BelowEnd, "电脑操作", width = 200.dp) {
                MenuRow("重命名", onRename, icon = TeleplyIcons.Pencil)
                MenuRow("移除", onRemove, icon = TeleplyIcons.Trash, danger = true)
            })
        }, modifier = Modifier.menuAnchor(anchor), style = IconButtonStyle.Plain, tint = c.ink)
    }
}
