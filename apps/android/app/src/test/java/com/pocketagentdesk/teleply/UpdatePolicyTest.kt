package com.pocketagentdesk.teleply

import java.io.IOException
import java.security.KeyFactory
import java.security.KeyPairGenerator
import java.security.Signature
import java.security.interfaces.ECPublicKey
import java.security.spec.ECGenParameterSpec
import java.security.spec.X509EncodedKeySpec
import java.util.Base64
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test

/** In-app updates (1.0.3): a manifest signed by deploy/updates/publish.py, Alibaba Cloud first and GitHub second. */
class UpdatePolicyTest {
    private val pair = KeyPairGenerator.getInstance("EC").apply { initialize(ECGenParameterSpec("secp256r1")) }.generateKeyPair()
    private val key = Base64.getEncoder().encodeToString(pair.public.encoded)
    private fun sign(bytes: ByteArray) =
        Base64.getEncoder().encodeToString(Signature.getInstance("SHA256withECDSA").run { initSign(pair.private); update(bytes); sign() }) + "\n"
    private val sha = "a".repeat(64)
    private val apk = "Teleply-1.0.3-14.apk"
    private fun manifest(
        code: Long = 14, version: String = "1.0.3", name: String = "Teleply-$version-$code.apk", product: String = "android",
        pkg: String = UpdatePolicy.Package, notes: String = "这一版的说明",
        urls: List<String> = listOf(UpdatePolicy.Mirror + name, UpdatePolicy.Prefix + "android-v$version/" + name),
    ) = JSONObject().put("schema", 1).put("product", product).put("package", pkg).put("version", version).put("code", code).put("name", name)
        .put("size", 2213247).put("sha256", sha).put("notes", notes).put("urls", JSONArray(urls)).toString().toByteArray()
    private fun read(bytes: ByteArray, installed: Long = 13) = UpdatePolicy.read(bytes, sign(bytes), installed, null, key)

    @Test fun checksTheSignatureTheReleaseToolMakes() {
        // Made by Python's cryptography, as publish.py signs, with a throwaway key; relay_updates checks the same three.
        val testKey = "MFkwEwYHKoZIzj0CAQYIKoZIzj0DAQcDQgAEDkPNGGjzdLIPjYcTneoLrTl/YNy/J1OZq6DwHVlVEzB2Mv5avsQp1nJpAKbvwxLnMLZP6582cQg0yaq8K+4/qA=="
        val message = "{\"schema\": 1, \"product\": \"test\", \"notes\": \"测试 vector\"}".toByteArray()
        val signatures = listOf(
            "MEUCIBVNtELOXily0NHImShXkJ2NNM6ruLSdnldAVpIUUg/GAiEAuPstKCioXosZhoO6TjndERhVntPPst9S/ybnZL2q4S8=",
            "MEMCH1jg7fCGg0URdJj5GO1Sq3IYNE4W3oy5nlVouYNZpEUCIAJEt6I/UtDMaRSSlDc6YUMbXThF5iHam26jHiQBp0wT",
        )
        for (signature in signatures) assertTrue(UpdatePolicy.verify(message, signature + "\n", testKey))
        assertFalse(UpdatePolicy.verify(message + ' '.code.toByte(), signatures[0], testKey))
        assertFalse(UpdatePolicy.verify(message, signatures[0], UpdatePolicy.Key))
        assertFalse(UpdatePolicy.verify(message, "AAAA", testKey))
        assertFalse(UpdatePolicy.verify(message, "not base64!", testKey))
    }

    @Test fun theAppCarriesAP256Key() {
        val bytes = Base64.getDecoder().decode(UpdatePolicy.Key)
        assertEquals(91, bytes.size)
        val parsed = KeyFactory.getInstance("EC").generatePublic(X509EncodedKeySpec(bytes)) as ECPublicKey
        assertEquals(256, parsed.params.curve.field.fieldSize)
    }

    @Test fun readsASignedManifestAndOnlyANewerOne() {
        val found = read(manifest())!!
        assertEquals(14L, found.code); assertEquals("1.0.3", found.version); assertEquals(2213247L, found.size); assertEquals(sha, found.sha256)
        assertEquals("这一版的说明", found.notes)
        assertEquals(listOf(UpdatePolicy.Mirror + apk, UpdatePolicy.Prefix + "android-v1.0.3/" + apk), found.urls)
        assertNull(read(manifest(), installed = 14))
        assertEquals(501, read(manifest(notes = "长".repeat(600)))!!.notes.length)
    }

    @Test fun refusesWhatTheSignatureDoesNotCover() {
        val bytes = manifest()
        assertThrows(IOException::class.java) { UpdatePolicy.read(bytes, sign(manifest(code = 15)), 13, null, key) }
        assertThrows(IOException::class.java) { UpdatePolicy.read(bytes, sign(bytes), 13, null, UpdatePolicy.Key) }
        assertThrows(IOException::class.java) { UpdatePolicy.read(bytes, "", 13, null, key) }
    }

