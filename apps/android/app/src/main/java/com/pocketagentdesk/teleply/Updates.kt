package com.pocketagentdesk.teleply

import android.content.Context
import android.content.Intent
import android.content.pm.PackageInfo
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.provider.Settings
import android.widget.Toast
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.core.content.FileProvider
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import java.io.File
import java.io.IOException
import java.security.MessageDigest
import java.util.Locale
import java.util.concurrent.TimeUnit
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.ensureActive
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import org.json.JSONArray

/**
 * In-app updates (0.8), as the old app's (mobile/native/android): this repository's GitHub Releases, assets named
 * Teleply-<version>-<code>.apk since 1.0. The preview's TeleplyNative-… files belong to another package and key, so they
 * are never offered. Only the app updates itself; the development copy (.dev) never does.
 */
object UpdatePolicy {
    const val Api = "https://api.github.com/repos/Zeng-HY/Agent_24-7/releases?per_page=30"
    const val Prefix = "https://github.com/Zeng-HY/Agent_24-7/releases/download/"
    const val MaxApk = 128L * 1024 * 1024
    const val Package = "com.pocketagentdesk.teleply"
    private val Name = Regex("Teleply-(\\d+\\.\\d+\\.\\d+)-(\\d+)\\.apk")
    private val Digest = Regex("sha256:[a-fA-F0-9]{64}")
    data class Release(val version: String, val code: Long, val size: Long, val url: String, val sha256: String, val notes: String)

    /**
     * The newest asset above [installed]. Pre-releases count: every release of the repository is one so far
     * (windows-v0.27.0-dev.N). An asset needs GitHub's SHA-256 digest and its exact download address.
     */
    fun choose(json: String, installed: Long): Release? {
        val releases = JSONArray(json)
        var best: Release? = null
        for (i in 0 until releases.length()) {
            val release = releases.getJSONObject(i)
            if (release.optBoolean("draft")) continue
            val assets = release.optJSONArray("assets") ?: continue
            for (j in 0 until assets.length()) {
                val asset = assets.getJSONObject(j)
                val name = asset.optString("name")
                val digest = asset.optString("digest")
                val url = asset.optString("browser_download_url")
                val match = Name.matchEntire(name) ?: continue
                if (!Digest.matches(digest)) continue
                val code = match.groupValues[2].toLongOrNull() ?: continue
                val size = asset.optLong("size")
                if (code <= installed || best != null && code <= best.code || size <= 0 || size > MaxApk) continue
                if (url != Prefix + release.optString("tag_name") + "/" + name || !allowedUrl(url)) continue
                val body = release.optString("body", "").trim()
                best = Release(match.groupValues[1], code, size, url, digest.removePrefix("sha256:").lowercase(Locale.ROOT), if (body.length > 500) body.take(500) + "…" else body)
            }
        }
        return best
    }

    /** The release list, this repository's downloads and GitHub's download hosts; HTTPS on 443 only. */
    fun allowedUrl(value: String): Boolean = runCatching {
        val u = java.net.URI(value)
        if (u.scheme != "https" || u.userInfo != null || u.port != -1 && u.port != 443) return false
        when (u.host) {
            "api.github.com" -> value == Api
            "github.com" -> value.startsWith(Prefix) && !u.path.contains("..")
            "release-assets.githubusercontent.com", "objects.githubusercontent.com" -> true
            else -> false
        }
    }.getOrDefault(false)
}

/** Where an update stands; the dialogs show it. */
sealed interface UpdateStep {
    data object Idle : UpdateStep
    data class Found(val release: UpdatePolicy.Release) : UpdateStep
    data class Downloading(val release: UpdatePolicy.Release, val percent: Int) : UpdateStep
    data class Ready(val release: UpdatePolicy.Release, val file: File) : UpdateStep
    /** The phone has not let this app install apps yet: system settings first, then 继续安装. */
    data class Permission(val release: UpdatePolicy.Release, val file: File) : UpdateStep
    data class Failed(val release: UpdatePolicy.Release?, val message: String) : UpdateStep
}

/**
 * Checks, downloads and hands an update to the system installer; never installs silently, never uninstalls. A
 * download is checked for its length, SHA-256, package, version and the very signing key of the installed app.
 */
