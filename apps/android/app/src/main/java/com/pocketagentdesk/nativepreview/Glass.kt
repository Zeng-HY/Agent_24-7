package com.pocketagentdesk.nativepreview

import android.app.UiModeManager
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.os.Build
import android.os.PowerManager
import androidx.compose.animation.core.Animatable
import androidx.compose.animation.core.spring
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.interaction.InteractionSource
import androidx.compose.foundation.interaction.PressInteraction
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxScope
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.Stable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.RectangleShape
import androidx.compose.ui.graphics.Shape
import androidx.compose.ui.graphics.drawscope.DrawScope
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.graphics.isSpecified
import androidx.compose.ui.graphics.toArgb
import androidx.compose.ui.layout.onSizeChanged
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.platform.LocalInspectionMode
import androidx.compose.ui.platform.LocalView
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.core.content.ContextCompat
import com.pocketagentdesk.nativepreview.glass.Backdrop
import com.pocketagentdesk.nativepreview.glass.BackdropEffectScope
import com.pocketagentdesk.nativepreview.glass.BackdropShadow
import com.pocketagentdesk.nativepreview.glass.Highlight
import com.pocketagentdesk.nativepreview.glass.blur
import com.pocketagentdesk.nativepreview.glass.colorControls
import com.pocketagentdesk.nativepreview.glass.drawBackdrop
import com.pocketagentdesk.nativepreview.glass.drawPlainBackdrop
import com.pocketagentdesk.nativepreview.glass.emptyBackdrop
import com.pocketagentdesk.nativepreview.glass.layerBackdrop
import com.pocketagentdesk.nativepreview.glass.lens
import com.pocketagentdesk.nativepreview.glass.rememberLayerBackdrop
import com.pocketagentdesk.nativepreview.glass.runtimeShaderEffect
import com.pocketagentdesk.nativepreview.glass.vibrancy
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.launch

/**
 * Liquid glass levels (spec 2.5). Liquid: refraction, blur, saturation and the angle-dependent rim (Android 13+, AGSL).
 * Frosted: blur and saturation, flat rim (Android 12). Solid: the 0.2 look with solid panels (Android 8–11, battery
 * saver, raised system contrast, JVM tests and previews).
 */
enum class GlassMode { Solid, Frosted, Liquid }

val LocalGlassMode = staticCompositionLocalOf { GlassMode.Solid }

/** What glass on the current page samples; null where nothing is recorded (glass then shows only tint and rim). */
val LocalGlassBackdrop = staticCompositionLocalOf<Backdrop?> { null }

@Composable
fun rememberGlassMode(): GlassMode {
    val context = LocalContext.current
    val view = LocalView.current
    val inspection = LocalInspectionMode.current
    // Robolectric reports hardware drawing but cannot run RenderEffect or AGSL.
    val capable = remember(view) { !inspection && Build.FINGERPRINT != "robolectric" && view.isHardwareAccelerated && Build.VERSION.SDK_INT >= 31 }
    var powerSave by remember { mutableStateOf(false) }
    var contrast by remember { mutableFloatStateOf(0f) }
    DisposableEffect(context, capable) {
        if (!capable) return@DisposableEffect onDispose { }
        val power = context.getSystemService(PowerManager::class.java)
        powerSave = power?.isPowerSaveMode == true
        val receiver = object : BroadcastReceiver() {
            override fun onReceive(c: Context, intent: Intent) {
                powerSave = power?.isPowerSaveMode == true
            }
        }
        ContextCompat.registerReceiver(context, receiver, IntentFilter(PowerManager.ACTION_POWER_SAVE_MODE_CHANGED), ContextCompat.RECEIVER_NOT_EXPORTED)
        val ui = context.getSystemService(UiModeManager::class.java)
        val listener = if (Build.VERSION.SDK_INT >= 34 && ui != null) {
            contrast = ui.contrast
            UiModeManager.ContrastChangeListener { contrast = it }.also { ui.addContrastChangeListener(context.mainExecutor, it) }
        } else null
        onDispose {
            context.unregisterReceiver(receiver)
            if (Build.VERSION.SDK_INT >= 34 && listener != null) ui?.removeContrastChangeListener(listener)
        }
    }
    return when {
        !capable || powerSave || contrast >= 0.5f -> GlassMode.Solid
        Build.VERSION.SDK_INT < 33 -> GlassMode.Frosted
        else -> GlassMode.Liquid
    }
}

