package com.pocketagentdesk.nativepreview

import android.animation.ValueAnimator
import androidx.compose.animation.core.CubicBezierEasing
import androidx.compose.animation.core.FiniteAnimationSpec
import androidx.compose.animation.core.spring
import androidx.compose.animation.core.tween
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.ColorScheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Shapes
import androidx.compose.material3.Typography
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.Immutable
import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.dropShadow
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Shape
import androidx.compose.ui.graphics.shadow.Shadow
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.DpOffset
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

/**
 * Colours come from the web client (remote.html :root and static/theme.css), Android spec 0.3 §2.2 and §2.5.
 * Components read them by purpose through LocalTeleply; Material roles map to the same values.
 */
@Immutable
data class TeleplyPalette(
    val dark: Boolean,
    val page: Color,
    val panel: Color,
    val control: Color,
    val card: Color,
    val line: Color,
    /** Edge of buttons and the composer in dark mode; light mode relies on shadows instead. */
    val edge: Color,
    val text: Color,
    val muted: Color,
    val accent: Color,
    val onAccent: Color,
    val selected: Color,
    val onSelected: Color,
    val success: Color,
    val amber: Color,
    val error: Color,
    val askDot: Color,
    val askGo: Color,
    val noteBg: Color,
    val noteText: Color,
    val stopBg: Color,
    val stopText: Color,
    val pressed: Color,
    /** Liquid glass tints (spec 2.5): small tier (buttons, pills) and large tier (menus, short-choice sheets). */
    val glassTint: Color,
    val glassPanel: Color,
    /** "停止这一轮" glass tint. */
    val stopTint: Color,
    /** Solid fallback for glass panels, and their edge. */
    val glassSolid: Color,
    val glassEdge: Color,
    /** Composer glass tint (spec 0.4 §2.5): heavier than menus because it is typed on. */
    val composerTint: Color,
    /** Light fills on glass: tiles in 会话状态, the effort track in menus. */
    val glassFill: Color,
    val glassTrack: Color,
    /** Grouped cards on a page or sheet (spec 0.4 §2.4): light grey, no edge or shadow; and their pressed row. */
    val group: Color,
    val groupPressed: Color,
    val scrim: Color,
    val bubble: Color,
    val onBubble: Color,
    val bubbleEdge: Color,
    val tray: Color,
    val codeFill: Color,
    val codeEdge: Color,
)

val TeleplyLightPalette = TeleplyPalette(
    dark = false,
    page = Color(0xFFFFFFFF), panel = Color(0xFFF4F5F7), control = Color(0xFFF4F5F7), card = Color(0xFFFFFFFF),
    line = Color(0xFFE1E4EA), edge = Color.Transparent,
    text = Color(0xFF1D2330), muted = Color(0xFF6B7280),
    accent = Color(0xFF2563EB), onAccent = Color(0xFFFFFFFF),
    selected = Color(0xFFEEF2FF), onSelected = Color(0xFF2563EB),
    success = Color(0xFF16A34A), amber = Color(0xFFD97706), error = Color(0xFFDC2626),
    askDot = Color(0xFFF97316), askGo = Color(0xFFC2410C),
    noteBg = Color(0xFFFFF7ED), noteText = Color(0xFF92400E),
    stopBg = Color(0xFFFFF1F2), stopText = Color(0xFFDC2626),
    pressed = Color(0xFFEEF0F4),
    // White 50% and #FAFAFA 60%: the upstream Backdrop navigation bar and dialog values.
    glassTint = Color(0x80FFFFFF), glassPanel = Color(0x99FAFAFA), stopTint = Color(0xB3FFF1F2),
    glassSolid = Color(0xFFFFFFFF), glassEdge = Color(0x38787882),
    composerTint = Color(0x99FFFFFF), glassFill = Color(0x0A000000), glassTrack = Color(0x12000000),
    group = Color(0xFFF4F5F7), groupPressed = Color(0xFFE8EAEE),
    scrim = Color(0x381D2330),
    bubble = Color(0xFF2563EB), onBubble = Color(0xFFFFFFFF), bubbleEdge = Color.Transparent,
    tray = Color(0xFFF4F5F7),
    codeFill = Color(0xFFF5F5F5), codeEdge = Color(0xFFE3E3E3),
)