class AppUpdater(private val context: Context, base: OkHttpClient = OkHttpClient()) {
    private val client = base.newBuilder().followRedirects(false).followSslRedirects(false).retryOnConnectionFailure(false)
        .connectTimeout(15, TimeUnit.SECONDS).readTimeout(20, TimeUnit.SECONDS).build()
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main.immediate)
    private val prefs = context.getSharedPreferences("app_updates", Context.MODE_PRIVATE)
    private val mutable = MutableStateFlow<UpdateStep>(UpdateStep.Idle)
    val step = mutable.asStateFlow()
    private var work: Job? = null
    /** Only the app itself: the development copy has another package and could never take the update. */
    val enabled: Boolean get() = context.packageName == UpdatePolicy.Package
    val version: String get() = runCatching { installed().let { it.versionName + " / " + code(it) } }.getOrDefault(BuildConfig.VERSION_NAME)

    /** Once a day by itself, quietly; a failed look waits an hour. [manual]: now, and says what it found. */
    fun check(manual: Boolean) {
        if (!enabled) { if (manual) toast("开发版不检查更新"); return }
        val now = System.currentTimeMillis()
        if (!manual && now - prefs.getLong("checked", 0) < Day) return
        if (work?.isActive == true) { if (manual) toast("正在检查或下载更新"); return }
        if (manual) toast("正在检查更新…")
        work = scope.launch {
            try {
                val release = withContext(Dispatchers.IO) { UpdatePolicy.choose(text(UpdatePolicy.Api, 2L * 1024 * 1024), code(installed())) }
                prefs.edit().putLong("checked", now).apply()
                when {
                    release == null -> if (manual) toast("当前已是最新可用版本")
                    !manual && prefs.getLong("skipped", 0) == release.code -> Unit
                    else -> mutable.value = UpdateStep.Found(release)
                }
            } catch (e: kotlinx.coroutines.CancellationException) { throw e }
            catch (_: Exception) {
                prefs.edit().putLong("checked", now - Day + Hour).apply()
                if (manual) toast("无法检查更新，请检查网络后重试")
            }
        }
    }
    /** 稍后: no reminder for this version by itself; 检查更新 still offers it. */
    fun later(release: UpdatePolicy.Release) { prefs.edit().putLong("skipped", release.code).apply(); mutable.value = UpdateStep.Idle }
    fun dismiss() { if (mutable.value !is UpdateStep.Downloading) mutable.value = UpdateStep.Idle }
    fun cancel() { work?.cancel(); mutable.value = UpdateStep.Idle }

    fun download(release: UpdatePolicy.Release) {
        if (work?.isActive == true) return
        mutable.value = UpdateStep.Downloading(release, 0)
        work = scope.launch {
            val dir = File(context.cacheDir, "updates").apply { mkdirs() }
            val part = File(dir, "update.part")
            val apk = File(dir, "update.apk")
            try {
                withContext(Dispatchers.IO) {
                    open(release.url).use { response ->
                        val input = response.body?.byteStream() ?: throw IOException("Empty download")
                        val hash = MessageDigest.getInstance("SHA-256")
                        var total = 0L
                        var last = -1
                        part.outputStream().use { out ->
                            val buffer = ByteArray(65536)
                            while (true) {
                                ensureActive()
                                val n = input.read(buffer)
                                if (n < 0) break
                                total += n
                                if (total > release.size || total > UpdatePolicy.MaxApk) throw IOException("Too large")
                                hash.update(buffer, 0, n); out.write(buffer, 0, n)
                                val percent = (total * 100 / release.size).toInt()
                                if (percent != last) { last = percent; mutable.value = UpdateStep.Downloading(release, percent) }
                            }
                        }
                        if (total != release.size || hex(hash.digest()) != release.sha256) throw IOException("Checksum mismatch")
                    }
                    verify(part, release.code)
                    if (apk.exists() && !apk.delete()) throw IOException("Cannot replace cache")
                    if (!part.renameTo(apk)) throw IOException("Cannot save APK")
                }
                mutable.value = UpdateStep.Ready(release, apk)
            } catch (e: kotlinx.coroutines.CancellationException) { part.delete(); throw e }
            catch (_: Exception) {
                part.delete()
                mutable.value = UpdateStep.Failed(release, "下载或校验没有完成，原来的版本没有改动。请检查网络后重试。")
            }
        }
    }

    /** Hands the checked file to the system installer, which asks the user; data stay. */
    fun install(release: UpdatePolicy.Release, file: File) {
        if (!context.packageManager.canRequestPackageInstalls()) { mutable.value = UpdateStep.Permission(release, file); return }
        try {
            verify(file, release.code)
            val uri = FileProvider.getUriForFile(context, context.packageName + ".files", file)
            context.startActivity(Intent(Intent.ACTION_VIEW).setDataAndType(uri, "application/vnd.android.package-archive")
                .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_ACTIVITY_NEW_TASK))
            mutable.value = UpdateStep.Idle
        } catch (_: Exception) { mutable.value = UpdateStep.Failed(release, "这个安装包装不了，请重新检查更新。") }
    }
    /** 允许安装更新: the system page where this app may install apps; the dialog stays for 继续安装. */
    fun openPermission() {
        runCatching { context.startActivity(Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES, Uri.parse("package:" + context.packageName)).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) }
            .onFailure { toast("无法打开安装权限设置") }
    }

    private fun open(start: String): Response {
        var url = start
        repeat(5) {
            if (!UpdatePolicy.allowedUrl(url)) throw IOException("Untrusted update address")
            val response = client.newCall(Request.Builder().url(url).header("User-Agent", "Teleply-Android-Updater")
                .header("Accept", "application/vnd.github+json, application/octet-stream").header("Cache-Control", "no-cache").build()).execute()
            if (response.code in 300..399) {
                val next = response.header("Location"); response.close()
                url = java.net.URL(java.net.URL(url), next ?: throw IOException("Missing redirect")).toString()
                return@repeat
            }
            if (response.code != 200) { response.close(); throw IOException("Update unavailable") }
            return response
        }
        throw IOException("Too many redirects")
    }
    private fun text(url: String, limit: Long): String = open(url).use { r ->
        val source = r.body?.source() ?: throw IOException("Empty")
        if (source.request(limit + 1)) throw IOException("Metadata too large")
        source.readUtf8()
    }
    @Suppress("DEPRECATION")
    private fun installed(): PackageInfo = context.packageManager.getPackageInfo(context.packageName, if (Build.VERSION.SDK_INT >= 28) PackageManager.GET_SIGNING_CERTIFICATES else PackageManager.GET_SIGNATURES)
    @Suppress("DEPRECATION")
    private fun code(info: PackageInfo): Long = if (Build.VERSION.SDK_INT >= 28) info.longVersionCode else info.versionCode.toLong()
    @Suppress("DEPRECATION")
    private fun signers(info: PackageInfo?) = (if (Build.VERSION.SDK_INT >= 28) info?.signingInfo?.apkContentsSigners else info?.signatures)?.map { it.toCharsString() }?.toSet()
    @Suppress("DEPRECATION")
    private fun verify(file: File, expected: Long) {
        val pm = context.packageManager
        val flags = if (Build.VERSION.SDK_INT >= 28) PackageManager.GET_SIGNING_CERTIFICATES else PackageManager.GET_SIGNATURES
        val current = installed()
        val candidate = pm.getPackageArchiveInfo(file.path, flags) ?: throw IOException("Not a package")
        if (candidate.packageName != context.packageName || code(candidate) != expected || expected <= code(current)) throw IOException("Wrong package or version")
        val old = signers(current); val next = signers(candidate)
        if (old.isNullOrEmpty() || next.isNullOrEmpty() || old != next) throw IOException("Signing key changed")
    }
    private fun toast(text: String) = Toast.makeText(context, text, Toast.LENGTH_LONG).show()
    private fun hex(bytes: ByteArray) = bytes.joinToString("") { "%02x".format(Locale.ROOT, it.toInt() and 255) }
    private companion object { const val Day = 24L * 60 * 60 * 1000; const val Hour = 60L * 60 * 1000 }
}

