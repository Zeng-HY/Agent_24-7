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
   65ab177e90e5c1d8c62e70cf7755841982da65f6): highlight/Highlight.kt, highlight/HighlightStyle.kt,
   highlight/HighlightModifier.kt, internal/Outline.kt and the Android internal/Paint.kt merged into this file.
   Changes: package renamed; Android only (android.graphics.RuntimeShader and BlurMaskFilter used directly).
   Default values are unchanged. Teleply 0.9.1: the rim shaders come from the app-wide SharedRuntimeShaders (Effects.kt).
 */

package com.pocketagentdesk.teleply.glass

import android.graphics.BlurMaskFilter
import android.graphics.RuntimeShader
import android.os.Build
import androidx.annotation.FloatRange
import androidx.annotation.RequiresApi
import androidx.compose.foundation.shape.CornerBasedShape
import androidx.compose.runtime.Immutable
import androidx.compose.runtime.Stable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.BlendMode
import androidx.compose.ui.graphics.Canvas
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Outline
import androidx.compose.ui.graphics.Paint
import androidx.compose.ui.graphics.PaintingStyle
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.Shape
import androidx.compose.ui.graphics.drawOutline
import androidx.compose.ui.graphics.drawscope.ContentDrawScope
import androidx.compose.ui.graphics.drawscope.DrawScope
import androidx.compose.ui.graphics.drawscope.translate
import androidx.compose.ui.graphics.layer.GraphicsLayer
import androidx.compose.ui.graphics.layer.drawLayer
import androidx.compose.ui.graphics.toArgb
import androidx.compose.ui.node.DrawModifierNode
import androidx.compose.ui.node.ModifierNodeElement
import androidx.compose.ui.node.invalidateDraw
import androidx.compose.ui.node.requireGraphicsContext
import androidx.compose.ui.platform.InspectorInfo
import androidx.compose.ui.unit.Density
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.IntSize
import androidx.compose.ui.unit.LayoutDirection
import androidx.compose.ui.unit.dp
import androidx.compose.ui.util.fastCoerceAtMost
import kotlin.math.PI
import kotlin.math.ceil

/** The bright band along the rim: not a stroke, it fades by angle (Fresnel-like). */
@Immutable
data class Highlight(
    val width: Dp = 0.5f.dp,
    val blurRadius: Dp = width / 2f,
    @param:FloatRange(from = 0.0, to = 1.0) val alpha: Float = 1f,
    val style: HighlightStyle = HighlightStyle.Default,
) {
    companion object {
        @Stable val Default: Highlight = Highlight()
        @Stable val Ambient: Highlight = Highlight(style = HighlightStyle.Ambient)
        @Stable val Plain: Highlight = Highlight(style = HighlightStyle.Plain)
    }
}

@Immutable
interface HighlightStyle {

    val color: Color

    val blendMode: BlendMode

    fun DrawScope.createShader(shape: Shape, cache: RuntimeShaderCache): RuntimeShader?

    @Immutable
    data class Plain(
        override val color: Color = Color.White.copy(alpha = 0.38f),
        override val blendMode: BlendMode = BlendMode.Plus,
    ) : HighlightStyle {
        override fun DrawScope.createShader(shape: Shape, cache: RuntimeShaderCache): RuntimeShader? = null
    }

    /** Lit from [angle] degrees (45 = top left); [falloff] sharpens the fade. */
    @Immutable
    data class Default(
        override val color: Color = Color.White.copy(alpha = 0.5f),
        override val blendMode: BlendMode = BlendMode.Plus,
        val angle: Float = 45f,
        @param:FloatRange(from = 0.0) val falloff: Float = 1f,
    ) : HighlightStyle {
        override fun DrawScope.createShader(shape: Shape, cache: RuntimeShaderCache): RuntimeShader? =
            if (isRuntimeShaderSupported()) defaultShader(cache, shape, color, angle, falloff) else null
    }

    @Immutable
    data class Ambient(@param:FloatRange(from = 0.0, to = 1.0) val intensity: Float = 0.38f) : HighlightStyle {
        override val color: Color = Color.White.copy(alpha = intensity)
        override val blendMode: BlendMode = DrawScope.DefaultBlendMode
        override fun DrawScope.createShader(shape: Shape, cache: RuntimeShaderCache): RuntimeShader? =
            if (isRuntimeShaderSupported()) ambientShader(cache, shape) else null
    }

    companion object {
        @Stable val Default: Default = Default()
        @Stable val Ambient: Ambient = Ambient()
        @Stable val Plain: Plain = Plain()
    }
}

@RequiresApi(Build.VERSION_CODES.TIRAMISU)
private fun DrawScope.defaultShader(cache: RuntimeShaderCache, shape: Shape, color: Color, angle: Float, falloff: Float): RuntimeShader =
    cache.obtainRuntimeShader("Default", DefaultHighlightShaderString).apply {
        setFloatUniform("size", size.width, size.height)
        setFloatUniform("cornerRadii", cornerRadiiOf(shape))
        setColorUniform("color", color.copy(alpha = 1f).toArgb())
        setFloatUniform("angle", angle * (PI / 180f).toFloat())
        setFloatUniform("falloff", falloff)
    }