    @Test fun refusesAnotherProductPackageOrFile() {
        for (bad in listOf(manifest(product = "windows"), manifest(pkg = UpdatePolicy.Package + ".dev"), manifest(name = "TeleplyNative-1.0.3-14.apk"),
            manifest(name = "PocketAgentDesk-1.0.3-14.apk"), manifest(version = "1.0"), manifest(code = 0)))
            assertThrows(IOException::class.java) { read(bad) }
    }

    @Test fun keepsOnlyAddressesItTrusts() {
        val found = read(manifest(urls = listOf("https://evil.example/android/$apk", UpdatePolicy.Aliyun + "Teleply-9.9.9-99.apk",
            "http://dl.pocketagentdesk.com/android/$apk", UpdatePolicy.Aliyun + apk)))!!
        assertEquals(listOf(UpdatePolicy.Aliyun + apk), found.urls)
        assertThrows(IOException::class.java) { read(manifest(urls = listOf("https://evil.example/android/$apk"))) }
    }

    @Test fun githubNeedsTheSignedManifestAndAnApkThatAgrees() {
        val tag = "android-v1.0.3"
        val bytes = manifest()
        fun asset(name: String, at: String = tag, digest: String = "sha256:$sha") =
            JSONObject().put("name", name).put("size", 2213247).put("digest", digest).put("browser_download_url", UpdatePolicy.Prefix + "$at/$name")
        fun release(vararg assets: JSONObject, at: String = tag, draft: Boolean = false) =
            JSONObject().put("tag_name", at).put("draft", draft).put("prerelease", false).put("body", "说明").put("assets", JSONArray(assets.toList()))
        val files = mapOf(UpdatePolicy.Prefix + "$tag/android-update.json" to bytes, UpdatePolicy.Prefix + "$tag/android-update.json.sig" to sign(bytes).toByteArray())
        val fetch = { url: String -> files[url] ?: throw IOException("No $url") }
        fun newest(vararg releases: JSONObject, installed: Long = 13) = UpdatePolicy.newestOnGithub(JSONArray(releases.toList()).toString(), installed, fetch, key)
        val complete = release(asset(apk), asset("android-update.json"), asset("android-update.json.sig"))

        val found = newest(complete, release(asset("Teleply-1.0.2-13.apk", at = "android-v1.0.2"), at = "android-v1.0.2"))!!
        assertEquals(listOf(UpdatePolicy.Prefix + "$tag/$apk", UpdatePolicy.Mirror + apk), found.urls)
        assertNull(newest(complete, installed = 14))
        assertNull(newest(release(asset(apk), asset("android-update.json"))))
        assertNull(newest(release(asset(apk), asset("android-update.json"), asset("android-update.json.sig"), draft = true)))
        assertThrows(IOException::class.java) { newest(release(asset(apk, digest = "sha256:" + "b".repeat(64)), asset("android-update.json"), asset("android-update.json.sig"))) }
        assertThrows(IOException::class.java) { newest(release(asset("android-update.json"), asset("android-update.json.sig"))) }
    }

    @Test fun downloadsOnlyFromTheRepositoryGithubAndTheAppsFolderOnAlibabaCloud() {
        assertTrue(UpdatePolicy.allowedUrl(UpdatePolicy.Api))
        assertTrue(UpdatePolicy.allowedUrl(UpdatePolicy.Prefix + "android-v1.0.3/$apk"))
        assertTrue(UpdatePolicy.allowedUrl("https://release-assets.githubusercontent.com/some/path"))
        assertTrue(UpdatePolicy.allowedUrl(UpdatePolicy.Aliyun + UpdatePolicy.Manifest))
        assertTrue(UpdatePolicy.allowedUrl(UpdatePolicy.Mirror + apk))
        assertFalse(UpdatePolicy.allowedUrl("https://teleply-updates.oss-cn-guangzhou.aliyuncs.com/windows/AgentRemote-0.27.0-dev.24-Setup.exe"))
        assertFalse(UpdatePolicy.allowedUrl("https://other.oss-cn-guangzhou.aliyuncs.com/android/$apk"))
        assertFalse(UpdatePolicy.allowedUrl("https://teleply-updates.oss-cn-guangzhou.aliyuncs.com.evil.test/android/$apk"))
        assertFalse(UpdatePolicy.allowedUrl(UpdatePolicy.Aliyun + "$apk?response-content-type=text/plain"))
        assertFalse(UpdatePolicy.allowedUrl(UpdatePolicy.Aliyun + "../windows/x"))
        assertFalse(UpdatePolicy.allowedUrl("http://github.com/Zeng-HY/Agent_24-7/releases/download/x/y.apk"))
        assertFalse(UpdatePolicy.allowedUrl("https://github.com/other/repo/releases/download/x/y.apk"))
        assertFalse(UpdatePolicy.allowedUrl("https://github.com:8443/Zeng-HY/Agent_24-7/releases/download/x/y.apk"))
        assertFalse(UpdatePolicy.allowedUrl("https://user@github.com/Zeng-HY/Agent_24-7/releases/download/x/y.apk"))
        assertFalse(UpdatePolicy.allowedUrl("https://evil.example/Zeng-HY/Agent_24-7/releases/download/x/y.apk"))
    }
}
