/*
   Copyright 2025 Kyant

   Licensed under the Apache License, Version 2.0 (the "License");
   you may not use this file except in compliance with the License.
   You may obtain a copy of the License at

       http://www.apache.org/licenses/LICENSE-2.0

   Unless required by applicable law or agreed to in writing, software
   distributed under the License is distributed on an "AS IS" BASIS,
   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
   See the License for the specific language governing permissions and
   limitations under the License.

   Modified for Teleply in 2026: ported from Kyant0/AndroidLiquidGlass ("backdrop" module, commit
   65ab177e90e5c1d8c62e70cf7755841982da65f6): BackdropEffectScope.kt, RuntimeShader.kt, RuntimeShaderCache.kt,
   Platform.kt, effects/Blur.kt, effects/ColorFilter.kt, effects/Lens.kt, effects/RenderEffect.kt and the Android
   internal/RenderEffect.kt merged into this file. Changes: package renamed; Android only, so the multiplatform
   RuntimeShader wrapper is replaced by android.graphics.RuntimeShader; kyant "shapes" support removed from lens()
   (Teleply passes Compose RoundedCornerShape only). Effect math and default values are unchanged.
   Changed again for Teleply 0.9.1: one compiled shader per key for the whole app (SharedRuntimeShaders), which can
   be compiled ahead on a background thread, instead of a new compile for every glass node.
 */

package com.pocketagentdesk.teleply.glass

import android.graphics.RuntimeShader
import android.os.Build
import androidx.annotation.ChecksSdkIntAtLeast
import androidx.annotation.FloatRange
import androidx.annotation.RequiresApi
import androidx.compose.foundation.shape.CornerBasedShape
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.BlurEffect
import androidx.compose.ui.graphics.ColorFilter
import androidx.compose.ui.graphics.ColorMatrix
import androidx.compose.ui.graphics.ColorMatrixColorFilter
import androidx.compose.ui.graphics.RenderEffect
import androidx.compose.ui.graphics.Shape
import androidx.compose.ui.graphics.TileMode
import androidx.compose.ui.graphics.asAndroidColorFilter
import androidx.compose.ui.graphics.asComposeRenderEffect
import androidx.compose.ui.graphics.drawscope.DrawScope
import androidx.compose.ui.unit.Density
import androidx.compose.ui.unit.LayoutDirection
import androidx.compose.ui.util.fastCoerceAtLeast
import androidx.compose.ui.util.fastCoerceAtMost
import java.util.concurrent.ConcurrentHashMap

@ChecksSdkIntAtLeast(api = Build.VERSION_CODES.S)
fun isRenderEffectSupported(): Boolean = Build.VERSION.SDK_INT >= Build.VERSION_CODES.S

@ChecksSdkIntAtLeast(api = Build.VERSION_CODES.TIRAMISU)
fun isRuntimeShaderSupported(): Boolean = Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU

/** Shaders are compiled once per key, then only their uniforms change. */
sealed interface RuntimeShaderCache {
    @RequiresApi(Build.VERSION_CODES.TIRAMISU)
    fun obtainRuntimeShader(key: String, string: String): RuntimeShader
}

/**
 * One compiled copy of each shader for the whole app (Teleply 0.9.1). Upstream compiled the AGSL again, on the main
 * thread, for every glass node it attached, so every sheet, menu and glass button that appeared paid for it once more.
 * Sharing one instance is safe: each user sets every uniform right before using it, on the main thread, and a
 * RenderEffect or a recorded paint keeps its own copy of the uniform values from that moment.
 */
internal object SharedRuntimeShaders {
    private val shaders = ConcurrentHashMap<String, RuntimeShader>()

    @RequiresApi(Build.VERSION_CODES.TIRAMISU)
    fun obtain(key: String, string: String): RuntimeShader = shaders[key] ?: RuntimeShader(string).let { shaders.putIfAbsent(key, it) ?: it }

    /** Compiles [sources] (key to AGSL) on a background thread, so the first glass on screen does not wait for them. */
    fun prewarm(sources: List<Pair<String, String>>) {
        if (!isRuntimeShaderSupported()) return
        Thread({
            sources.forEach { (key, string) -> runCatching { obtain(key, string) } }
        }, "glass-shaders").apply { isDaemon = true; priority = Thread.MIN_PRIORITY }.start()
    }
}

internal class RuntimeShaderCacheImpl : RuntimeShaderCache {
    @RequiresApi(Build.VERSION_CODES.TIRAMISU)
    override fun obtainRuntimeShader(key: String, string: String): RuntimeShader = SharedRuntimeShaders.obtain(key, string)