/** The update dialogs, over every page: found, downloading, downloaded, permission, failed. */
@Composable
fun UpdateDialogs(updater: AppUpdater) {
    val step by updater.step.collectAsStateWithLifecycle()
    when (val s = step) {
        UpdateStep.Idle -> Unit
        is UpdateStep.Found -> AlertDialog(
            onDismissRequest = { updater.later(s.release) },
            title = { Text("发现新版本 ${s.release.version}") },
            text = { Text(String.format(Locale.ROOT, "%.1f MB", s.release.size / 1048576.0) + if (s.release.notes.isNotBlank()) "\n\n" + s.release.notes else "") },
            confirmButton = { TextButton({ updater.download(s.release) }) { Text("下载更新") } },
            dismissButton = { TextButton({ updater.later(s.release) }) { Text("稍后") } },
        )
        is UpdateStep.Downloading -> AlertDialog(
            onDismissRequest = {},
            title = { Text("正在下载 ${s.release.version}") },
            text = { Column { LinearProgressIndicator({ s.percent / 100f }, Modifier.fillMaxWidth().padding(top = 8.dp)); Text("${s.percent}%", style = MaterialTheme.typography.bodySmall, modifier = Modifier.padding(top = 8.dp)) } },
            confirmButton = {},
            dismissButton = { TextButton(updater::cancel) { Text("取消") } },
        )
        is UpdateStep.Ready -> AlertDialog(
            onDismissRequest = updater::dismiss,
            title = { Text("更新已下载") },
            text = { Text("安装时保留应用里的数据和登录。") },
            confirmButton = { TextButton({ updater.install(s.release, s.file) }) { Text("安装") } },
            dismissButton = { TextButton(updater::dismiss) { Text("稍后") } },
        )
        is UpdateStep.Permission -> AlertDialog(
            onDismissRequest = updater::dismiss,
            title = { Text("允许安装更新") },
            text = { Text("在系统设置里允许遥应安装应用，回来后点「继续安装」。") },
            confirmButton = { TextButton({ updater.install(s.release, s.file) }) { Text("继续安装") } },
            dismissButton = { TextButton(updater::openPermission) { Text("打开设置") } },
        )
        is UpdateStep.Failed -> AlertDialog(
            onDismissRequest = updater::dismiss,
            title = { Text("更新没有完成") },
            text = { Text(s.message) },
            confirmButton = { if (s.release != null) TextButton({ updater.download(s.release) }) { Text("重试") } },
            dismissButton = { TextButton(updater::dismiss) { Text("取消") } },
        )
    }
}

/** The app's updater from any composable; null in previews and tests without the application. */
@Composable
fun rememberUpdater(): AppUpdater? = (LocalContext.current.applicationContext as? NativeApplication)?.updater
