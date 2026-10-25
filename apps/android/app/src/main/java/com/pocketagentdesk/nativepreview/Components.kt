package com.pocketagentdesk.nativepreview

import android.os.Build
import androidx.activity.compose.BackHandler
import androidx.compose.animation.core.MutableTransitionState
import androidx.compose.animation.core.Transition
import androidx.compose.animation.core.animateDp
import androidx.compose.animation.core.animateDpAsState
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.keyframes
import androidx.compose.animation.core.rememberTransition
import androidx.compose.animation.core.snap
import androidx.compose.animation.core.spring
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.interaction.InteractionSource
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.interaction.collectIsPressedAsState
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.RowScope
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.WindowInsetsSides
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.only
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawing
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.layout.windowInsetsPadding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.selection.selectable
import androidx.compose.foundation.selection.selectableGroup
import androidx.compose.foundation.selection.toggleable
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Text
import androidx.compose.material3.minimumInteractiveComponentSize
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.Stable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.composed
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.draw.drawWithContent
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Rect
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.BlurEffect
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.ColorFilter
import androidx.compose.ui.graphics.ColorMatrix
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.graphics.TileMode
import androidx.compose.ui.graphics.TransformOrigin
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.drawscope.translate
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.graphics.isSpecified
import androidx.compose.ui.graphics.layer.GraphicsLayer
import androidx.compose.ui.graphics.layer.drawLayer
import androidx.compose.ui.graphics.rememberGraphicsLayer
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.layout.Layout
import androidx.compose.ui.layout.boundsInRoot
import androidx.compose.ui.layout.onGloballyPositioned
import androidx.compose.ui.layout.positionInRoot
import androidx.compose.ui.platform.LocalClipboardManager
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.platform.LocalView
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.clearAndSetSemantics
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.paneTitle
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.semantics.stateDescription
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Constraints
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.IntOffset
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.isSpecified
import androidx.compose.ui.unit.sp
import androidx.compose.ui.unit.toIntSize
import com.pocketagentdesk.nativepreview.glass.layerBackdrop
import com.pocketagentdesk.nativepreview.glass.rememberLayerBackdrop
import kotlin.math.min

/** Press shrinks to 0.97 (web :active, about 100 ms); no scaling when system animations are off. */
fun Modifier.pressScale(interaction: InteractionSource, pressed: Float = 0.97f): Modifier = composed {
    val isPressed by interaction.collectIsPressedAsState()
    val animate = remember { TeleplyMotion.enabled() }
    val scale by animateFloatAsState(if (isPressed && animate) pressed else 1f, tween(100), label = "press")
    graphicsLayer {
        scaleX = scale
        scaleY = scale
    }
}

/** Round: glass circle (title bars, drawer). Solid: the web's solid circle, for the content layer. Plain: no circle. */
enum class IconButtonStyle { Round, Solid, Plain }

/**
 * Navigation icon button: a 44dp glass circle with a 22dp icon and a 48dp touch target (spec 2.4, 2.5). Glass grows
 * a little and lights up under the finger when pressed, like iOS; the solid fallback shrinks to 0.97 like the web.
 * Plain draws no circle: for buttons inside a glass capsule, in panel headers and in rows.
 */
@Composable
fun TeleplyIconButton(
    icon: ImageVector,
    description: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    style: IconButtonStyle = IconButtonStyle.Round,
    enabled: Boolean = true,
    tint: Color = Color.Unspecified,
    disabledReason: String? = null,
    /** Solid fill for the fallback when the button sits on the grey panel, where the button fill would disappear. */
    container: Color = Color.Unspecified,
) {
    val p = LocalTeleply.current
    val interaction = remember { MutableInteractionSource() }
    val round = style == IconButtonStyle.Round
    val liquid = round && LocalGlassMode.current != GlassMode.Solid
    val press = if (liquid) rememberGlassPress(interaction) else null
    val solidFill = if (container.isSpecified) container else p.control
    Box(
        modifier
            .minimumInteractiveComponentSize()
            .size(44.dp)
            .then(if (liquid) Modifier else Modifier.pressScale(interaction))
            .then(
                when (style) {
                    IconButtonStyle.Round -> Modifier.glass(CircleShape, press = press, solid = container)
                    IconButtonStyle.Solid -> Modifier.softShadow(CircleShape, p, TeleplyShadow.Control).background(solidFill, CircleShape)
                        .then(if (p.dark) Modifier.border(1.dp, p.edge, CircleShape) else Modifier)
                    IconButtonStyle.Plain -> Modifier
                },
            )
            .clip(CircleShape)
            .clickable(interaction, indication = null, enabled = enabled, role = Role.Button, onClick = onClick)
            .semantics {
                contentDescription = description
                if (!enabled && disabledReason != null) stateDescription = disabledReason
            },
        contentAlignment = Alignment.Center,
    ) {
        val color = if (tint.isSpecified) tint else p.text
        Icon(icon, contentDescription = null, tint = color.copy(alpha = if (enabled) color.alpha else 0.35f), modifier = Modifier.size(22.dp))
    }
}

enum class PillStyle { Primary, Secondary, Text, Danger }

