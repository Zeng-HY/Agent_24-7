package com.pocketagentdesk.teleply

import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test

/** In-app updates (0.8; Teleply-… names since 1.0): only this repository's APKs of the app, with GitHub's digest, at their exact address. */
class UpdatePolicyTest {
    private val tag = "windows-v0.27.0-dev.16"
    private fun asset(name: String, size: Long = 1000, digest: String = "sha256:" + "a".repeat(64), at: String = tag, url: String? = null) =
        JSONObject().put("name", name).put("size", size).put("digest", digest).put("browser_download_url", url ?: (UpdatePolicy.Prefix + at + "/" + name))
    private fun release(vararg assets: JSONObject, at: String = tag, draft: Boolean = false) =
        JSONObject().put("tag_name", at).put("draft", draft).put("prerelease", true).put("body", "这一版的说明").put("assets", JSONArray(assets.toList()))

    @Test fun picksTheNewestAppApkAndIgnoresThePreviewTheOldAppAndWindows() {
        val json = JSONArray()
            .put(release(asset("PocketAgentDesk-0.7.4-11.apk"), asset("Teleply-1.0.0-11.apk"), asset("AgentRemote-0.27.0-dev.16-Setup.exe")))
            .put(release(asset("Teleply-1.0.1-12.apk", at = "windows-v0.27.0-dev.17"), asset("TeleplyNative-0.9.9-99.apk", at = "windows-v0.27.0-dev.17"), at = "windows-v0.27.0-dev.17")).toString()
        val found = UpdatePolicy.choose(json, 10)!!
        assertEquals(12L, found.code); assertEquals("1.0.1", found.version); assertEquals("a".repeat(64), found.sha256)
        assertEquals("这一版的说明", found.notes)
        assertNull(UpdatePolicy.choose(json, 12))
    }

    @Test fun neverOffersThePreviewsOrTheOldAppsFiles() {
        val json = JSONArray().put(release(asset("TeleplyNative-0.9.1-10.apk"), asset("PocketAgentDesk-0.7.5-12.apk"), asset("Teleply-1.0.0-11.apk.sig"))).toString()
        assertNull(UpdatePolicy.choose(json, 1))
    }

    @Test fun refusesWithoutDigestAtAnotherAddressTooLargeOrInADraft() {
        fun only(vararg assets: JSONObject, draft: Boolean = false) = UpdatePolicy.choose(JSONArray().put(release(*assets, draft = draft)).toString(), 10)
        assertNull(only(asset("Teleply-1.0.0-11.apk", digest = "")))
        assertNull(only(asset("Teleply-1.0.0-11.apk", url = "https://example.com/Teleply-1.0.0-11.apk")))
        assertNull(only(asset("Teleply-1.0.0-11.apk", size = UpdatePolicy.MaxApk + 1)))
        assertNull(only(asset("Teleply-1.0.0-11.apk"), draft = true))
        assertNotNull(only(asset("Teleply-1.0.0-11.apk")))
    }

    @Test fun downloadsOnlyFromTheRepositoryAndGithubHosts() {
        assertTrue(UpdatePolicy.allowedUrl(UpdatePolicy.Api))
        assertTrue(UpdatePolicy.allowedUrl(UpdatePolicy.Prefix + tag + "/Teleply-1.0.0-11.apk"))
        assertTrue(UpdatePolicy.allowedUrl("https://release-assets.githubusercontent.com/some/path"))
        assertFalse(UpdatePolicy.allowedUrl("http://github.com/Zeng-HY/Agent_24-7/releases/download/x/y.apk"))
        assertFalse(UpdatePolicy.allowedUrl("https://github.com/other/repo/releases/download/x/y.apk"))
        assertFalse(UpdatePolicy.allowedUrl("https://github.com:8443/Zeng-HY/Agent_24-7/releases/download/x/y.apk"))
        assertFalse(UpdatePolicy.allowedUrl("https://user@github.com/Zeng-HY/Agent_24-7/releases/download/x/y.apk"))
        assertFalse(UpdatePolicy.allowedUrl("https://evil.example/Zeng-HY/Agent_24-7/releases/download/x/y.apk"))
    }
}
