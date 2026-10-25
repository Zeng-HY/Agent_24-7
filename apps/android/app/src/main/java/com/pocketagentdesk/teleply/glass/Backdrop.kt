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
   65ab177e90e5c1d8c62e70cf7755841982da65f6): Backdrop.kt, backdrops/LayerBackdrop.kt,
   backdrops/LayerBackdropModifier.kt, backdrops/EmptyBackdrop.kt and internal/LayerRecorder.kt merged into this
   Android-only file. Changes: package renamed; builds with Compose 1.9.3 and Kotlin 2.2 (no context parameters);
   the inverse layer transform is reduced to a uniform scale, the only transform Teleply puts on glass;
   the custom onDraw hook of LayerBackdrop is dropped.
 */

package com.pocketagentdesk.teleply.glass

import androidx.compose.runtime.Composable
import androidx.compose.runtime.Immutable
import androidx.compose.runtime.Stable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.drawscope.ContentDrawScope
import androidx.compose.ui.graphics.drawscope.DrawScope
import androidx.compose.ui.graphics.drawscope.withTransform
import androidx.compose.ui.graphics.layer.GraphicsLayer
import androidx.compose.ui.graphics.layer.drawLayer
import androidx.compose.ui.graphics.rememberGraphicsLayer
import androidx.compose.ui.layout.LayoutCoordinates
import androidx.compose.ui.layout.positionInWindow
import androidx.compose.ui.node.DelegatableNode
import androidx.compose.ui.node.DrawModifierNode
import androidx.compose.ui.node.GlobalPositionAwareModifierNode
import androidx.compose.ui.node.ModifierNodeElement
import androidx.compose.ui.node.invalidateDraw
import androidx.compose.ui.node.requireDensity
import androidx.compose.ui.platform.InspectorInfo
import androidx.compose.ui.unit.Density
import androidx.compose.ui.unit.IntSize
import androidx.compose.ui.unit.toIntSize

/** Something glass can sample: an image of what lies behind it. */
interface Backdrop {

    val isCoordinatesDependent: Boolean

    /** Draws the backdrop as seen from [coordinates]; [scale] is the glass node's own scale, undone here. */
    fun DrawScope.drawBackdrop(density: Density, coordinates: LayoutCoordinates?, scale: Float)
}

@Composable
fun rememberLayerBackdrop(graphicsLayer: GraphicsLayer = rememberGraphicsLayer()): LayerBackdrop =
    remember(graphicsLayer) { LayerBackdrop(graphicsLayer) }

/** An offscreen copy of one node's drawing, filled by [Modifier.layerBackdrop]. */
@Stable
class LayerBackdrop internal constructor(val graphicsLayer: GraphicsLayer) : Backdrop {

    override val isCoordinatesDependent: Boolean = true

    internal var layerCoordinates: LayoutCoordinates? by mutableStateOf(null)

    override fun DrawScope.drawBackdrop(density: Density, coordinates: LayoutCoordinates?, scale: Float) {
        val coordinates = coordinates ?: return
        val layerCoordinates = layerCoordinates ?: return
        withTransform({
            if (scale != 1f && scale != 0f) scale(1f / scale, 1f / scale, Offset.Zero)
            val offset =
                try {
                    layerCoordinates.localPositionOf(coordinates, Offset.Zero)
                } catch (_: Exception) {
                    coordinates.positionInWindow() - layerCoordinates.positionInWindow()
                }
            translate(-offset.x, -offset.y)
        }) {
            drawLayer(graphicsLayer)
        }
    }
}

/** Glass on an opaque panel: nothing to sample, so only tint, highlight and shadow show. */
@Stable
fun emptyBackdrop(): Backdrop = EmptyBackdrop

@Immutable
private object EmptyBackdrop : Backdrop {
    override val isCoordinatesDependent: Boolean = false
    override fun DrawScope.drawBackdrop(density: Density, coordinates: LayoutCoordinates?, scale: Float) = Unit
}

/** Records everything this node draws into [backdrop] each time it draws. Glass must not sample its own recorder. */
fun Modifier.layerBackdrop(backdrop: LayerBackdrop): Modifier = this then LayerBackdropElement(backdrop)

private class LayerBackdropElement(val backdrop: LayerBackdrop) : ModifierNodeElement<LayerBackdropNode>() {

    override fun create(): LayerBackdropNode = LayerBackdropNode(backdrop)

    override fun update(node: LayerBackdropNode) {
        if (node.backdrop != backdrop) {
            node.backdrop.layerCoordinates = null
            node.backdrop = backdrop
        }
        node.invalidateDraw()
    }

    override fun InspectorInfo.inspectableProperties() {
        name = "layerBackdrop"
        properties["backdrop"] = backdrop
    }

    override fun equals(other: Any?): Boolean = this === other || other is LayerBackdropElement && backdrop == other.backdrop

    override fun hashCode(): Int = backdrop.hashCode()
}

private class LayerBackdropNode(var backdrop: LayerBackdrop) : DrawModifierNode, GlobalPositionAwareModifierNode, Modifier.Node() {

    override fun ContentDrawScope.draw() {
        drawContent()
        recordLayer(this@LayerBackdropNode, backdrop.graphicsLayer) { this@draw.drawContent() }
    }

    override fun onGloballyPositioned(coordinates: LayoutCoordinates) {
        if (coordinates.isAttached) backdrop.layerCoordinates = coordinates
    }

    override fun onDetach() {
        backdrop.layerCoordinates = null
    }
}

/** Records [block] into [layer] using the node's density (the upstream LayerRecorder). */
internal fun DrawScope.recordLayer(node: DelegatableNode, layer: GraphicsLayer, size: IntSize = this.size.toIntSize(), block: DrawScope.() -> Unit) {
    val density = node.requireDensity()
    layer.record(size) {
        val previous = drawContext.density
        drawContext.density = density
        try {
            this.block()
        } finally {
            drawContext.density = previous
        }
    }
}