val TeleplyDarkPalette = TeleplyPalette(
    dark = true,
    page = Color(0xFF000000), panel = Color(0xFF141414), control = Color(0xFF1E1E1E), card = Color(0xFF1E1E1E),
    line = Color(0xFF333333), edge = Color(0xFF767676),
    text = Color(0xFFEEEEEE), muted = Color(0xFFA8A8A8),
    accent = Color(0xFF8AB4FF), onAccent = Color(0xFF101010),
    selected = Color(0xFF17253B), onSelected = Color(0xFFB1CDFF),
    success = Color(0xFF66D997), amber = Color(0xFFEFBD6A), error = Color(0xFFFF9A9A),
    askDot = Color(0xFFEFBD6A), askGo = Color(0xFFEFBD6A),
    noteBg = Color(0xFF302513), noteText = Color(0xFFEFBD6A),
    // The web defines no dark "停止这一轮"; button fill with the error colour.
    stopBg = Color(0xFF1E1E1E), stopText = Color(0xFFFF9A9A),
    pressed = Color(0xFF292929),
    // #121212 40%: the upstream Backdrop dark bar and dialog value.
    glassTint = Color(0x66121212), glassPanel = Color(0x66121212), stopTint = Color(0x66121212),
    glassSolid = Color(0xFF1E1E1E), glassEdge = Color(0x33D2D2DC),
    composerTint = Color(0x99121212), glassFill = Color(0x14FFFFFF), glassTrack = Color(0x1FFFFFFF),
    group = Color(0xFF1E1E1E), groupPressed = Color(0xFF292929),
    scrim = Color(0x99000000),
    bubble = Color(0xFF1E1E1E), onBubble = Color(0xFFEEEEEE), bubbleEdge = Color(0xFF333333),
    tray = Color(0xFF141414),
    codeFill = Color(0xFF1E1E1E), codeEdge = Color(0xFF333333),
)

private fun schemeFor(p: TeleplyPalette): ColorScheme = if (!p.dark) {
    lightColorScheme(
        primary = p.accent, onPrimary = p.onAccent, primaryContainer = p.selected, onPrimaryContainer = p.onSelected,
        inversePrimary = Color(0xFF8AB4FF),
        secondary = Color(0xFF4B5563), onSecondary = Color.White, secondaryContainer = p.selected, onSecondaryContainer = p.onSelected,
        tertiary = p.amber, onTertiary = Color.White, tertiaryContainer = p.noteBg, onTertiaryContainer = p.noteText,
        background = p.page, onBackground = p.text, surface = p.page, onSurface = p.text,
        // Slightly different from the panel colour: contentColorFor looks roles up by value.
        surfaceVariant = Color(0xFFF2F3F5), onSurfaceVariant = p.muted, surfaceTint = p.accent,
        inverseSurface = Color(0xFF111111), inverseOnSurface = Color.White,
        error = p.error, onError = Color.White, errorContainer = p.stopBg, onErrorContainer = Color(0xFFB91C1C),
        outline = Color(0xFFD1D5DB), outlineVariant = p.line, scrim = Color(0xFF1D2330),
        surfaceBright = Color.White, surfaceDim = Color(0xFFE5E7EB),
        surfaceContainerLowest = Color.White, surfaceContainerLow = Color(0xFFFAFAFB),
        surfaceContainer = p.panel, surfaceContainerHigh = p.pressed, surfaceContainerHighest = Color(0xFFE5E7EB),
    )
} else {
    darkColorScheme(
        primary = p.accent, onPrimary = p.onAccent, primaryContainer = p.selected, onPrimaryContainer = p.onSelected,
        inversePrimary = Color(0xFF2563EB),
        secondary = p.muted, onSecondary = Color(0xFF101010), secondaryContainer = p.selected, onSecondaryContainer = p.onSelected,
        tertiary = p.amber, onTertiary = Color(0xFF101010), tertiaryContainer = p.noteBg, onTertiaryContainer = p.noteText,
        background = p.page, onBackground = p.text, surface = p.page, onSurface = p.text,
        surfaceVariant = Color(0xFF202020), onSurfaceVariant = p.muted, surfaceTint = p.accent,
        inverseSurface = p.text, inverseOnSurface = Color(0xFF111111),
        error = p.error, onError = Color(0xFF101010), errorContainer = Color(0xFF351D20), onErrorContainer = p.error,
        outline = p.edge, outlineVariant = p.line, scrim = Color.Black,
        surfaceBright = Color(0xFF2A2A2A), surfaceDim = Color.Black,
        surfaceContainerLowest = Color.Black, surfaceContainerLow = Color(0xFF0A0A0A),
        surfaceContainer = p.panel, surfaceContainerHigh = p.control, surfaceContainerHighest = p.pressed,
    )
}

val LocalTeleply = staticCompositionLocalOf { TeleplyLightPalette }

private val Base = Typography()

private fun TextStyle.cjk() = copy(letterSpacing = 0.sp)

/**
 * Sizes follow the web (spec §2.3): list title 20/600, page titles 16–17/600, buttons 14/500, chips 12/500.
 * Letter spacing is always 0: Material's 0.1–0.5sp is meant for Latin text and spreads Chinese apart.
 */