    fun clear() = Unit
}

/** What an effects block sees: the glass size and shape, plus the render effect built so far. */
sealed interface BackdropEffectScope : Density, RuntimeShaderCache {
    val size: Size
    val layoutDirection: LayoutDirection
    val shape: Shape
    var padding: Float
    var renderEffect: RenderEffect?
}

internal abstract class BackdropEffectScopeImpl : BackdropEffectScope, RuntimeShaderCache {

    override var density: Float = 1f
    override var fontScale: Float = 1f
    override var size: Size = Size.Unspecified
    override var layoutDirection: LayoutDirection = LayoutDirection.Ltr
    override var padding: Float = 0f
    override var renderEffect: RenderEffect? = null

    private val runtimeShaderCache = RuntimeShaderCacheImpl()

    @RequiresApi(Build.VERSION_CODES.TIRAMISU)
    override fun obtainRuntimeShader(key: String, string: String): RuntimeShader = runtimeShaderCache.obtainRuntimeShader(key, string)

    fun update(scope: DrawScope): Boolean {
        val changed = scope.density != density || scope.fontScale != fontScale || scope.size != size || scope.layoutDirection != layoutDirection
        if (changed) {
            density = scope.density
            fontScale = scope.fontScale
            size = scope.size
            layoutDirection = scope.layoutDirection
        }
        return changed
    }

    fun apply(effects: BackdropEffectScope.() -> Unit) {
        padding = 0f
        renderEffect = null
        effects()
    }

    fun reset() {
        density = 1f
        fontScale = 1f
        size = Size.Unspecified
        layoutDirection = LayoutDirection.Ltr
        padding = 0f
        renderEffect = null
        runtimeShaderCache.clear()
    }
}

@RequiresApi(Build.VERSION_CODES.S)
internal fun RenderEffect?.chain(other: RenderEffect): RenderEffect =
    if (this != null) android.graphics.RenderEffect.createChainEffect(other.asAndroidRenderEffect(), asAndroidRenderEffect()).asComposeRenderEffect()
    else other

@RequiresApi(Build.VERSION_CODES.TIRAMISU)
internal fun runtimeShaderRenderEffect(shader: RuntimeShader, uniformShaderName: String): RenderEffect =
    android.graphics.RenderEffect.createRuntimeShaderEffect(shader, uniformShaderName).asComposeRenderEffect()

@RequiresApi(Build.VERSION_CODES.S)
internal fun colorFilterRenderEffect(renderEffect: RenderEffect?, colorFilter: ColorFilter): RenderEffect =
    if (renderEffect != null) android.graphics.RenderEffect.createColorFilterEffect(colorFilter.asAndroidColorFilter(), renderEffect.asAndroidRenderEffect()).asComposeRenderEffect()
    else android.graphics.RenderEffect.createColorFilterEffect(colorFilter.asAndroidColorFilter()).asComposeRenderEffect()

/** Gaussian blur of what is behind the glass. */
fun BackdropEffectScope.blur(@FloatRange(from = 0.0) radius: Float, edgeTreatment: TileMode = TileMode.Clamp) {
    if (!isRenderEffectSupported()) return
    if (radius <= 0f) return
    if (edgeTreatment != TileMode.Clamp || renderEffect != null) {
        if (radius > padding) padding = radius
    }
    renderEffect = BlurEffect(renderEffect, radius, radius, edgeTreatment)
}

fun BackdropEffectScope.colorFilter(colorFilter: ColorFilter) {
    if (!isRenderEffectSupported()) return
    renderEffect = colorFilterRenderEffect(renderEffect, colorFilter)
}

fun BackdropEffectScope.opacity(@FloatRange(from = 0.0, to = 1.0) alpha: Float) {
    colorFilter(
        ColorMatrixColorFilter(
            ColorMatrix(
                floatArrayOf(
                    1f, 0f, 0f, 0f, 0f,
                    0f, 1f, 0f, 0f, 0f,
                    0f, 0f, 1f, 0f, 0f,
                    0f, 0f, 0f, alpha, 0f,
                ),
            ),
        ),
    )
}

fun BackdropEffectScope.colorControls(brightness: Float = 0f, contrast: Float = 1f, saturation: Float = 1f) {
    if (brightness == 0f && contrast == 1f && saturation == 1f) return
    colorFilter(colorControlsColorFilter(brightness, contrast, saturation))
}