@RequiresApi(Build.VERSION_CODES.TIRAMISU)
private fun DrawScope.ambientShader(cache: RuntimeShaderCache, shape: Shape): RuntimeShader =
    cache.obtainRuntimeShader("Ambient", AmbientHighlightShaderString).apply {
        setFloatUniform("size", size.width, size.height)
        setFloatUniform("cornerRadii", cornerRadiiOf(shape))
        setFloatUniform("angle", 45f * (PI / 180f).toFloat())
        setFloatUniform("falloff", 1f)
    }

private fun DrawScope.cornerRadiiOf(shape: Shape): FloatArray {
    val size = size
    val maxRadius = size.minDimension / 2f
    val corners = shape as? CornerBasedShape ?: return FloatArray(4) { maxRadius }
    val isLtr = layoutDirection == LayoutDirection.Ltr
    val topLeft = if (isLtr) corners.topStart.toPx(size, this) else corners.topEnd.toPx(size, this)
    val topRight = if (isLtr) corners.topEnd.toPx(size, this) else corners.topStart.toPx(size, this)
    val bottomRight = if (isLtr) corners.bottomEnd.toPx(size, this) else corners.bottomStart.toPx(size, this)
    val bottomLeft = if (isLtr) corners.bottomStart.toPx(size, this) else corners.bottomEnd.toPx(size, this)
    return floatArrayOf(
        topLeft.fastCoerceAtMost(maxRadius),
        topRight.fastCoerceAtMost(maxRadius),
        bottomRight.fastCoerceAtMost(maxRadius),
        bottomLeft.fastCoerceAtMost(maxRadius),
    )
}

internal fun Canvas.clipOutline(outline: Outline, path: Path?) {
    when (outline) {
        is Outline.Rectangle -> clipRect(outline.rect)
        is Outline.Rounded -> {
            path!!.rewind()
            path.addRoundRect(outline.roundRect)
            clipPath(path)
        }
        is Outline.Generic -> clipPath(outline.path)
    }
}

internal fun Paint.blur(radius: Float) {
    asFrameworkPaint().maskFilter = if (radius > 0f) BlurMaskFilter(radius, BlurMaskFilter.Blur.NORMAL) else null
}

internal class HighlightElement(val shapeProvider: ShapeProvider, val highlight: () -> Highlight?) : ModifierNodeElement<HighlightNode>() {

    override fun create(): HighlightNode = HighlightNode(shapeProvider, highlight)

    override fun update(node: HighlightNode) {
        node.shapeProvider = shapeProvider
        node.highlight = highlight
        node.invalidateDraw()
    }

    override fun InspectorInfo.inspectableProperties() {
        name = "highlight"
        properties["shapeProvider"] = shapeProvider
        properties["highlight"] = highlight
    }

    override fun equals(other: Any?): Boolean =
        this === other || other is HighlightElement && shapeProvider == other.shapeProvider && highlight == other.highlight

    override fun hashCode(): Int = 31 * shapeProvider.hashCode() + highlight.hashCode()
}

internal class HighlightNode(var shapeProvider: ShapeProvider, var highlight: () -> Highlight?) : DrawModifierNode, Modifier.Node() {

    override val shouldAutoInvalidate: Boolean = false

    private var highlightLayer: GraphicsLayer? = null
    private val paint = Paint().apply { style = PaintingStyle.Stroke }
    private var clipPath: Path? = null
    private val shaderCache = RuntimeShaderCacheImpl()

    override fun ContentDrawScope.draw() {
        val highlight = highlight()
        drawContent()
        if (highlight == null || highlight.width.value <= 0f) return
        val layer = highlightLayer ?: return
        val size = size
        val density: Density = this
        val safeSize = IntSize(ceil(size.width).toInt() + 2, ceil(size.height).toInt() + 2)
        val outline = shapeProvider.shape.createOutline(size, layoutDirection, density)
        val clip = if (outline is Outline.Rounded) clipPath ?: Path().also { clipPath = it } else null
        paint.color = highlight.style.color
        paint.strokeWidth = ceil(highlight.width.toPx().fastCoerceAtMost(size.minDimension / 2f)) * 2f
        paint.blur(highlight.blurRadius.toPx())
        val shader = with(highlight.style) { createShader(shapeProvider.shape, shaderCache) }
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) paint.asFrameworkPaint().shader = shader
        else paint.asFrameworkPaint().shader = null
        layer.alpha = highlight.alpha
        layer.blendMode = highlight.style.blendMode
        layer.record(safeSize) {
            translate(1f, 1f) {
                val canvas = drawContext.canvas
                canvas.save()
                canvas.clipOutline(outline, clip)
                canvas.drawOutline(outline, paint)
                canvas.restore()
            }
        }
        translate(-1f, -1f) { drawLayer(layer) }
    }

    override fun onAttach() {
        highlightLayer = requireGraphicsContext().createGraphicsLayer()
    }

    override fun onDetach() {
        highlightLayer?.let { requireGraphicsContext().releaseGraphicsLayer(it) }
        highlightLayer = null
        clipPath = null
        shaderCache.clear()
    }
}