/**
 * Small: buttons, capsules and pills (upstream LiquidButton). Large: menus, 会话状态 and the new-conversation sheet
 * (upstream DialogContent). Card: the composer (spec 0.4), the large recipe with the small tier's angled rim.
 */
enum class GlassSize { Small, Large, Card }

private val SmallEffects: BackdropEffectScope.() -> Unit = {
    vibrancy()
    blur(2f.dp.toPx())
    lens(12f.dp.toPx(), 24f.dp.toPx())
}
private val LargeLightEffects: BackdropEffectScope.() -> Unit = {
    colorControls(brightness = 0.2f, saturation = 1.5f)
    blur(16f.dp.toPx())
    lens(24f.dp.toPx(), 48f.dp.toPx(), depthEffect = true)
}
private val LargeDarkEffects: BackdropEffectScope.() -> Unit = {
    colorControls(saturation = 1.5f)
    blur(8f.dp.toPx())
    lens(24f.dp.toPx(), 48f.dp.toPx(), depthEffect = true)
}
/**
 * The composer (spec 0.4): lighter than the large tier, no brightening and half its blur, so what slides behind it
 * still shows as soft shapes; the 60% tint keeps the typed text readable.
 */
private val CardEffects: BackdropEffectScope.() -> Unit = {
    vibrancy()
    blur(8f.dp.toPx())
    lens(20f.dp.toPx(), 40f.dp.toPx(), depthEffect = true)
}
private val DefaultRim = { Highlight.Default }
private val PlainRim = { Highlight.Plain }
private val GlassShadow = { BackdropShadow.Default }

/**
 * Press feedback for glass (spec 2.5, upstream LiquidButton and InteractiveHighlight): the glass grows by 4dp in
 * height with a spring, and a soft light follows the finger. With system animations off only the light shows.
 */
@Stable
class GlassPress internal constructor(private val scope: CoroutineScope, private val grow: Boolean, private val growPx: Float) {
    private val progress = Animatable(0f, 0.001f)
    var position by mutableStateOf(Offset.Zero)
        private set
    internal var height by mutableFloatStateOf(0f)
    val pressProgress: Float get() = progress.value
    val scale: Float get() = if (!grow || height <= 0f) 1f else 1f + growPx / height * progress.value

    internal suspend fun track(source: InteractionSource) {
        source.interactions.collect { interaction ->
            when (interaction) {
                is PressInteraction.Press -> {
                    position = interaction.pressPosition
                    scope.launch { progress.animateTo(1f, PressSpring) }
                }
                is PressInteraction.Release, is PressInteraction.Cancel -> scope.launch { progress.animateTo(0f, PressSpring) }
            }
        }
    }

    private companion object {
        val PressSpring = spring<Float>(dampingRatio = 0.5f, stiffness = 300f, visibilityThreshold = 0.001f)
    }
}

@Composable
fun rememberGlassPress(source: InteractionSource): GlassPress {
    val scope = rememberCoroutineScope()
    val grow = remember { TeleplyMotion.enabled() }
    val growPx = with(LocalDensity.current) { 4.dp.toPx() }
    val press = remember(scope, grow, growPx) { GlassPress(scope, grow, growPx) }
    LaunchedEffect(press, source) { press.track(source) }
    return press
}

/**
 * Glass surface for the control layer (spec 2.5): samples the page's recorded content, applies the size's recipe,
 * a light tint, the rim highlight and a soft shadow. In Solid mode it is the web's solid button or panel instead.
 * [solid] is the fill used then; dark mode adds the 1dp edge the web uses.
 */
