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
   65ab177e90e5c1d8c62e70cf7755841982da65f6): shadow/Shadow.kt and shadow/ShadowModifier.kt. Changes: package
   renamed; the class is called BackdropShadow so it does not clash with Compose's own Shadow type. The inner shadow
   is not ported (Teleply does not use it). Default values are unchanged.
 */

package com.pocketagentdesk.nativepreview.glass

import androidx.annotation.FloatRange
import androidx.compose.runtime.Immutable
import androidx.compose.runtime.Stable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.BlendMode
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Paint
import androidx.compose.ui.graphics.drawOutline
import androidx.compose.ui.graphics.drawscope.ContentDrawScope
import androidx.compose.ui.graphics.drawscope.DrawScope
import androidx.compose.ui.graphics.drawscope.translate
import androidx.compose.ui.graphics.layer.CompositingStrategy
import androidx.compose.ui.graphics.layer.GraphicsLayer
import androidx.compose.ui.graphics.layer.drawLayer
import androidx.compose.ui.node.DrawModifierNode
import androidx.compose.ui.node.ModifierNodeElement
import androidx.compose.ui.node.invalidateDraw
import androidx.compose.ui.node.requireGraphicsContext
import androidx.compose.ui.platform.InspectorInfo
import androidx.compose.ui.unit.Density
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.DpOffset
import androidx.compose.ui.unit.IntSize
import androidx.compose.ui.unit.dp
import kotlin.math.ceil

/** Soft outer shadow that lifts the glass; it is cut out under the glass so it never shows through the tint. */
@Immutable
data class BackdropShadow(
    val radius: Dp = 24f.dp,
    val offset: DpOffset = DpOffset(0f.dp, radius / 6f),
    val color: Color = Color.Black.copy(alpha = 0.1f),
    @param:FloatRange(from = 0.0, to = 1.0) val alpha: Float = 1f,
    val blendMode: BlendMode = DrawScope.DefaultBlendMode,
) {
    companion object {
        @Stable val Default: BackdropShadow = BackdropShadow()
    }
}

internal class ShadowElement(val shapeProvider: ShapeProvider, val shadow: () -> BackdropShadow?) : ModifierNodeElement<ShadowNode>() {

    override fun create(): ShadowNode = ShadowNode(shapeProvider, shadow)

    override fun update(node: ShadowNode) {
        node.shapeProvider = shapeProvider
        node.shadow = shadow
        node.invalidateDraw()
    }

    override fun InspectorInfo.inspectableProperties() {
        name = "shadow"
        properties["shapeProvider"] = shapeProvider
        properties["shadow"] = shadow
    }

    override fun equals(other: Any?): Boolean =
        this === other || other is ShadowElement && shapeProvider == other.shapeProvider && shadow == other.shadow

    override fun hashCode(): Int = 31 * shapeProvider.hashCode() + shadow.hashCode()
}

internal class ShadowNode(var shapeProvider: ShapeProvider, var shadow: () -> BackdropShadow?) : DrawModifierNode, Modifier.Node() {

    override val shouldAutoInvalidate: Boolean = false

    private var shadowLayer: GraphicsLayer? = null
    private val paint = Paint()

    override fun ContentDrawScope.draw() {
        val shadow = shadow() ?: return drawContent()
        val layer = shadowLayer
        if (layer != null) {
            val size = size
            val density: Density = this
            val radius = shadow.radius.toPx()
            val offsetX = shadow.offset.x.toPx()
            val offsetY = shadow.offset.y.toPx()
            val shadowSize = IntSize(ceil(size.width + radius * 4f + offsetX).toInt(), ceil(size.height + radius * 4f + offsetY).toInt())
            val outline = shapeProvider.shape.createOutline(size, layoutDirection, density)
            paint.color = shadow.color
            paint.blur(radius)
            layer.alpha = shadow.alpha
            layer.blendMode = shadow.blendMode
            layer.record(shadowSize) {
                translate(radius * 2f + offsetX, radius * 2f + offsetY) {
                    val canvas = drawContext.canvas
                    canvas.drawOutline(outline, paint)
                    canvas.translate(-offsetX, -offsetY)
                    canvas.drawOutline(outline, ShadowMaskPaint)
                    canvas.translate(offsetX, offsetY)
                }
            }
            translate(-radius * 2f, -radius * 2f) { drawLayer(layer) }
        }
        drawContent()
    }

    override fun onAttach() {
        shadowLayer = requireGraphicsContext().createGraphicsLayer().apply { compositingStrategy = CompositingStrategy.Offscreen }
    }

    override fun onDetach() {
        shadowLayer?.let { requireGraphicsContext().releaseGraphicsLayer(it) }
        shadowLayer = null
    }
}

private val ShadowMaskPaint = Paint().apply { blendMode = BlendMode.Clear }
