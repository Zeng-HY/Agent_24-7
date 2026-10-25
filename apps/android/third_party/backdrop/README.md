# Backdrop（液态玻璃）移植说明

来源：[Kyant0/AndroidLiquidGlass](https://github.com/Kyant0/AndroidLiquidGlass) 的 `backdrop` 模块，commit `65ab177e90e5c1d8c62e70cf7755841982da65f6`（2026-08-26），Apache License 2.0，版权 2025 Kyant。许可证原文见同目录 `LICENSE`，APK 内另有一份 `assets/licenses/backdrop-LICENSE.txt`。

移植到 `app/src/main/java/com/pocketagentdesk/teleply/glass/`：

| 本工程文件 | 上游文件 |
|---|---|
| `Backdrop.kt` | `Backdrop.kt`、`backdrops/LayerBackdrop.kt`、`backdrops/LayerBackdropModifier.kt`、`backdrops/EmptyBackdrop.kt`、`internal/LayerRecorder.kt` |
| `DrawBackdrop.kt` | `DrawBackdropModifier.kt`、`internal/ShapeProvider.kt` |
| `Effects.kt` | `BackdropEffectScope.kt`、`RuntimeShader.kt`、`RuntimeShaderCache.kt`、`Platform.kt`、`effects/Blur.kt`、`effects/ColorFilter.kt`、`effects/Lens.kt`、`effects/RenderEffect.kt`、Android 的 `internal/RenderEffect.kt` |
| `Highlight.kt` | `highlight/Highlight.kt`、`highlight/HighlightStyle.kt`、`highlight/HighlightModifier.kt`、`internal/Outline.kt`、Android 的 `internal/Paint.kt` |
| `BackdropShadow.kt` | `shadow/Shadow.kt`、`shadow/ShadowModifier.kt` |
| `Shaders.kt` | `internal/Shaders.kt`（着色器文字未改） |

改动：只保留 Android；包名改为本工程；能在 Compose 1.9.3、Kotlin 2.2.20 下编译（不用 context parameters）；玻璃上的变换只保留统一缩放（按下变大），反向变换随之简化；去掉 kyant shapes 支持（折射只接受 Compose 的 `CornerBasedShape`）；`Shadow` 改名 `BackdropShadow`；未移植内阴影、`exportedBackdrop`、组合背景和多平台代码。效果数值和默认参数未改。

为什么不直接引用 Maven 上的 `io.github.kyant0:backdrop`：2.0.0 要求 Compose 1.11、Kotlin 2.3，1.0.6 也要 Compose 1.10.3，而本工程是 Compose 1.9.3、Kotlin 2.2.20。工程升级到 Compose 1.11 以上后，应改回官方版本并删除这些文件。

参考资料：[sitong-zhang/apple-liquid-glass-guide](https://github.com/sitong-zhang/apple-liquid-glass-guide)（参数表与实践记录）。