/** Web capsule buttons: primary is solid accent, secondary a neutral fill, text has no fill; 35% when disabled. */
@Composable
fun PillButton(
    text: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    style: PillStyle = PillStyle.Secondary,
    enabled: Boolean = true,
    leading: ImageVector? = null,
    minHeight: Dp = 44.dp,
    description: String? = null,
) {
    val p = LocalTeleply.current
    val interaction = remember { MutableInteractionSource() }
    val (background, content) = when (style) {
        PillStyle.Primary -> p.accent to p.onAccent
        PillStyle.Secondary -> p.control to p.text
        PillStyle.Text -> Color.Transparent to p.accent
        PillStyle.Danger -> p.stopBg to p.stopText
    }
    Row(
        modifier
            .minimumInteractiveComponentSize()
            .heightIn(min = minHeight)
            .pressScale(interaction)
            .graphicsLayer { alpha = if (enabled) 1f else 0.35f }
            .clip(CircleShape)
            .background(background)
            .clickable(interaction, indication = null, enabled = enabled, role = Role.Button, onClick = onClick)
            .then(if (description != null) Modifier.semantics { contentDescription = description } else Modifier)
            .padding(horizontal = if (style == PillStyle.Text) 10.dp else 16.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.Center,
    ) {
        if (leading != null) {
            Icon(leading, contentDescription = null, tint = content, modifier = Modifier.size(18.dp))
            Spacer(Modifier.width(8.dp))
        }
        Text(text, style = MaterialTheme.typography.labelLarge, color = content, maxLines = 1, overflow = TextOverflow.Ellipsis)
    }
}

/**
 * Tool group: sibling buttons in one glass capsule, like the iOS navigation bar groups them (spec 3, 2.5); the
 * buttons inside use [IconButtonStyle.Plain]. The capsule itself does not react to presses, its buttons do.
 */
@Composable
fun CapsuleToolbar(modifier: Modifier = Modifier, content: @Composable RowScope.() -> Unit) {
    Row(
        modifier
            .glass(CircleShape)
            .padding(horizontal = 2.dp),
        verticalAlignment = Alignment.CenterVertically,
        content = content,
    )
}

/**
 * Small glass capsule with text, e.g. "有新消息 ↓" (spec 4.3). Grows and lights up when pressed, like the round buttons.
 */
@Composable
fun GlassPill(
    text: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    leading: ImageVector? = null,
    description: String? = null,
    tint: Color = Color.Unspecified,
    color: Color = Color.Unspecified,
    enabled: Boolean = true,
) {
    val p = LocalTeleply.current
    val interaction = remember { MutableInteractionSource() }
    val liquid = LocalGlassMode.current != GlassMode.Solid
    val press = if (liquid) rememberGlassPress(interaction) else null
    val ink = if (color.isSpecified) color else p.text
    Row(
        modifier
            .minimumInteractiveComponentSize()
            .heightIn(min = 40.dp)
            .then(if (liquid) Modifier else Modifier.pressScale(interaction))
            .glass(CircleShape, tint = tint, press = press, solid = p.card)
            .clip(CircleShape)
            .clickable(interaction, indication = null, enabled = enabled, role = Role.Button, onClick = onClick)
            .then(if (description != null) Modifier.semantics { contentDescription = description } else Modifier)
            .padding(horizontal = 14.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.Center,
    ) {
        if (leading != null) {
            Icon(leading, contentDescription = null, tint = ink, modifier = Modifier.size(16.dp))
            Spacer(Modifier.width(6.dp))
        }
        Text(text, style = MaterialTheme.typography.labelMedium.copy(fontSize = 13.sp), color = ink.copy(alpha = if (enabled) 1f else 0.45f), maxLines = 1)
    }
}

/** Web segmented choice: one capsule track with a sliding thumb (跟随系统／浅色／深色). */
@Composable
fun <T> SegmentedChoice(options: List<Pair<T, String>>, selected: T, onSelect: (T) -> Unit, modifier: Modifier = Modifier) {
    val p = LocalTeleply.current
    val track = if (p.dark) p.control else Color(0xFFF4F4F6)
    val thumb = if (p.dark) Color(0xFF38383A) else p.card
    val animate = remember { TeleplyMotion.enabled() }
    BoxWithConstraints(modifier.fillMaxWidth().clip(CircleShape).background(track).padding(4.dp)) {
        val segment = maxWidth / options.size
        val index = options.indexOfFirst { it.first == selected }.coerceAtLeast(0)
        val offset by animateDpAsState(segment * index, if (animate) spring(dampingRatio = 0.85f, stiffness = 700f) else snap(), label = "segment")
        Box(
            Modifier.offset(x = offset).width(segment).height(44.dp)
                .softShadow(CircleShape, p, TeleplyShadow.Segment)
                .background(thumb, CircleShape),
        )
        Row(Modifier.fillMaxWidth().selectableGroup()) {
            options.forEach { (value, label) ->
                val isSelected = value == selected
                Box(
                    Modifier.weight(1f).heightIn(min = 44.dp).clip(CircleShape)
                        .selectable(isSelected, role = Role.RadioButton, onClick = { onSelect(value) }),
                    contentAlignment = Alignment.Center,
                ) {
                    Text(label, style = MaterialTheme.typography.labelLarge, color = if (isSelected) p.text else p.muted, maxLines = 1)
                }
            }
        }
    }
}

/**
 * Context usage ring (web .ctx-ring): 26dp, 3dp stroke, the percentage inside; amber from 80%.
 * The number is decorative and does not scale with the font; screen readers get a full sentence.
 */
@Composable
fun ContextRing(percent: Int, onClick: () -> Unit, modifier: Modifier = Modifier) {
    val p = LocalTeleply.current
    val value = percent.coerceIn(0, 100)
    val warn = value >= 80
    val numberSize = with(LocalDensity.current) { 9.dp.toSp() }
    Box(
        modifier
            .minimumInteractiveComponentSize()
            .size(44.dp)
            .clip(CircleShape)
            .clickable(role = Role.Button, onClick = onClick)
            .semantics { contentDescription = "上下文已用约 $value%，查看会话状态" },
        contentAlignment = Alignment.Center,
    ) {
        Canvas(Modifier.size(26.dp)) {
            val stroke = 3.dp.toPx()
            val inset = Offset(stroke / 2, stroke / 2)
            val arc = Size(size.width - stroke, size.height - stroke)
            drawArc(p.line, 0f, 360f, useCenter = false, topLeft = inset, size = arc, style = Stroke(stroke))
            drawArc(if (warn) p.amber else p.muted, -90f, 3.6f * value, useCenter = false, topLeft = inset, size = arc, style = Stroke(stroke))
        }
        Text("$value", style = TextStyle(fontSize = numberSize, lineHeight = numberSize, fontWeight = FontWeight.SemiBold), color = p.muted)
    }
}

/**
 * "停止这一轮" in the title bar, only while running: its own glass capsule tinted light red, red text (web .stop-turn,
 * spec 2.5). The solid fallback is the web's light red capsule.
 */
@Composable
fun StopPill(label: String, enabled: Boolean, disabledReason: String?, onClick: () -> Unit) {
    val p = LocalTeleply.current
    val interaction = remember { MutableInteractionSource() }
    val liquid = LocalGlassMode.current != GlassMode.Solid
    val press = if (liquid) rememberGlassPress(interaction) else null
    Box(
        Modifier
            .minimumInteractiveComponentSize()
            .heightIn(min = 40.dp)
            .then(if (liquid) Modifier else Modifier.pressScale(interaction))
            .glass(CircleShape, tint = p.stopTint, press = press, solid = p.stopBg)
            .clip(CircleShape)
            .clickable(interaction, indication = null, enabled = enabled, role = Role.Button, onClick = onClick)
            .semantics { if (!enabled && disabledReason != null) stateDescription = disabledReason }
            .padding(horizontal = 12.dp),
        contentAlignment = Alignment.Center,
    ) {
        Text(label, style = MaterialTheme.typography.labelMedium, color = p.stopText.copy(alpha = if (enabled) 1f else 0.45f), maxLines = 1)
    }
}

/**
 * Detail page title bar (web .tp-header-title): glass back button, centred title, glass capsule tools on the right.
 * No background of its own inside a [GlassScreen] (the scroll edge keeps the title readable); [solid] gives it the page
 * colour where nothing scrolls underneath.
 */
@Composable
fun DetailTopBar(
    title: String,
    subtitle: String?,
    onBack: (() -> Unit)?,
    backLabel: String = "返回",
    insets: Boolean = true,
    solid: Boolean = false,
    actions: @Composable RowScope.() -> Unit = {},
) {
    val p = LocalTeleply.current
    Row(
        Modifier.fillMaxWidth().then(if (solid) Modifier.background(p.page) else Modifier)
            .then(if (insets) Modifier.windowInsetsPadding(WindowInsets.safeDrawing.only(WindowInsetsSides.Top + WindowInsetsSides.Horizontal)) else Modifier)
            .heightIn(min = 64.dp)
            .padding(horizontal = 12.dp, vertical = 8.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        if (onBack != null) TeleplyIconButton(TeleplyIcons.Back, backLabel, onBack) else Spacer(Modifier.width(48.dp))
        Column(Modifier.weight(1f).padding(horizontal = 8.dp), horizontalAlignment = Alignment.CenterHorizontally) {
            Text(
                title,
                style = MaterialTheme.typography.titleMedium,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
                textAlign = TextAlign.Center,
                modifier = Modifier.semantics { heading() },
            )
            if (!subtitle.isNullOrBlank()) {
                Text(subtitle, style = MaterialTheme.typography.bodySmall, color = p.muted, maxLines = 1, overflow = TextOverflow.Ellipsis)
            }
        }
        Row(Modifier.widthIn(min = 48.dp), horizontalArrangement = Arrangement.End, verticalAlignment = Alignment.CenterVertically, content = actions)
    }
}

/**
 * The thin line under a title bar while a page reads (0.8): it shows only when the wait lasts past 400 ms, so a quick
 * read (back to the list, a new conversation's sheet) does not flash it.
 */
@Composable
fun ProgressLine(busy: Boolean, track: Color = Color.Transparent) {
    val p = LocalTeleply.current
    var shown by remember { mutableStateOf(false) }
    LaunchedEffect(busy) { if (busy) { kotlinx.coroutines.delay(400); shown = true } else shown = false }
    if (busy && shown) androidx.compose.material3.LinearProgressIndicator(
        Modifier.fillMaxWidth().height(2.dp).semantics { contentDescription = "正在读取" },
        color = p.accent, trackColor = track,
    )
}

/** Full-width note bar (web .connection-note / .notice): amber for connection, red for errors, plain for info. */
enum class NoteTone { Connection, Error, Info }

@Composable
fun NoteBar(text: String, tone: NoteTone, modifier: Modifier = Modifier, action: String? = null, actionEnabled: Boolean = true, onAction: () -> Unit = {}) {
    val p = LocalTeleply.current
    val (background, color, icon) = when (tone) {
        NoteTone.Connection -> Triple(p.noteBg, p.noteText, TeleplyIcons.Warning)
        NoteTone.Error -> Triple(p.stopBg, p.error, TeleplyIcons.Warning)
        NoteTone.Info -> Triple(p.panel, p.muted, TeleplyIcons.Info)
    }
    Row(
        modifier.fillMaxWidth().background(background).heightIn(min = 44.dp).padding(start = 16.dp, end = 4.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Icon(icon, contentDescription = null, tint = color, modifier = Modifier.size(16.dp))
        Spacer(Modifier.width(10.dp))
        Text(text, style = MaterialTheme.typography.note, color = color, modifier = Modifier.weight(1f).padding(vertical = 8.dp))
        if (action != null) PillButton(action, onClick = onAction, style = PillStyle.Text, enabled = actionEnabled, minHeight = 36.dp)
    }
}

/** Form field in the web style: rounded 16dp, line-coloured border, accent when focused. Keeps the label for TalkBack. */
@Composable
fun TeleplyTextField(
    value: String,
    onValueChange: (String) -> Unit,
    label: String,
    modifier: Modifier = Modifier,
    placeholder: String? = null,
    singleLine: Boolean = true,
    minLines: Int = 1,
    maxLines: Int = if (singleLine) 1 else Int.MAX_VALUE,
    enabled: Boolean = true,
    keyboardType: KeyboardType = KeyboardType.Text,
    visualTransformation: VisualTransformation = VisualTransformation.None,
) {
    val p = LocalTeleply.current
    OutlinedTextField(
        value = value,
        onValueChange = onValueChange,
        modifier = modifier.fillMaxWidth(),
        label = { Text(label) },
        placeholder = placeholder?.let { { Text(it, color = p.muted) } },
        singleLine = singleLine,
        minLines = minLines,
        maxLines = maxLines,
        enabled = enabled,
        textStyle = MaterialTheme.typography.bodyLarge.copy(color = p.text),
        keyboardOptions = KeyboardOptions(keyboardType = keyboardType),
        visualTransformation = visualTransformation,
        shape = TeleplyShape.Card,
        colors = OutlinedTextFieldDefaults.colors(
            focusedBorderColor = p.accent,
            unfocusedBorderColor = if (p.dark) p.edge else p.line,
            focusedLabelColor = p.accent,
            unfocusedLabelColor = p.muted,
            cursorColor = p.accent,
            focusedContainerColor = p.card,
            unfocusedContainerColor = p.card,
            disabledContainerColor = p.panel,
        ),
    )
}

/** A grouped card on a page or sheet (settings groups, device rows; spec 0.4 §2.4): light grey, no edge or shadow. */
@Composable
fun CardSection(modifier: Modifier = Modifier, content: @Composable ColumnScope.() -> Unit) {
    val p = LocalTeleply.current
    Column(
        modifier.fillMaxWidth()
            .clip(TeleplyShape.Card)
            .background(p.group)
            .padding(vertical = 4.dp),
        content = content,
    )
}

/** A whole-row button inside a card section: title, optional detail and value, chevron when it opens a page. */
@Composable
fun CardRow(title: String, onClick: (() -> Unit)?, detail: String? = null, value: String? = null, chevron: Boolean = false, icon: ImageVector? = null, danger: Boolean = false, enabled: Boolean = true) {
    val p = LocalTeleply.current
    val interaction = remember { MutableInteractionSource() }
    val pressed by interaction.collectIsPressedAsState()
    Row(
        Modifier.fillMaxWidth().heightIn(min = 52.dp)
            .background(if (pressed) p.groupPressed else Color.Transparent)
            .then(if (onClick != null) Modifier.clickable(interaction, indication = null, enabled = enabled, role = Role.Button, onClick = onClick) else Modifier)
            .padding(horizontal = 16.dp, vertical = 10.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        if (icon != null) Icon(icon, contentDescription = null, tint = if (danger) p.error else p.muted, modifier = Modifier.size(20.dp))
        Column(Modifier.weight(1f)) {
            Text(title, style = MaterialTheme.typography.bodyLarge, color = (if (danger) p.error else p.text).copy(alpha = if (enabled) 1f else 0.45f))
            if (!detail.isNullOrBlank()) Text(detail, style = MaterialTheme.typography.bodySmall, color = p.muted)
        }
        if (!value.isNullOrBlank()) Text(value, style = MaterialTheme.typography.bodyMedium, color = p.muted, maxLines = 1, overflow = TextOverflow.Ellipsis)
        if (chevron) Icon(TeleplyIcons.ChevronRight, contentDescription = null, tint = p.muted, modifier = Modifier.size(18.dp))
    }
}

@Composable
fun CardDivider() {
    Box(Modifier.fillMaxWidth().padding(start = 16.dp).height(1.dp).background(LocalTeleply.current.line))
}

@Composable
fun SectionLabel(text: String, modifier: Modifier = Modifier) {
    Text(
        text,
        style = MaterialTheme.typography.labelMedium.copy(fontSize = 13.sp),
        color = LocalTeleply.current.muted,
        modifier = modifier.padding(top = 4.dp).semantics { heading() },
    )
}

@Composable
fun InfoNote(text: String, modifier: Modifier = Modifier, color: Color = Color.Unspecified) {
    val p = LocalTeleply.current
    val ink = if (color.isSpecified) color else p.muted
    Row(modifier.fillMaxWidth(), verticalAlignment = Alignment.Top) {
        Icon(TeleplyIcons.Info, contentDescription = null, tint = ink, modifier = Modifier.padding(top = 1.dp).size(16.dp))
        Spacer(Modifier.width(8.dp))
        Text(text, style = MaterialTheme.typography.note, color = ink)
    }
}

/**
 * Option card (web .option-card): 14dp corners and a thin edge; selected gets the accent edge and selected fill.
 * Single choice shows a radio dot; multiple choice a rounded check box. The whole card is one TalkBack control.
 */
@Composable
fun OptionCard(
    title: String,
    detail: String?,
    selected: Boolean,
    enabled: Boolean = true,
    multiple: Boolean = false,
    description: String? = null,
    status: String? = null,
    onChange: (Boolean) -> Unit,
) {
    val p = LocalTeleply.current
    val action = if (multiple) Modifier.toggleable(selected, enabled = enabled, role = Role.Checkbox, onValueChange = onChange)
    else Modifier.selectable(selected, enabled = enabled, role = Role.RadioButton, onClick = { onChange(true) })
    Row(
        Modifier.fillMaxWidth().heightIn(min = 56.dp)
            .clip(TeleplyShape.Option)
            .background(if (selected) p.selected else p.card)
            .border(1.dp, if (selected) p.accent else p.line, TeleplyShape.Option)
            .then(action)
            .semantics(mergeDescendants = true) { if (description != null) contentDescription = description }
            .graphicsLayer { alpha = if (enabled || selected) 1f else 0.5f }
            .padding(12.dp),
        horizontalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        val ring = if (p.dark) p.edge else Color(0xFFC9CED8)
        if (multiple) {
            Box(
                Modifier.padding(top = 2.dp).size(18.dp).clip(RoundedCornerShape(5.dp))
                    .background(if (selected) p.accent else Color.Transparent)
                    .border(1.dp, if (selected) p.accent else ring, RoundedCornerShape(5.dp)),
                contentAlignment = Alignment.Center,
            ) { if (selected) Icon(TeleplyIcons.Check, contentDescription = null, tint = p.onAccent, modifier = Modifier.size(14.dp)) }
        } else {
            Box(Modifier.padding(top = 2.dp).size(18.dp).border(if (selected) 5.dp else 1.dp, if (selected) p.accent else ring, CircleShape))
        }
        Column(Modifier.weight(1f)) {
            Text(title, style = MaterialTheme.typography.bodyMedium, color = p.text)
            if (!detail.isNullOrBlank()) Text(detail, style = MaterialTheme.typography.bodySmall, color = p.muted, modifier = Modifier.padding(top = 2.dp))
            if (!status.isNullOrBlank()) Text(status, style = MaterialTheme.typography.bodySmall, color = p.accent, modifier = Modifier.padding(top = 2.dp))
        }
    }
}

/**
 * Code and command panel (web .code-wrap): light grey, thin edge, 12dp corners; a header with the label and buttons
 * that do not scroll with the content. Wraps by default; "原始行" keeps lines and scrolls sideways. Copy is always the
 * complete original text (B16).
 */
@Composable
fun CodePanel(label: String, code: String, copyLabel: String, modifier: Modifier = Modifier, maxLines: Int = Int.MAX_VALUE, wrapByDefault: Boolean = true) {
    val p = LocalTeleply.current
    val clipboard = LocalClipboardManager.current
    var original by remember { mutableStateOf(!wrapByDefault) }
    val full = code.trimEnd('\n')
    val lines = full.lines()
    val clipped = lines.size > maxLines
    val shown = if (clipped) lines.take(maxLines).joinToString("\n") else full
    Column(modifier.fillMaxWidth().clip(TeleplyShape.Code).background(p.codeFill).border(1.dp, p.codeEdge, TeleplyShape.Code)) {
        Row(Modifier.fillMaxWidth().padding(start = 12.dp, end = 4.dp), verticalAlignment = Alignment.CenterVertically) {
            Text(label, style = MaterialTheme.typography.note, color = p.muted, modifier = Modifier.weight(1f), maxLines = 1, overflow = TextOverflow.Ellipsis)
            CodeHeadButton(if (original) "自动换行" else "原始行", null) { original = !original }
            CodeHeadButton("复制", copyLabel) { clipboard.setText(AnnotatedString(full)) }
        }
        Box(Modifier.fillMaxWidth().height(1.dp).background(p.codeEdge))
        Text(
            shown,
            style = MaterialTheme.typography.code,
            color = p.text,
            softWrap = !original,
            modifier = Modifier.fillMaxWidth()
                .then(if (original) Modifier.horizontalScroll(rememberScrollState()) else Modifier)
                .padding(start = 12.dp, end = 12.dp, top = 12.dp, bottom = if (clipped) 4.dp else 12.dp),
        )
        if (clipped) Text("还有 ${lines.size - maxLines} 行未显示", style = MaterialTheme.typography.bodySmall, color = p.muted, modifier = Modifier.padding(start = 12.dp, bottom = 10.dp))
    }
}

@Composable
private fun CodeHeadButton(text: String, description: String?, onClick: () -> Unit) {
    val p = LocalTeleply.current
    Box(
        Modifier.minimumInteractiveComponentSize().clip(CircleShape)
            .clickable(role = Role.Button, onClick = onClick)
            .then(if (description != null) Modifier.semantics { contentDescription = description } else Modifier)
            .padding(horizontal = 8.dp, vertical = 4.dp),
        contentAlignment = Alignment.Center,
    ) {
        Text(text, style = MaterialTheme.typography.note.copy(fontWeight = FontWeight.Normal), color = p.muted)
    }
}

// ---------------------------------------------------------------------------------------------
// Glass menus (spec 2.5, 4.7, 5): drawn in the app window so they can sample the page behind them. While a menu is
// open the page is recorded once; the menu is large-tier liquid glass on it. Solid mode: the web's solid panel.

enum class MenuPlacement { BelowEnd, BelowStart, AtPoint }

class MenuRequest(
    /** Button or finger position in root coordinates. */
    val anchor: Rect,
    val placement: MenuPlacement,
    /** Pane title read by TalkBack. */
    val label: String,
    val width: Dp = 280.dp,
    /** What the menu is for (a message id), so that message can show it is picked. */
    val key: Any? = null,
    /** False when the content scrolls only a part of itself and keeps the rest in view (the effort row, a search field). */
    val scrolls: Boolean = true,
    /** Tallest the menu may get; the room above or below the anchor limits it as well. */
    val maxHeight: Dp = Dp.Unspecified,
    val content: @Composable MenuScope.() -> Unit,
)

@Stable
class MenuHostState {
    var request by mutableStateOf<MenuRequest?>(null)
        private set
    internal var queued by mutableStateOf<MenuRequest?>(null)
        private set

    fun show(request: MenuRequest) {
        queued = null
        this.request = request
    }

    /** Opens [request] once the menu now open has finished closing, so one menu does not jump into the next. */
    fun showAfter(request: MenuRequest) {
        this.request = null
        queued = request
    }

    fun dismiss() {
        request = null
    }

    internal fun promote() {
        queued?.let {
            queued = null
            request = it
        }
    }
}

class MenuScope internal constructor(private val host: MenuHostState) {
    internal var index = 0
    fun dismiss() = host.dismiss()
}

val LocalMenuHost = staticCompositionLocalOf<MenuHostState?> { null }
private val LocalMenuTransition = staticCompositionLocalOf<Transition<Boolean>?> { null }

/** Remembers where a button is in root coordinates; the menu grows from there. */
@Stable
class MenuAnchor {
    var bounds by mutableStateOf(Rect.Zero)
}

fun Modifier.menuAnchor(anchor: MenuAnchor): Modifier = onGloballyPositioned { anchor.bounds = it.boundsInRoot() }

private class LastRequest {
    var value: MenuRequest? = null
}

/**
 * Host for glass menus, wrapped around the whole app. An outer host is reused (two panes share one).
 * While a menu is open the page below is recorded for the glass, hidden from TalkBack, and system Back closes the
 * menu first.
 */
@Composable
fun MenuHost(modifier: Modifier = Modifier, content: @Composable () -> Unit) {
    if (LocalMenuHost.current != null) {
        Box(modifier) { content() }
        return
    }
    val state = remember { MenuHostState() }
    val glass = LocalGlassMode.current != GlassMode.Solid
    val record = rememberLayerBackdrop()
    val visible = remember { MutableTransitionState(false) }
    visible.targetState = state.request != null
    val last = remember { LastRequest() }
    state.request?.let { last.value = it }
    val showing = visible.currentState || visible.targetState
    var hostOrigin by remember { mutableStateOf(Offset.Zero) }
    CompositionLocalProvider(LocalMenuHost provides state) {
        Box(modifier.onGloballyPositioned { hostOrigin = it.positionInRoot() }) {
            Box(
                Modifier.fillMaxSize()
                    // Record only while a menu reads it: recording is the one real cost of glass (spec 2.5).
                    .then(if (glass && showing) Modifier.layerBackdrop(record) else Modifier)
                    .graphicsLayer()
                    .then(if (state.request != null) Modifier.clearAndSetSemantics { } else Modifier),
            ) { content() }
            if (!showing && state.queued != null) LaunchedEffect(state.queued) { state.promote() }
            val request = last.value
            if (showing && request != null) {
                BackHandler(enabled = state.request != null) { state.dismiss() }
                CompositionLocalProvider(LocalGlassBackdrop provides if (glass) record else null) {
                    MenuOverlay(state, request, visible, hostOrigin)
                }
            }
        }
    }
}

@Composable
private fun MenuOverlay(state: MenuHostState, request: MenuRequest, visible: MutableTransitionState<Boolean>, hostOrigin: Offset) {
    val transition = rememberTransition(visible, label = "menu")
    val animate = remember { TeleplyMotion.enabled() }
    // Web values: 220 ms, scale 0.96 → 1.005 → 1, rising about 6dp; closing fades in 120 ms with a slight shrink.
    val scale by transition.animateFloat(
        transitionSpec = {
            when {
                !animate -> snap()
                targetState -> keyframes {
                    durationMillis = 220
                    0.96f at 0
                    1.005f at 165
                    1f at 220
                }
                else -> tween(120)
            }
        },
        label = "menu-scale",
    ) { open -> if (open || !animate) 1f else 0.98f }
    val alpha by transition.animateFloat(
        transitionSpec = {
            when {
                !animate -> tween(80)
                targetState -> keyframes {
                    durationMillis = 220
                    0f at 0
                    1f at 165
                }
                else -> tween(120)
            }
        },
        label = "menu-alpha",
    ) { open -> if (open) 1f else 0f }
    val lift by transition.animateDp(
        transitionSpec = {
            when {
                !animate -> snap()
                targetState -> keyframes {
                    durationMillis = 220
                    6.dp at 0
                    0.dp at 220
                }
                else -> snap(delayMillis = 120)
            }
        },
        label = "menu-lift",
    ) { open -> if (open || !animate) 0.dp else 6.dp }
    var origin by remember { mutableStateOf(TransformOrigin(1f, 0f)) }
    // The keyboard, status bar and navigation bar are off limits: a menu under the keyboard could not be seen.
    val safe = WindowInsets.safeDrawing
    // A tap outside closes the menu; this layer also stops the tap reaching what is underneath.
    Box(Modifier.fillMaxSize().pointerInput(state) { detectTapGestures { state.dismiss() } })
    Layout(
        content = {
            MenuPanel(request, state, transition, { scale }, { alpha }, { lift }, { origin })
        },
        modifier = Modifier.fillMaxSize(),
    ) { measurables, constraints ->
        val margin = 12.dp.roundToPx()
        val gap = 6.dp.roundToPx()
        val top = maxOf(margin, safe.getTop(this) + 4.dp.roundToPx())
        val bottom = constraints.maxHeight - maxOf(margin, safe.getBottom(this) + 6.dp.roundToPx())
        val width = min(request.width.roundToPx(), constraints.maxWidth - margin * 2)
        val anchor = request.anchor.translate(-hostOrigin)
        val roomBelow = bottom - (anchor.bottom.toInt() + gap)
        val roomAbove = anchor.top.toInt() - gap - top
        // Measured for the roomier side, so a long list never covers its own button; very tight rooms still get 200dp.
        val room = maxOf(roomAbove, roomBelow, min(200.dp.roundToPx(), bottom - top)).coerceAtLeast(0)
        val cap = if (request.maxHeight.isSpecified) request.maxHeight.roundToPx() else Int.MAX_VALUE
        val panel = measurables.first().measure(Constraints(minWidth = width, maxWidth = width, maxHeight = min(room, cap)))
        val below = panel.height <= roomBelow || roomBelow >= roomAbove
        val rawY = if (below) anchor.bottom.toInt() + gap else anchor.top.toInt() - gap - panel.height
        val rawX = when (request.placement) {
            MenuPlacement.BelowEnd -> anchor.right.toInt() - panel.width
            MenuPlacement.BelowStart, MenuPlacement.AtPoint -> anchor.left.toInt()
        }
        val x = rawX.coerceIn(margin, (constraints.maxWidth - margin - panel.width).coerceAtLeast(margin))
        val y = rawY.coerceIn(top, (bottom - panel.height).coerceAtLeast(top))
        val pivotX = if (panel.width == 0) 0.5f else ((anchor.center.x - x) / panel.width).coerceIn(0f, 1f)
        origin = TransformOrigin(pivotX, if (below) 0f else 1f)
        layout(constraints.maxWidth, constraints.maxHeight) { panel.place(x, y) }
    }
}

@Composable
private fun MenuPanel(
    request: MenuRequest,
    state: MenuHostState,
    transition: Transition<Boolean>,
    scale: () -> Float,
    alpha: () -> Float,
    lift: () -> Dp,
    origin: () -> TransformOrigin,
) {
    val shape = TeleplyShape.Panel
    val scope = remember(state) { MenuScope(state) }
    Column(
        Modifier
            .graphicsLayer {
                val s = scale()
                scaleX = s
                scaleY = s
                this.alpha = alpha()
                translationY = lift().toPx()
                transformOrigin = origin()
            }
            .glass(shape, GlassSize.Large)
            .clip(shape)
            .semantics { paneTitle = request.label }
            .then(if (request.scrolls) Modifier.verticalScroll(rememberScrollState()) else Modifier)
            .padding(vertical = 6.dp),
    ) {
        CompositionLocalProvider(LocalMenuTransition provides transition) {
            scope.index = 0
            request.content(scope)
        }
    }
}

enum class MenuTrailing { None, Chevron, Checked }

/**
 * Menu row (web .tp-menu > button): whole row, at least 48dp; icon, text (current value under it), chevron or check.
 * Pressed rows get the pressed fill instead of a ripple. Rows follow in: 140 ms each, 15 ms later per row, 60 ms at most.
 */
@Composable
fun MenuScope.MenuRow(
    text: String,
    onClick: () -> Unit,
    icon: ImageVector? = null,
    detail: String? = null,
    trailing: MenuTrailing = MenuTrailing.None,
    count: Int = 0,
    danger: Boolean = false,
    enabled: Boolean = true,
    dismissOnClick: Boolean = true,
) {
    val p = LocalTeleply.current
    val appear = appear() ?: return
    val interaction = remember { MutableInteractionSource() }
    val pressed by interaction.collectIsPressedAsState()
    val content = if (danger) p.error else p.text
    Row(
        Modifier.fillMaxWidth().heightIn(min = 48.dp)
            .then(appear)
            .background(if (pressed) p.pressed else Color.Transparent)
            .clickable(interaction, indication = null, enabled = enabled, role = Role.Button) {
                if (dismissOnClick) dismiss()
                onClick()
            }
            .padding(horizontal = 18.dp, vertical = 8.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        if (icon != null) Icon(icon, contentDescription = null, tint = if (danger) p.error else p.muted, modifier = Modifier.size(22.dp))
        Column(Modifier.weight(1f)) {
            Text(text, style = MaterialTheme.typography.labelLarge, color = content.copy(alpha = if (enabled) 1f else 0.45f))
            if (detail != null) Text(detail, style = MaterialTheme.typography.bodySmall, color = p.muted)
        }
        if (count > 0) {
            Box(Modifier.heightIn(min = 20.dp).widthIn(min = 20.dp).background(p.error, CircleShape).padding(horizontal = 6.dp), contentAlignment = Alignment.Center) {
                Text("$count", style = MaterialTheme.typography.labelSmall, color = Color.White)
            }
        }
        when (trailing) {
            MenuTrailing.Chevron -> Icon(TeleplyIcons.ChevronRight, contentDescription = null, tint = p.muted, modifier = Modifier.size(18.dp))
            MenuTrailing.Checked -> Icon(TeleplyIcons.Check, contentDescription = "已选", tint = p.accent, modifier = Modifier.size(18.dp))
            MenuTrailing.None -> Unit
        }
    }
}

@Composable
fun MenuScope.MenuDivider() {
    Box(Modifier.fillMaxWidth().padding(vertical = 4.dp).height(1.dp).background(LocalTeleply.current.line))
}

/** Grey note at the bottom of a menu (web #convFolder). */
@Composable
fun MenuScope.MenuHint(text: String) {
    Text(
        text,
        style = MaterialTheme.typography.note,
        color = LocalTeleply.current.muted,
        modifier = Modifier.fillMaxWidth().padding(horizontal = 18.dp, vertical = 8.dp),
    )
}

/**
 * How each part of a menu comes in: 140 ms, 15 ms later per part, 60 ms at most (web .tp-menu). Null outside a menu.
 */
@Composable
private fun MenuScope.appear(): Modifier? {
    val position = index++
    val animate = remember { TeleplyMotion.enabled() }
    val transition = LocalMenuTransition.current ?: return null
    val progress by transition.animateFloat(
        transitionSpec = {
            when {
                !animate -> snap()
                targetState -> tween(140, delayMillis = min(position * 15, 60))
                else -> snap(delayMillis = 120)
            }
        },
        label = "menu-row",
    ) { open -> if (open || !animate) 1f else 0f }
    return Modifier.graphicsLayer {
        alpha = progress
        translationY = (1f - progress) * 3.dp.toPx()
    }
}

/** Small grey heading inside a menu, e.g. 推理强度 above its segments. */
@Composable
fun MenuScope.MenuCaption(text: String) {
    val appear = appear() ?: return
    Text(
        text,
        style = MaterialTheme.typography.labelMedium.copy(fontSize = 12.sp),
        color = LocalTeleply.current.muted,
        modifier = Modifier.fillMaxWidth().then(appear).padding(start = 18.dp, end = 18.dp, top = 8.dp, bottom = 2.dp).semantics { heading() },
    )
}

/** A quiet "reading…" row while the menu waits for the computer. */
@Composable
fun MenuScope.MenuLoading(text: String) {
    val p = LocalTeleply.current
    val appear = appear() ?: return
    Row(
        Modifier.fillMaxWidth().heightIn(min = 48.dp).then(appear).padding(horizontal = 18.dp).semantics(mergeDescendants = true) { },
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        CircularProgressIndicator(Modifier.size(16.dp), color = p.muted, strokeWidth = 2.dp, trackColor = Color.Transparent)
        Text(text, style = MaterialTheme.typography.bodyMedium, color = p.muted)
    }
}

/**
 * A row of segments inside a menu (spec 0.4 §4.3: the effort under the model list). One tap applies the choice and
 * closes the menu. Up to six segments share the width; more scroll sideways.
 */
@Composable
fun MenuScope.MenuSegments(options: List<Pair<String, String>>, selected: String?, enabled: Boolean = true, onSelect: (String) -> Unit) {
    val p = LocalTeleply.current
    val appear = appear() ?: return
    val thumb = if (p.dark) Color(0xFF3A3A3C) else Color.White
    val fits = options.size <= 6
    Row(
        Modifier.fillMaxWidth().then(appear).padding(horizontal = 12.dp, vertical = 6.dp)
            .clip(CircleShape).background(p.glassTrack)
            .then(if (fits) Modifier else Modifier.horizontalScroll(rememberScrollState()))
            .padding(3.dp)
            .selectableGroup(),
        horizontalArrangement = Arrangement.spacedBy(2.dp),
    ) {
        options.forEach { (value, label) ->
            val on = value == selected
            Box(
                Modifier.then(if (fits) Modifier.weight(1f) else Modifier.widthIn(min = 52.dp))
                    .heightIn(min = 44.dp)
                    .then(if (on) Modifier.softShadow(CircleShape, p, TeleplyShadow.Segment) else Modifier)
                    .clip(CircleShape)
                    .background(if (on) thumb else Color.Transparent)
                    .selectable(on, enabled = enabled, role = Role.RadioButton) {
                        dismiss()
                        if (!on) onSelect(value)
                    }
                    .padding(horizontal = 8.dp),
                contentAlignment = Alignment.Center,
            ) {
                Text(label, style = MaterialTheme.typography.labelLarge, color = (if (on) p.text else p.muted).copy(alpha = if (enabled) 1f else 0.45f), maxLines = 1)
            }
        }
    }
}

/** Search box at the top of a long menu (the project menu over 8 projects). Typing filters; nothing is sent. */
@Composable
fun MenuScope.MenuSearch(value: String, onValueChange: (String) -> Unit, placeholder: String) {
    val p = LocalTeleply.current
    val appear = appear() ?: return
    Row(
        Modifier.fillMaxWidth().then(appear).padding(horizontal = 12.dp, vertical = 4.dp)
            .heightIn(min = 44.dp).clip(CircleShape).background(p.glassTrack).padding(horizontal = 12.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Icon(TeleplyIcons.Search, contentDescription = null, tint = p.muted, modifier = Modifier.size(18.dp))
        Spacer(Modifier.width(8.dp))
        Box(Modifier.weight(1f), contentAlignment = Alignment.CenterStart) {
            if (value.isEmpty()) Text(placeholder, style = MaterialTheme.typography.bodyMedium, color = p.muted, maxLines = 1)
            BasicTextField(
                value,
                onValueChange,
                Modifier.fillMaxWidth().semantics { contentDescription = placeholder },
                singleLine = true,
                textStyle = MaterialTheme.typography.bodyMedium.copy(color = p.text),
                cursorBrush = SolidColor(p.accent),
                keyboardOptions = KeyboardOptions(imeAction = ImeAction.Search),
            )
        }
    }
}
