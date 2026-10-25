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
   65ab177e90e5c1d8c62e70cf7755841982da65f6): DrawBackdropModifier.kt and internal/ShapeProvider.kt. Changes:
   package renamed; the free-form layerBlock is replaced by a uniform scale (press feedback), exportedBackdrop,
   onDrawBehind, onDrawBackdrop and the inner shadow are not ported; Shadow is BackdropShadow.
 */

package com.pocketagentdesk.teleply.glass

import androidx.compose.runtime.Immutable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.neverEqualPolicy
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.CompositingStrategy
import androidx.compose.ui.graphics.GraphicsLayerScope
import androidx.compose.ui.graphics.Outline
import androidx.compose.ui.graphics.Shape
import androidx.compose.ui.graphics.drawscope.ContentDrawScope
import androidx.compose.ui.graphics.drawscope.DrawScope
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.graphics.layer.GraphicsLayer
import androidx.compose.ui.graphics.layer.drawLayer
import androidx.compose.ui.layout.LayoutCoordinates
import androidx.compose.ui.layout.Measurable
import androidx.compose.ui.layout.MeasureResult
import androidx.compose.ui.layout.MeasureScope
import androidx.compose.ui.node.DrawModifierNode
import androidx.compose.ui.node.GlobalPositionAwareModifierNode
import androidx.compose.ui.node.LayoutModifierNode
import androidx.compose.ui.node.ModifierNodeElement
import androidx.compose.ui.node.ObserverModifierNode
import androidx.compose.ui.node.observeReads
import androidx.compose.ui.node.requireGraphicsContext
import androidx.compose.ui.platform.InspectorInfo
import androidx.compose.ui.unit.Constraints
import androidx.compose.ui.unit.Density
import androidx.compose.ui.unit.IntOffset
import androidx.compose.ui.unit.IntSize
import androidx.compose.ui.unit.LayoutDirection

private val DefaultHighlight = { Highlight.Default }
private val DefaultShadow = { BackdropShadow.Default }

/**
 * Liquid glass: samples [backdrop] behind this node, runs [effects] (colour → blur → lens, in that order), clips it to
 * [shape] and adds the rim highlight and shadow. [scale] is the node's press scale; the sampled image is not scaled.
 * [onDrawSurface] is the tint, drawn over the glass and under the content.
 */
fun Modifier.drawBackdrop(
    backdrop: Backdrop,
    shape: () -> Shape,
    effects: BackdropEffectScope.() -> Unit,
    highlight: (() -> Highlight?)? = DefaultHighlight,
    shadow: (() -> BackdropShadow?)? = DefaultShadow,
    scale: (() -> Float)? = null,
    onDrawSurface: (DrawScope.() -> Unit)? = null,
    onDrawFront: (DrawScope.() -> Unit)? = null,
): Modifier {
    val shapeProvider = ShapeProvider(shape)
    return this
        .then(if (scale != null) Modifier.graphicsLayer { val s = scale(); scaleX = s; scaleY = s } else Modifier)
        .then(if (shadow != null) ShadowElement(shapeProvider, shadow) else Modifier)
        .then(if (highlight != null) HighlightElement(shapeProvider, highlight) else Modifier)
        .then(DrawBackdropElement(backdrop, shapeProvider, effects, scale, onDrawSurface, onDrawFront))
}

/** The same sampling with no highlight or shadow, e.g. the blurred band behind a title bar. */
fun Modifier.drawPlainBackdrop(
    backdrop: Backdrop,
    shape: () -> Shape,
    effects: BackdropEffectScope.() -> Unit,
    onDrawSurface: (DrawScope.() -> Unit)? = null,
): Modifier = this.then(DrawBackdropElement(backdrop, ShapeProvider(shape), effects, null, onDrawSurface, null))

private class DrawBackdropElement(
    val backdrop: Backdrop,
    val shapeProvider: ShapeProvider,
    val effects: BackdropEffectScope.() -> Unit,
    val scale: (() -> Float)?,
    val onDrawSurface: (DrawScope.() -> Unit)?,
    val onDrawFront: (DrawScope.() -> Unit)?,
) : ModifierNodeElement<DrawBackdropNode>() {

    override fun create(): DrawBackdropNode = DrawBackdropNode(backdrop, shapeProvider, effects, scale, onDrawSurface, onDrawFront)

    override fun update(node: DrawBackdropNode) {
        node.backdrop = backdrop
        node.shapeProvider = shapeProvider
        node.effects = effects
        node.scale = scale
        node.onDrawSurface = onDrawSurface
        node.onDrawFront = onDrawFront
        node.invalidateDrawCache()
    }

    override fun InspectorInfo.inspectableProperties() {
        name = "drawBackdrop"
        properties["backdrop"] = backdrop
        properties["shapeProvider"] = shapeProvider
        properties["effects"] = effects
    }

    override fun equals(other: Any?): Boolean {
        if (this === other) return true
        if (other !is DrawBackdropElement) return false
        return backdrop == other.backdrop && shapeProvider == other.shapeProvider && effects == other.effects &&
            scale == other.scale && onDrawSurface == other.onDrawSurface && onDrawFront == other.onDrawFront
    }

    override fun hashCode(): Int {
        var result = backdrop.hashCode()
        result = 31 * result + shapeProvider.hashCode()
        result = 31 * result + effects.hashCode()
        result = 31 * result + (scale?.hashCode() ?: 0)
        result = 31 * result + (onDrawSurface?.hashCode() ?: 0)
        result = 31 * result + (onDrawFront?.hashCode() ?: 0)
        return result
    }
}