val TeleplyTypography = with(Base) {
    Typography(
        displayLarge = displayLarge.cjk(), displayMedium = displayMedium.cjk(), displaySmall = displaySmall.cjk(),
        headlineLarge = headlineLarge.cjk(), headlineMedium = headlineMedium.cjk(), headlineSmall = headlineSmall.cjk(),
        titleLarge = titleLarge.copy(fontSize = 20.sp, lineHeight = 28.sp, fontWeight = FontWeight.SemiBold).cjk(),
        titleMedium = titleMedium.copy(fontSize = 16.sp, lineHeight = 24.sp, fontWeight = FontWeight.SemiBold).cjk(),
        titleSmall = titleSmall.copy(fontSize = 14.sp, lineHeight = 20.sp, fontWeight = FontWeight.SemiBold).cjk(),
        bodyLarge = bodyLarge.copy(fontSize = 16.sp, lineHeight = 24.sp).cjk(),
        bodyMedium = bodyMedium.copy(fontSize = 14.sp, lineHeight = 21.sp).cjk(),
        bodySmall = bodySmall.copy(fontSize = 12.sp, lineHeight = 18.sp).cjk(),
        labelLarge = labelLarge.copy(fontSize = 14.sp, lineHeight = 20.sp, fontWeight = FontWeight.Medium).cjk(),
        labelMedium = labelMedium.copy(fontSize = 12.sp, lineHeight = 16.sp, fontWeight = FontWeight.Medium).cjk(),
        labelSmall = labelSmall.copy(fontSize = 11.sp, lineHeight = 16.sp, fontWeight = FontWeight.Medium).cjk(),
    )
}

/** Answers and user messages: 16sp, line height 1.7 (web .bub). */
val Typography.reading: TextStyle get() = bodyLarge.copy(lineHeight = 27.sp)

/** Process area and tool records: 14sp, line height 1.55 (design language §8). */
val Typography.process: TextStyle get() = bodyMedium.copy(lineHeight = 22.sp)

/** Question card text: 15sp, line height 1.6 (.codex-card). */
val Typography.card: TextStyle get() = bodyLarge.copy(fontSize = 15.sp, lineHeight = 24.sp)

/** Prompt bars and notes: 13sp. */
val Typography.note: TextStyle get() = bodyMedium.copy(fontSize = 13.sp, lineHeight = 19.sp)

/** Code: monospace 13sp, line height 1.6 (.code-wrap pre). */
val Typography.code: TextStyle get() = bodyMedium.copy(fontSize = 13.sp, lineHeight = 21.sp, fontFamily = FontFamily.Monospace)

/** Chat page title: 17sp / 600 (web #cvTitle). */
val Typography.chatTitle: TextStyle get() = titleMedium.copy(fontSize = 17.sp, lineHeight = 24.sp)

/** Bottom panel title: 17sp / 600 (.sheet .sh-head b). */
val Typography.sheetTitle: TextStyle get() = titleMedium.copy(fontSize = 17.sp, lineHeight = 24.sp)

/** "选择文字" reading panel: 17sp, line height 1.75 (#readerSheet .reader-text). */
val Typography.reader: TextStyle get() = bodyLarge.copy(fontSize = 17.sp, lineHeight = 30.sp)

/** Corner radii follow the web tokens: cards 16, menus and panels 24, composer 26; buttons and chips fully round. */
val TeleplyShapes = Shapes(
    extraSmall = RoundedCornerShape(8.dp),
    small = RoundedCornerShape(12.dp),
    medium = RoundedCornerShape(16.dp),
    large = RoundedCornerShape(24.dp),
    extraLarge = RoundedCornerShape(26.dp),
)

object TeleplyShape {
    val Card = RoundedCornerShape(16.dp)
    val Panel = RoundedCornerShape(24.dp)
    val SheetTop = RoundedCornerShape(topStart = 24.dp, topEnd = 24.dp)
    val Drawer = RoundedCornerShape(topEnd = 20.dp, bottomEnd = 20.dp)
    val Composer = RoundedCornerShape(26.dp)
    /** Values the web uses today, kept until the web unifies them (spec §2.4). */
    val QuestionCard = RoundedCornerShape(20.dp)
    val Option = RoundedCornerShape(14.dp)
    val AskPill = RoundedCornerShape(16.dp)
    val Thumb = RoundedCornerShape(12.dp)
    val Code = RoundedCornerShape(12.dp)
    val Bubble = RoundedCornerShape(20.dp)
    val Tray = RoundedCornerShape(18.dp)
    val Pill = CircleShape
}