@Composable
fun Modifier.glass(
    shape: Shape,
    size: GlassSize = GlassSize.Small,
    tint: Color = Color.Unspecified,
    press: GlassPress? = null,
    solid: Color = Color.Unspecified,
): Modifier {
    val p = LocalTeleply.current
    val mode = LocalGlassMode.current
    if (mode == GlassMode.Solid) {
        val small = size == GlassSize.Small
        val fill = when {
            solid.isSpecified -> solid
            small -> p.control
            else -> p.glassSolid
        }
        val shadow = if (small) TeleplyShadow.Control else TeleplyShadow.Menu
        val edge = if (small) p.edge else p.glassEdge
        return this
            .softShadow(shape, p, shadow)
            .background(fill, shape)
            .then(if (p.dark || !small) Modifier.border(1.dp, edge, shape) else Modifier)
    }
    val backdrop = LocalGlassBackdrop.current ?: emptyBackdrop()
    val fill = when {
        tint.isSpecified -> tint
        size == GlassSize.Small -> p.glassTint
        size == GlassSize.Card -> p.composerTint
        else -> p.glassPanel
    }
    val effects = when {
        size == GlassSize.Small -> SmallEffects
        size == GlassSize.Card -> CardEffects
        p.dark -> LargeDarkEffects
        else -> LargeLightEffects
    }
    val shapeOf = remember(shape) { { shape } }
    val surface: DrawScope.() -> Unit = remember(fill) { { drawRect(fill) } }
    val scale: (() -> Float)? = remember(press) { press?.let { pressed -> { pressed.scale } } }
    val front: (DrawScope.() -> Unit)? = remember(press) {
        press?.let { pressed ->
            val sheen: DrawScope.() -> Unit = {
                val t = pressed.pressProgress
                if (t > 0.01f) {
                    drawRect(Brush.radialGradient(listOf(Color.White.copy(alpha = 0.13f * t), Color.Transparent), center = pressed.position, radius = this.size.maxDimension * 0.8f))
                }
            }
            sheen
        }
    }
    return this
        .then(if (press != null) Modifier.onSizeChanged { press.height = it.height.toFloat() } else Modifier)
        .drawBackdrop(
            backdrop = backdrop,
            shape = shapeOf,
            effects = effects,
            highlight = if (size == GlassSize.Large) PlainRim else DefaultRim,
            shadow = GlassShadow,
            scale = scale,
            onDrawSurface = surface,
            onDrawFront = front,
        )
}

/**
 * One page with glass on top (spec 2.5). [content] is recorded once for the whole page, together with the
 * blurred band under the title bar ([topEdge] tall, status bar included) and the band over the input area
 * ([bottomEdge] tall, spec 0.4); glass in [overlay] samples that recording. Solid mode draws no bottom band: the
 * input area there is opaque, as on the web.
 */
@Composable
fun GlassScreen(modifier: Modifier = Modifier, topEdge: Dp = 0.dp, bottomEdge: Dp = 0.dp, content: @Composable BoxScope.() -> Unit, overlay: @Composable BoxScope.() -> Unit) {
    val mode = LocalGlassMode.current
    Box(modifier) {
        if (mode == GlassMode.Solid) {
            Box(Modifier.matchParentSize(), content = content)
            if (topEdge > 0.dp) TopScrollEdge(null, topEdge)
            CompositionLocalProvider(LocalGlassBackdrop provides null) { overlay() }
        } else {
            val page = rememberLayerBackdrop()
            val body = rememberLayerBackdrop()
            // The extra graphics layers keep each recording a reference to the drawn content, not a second drawing.
            Box(Modifier.matchParentSize().layerBackdrop(page).graphicsLayer()) {
                Box(Modifier.matchParentSize().layerBackdrop(body).graphicsLayer(), content = content)
                if (topEdge > 0.dp) TopScrollEdge(body, topEdge)
                if (bottomEdge > 0.dp) BottomScrollEdge(body, bottomEdge)
            }
            CompositionLocalProvider(LocalGlassBackdrop provides page) { overlay() }
        }
    }
}

/**
 * iOS 26 style scroll edge under the title bar: the content gets blurrier and fades into the page colour towards
 * the top, so the title stays readable. Android 13+ blurs through an AGSL mask (idea from the upstream
 * ProgressiveBlurContent sample); earlier versions only fade.
 */