private class DrawBackdropNode(
    var backdrop: Backdrop,
    var shapeProvider: ShapeProvider,
    var effects: BackdropEffectScope.() -> Unit,
    var scale: (() -> Float)?,
    var onDrawSurface: (DrawScope.() -> Unit)?,
    var onDrawFront: (DrawScope.() -> Unit)?,
) : LayoutModifierNode, DrawModifierNode, GlobalPositionAwareModifierNode, ObserverModifierNode, Modifier.Node() {

    private val effectScope = object : BackdropEffectScopeImpl() {
        override val shape: Shape get() = shapeProvider.innerShape
    }

    private var graphicsLayer: GraphicsLayer? = null

    // The content (and this node's own drawing) is clipped to the glass shape in an offscreen layer.
    private val layoutLayerBlock: GraphicsLayerScope.() -> Unit = {
        clip = true
        shape = shapeProvider.shape
        compositingStrategy = CompositingStrategy.Offscreen
    }

    private var layoutCoordinates: LayoutCoordinates? by mutableStateOf(null, neverEqualPolicy())

    private var padding by mutableFloatStateOf(0f)

    private val recordBackdropBlock: DrawScope.() -> Unit = {
        val canvas = drawContext.canvas
        val padding = padding
        if (padding != 0f) canvas.translate(padding, padding)
        val s = scale?.invoke() ?: 1f
        with(backdrop) { drawBackdrop(effectScope, layoutCoordinates, s) }
        if (padding != 0f) canvas.translate(-padding, -padding)
    }

    private val drawBackdropLayer: DrawScope.() -> Unit = {
        val layer = graphicsLayer
        if (layer != null) {
            val padding = padding
            recordLayer(
                this@DrawBackdropNode,
                layer,
                size = IntSize(size.width.toInt() + padding.toInt() * 2, size.height.toInt() + padding.toInt() * 2),
                block = recordBackdropBlock,
            )
            layer.topLeft = if (padding != 0f) IntOffset(-padding.toInt(), -padding.toInt()) else IntOffset.Zero
            drawLayer(layer)
        }
    }

    override fun MeasureScope.measure(measurable: Measurable, constraints: Constraints): MeasureResult {
        val placeable = measurable.measure(constraints)
        return layout(placeable.width, placeable.height) {
            placeable.placeWithLayer(IntOffset.Zero, layerBlock = layoutLayerBlock)
        }
    }

    override fun ContentDrawScope.draw() {
        if (effectScope.update(this)) updateEffects()
        drawBackdropLayer()
        onDrawSurface?.invoke(this)
        drawContent()
        onDrawFront?.invoke(this)
    }

    override fun onGloballyPositioned(coordinates: LayoutCoordinates) {
        if (coordinates.isAttached) {
            if (backdrop.isCoordinatesDependent) layoutCoordinates = coordinates
            else if (layoutCoordinates != null) layoutCoordinates = null
        }
    }

    override fun onObservedReadsChanged() {
        invalidateDrawCache()
    }

    fun invalidateDrawCache() {
        observeReads { updateEffects() }
    }

    private fun updateEffects() {
        if (!isRenderEffectSupported()) return
        effectScope.apply(effects)
        graphicsLayer?.renderEffect = effectScope.renderEffect
        padding = effectScope.padding
    }

    override fun onAttach() {
        graphicsLayer = requireGraphicsContext().createGraphicsLayer()
        observeReads { updateEffects() }
    }

    override fun onDetach() {
        graphicsLayer?.let { requireGraphicsContext().releaseGraphicsLayer(it) }
        graphicsLayer = null
        effectScope.reset()
        layoutCoordinates = null
    }
}

/** Caches the outline per size so the glass, its highlight and its shadow share one shape (upstream ShapeProvider). */
@Immutable
internal class ShapeProvider(val shapeBlock: () -> Shape) {

    private var cachedShape: Shape? = null
    private var cachedOutline: Outline? = null
    private var cachedSize: Size = Size.Unspecified
    private var cachedDirection: LayoutDirection? = null
    private var cachedDensity: Float? = null

    val innerShape: Shape get() = shapeBlock()

    val shape: Shape = object : Shape {
        override fun createOutline(size: Size, layoutDirection: LayoutDirection, density: Density): Outline {
            val shape = shapeBlock()
            if (cachedShape != shape) {
                cachedShape = shape
                cachedOutline = null
            }
            if (cachedOutline == null || cachedSize != size || cachedDirection != layoutDirection || cachedDensity != density.density) {
                cachedSize = size
                cachedDirection = layoutDirection
                cachedDensity = density.density
                cachedOutline = shape.createOutline(size, layoutDirection, density)
            }
            return cachedOutline!!
        }
    }
}