/** Shadows use the web's numbers (spec §2.4): y offset, blur radius, colour. Not drawn in dark mode; edges instead. */
object TeleplyShadow {
    private val ink = Color(0xFF1D2330)
    private val slate = Color(0xFF0F172A)
    val Control = Shadow(radius = 18.dp, color = ink.copy(alpha = 0.03f), offset = DpOffset(0.dp, 4.dp))
    val ComposerNear = Shadow(radius = 2.dp, color = slate.copy(alpha = 0.05f), offset = DpOffset(0.dp, 1.dp))
    val Menu = Shadow(radius = 36.dp, color = Color.Black.copy(alpha = 0.13f), offset = DpOffset(0.dp, 12.dp))
    val Panel = Shadow(radius = 32.dp, color = ink.copy(alpha = 0.09f), offset = DpOffset(0.dp, 8.dp))
    val Card = Shadow(radius = 12.dp, color = ink.copy(alpha = 0.025f), offset = DpOffset(0.dp, 2.dp))
    val Segment = Shadow(radius = 5.dp, color = ink.copy(alpha = 0.08f), offset = DpOffset(0.dp, 1.dp))

    /** Composer outer shadow: focus 0..1, like the web's :focus-within deepening. */
    fun composerFar(focus: Float) = Shadow(
        radius = (24 + 8 * focus).dp,
        color = slate.copy(alpha = 0.09f + 0.05f * focus),
        offset = DpOffset(0.dp, (8 + 4 * focus).dp),
    )
}

/** Light mode draws the web's soft shadows; dark mode skips them (callers draw an edge). */
fun Modifier.softShadow(shape: Shape, palette: TeleplyPalette, vararg shadows: Shadow): Modifier =
    if (palette.dark) this else shadows.fold(this) { modifier, shadow -> modifier.dropShadow(shape, shadow) }

/**
 * App theme. [dynamic] is accepted for stored settings from 0.4.0 and ignored: spec 0.2 dropped wallpaper colours
 * because the web has none and they replace the brand colour.
 */
@Suppress("UNUSED_PARAMETER")
@Composable
fun TeleplyTheme(theme: String = "system", dynamic: Boolean = false, content: @Composable () -> Unit) {
    val dark = theme == "dark" || theme == "system" && isSystemInDarkTheme()
    val palette = if (dark) TeleplyDarkPalette else TeleplyLightPalette
    val glass = rememberGlassMode()
    CompositionLocalProvider(LocalTeleply provides palette, LocalStatusColors provides statusColorsFor(palette), LocalGlassMode provides glass) {
        MaterialTheme(colorScheme = schemeFor(palette), typography = TeleplyTypography, shapes = TeleplyShapes) {
            // Pages have no Material Surface around them, so text needs its colour from here.
            CompositionLocalProvider(androidx.compose.material3.LocalContentColor provides palette.text, content = content)
        }
    }
}

/** Status colours in one place: list status, prompt bars, process summaries and connection notes use these. */
@Immutable
data class StatusStyle(val container: Color, val onContainer: Color, val accent: Color, val emphasized: Boolean = false) {
    val weight: FontWeight? get() = if (emphasized) FontWeight.SemiBold else null
}

@Immutable
data class TeleplyStatusColors(
    val running: StatusStyle,
    val needsAnswer: StatusStyle,
    val failed: StatusStyle,
    val unconfirmed: StatusStyle,
    val connection: StatusStyle,
)

fun statusColorsFor(p: TeleplyPalette) = TeleplyStatusColors(
    running = StatusStyle(Color.Transparent, p.text, p.accent),
    needsAnswer = StatusStyle(p.noteBg, p.noteText, p.askGo, emphasized = true),
    failed = StatusStyle(p.stopBg, p.error, p.error, emphasized = true),
    unconfirmed = StatusStyle(p.control, p.text, p.muted),
    connection = StatusStyle(p.noteBg, p.noteText, p.noteText),
)

val LocalStatusColors = staticCompositionLocalOf { statusColorsFor(TeleplyLightPalette) }

/** Motion values from the web design language §5; Material's motion scheme is internal in 1.4.0. */
object TeleplyMotion {
    val StandardAccelerate = CubicBezierEasing(0.3f, 0f, 1f, 1f)
    val StandardDecelerate = CubicBezierEasing(0f, 0f, 0f, 1f)
    fun <T> fastSpatial(): FiniteAnimationSpec<T> = spring(dampingRatio = 0.9f, stiffness = 1400f)
    fun <T> defaultEffects(): FiniteAnimationSpec<T> = spring(dampingRatio = 1f, stiffness = 1600f)
    fun <T> fadeOut(): FiniteAnimationSpec<T> = tween(100)
    fun <T> collapse(): FiniteAnimationSpec<T> = tween(200, easing = StandardAccelerate)

    /** False when the system "remove animations" setting is on: short fades only, no scaling or movement. */
    fun enabled(): Boolean = ValueAnimator.areAnimatorsEnabled()
}