@Composable
private fun BoxScope.TopScrollEdge(body: Backdrop?, height: Dp) {
    val p = LocalTeleply.current
    val mode = LocalGlassMode.current
    val fadePx = with(LocalDensity.current) { 28.dp.toPx() }
    val band = Modifier.matchParentSizeWidth().height(height)
    if (body != null && mode == GlassMode.Liquid) {
        val tint = p.page
        val effects: BackdropEffectScope.() -> Unit = remember(tint, fadePx) {
            {
                // 8dp: under the title the content should read as soft colour, not as letters (checked on the emulator).
                blur(8f.dp.toPx())
                runtimeShaderEffect("ScrollEdge", ScrollEdgeShader, "content") {
                    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
                        setFloatUniform("size", size.width, size.height)
                        setFloatUniform("fade", fadePx)
                        setColorUniform("tint", tint.toArgb())
                        setFloatUniform("tintIntensity", 0.82f)
                    }
                }
            }
        }
        Box(band.drawPlainBackdrop(body, { RectangleShape }, effects))
    } else {
        val page = p.page
        Box(
            band.drawBehind {
                val solidUntil = ((size.height - fadePx) / size.height).coerceIn(0f, 1f)
                drawRect(Brush.verticalGradient(0f to page.copy(alpha = 0.96f), solidUntil to page.copy(alpha = 0.96f), 1f to page.copy(alpha = 0f)))
            },
        )
    }
}

/**
 * The same edge turned upside down over the input area (spec 0.4 §2.5): messages blur and soften towards the bottom,
 * with a lighter tint than under the title bar so the glass composer still shows colour moving behind it. Its top
 * [fade] fades out. Android 12 only fades.
 */
@Composable
private fun BoxScope.BottomScrollEdge(body: Backdrop, height: Dp) {
    val p = LocalTeleply.current
    val mode = LocalGlassMode.current
    val fadePx = with(LocalDensity.current) { 24.dp.toPx() }
    val band = Modifier.align(Alignment.BottomCenter).fillMaxWidth().height(height)
    if (mode == GlassMode.Liquid) {
        val tint = p.page
        val effects: BackdropEffectScope.() -> Unit = remember(tint, fadePx) {
            {
                blur(6f.dp.toPx())
                runtimeShaderEffect("BottomEdge", BottomEdgeShader, "content") {
                    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
                        setFloatUniform("fade", fadePx)
                        setColorUniform("tint", tint.toArgb())
                        setFloatUniform("tintIntensity", 0.35f)
                    }
                }
            }
        }
        Box(band.drawPlainBackdrop(body, { RectangleShape }, effects))
    } else {
        val page = p.page
        Box(
            band.drawBehind {
                val solidFrom = (fadePx / size.height).coerceIn(0f, 1f)
                drawRect(Brush.verticalGradient(0f to page.copy(alpha = 0f), solidFrom to page.copy(alpha = 0.6f), 1f to page.copy(alpha = 0.6f)))
            },
        )
    }
}

private fun Modifier.matchParentSizeWidth(): Modifier = fillMaxWidth()

/** Full effect down to [fade] above the bottom edge, then fades out; mixes the blurred content with the page colour. */
private const val ScrollEdgeShader = """
uniform shader content;
uniform float2 size;
uniform float fade;
layout(color) uniform half4 tint;
uniform float tintIntensity;

half4 main(float2 coord) {
    float alpha = smoothstep(size.y, size.y - fade, coord.y);
    return mix(content.eval(coord) * alpha, tint * alpha, tintIntensity);
}"""

/** Full effect from [fade] below the top edge downwards; above that it fades out. Lighter mix than the top edge. */
private const val BottomEdgeShader = """
uniform shader content;
uniform float fade;
layout(color) uniform half4 tint;
uniform float tintIntensity;

half4 main(float2 coord) {
    float alpha = smoothstep(0.0, fade, coord.y);
    return mix(content.eval(coord) * alpha, tint * alpha, tintIntensity);
}"""

/** Soft fade above an opaque input area (Solid mode only since 0.4), instead of a divider line (spec 4.3 item 5). */
@Composable
fun BottomFade(modifier: Modifier = Modifier, height: Dp = 20.dp) {
    val page = LocalTeleply.current.page
    Box(modifier.fillMaxWidth().height(height).background(Brush.verticalGradient(listOf(page.copy(alpha = 0f), page))))
}
