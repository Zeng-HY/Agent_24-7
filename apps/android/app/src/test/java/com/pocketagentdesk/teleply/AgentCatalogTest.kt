package com.pocketagentdesk.teleply

import androidx.compose.ui.graphics.Color
import java.util.Locale
import kotlinx.coroutines.test.runTest
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test

class AgentCatalogTest {
    private val testingJson = JSONObject(
        """
        {
          "schema": 1,
          "id": "testing",
          "name": {"zh": "测试助手", "en": "Test Helper"},
          "order": 99,
          "color": "#7C3AED",
          "color_dark": "#A78BFA",
          "icon": {"kind": "builtin", "key": "generic"},
          "legacy": false,
          "min_protocol": 2,
          "capabilities": {
            "list": true, "read": true, "search": true, "open": true,
            "stop": true, "queue": true, "steer": true, "approve": true,
            "answer": true, "new": true, "new_projectless": true, "new_permission": true,
            "archive": true, "restore": true, "delete": true, "usage": true,
            "waiting": true, "attachments": true, "slash_commands": true,
            "settings": ["model", "effort"],
            "send_modes": ["send", "steer", "queue"],
            "statuses": ["running", "waiting", "idle", "unknown"]
          },
          "params": {"state_timeout_s": 2, "send_timeout_s": 5, "refresh_ms": 1000},
          "ui": {"card_layout": "generic.v1", "waiting_text": "等待你处理"}
        }
        """.trimIndent(),
    )

    @Test fun parsesManifestOrderCapabilitiesAndLocale() {
        val info = parseAgentInfo(testingJson)!!
        assertEquals("testing", info.id)
        assertEquals("测试助手", info.displayName(Locale.CHINA))
        assertEquals("Test Helper", info.displayName(Locale.US))
        assertEquals(99, info.order)
        assertTrue(info.caps.stop)
        assertTrue(info.caps.delete)
        assertEquals(listOf("send", "steer", "queue"), info.caps.sendModes)
        assertEquals(2L, info.params.stateTimeoutS)
        assertEquals(1000L, info.params.refreshMs)
        assertEquals("generic.v1", info.ui.cardLayout)
        // Invalid id is ignored safely.
        assertNull(parseAgentInfo(JSONObject().put("id", "../evil")))
        assertNull(parseAgentInfo(JSONObject().put("id", "Upper")))
    }

    @Test fun builtinThreeKeepAppBrandColoursEvenWhenManifestDiffers() {
        val codexFromServer = parseAgentInfo(
            JSONObject(
                """{"id":"codex","name":{"zh":"Codex","en":"Codex"},"order":10,"color":"#1E222A","color_dark":"#FFFFFF","icon":{"kind":"builtin","key":"codex"}}""",
            ),
        )!!
        val snapshot = AgentCatalogSnapshot.fromServer(listOf(codexFromServer))
        assertEquals(Color(0xFF1E222A), snapshot.color("codex", dark = false))
        assertEquals(Color(0xFFEEEEEE), snapshot.color("codex", dark = true))
        assertEquals(Color(0xFF111111), snapshot.badgeColor("codex"))
        // Built-in defaults match Claude and DeepSeek too.
        assertEquals(Color(0xFFD97757), AgentCatalogSnapshot.Builtin.color("claude", false))
        assertEquals(Color(0xFF4D6BFE), AgentCatalogSnapshot.Builtin.color("deepseek", false))
    }

    @Test fun unknownAssistantFallsBackToIdNeutralGreyAndReadOnly() {
        val snap = AgentCatalogSnapshot.Builtin
        assertEquals("mystery_bot", snap.name("mystery_bot"))
        assertEquals(AgentCatalogSnapshot.NeutralLight, snap.color("mystery_bot", dark = false))
        assertEquals(AgentCatalogSnapshot.NeutralDark, snap.color("mystery_bot", dark = true))
        assertEquals(AgentCatalogSnapshot.NeutralLight, snap.badgeColor("mystery_bot"))
        assertEquals("generic", snap.icon("mystery_bot").key)
        assertTrue(snap.can("mystery_bot") { it.read })
        assertFalse(snap.can("mystery_bot") { it.stop })
        assertFalse(snap.can("mystery_bot") { it.archive })
        assertTrue(snap.sendModes("mystery_bot").isEmpty())
    }

    @Test fun cachesPerDeviceAndRefreshesWhenStatusVersionChanges() = runTest {
        val catalog = AgentCatalog()
        val devA = "a".repeat(32)
        val devB = "b".repeat(32)
        var callsA = 0
        var callsB = 0
        var includeTesting = false
        val api = object : TestApi() {
            override suspend fun agents(device: String): List<AgentInfo>? {
                if (device == devA) {
                    callsA++
                    return if (includeTesting) AgentCatalogSnapshot.BuiltinAgents + parseAgentInfo(testingJson)!! else AgentCatalogSnapshot.BuiltinAgents
                }
                callsB++
                return null // legacy host: 404
            }
        }
        val first = catalog.load(devA, api, statusVersion = "0.27.0-dev.43")
        assertTrue(first.fromServer)
        assertEquals(listOf("codex", "claude", "deepseek"), first.order)
        assertEquals(1, callsA)
        // Same version -> served from cache.
        catalog.load(devA, api, statusVersion = "0.27.0-dev.43")
        assertEquals(1, callsA)
        // Different device B -> 404 fallback, does not affect device A.
        val bSnap = catalog.load(devB, api, statusVersion = "0.26.0")
        assertFalse(bSnap.fromServer)
        assertEquals(listOf("codex", "claude", "deepseek"), bSnap.order)
        assertEquals(1, callsB)
        // Device A upgrades -> status version changes -> re-fetches /api/agents!
        includeTesting = true
        assertTrue(catalog.needsRefresh(devA, "0.27.0-dev.44"))
        val updated = catalog.load(devA, api, statusVersion = "0.27.0-dev.44")
        assertEquals(2, callsA)
        assertEquals(listOf("codex", "claude", "deepseek", "testing"), updated.order)
    }
}
