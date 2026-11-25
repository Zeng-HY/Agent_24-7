package com.pocketagentdesk.teleply

import android.annotation.SuppressLint
import android.webkit.WebResourceRequest
import android.webkit.WebResourceResponse
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.key
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.viewinterop.AndroidView
import java.io.ByteArrayInputStream

/** The host the code page's own files are served from: this app's assets and the one text, nothing else. */
const val ViewerHost = "viewer.teleply.invalid"

/**
 * 代码页 (file-preview design §6.2, last paragraph): highlight.js 11.12.0 in this app's `assets/viewer`, with line
 * numbers, wrap, find, copy and the line the answer named. It loads nothing but those assets and the text handed over
 * by this app; no network, no cookie, no bridge. Past 200 KB the text shows without highlighting, and a cut text says
 * what part of it is here.
 */
@SuppressLint("SetJavaScriptEnabled")
@Composable
fun CodeView(text: String, file: org.json.JSONObject, dark: Boolean, modifier: Modifier = Modifier) {
    val lang = codeLanguage(file.string("lang"), file.string("name"))
    val line = file.optInt("line")
    val total = file.optLong("total_size")
    val shown = text.toByteArray().size.toLong()
    val truncated = file.optBoolean("truncated")
    val query = buildString {
        append("dark=").append(if (dark) "1" else "0")
        append("&lang=").append(java.net.URLEncoder.encode(lang, "UTF-8"))
        append("&line=").append(line)
        if (truncated) {
            append("&truncated=1")
            append("&size=").append(shown)
            append("&total=").append(if (total > 0) total else shown)
        }
    }
    key(text) {
        AndroidView(
            factory = { context ->
                WebView(context).apply {
                    settings.apply {
                        javaScriptEnabled = true
                        domStorageEnabled = false
                        allowFileAccess = false
                        allowContentAccess = false
                        javaScriptCanOpenWindowsAutomatically = false
                        setSupportMultipleWindows(false)
                        setGeolocationEnabled(false)
                        builtInZoomControls = true
                        displayZoomControls = false
                        useWideViewPort = true
                        loadWithOverviewMode = false
                    }
                    webViewClient = object : WebViewClient() {
                        override fun shouldInterceptRequest(view: WebView, request: WebResourceRequest): WebResourceResponse? {
                            val url = request.url
                            if (url.host != ViewerHost) return notFound()
                            return when (val path = url.path.orEmpty().removePrefix("/")) {
                                "text" -> WebResourceResponse("text/plain", "utf-8", ByteArrayInputStream(text.toByteArray(Charsets.UTF_8)))
                                "code.html" -> asset(view, "viewer/code.html", "text/html")
                                "code.js" -> asset(view, "viewer/code.js", "text/javascript")
                                "highlight.min.js" -> asset(view, "viewer/highlight.min.js", "text/javascript")
                                "highlight.r.min.js" -> asset(view, "viewer/highlight.r.min.js", "text/javascript")
                                "highlight.powershell.min.js" -> asset(view, "viewer/highlight.powershell.min.js", "text/javascript")
                                "highlight.latex.min.js" -> asset(view, "viewer/highlight.latex.min.js", "text/javascript")
                                "highlight.dockerfile.min.js" -> asset(view, "viewer/highlight.dockerfile.min.js", "text/javascript")
                                "code-light.css" -> asset(view, "viewer/code-light.css", "text/css")
                                "code-dark.css" -> asset(view, "viewer/code-dark.css", "text/css")
                                else -> notFound()
                            }
                        }

                        private fun asset(view: WebView, name: String, type: String): WebResourceResponse? =
                            runCatching { view.context.assets.open(name) }.getOrNull()?.let { WebResourceResponse(type, "utf-8", it) } ?: notFound()

                        private fun notFound() = WebResourceResponse("text/plain", "utf-8", 404, "Not Found", emptyMap(), ByteArrayInputStream(ByteArray(0)))
                    }
                    loadUrl("https://$ViewerHost/code.html?$query")
                }
            },
            modifier = modifier.semantics { contentDescription = "代码：${file.string("name")}" },
        )
    }
}