private val VibrantColorFilter = colorControlsColorFilter(saturation = 1.5f)

/** Saturation ×1.5: blur greys colours out, this brings them back so the glass looks clear, not grey. */
fun BackdropEffectScope.vibrancy() {
    colorFilter(VibrantColorFilter)
}

private fun colorControlsColorFilter(brightness: Float = 0f, contrast: Float = 1f, saturation: Float = 1f): ColorFilter {
    val invSat = 1f - saturation
    val r = 0.213f * invSat
    val g = 0.715f * invSat
    val b = 0.072f * invSat
    val c = contrast
    val t = (0.5f - c * 0.5f + brightness) * 255f
    val s = saturation
    val cr = c * r
    val cg = c * g
    val cb = c * b
    val cs = c * s
    return ColorMatrixColorFilter(
        ColorMatrix(
            floatArrayOf(
                cr + cs, cg, cb, 0f, t,
                cr, cg + cs, cb, 0f, t,
                cr, cg, cb + cs, 0f, t,
                0f, 0f, 0f, 1f, 0f,
            ),
        ),
    )
}

/**
 * Refraction at the edge, like a lens raised at the rim. Both values are pixels. Needs Android 13 (AGSL); a no-op before.
 * The shape must be a Compose CornerBasedShape such as RoundedCornerShape.
 */
fun BackdropEffectScope.lens(
    @FloatRange(from = 0.0) refractionHeight: Float,
    @FloatRange(from = 0.0) refractionAmount: Float,
    depthEffect: Boolean = false,
    chromaticAberration: Boolean = false,
) {
    if (!isRuntimeShaderSupported()) return
    if (refractionHeight <= 0f || refractionAmount <= 0f) return
    if (padding > 0f) padding = (padding - refractionHeight).fastCoerceAtLeast(0f)
    val cornerRadii = cornerRadii ?: throw UnsupportedOperationException("Only CornerBasedShape is supported in lens effects.")
    val shader =
        if (!chromaticAberration) obtainRuntimeShader("Refraction", RoundedRectRefractionShaderString)
        else obtainRuntimeShader("RefractionWithDispersion", RoundedRectRefractionWithDispersionShaderString)
    shader.setFloatUniform("size", size.width, size.height)
    shader.setFloatUniform("offset", -padding, -padding)
    shader.setFloatUniform("cornerRadii", cornerRadii)
    shader.setFloatUniform("refractionHeight", refractionHeight)
    shader.setFloatUniform("refractionAmount", -refractionAmount)
    shader.setFloatUniform("depthEffect", if (depthEffect) 1f else 0f)
    if (chromaticAberration) shader.setFloatUniform("chromaticAberration", 1f)
    effect(runtimeShaderRenderEffect(shader, "content"))
}

private val BackdropEffectScope.cornerRadii: FloatArray?
    get() {
        val shape = shape as? CornerBasedShape ?: return null
        val size = size
        val maxRadius = size.minDimension / 2f
        val isLtr = layoutDirection == LayoutDirection.Ltr
        val topLeft = if (isLtr) shape.topStart.toPx(size, this) else shape.topEnd.toPx(size, this)
        val topRight = if (isLtr) shape.topEnd.toPx(size, this) else shape.topStart.toPx(size, this)
        val bottomRight = if (isLtr) shape.bottomEnd.toPx(size, this) else shape.bottomStart.toPx(size, this)
        val bottomLeft = if (isLtr) shape.bottomStart.toPx(size, this) else shape.bottomEnd.toPx(size, this)
        return floatArrayOf(
            topLeft.fastCoerceAtMost(maxRadius),
            topRight.fastCoerceAtMost(maxRadius),
            bottomRight.fastCoerceAtMost(maxRadius),
            bottomLeft.fastCoerceAtMost(maxRadius),
        )
    }

fun BackdropEffectScope.effect(effect: RenderEffect) {
    if (!isRenderEffectSupported()) return
    renderEffect = renderEffect.chain(effect)
}

/** Any AGSL effect on the sampled content, e.g. the progressive blur mask of the scroll edge. Android 13+. */
fun BackdropEffectScope.runtimeShaderEffect(key: String, shaderString: String, uniformShaderName: String, block: RuntimeShader.() -> Unit) {
    if (!isRuntimeShaderSupported()) return
    renderEffect = renderEffect.chain(runtimeShaderRenderEffect(obtainRuntimeShader(key, shaderString).apply(block), uniformShaderName))
}
