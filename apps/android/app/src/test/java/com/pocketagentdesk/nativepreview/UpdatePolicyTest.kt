package com.pocketagentdesk.nativepreview

import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test

/** In-app updates (0.8): only this repository's TeleplyNative APKs, with GitHub's digest, at their exact address. */
class UpdatePolicyTest {
    private val tag = "windows-v0.27.0-dev.16"
    private fun asset(name: String, size: Long = 1000, digest: String = "sha256:" + "a".repeat(64), at: String = tag, url: String? = null) =
        JSONObject().put("name", name).put("size", size).put("digest", digest).put("browser_download_url", url ?: (UpdatePolicy.Prefix + at + "/" + name))
    private fun release(vararg assets: JSONObject, at: String = tag, draft: Boolean = false) =
        JSONObject().put("tag_name", at).put("draft", draft).put("prerelease", true).put("body", "这一版的说明").put("assets", JSONArray(assets.toList()))

    @Test fun picksTheNewestNativeApkAndIgnoresTheOldAppAndWindows() {
        val json = JSONArray()
            .put(release(asset("PocketAgentDesk-0.7.4-11.apk"), asset("TeleplyNative-0.8.0-8.apk"), asset("AgentRemote-0.27.0-dev.16-Setup.exe")))
            .put(release(asset("TeleplyNative-0.9.0-9.apk", at = "windows-v0.27.0-dev.17"), at = "windows-v0.27.0-dev.17")).toString()
        val found = UpdatePolicy.choose(json, 7)!!
        assertEquals(9L, found.code); assertEquals("0.9.0", found.version); assertEquals("a".repeat(64), found.sha256)
        assertEquals("这一版的说明", found.notes)
        assertNull(UpdatePolicy.choose(json, 9))
    }

    @Test fun refusesWithoutDigestAtAnotherAddressTooLargeOrInADraft() {
        fun only(vararg assets: JSONObject, draft: Boolean = false) = UpdatePolicy.choose(JSONArray().put(release(*assets, draft = draft)).toString(), 7)
        assertNull(only(asset("TeleplyNative-0.8.0-8.apk", digest = "")))
        assertNull(only(asset("TeleplyNative-0.8.0-8.apk", url = "https://example.com/TeleplyNative-0.8.0-8.apk")))
        assertNull(only(asset("TeleplyNative-0.8.0-8.apk", size = UpdatePolicy.MaxApk + 1)))
        assertNull(only(asset("TeleplyNative-0.8.0-8.apk"), draft = true))
        assertNotNull(only(asset("TeleplyNative-0.8.0-8.apk")))
    }

    @Test fun downloadsOnlyFromTheRepositoryAndGithubHosts() {
        assertTrue(UpdatePolicy.allowedUrl(UpdatePolicy.Api))
        assertTrue(UpdatePolicy.allowedUrl(UpdatePolicy.Prefix + tag + "/TeleplyNative-0.8.0-8.apk"))
        assertTrue(UpdatePolicy.allowedUrl("https://release-assets.githubusercontent.com/some/path"))
        assertFalse(UpdatePolicy.allowedUrl("http://github.com/Zeng-HY/Agent_24-7/releases/download/x/y.apk"))
        assertFalse(UpdatePolicy.allowedUrl("https://github.com/other/repo/releases/download/x/y.apk"))
        assertFalse(UpdatePolicy.allowedUrl("https://github.com:8443/Zeng-HY/Agent_24-7/releases/download/x/y.apk"))
        assertFalse(UpdatePolicy.allowedUrl("https://user@github.com/Zeng-HY/Agent_24-7/releases/download/x/y.apk"))
        assertFalse(UpdatePolicy.allowedUrl("https://evil.example/Zeng-HY/Agent_24-7/releases/download/x/y.apk"))
    }
}
