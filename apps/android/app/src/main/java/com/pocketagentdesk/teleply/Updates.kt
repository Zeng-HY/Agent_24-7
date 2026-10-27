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
import java.security.KeyFactory
import java.security.MessageDigest
import java.security.Signature
import java.security.spec.X509EncodedKeySpec
import java.util.Base64
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
import org.json.JSONObject

/**
 * In-app updates: Alibaba Cloud first and this repository's GitHub Releases second (1.0.3). Both carry the same
 * android-update.json and its .sig, which deploy/updates/publish.py signs with a key that stays on the publisher's
 * computer; the manifest names Teleply-<version>-<code>.apk with its size and SHA-256. The preview's TeleplyNative-…
 * files belong to another package and key, so they are never offered. Only the app updates itself; the development
 * copy (.dev) never does.
 */
object UpdatePolicy {
    const val Api = "https://api.github.com/repos/Zeng-HY/Agent_24-7/releases?per_page=30"
    const val Prefix = "https://github.com/Zeng-HY/Agent_24-7/releases/download/"
    /** Alibaba Cloud OSS, bucket teleply-updates in cn-guangzhou: the manifest, its .sig and the APKs. */
    const val Aliyun = "https://teleply-updates.oss-cn-guangzhou.aliyuncs.com/android/"
    /** The same bucket under the ICP-filed domain: Alibaba Cloud serves APKs only there, not over its own address. */
    const val Mirror = "https://dl.pocketagentdesk.com/android/"
    const val Manifest = "android-update.json"
    /** Public half of the manifest signing key: ECDSA P-256, X.509 SubjectPublicKeyInfo; relay_updates.KEY is the same. */
    const val Key = "MFkwEwYHKoZIzj0CAQYIKoZIzj0DAQcDQgAEjHQ+zWxB7EZkKiwzv6Xgkyu0RjbzWW0qtW1L4qNgVHAx4/r/Hk29tMlDlWUjer+q+L91XkMnOWhVwDgVCmlSew=="
    const val MaxApk = 128L * 1024 * 1024
    const val MaxManifest = 16L * 1024
    const val Package = "com.pocketagentdesk.teleply"
    private val Version = Regex("\\d+\\.\\d+\\.\\d+")
    private val Sha256 = Regex("[0-9a-f]{64}")
    /** [urls]: every address to try in turn, the manifest's own source first. */
    data class Release(val version: String, val code: Long, val size: Long, val urls: List<String>, val sha256: String, val notes: String)

    /** Whether [signature] (base64 of the DER form) is [key]'s ECDSA P-256 / SHA-256 signature of exactly [manifest]. */
    fun verify(manifest: ByteArray, signature: String, key: String = Key): Boolean = runCatching {
        val decoder = Base64.getDecoder()
        val publicKey = KeyFactory.getInstance("EC").generatePublic(X509EncodedKeySpec(decoder.decode(key)))
        Signature.getInstance("SHA256withECDSA").run { initVerify(publicKey); update(manifest); verify(decoder.decode(signature.trim())) }
    }.getOrDefault(false)

    /**
     * The release a signed manifest offers above [installed], or null when it is not newer. [github]: the GitHub release
     * the manifest came with; its APK asset must agree (address, size, GitHub's digest), and that address goes first.
     * Addresses this build does not know (a later mirror) are skipped, not refused: the signature vouches for them.
     */
    fun read(manifest: ByteArray, signature: String, installed: Long, github: JSONObject? = null, key: String = Key): Release? {
        if (!verify(manifest, signature, key)) throw IOException("Update signature does not match")
        val m = JSONObject(String(manifest, Charsets.UTF_8))
        val version = m.optString("version")
        val code = m.optLong("code", -1)
        val name = m.optString("name")
        val size = m.optLong("size", -1)
        val sha256 = m.optString("sha256")
        if (m.optInt("schema") != 1 || m.optString("product") != "android" || m.optString("package") != Package || !Version.matches(version) ||
            code <= 0 || name != "Teleply-$version-$code.apk" || size !in 1..MaxApk || !Sha256.matches(sha256)) throw IOException("Unexpected update manifest")
        if (code <= installed) return null
        val urls = mutableListOf<String>()
        if (github != null) {
            val at = Prefix + github.optString("tag_name") + "/" + name
            val assets = github.optJSONArray("assets") ?: JSONArray()
            val asset = (0 until assets.length()).map(assets::getJSONObject).firstOrNull { it.optString("name") == name }
            if (asset == null || asset.optString("browser_download_url") != at || asset.optLong("size") != size || asset.optString("digest") != "sha256:$sha256")
                throw IOException("GitHub's APK disagrees with the manifest")
            urls += at
        }
        val listed = m.optJSONArray("urls") ?: JSONArray()
        for (i in 0 until minOf(listed.length(), 5)) {
            val url = listed.optString(i)
            if (url.endsWith("/$name") && allowedUrl(url) && url !in urls) urls += url
        }
        if (urls.isEmpty()) throw IOException("No usable download address")
        val notes = m.optString("notes", "").trim()
        return Release(version, code, size, urls, sha256, if (notes.length > 500) notes.take(500) + "…" else notes)
    }

