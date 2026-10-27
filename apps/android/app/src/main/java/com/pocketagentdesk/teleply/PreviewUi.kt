package com.pocketagentdesk.teleply

import android.annotation.SuppressLint
import android.content.Intent
import android.webkit.CookieManager
import android.webkit.WebResourceRequest
import android.webkit.WebResourceResponse
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import java.io.ByteArrayInputStream
import java.util.concurrent.atomic.AtomicInteger
import java.util.concurrent.atomic.AtomicLong
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeoutOrNull
import org.json.JSONObject

/** The made-up host a page's own files are asked from: the files beside it on the computer, as this conversation lists them. */
const val PreviewHost = "preview.teleply.invalid"

/** A path written in the page that may name a file beside it (web artifact-preview relative()). */
fun relativeResource(path: String) = path.isNotEmpty() && !path.startsWith("/") && !path.startsWith("\\") && ':' !in path && path.none { it == '?' || it == '#' || it.code < 0x20 }

/** Folds . and .. and the slashes, in lower case, as the web compares a page's resource with the listed files. */
fun normalizePath(path: String): String {
    val parts = ArrayDeque<String>()
    path.replace('\\', '/').split('/').forEach { bit -> when (bit) { "", "." -> Unit; ".." -> parts.removeLastOrNull(); else -> parts.addLast(bit) } }
    return parts.joinToString("/").lowercase()
}

/**
 * A path as [normalizePath] folds it, without a separator before a punctuation mark: the Markdown reader takes a
 * backslash before one for an escape and drops it (an answer's link to D:\a\.claude arrives as D:\a.claude). A file
 * link is matched this way when its exact path is not listed.
 */
fun looseFilePath(path: String) = normalizePath(path).replace(Regex("""/(?=[!-/:-@\[-`{-~])"""), "")

/** The page's base address: its own folder, so that relative paths (with ..) resolve as on the computer. */
fun previewBase(filePath: String): String {
    val folder = filePath.replace('\\', '/').substringBeforeLast('/', "")
    val encoded = folder.split('/').filter { it.isNotEmpty() }.joinToString("/") { android.net.Uri.encode(it, ":") }
    return "https://$PreviewHost/$encoded/"
}

/** The type a file beside the page is handed over as; anything else goes as plain bytes. */
private val ResourceTypes = mapOf(
    "png" to "image/png", "jpg" to "image/jpeg", "jpeg" to "image/jpeg", "webp" to "image/webp", "gif" to "image/gif", "svg" to "image/svg+xml",
    "css" to "text/css", "js" to "text/javascript", "mjs" to "text/javascript", "json" to "application/json", "html" to "text/html", "htm" to "text/html",
    "woff" to "font/woff", "woff2" to "font/woff2", "ttf" to "font/ttf", "otf" to "font/otf", "txt" to "text/plain", "csv" to "text/csv",
)

/**
 * 查看页面 of an HTML file: the page as a browser shows it, scripts and what it loads from the internet included (the
 * user's choice, 2026-10-24: "可以允许加载html文件，不要禁止"). Its own pictures, styles and scripts beside it come from
 * the files this conversation lists, matched exactly by path. What stays apart: the page gets no cookie of this app
 * and no bridge to it, cannot read the phone's files, and a link opens in the phone's browser when tapped.
 */
@SuppressLint("SetJavaScriptEnabled")
@Composable
fun HtmlPreview(source: String, file: JSONObject, vm: ReaderViewModel) {
    val height = (LocalConfiguration.current.screenHeightDp * 0.68f).dp
    val count = remember(source) { AtomicInteger(0) }
    val budget = remember(source) { AtomicLong(32L * 1024 * 1024) }
    val base = remember(file) { previewBase(file.string("path")) }
    val page = remember(source) { "<meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">" + source }
    val webView = remember { arrayOfNulls<WebView>(1) }
    DisposableEffect(Unit) { onDispose { webView[0]?.apply { stopLoading(); destroy() }; webView[0] = null } }
    AndroidView(
        factory = { context ->
            WebView(context).apply {
                webView[0] = this
                settings.apply {
                    javaScriptEnabled = true
                    domStorageEnabled = true
                    javaScriptCanOpenWindowsAutomatically = false
                    allowFileAccess = false
                    allowContentAccess = false
                    setSupportMultipleWindows(false)
                    setGeolocationEnabled(false)
                    mixedContentMode = WebSettings.MIXED_CONTENT_COMPATIBILITY_MODE
                    builtInZoomControls = true
                    displayZoomControls = false
                    useWideViewPort = true
                    loadWithOverviewMode = true
                }
                CookieManager.getInstance().setAcceptThirdPartyCookies(this, false)
                webViewClient = object : WebViewClient() {
                    override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest): Boolean {
                        val url = request.url
                        // A jump within the page stays here; a tapped link opens in the phone's browser; nothing else leaves.
                        if (url.host == PreviewHost) return url.fragment == null
                        if (request.hasGesture() && url.scheme in setOf("http", "https")) runCatching { view.context.startActivity(Intent(Intent.ACTION_VIEW, url).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) }
                        return true
                    }
                    override fun shouldInterceptRequest(view: WebView, request: WebResourceRequest): WebResourceResponse? {
                        val url = request.url
                        if (url.host != PreviewHost) return null  // the page itself (data) and the internet load as in a browser
                        val path = url.path.orEmpty().removePrefix("/")
                        val type = ResourceTypes[path.substringAfterLast('.', "").lowercase()] ?: "application/octet-stream"
                        if (count.incrementAndGet() <= 64) {
                            val bytes = runCatching { runBlocking { withTimeoutOrNull(30_000) { vm.workspace.previewResource(file, path) } } }.getOrNull()
                            if (bytes != null && budget.addAndGet(-bytes.size.toLong()) >= 0) return WebResourceResponse(type, null, ByteArrayInputStream(bytes))
                        }
                        return WebResourceResponse("text/plain", "utf-8", 404, "Not Found", emptyMap(), ByteArrayInputStream(ByteArray(0)))
                    }
                }
                loadDataWithBaseURL(base, page, "text/html", "utf-8", null)
            }
        },
        modifier = Modifier.fillMaxWidth().height(height).clip(TeleplyShape.Code).semantics { contentDescription = "网页预览：${file.string("name")}" },
    )
    Text("按网页打开：脚本和网上的图片照常加载；它拿不到这个应用的登录信息和手机里的文件，点链接用浏览器打开。", style = MaterialTheme.typography.note, color = LocalTeleply.current.muted)
}