    /**
     * The second source: the newest signed release in GitHub's list. Releases before 1.0.3 carry no signed manifest and
     * are older than this app anyway. Pre-releases count, as before. [fetch] reads an address's bytes.
     */
    fun newestOnGithub(json: String, installed: Long, fetch: (String) -> ByteArray, key: String = Key): Release? {
        val releases = JSONArray(json)
        var best: Release? = null
        for (i in 0 until releases.length()) {
            val release = releases.getJSONObject(i)
            if (release.optBoolean("draft")) continue
            val assets = release.optJSONArray("assets") ?: continue
            val urls = (0 until assets.length()).map { assets.getJSONObject(it).optString("browser_download_url") }
            val manifest = Prefix + release.optString("tag_name") + "/" + Manifest
            if (manifest !in urls || "$manifest.sig" !in urls) continue
            val found = read(fetch(manifest), String(fetch("$manifest.sig"), Charsets.US_ASCII), installed, release, key) ?: continue
            if (best == null || found.code > best.code) best = found
        }
        return best
    }

    /** The release list, this repository's downloads, GitHub's download hosts and the app's folder on Alibaba Cloud; HTTPS on 443 only. */
    fun allowedUrl(value: String): Boolean = runCatching {
        val u = java.net.URI(value)
        if (u.scheme != "https" || u.userInfo != null || u.port != -1 && u.port != 443) return false
        when (u.host) {
            "api.github.com" -> value == Api
            "github.com" -> value.startsWith(Prefix) && !u.path.contains("..")
            "release-assets.githubusercontent.com", "objects.githubusercontent.com" -> true
            else -> (value.startsWith(Aliyun) || value.startsWith(Mirror)) && !u.path.contains("..") && u.rawQuery == null
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
                val release = withContext(Dispatchers.IO) { latest(code(installed())) }
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
                    // Each address in turn, every one checked the same way; the last failure stands for all.
                    var failure: IOException? = null
                    for (url in release.urls) {
                        failure = try { save(url, release, part); null } catch (e: IOException) { part.delete(); e }
                        if (failure == null) break
                    }
                    failure?.let { throw it }
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

    /** Alibaba Cloud first; GitHub when it cannot answer (unreachable, or a manifest that does not check out). */
    private fun latest(installed: Long): UpdatePolicy.Release? {
        try {
            val manifest = UpdatePolicy.Aliyun + UpdatePolicy.Manifest
            return UpdatePolicy.read(bytes(manifest, UpdatePolicy.MaxManifest), String(bytes("$manifest.sig", UpdatePolicy.MaxManifest), Charsets.US_ASCII), installed)
        } catch (e: kotlinx.coroutines.CancellationException) { throw e }
        catch (_: Exception) { }
        return UpdatePolicy.newestOnGithub(String(bytes(UpdatePolicy.Api, 2L * 1024 * 1024), Charsets.UTF_8), installed, { bytes(it, UpdatePolicy.MaxManifest) })
    }

    /** One address into [part], checked for length and SHA-256. */
    private fun CoroutineScope.save(url: String, release: UpdatePolicy.Release, part: File) = open(url).use { response ->
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
    /** The exact bytes: a manifest's signature covers them, not a decoding of them. */
    private fun bytes(url: String, limit: Long): ByteArray = open(url).use { r ->
        val source = r.body?.source() ?: throw IOException("Empty")
        if (source.request(limit + 1)) throw IOException("Metadata too large")
        source.readByteArray()
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
