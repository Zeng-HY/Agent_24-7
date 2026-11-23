package com.pocketagentdesk.teleply

import kotlinx.coroutines.*
import kotlinx.coroutines.test.*
import org.json.JSONArray
import org.json.JSONObject
import org.junit.*
import org.junit.Assert.*

/** A store that keeps interaction details (the per-computer copy of its apps lives there). */
private class SourceStore(var prefs: Preferences = Preferences()) : ReaderStore {
    val details = mutableMapOf<Pair<ChatKey, String>, String>()
    override suspend fun detail(key: ChatKey, kind: String) = details[key to kind]
    override suspend fun detail(key: ChatKey, kind: String, value: String) { details[key to kind] = value }
    override suspend fun preferences() = prefs
    override suspend fun setOrigin(origin: String) { prefs = Preferences(origin = origin) }
    override suspend fun appearance(theme: String, dynamic: Boolean) = Unit
    override suspend fun selection(scope: String, device: String, chat: String, title: String) { prefs = prefs.copy(scope = scope, device = device, chat = chat, title = title) }
}

/** Two computers: A has all three apps, B only Codex and DeepSeek (like a tester's). The tree can be slow or fail. */
private class SourceApi : TestApi() {
    val apps = mutableMapOf(a.id to listOf("codex", "claude", "deepseek"), b.id to listOf("codex", "deepseek"))
    val manifests = mutableMapOf<String, List<AgentInfo>?>()
    var statusVersion = "0.27.0-dev.43"
    var agentsReads = 0
    var treeFails = false
    var treeDelay = 0L
    var treeReads = 0
    val listed = mutableListOf<Pair<String, String>>()
    override suspend fun agents(device: String): List<AgentInfo>? {
        agentsReads++
        return if (device in manifests) manifests[device] else null
    }
    override suspend fun detail(device: String, route: String, query: Map<String, String?>, body: JSONObject?): JSONObject {
        if (route == "status") return JSONObject().put("ok", true).put("ui_version", statusVersion)
        if (route != "chat/projects") return JSONObject()
        treeReads++
        if (treeDelay > 0) delay(treeDelay)
        if (treeFails) throw java.io.IOException("offline")
        // An app with no conversations is still a group (chat_projects.tree); an app not installed is not (remote.py).
        return JSONObject().put("apps", JSONArray(apps[device].orEmpty().map { JSONObject().put("app", it).put("name", manifests[device]?.find { m -> m.id == it }?.displayName() ?: sourceName(it)).put("projects", JSONArray()) }))
    }
    override suspend fun chatList(device: String, app: String, query: String, cursor: String?, sort: String, status: String): Page<Chat> {
        listed += device to app
        val rows = apps[device].orEmpty().filter { app == "all" || it == app }.map { Chat("$it-1", "$it 对话", app = it) }
        return Page(rows)
    }
}

@OptIn(ExperimentalCoroutinesApi::class)
class SourcesTest {
    private val dispatcher = StandardTestDispatcher()
    @Before fun setup() { Dispatchers.setMain(dispatcher) }
    @After fun cleanup() { Dispatchers.resetMain() }

    private suspend fun TestScope.signedIn(api: SourceApi, store: SourceStore = SourceStore()): ReaderViewModel {
        val vm = ReaderViewModel(store) { api }; advanceUntilIdle()
        vm.connect("https://example.invalid"); advanceUntilIdle()
        vm.login("fixture", "test"); advanceUntilIdle()
        return vm
    }

    @Test fun aComputerWithoutClaudeOffersOnlyItsOwnApps() = runTest(dispatcher) {
        val api = SourceApi(); val vm = signedIn(api)
        vm.select(api.b); advanceUntilIdle()
        assertEquals(listOf("codex", "deepseek"), vm.state.value.knownApps())
        // A new conversation asked for in Claude starts in an app this computer has.
        assertEquals("codex", vm.state.value.newApp("claude"))
        assertEquals("deepseek", vm.state.value.newApp("deepseek"))
    }

    @Test fun anAppWithoutConversationsStillCounts() = runTest(dispatcher) {
        val api = SourceApi(); val vm = signedIn(api)
        vm.select(api.a); advanceUntilIdle()
        assertEquals(listOf("codex", "claude", "deepseek"), vm.state.value.knownApps())
    }

    @Test fun notKnownWhileReadingAndAFailureNeverMeansAllThree() = runTest(dispatcher) {
        val api = SourceApi(); val vm = signedIn(api)
        api.treeDelay = 5_000
        vm.select(api.b); advanceTimeBy(1_000); runCurrent()
        assertEquals(Screen.Chats, vm.state.value.screen)
        assertNull(vm.state.value.knownApps())
        assertTrue(vm.state.value.sources.loading)
        api.treeFails = true; advanceUntilIdle()
        assertNull(vm.state.value.knownApps())
        assertNotNull(vm.state.value.sources.failed)
        assertFalse(vm.state.value.sources.loading)
        // 重试 once the computer answers again.
        api.treeFails = false; api.treeDelay = 0
        vm.retrySources(); advanceUntilIdle()
        assertEquals(listOf("codex", "deepseek"), vm.state.value.knownApps())
        assertNull(vm.state.value.sources.failed)
    }

    @Test fun thisPhonesCopyShowsAtOnceAndStaysWhenTheComputerCannotBeAsked() = runTest(dispatcher) {
        val api = SourceApi(); val store = SourceStore(); val vm = signedIn(api, store)
        vm.select(api.b); advanceUntilIdle()
        assertTrue(store.details.values.contains("codex,deepseek"))
        // The app starts again (same sign-in, same computer); the computer does not answer this time.
        val again = SourceApi().also { it.treeFails = true }
        val restarted = ReaderViewModel(store) { again }; advanceUntilIdle()
        assertEquals(api.b.id, restarted.state.value.device?.id)
        assertEquals(listOf("codex", "deepseek"), restarted.state.value.knownApps())
        assertNotNull(restarted.state.value.sources.failed)
    }

    @Test fun anotherComputerNeverShowsTheLastOnesApps() = runTest(dispatcher) {
        val api = SourceApi(); val vm = signedIn(api)
        vm.select(api.a); advanceUntilIdle()
        assertEquals(3, vm.state.value.knownApps()!!.size)
        api.treeDelay = 5_000
        vm.select(api.b); advanceTimeBy(1_000); runCurrent()
        // Never A's three while B is asked: unknown (B was not seen from this phone before).
        assertNull(vm.state.value.knownApps())
        advanceUntilIdle()
        assertEquals(listOf("codex", "deepseek"), vm.state.value.knownApps())
    }

    @Test fun aFilterOnAnAppTheNextComputerLacksFallsBackToAll() = runTest(dispatcher) {
        val api = SourceApi(); val vm = signedIn(api)
        vm.select(api.a); advanceUntilIdle()
        vm.listDisplay(source = "claude"); advanceUntilIdle()
        assertTrue(vm.state.value.chats.all { it.app == "claude" })
        vm.select(api.b); advanceUntilIdle()
        assertEquals("all", vm.state.value.listSource)
        assertEquals(setOf("codex", "deepseek"), vm.state.value.chats.map { it.app }.toSet())
        assertFalse(api.listed.contains(api.b.id to "claude"))
    }

    @Test fun anAppGoneFromTheComputerTakesItsFilterWithIt() = runTest(dispatcher) {
        val api = SourceApi(); val vm = signedIn(api)
        vm.select(api.a); advanceUntilIdle()
        vm.listDisplay(source = "claude"); advanceUntilIdle()
        // Claude was removed there; the next read of the computer says so.
        api.apps[api.a.id] = listOf("codex", "deepseek")
        vm.retrySources(); advanceUntilIdle()
        assertEquals("all", vm.state.value.listSource)
        assertEquals(setOf("codex", "deepseek"), vm.state.value.chats.map { it.app }.toSet())
        assertFalse(vm.state.value.busy)
    }

    @Test fun newConversationOpensWithoutWaitingOrCancellingTheList() = runTest(dispatcher) {
        val api = SourceApi(); val vm = signedIn(api)
        vm.select(api.b); advanceUntilIdle()
        val reads = api.treeReads
        vm.startNew("claude")
        // At once, no page operation: no progress, no new read of the computer's tree.
        assertFalse(vm.state.value.busy)
        assertEquals("codex", vm.state.value.pendingNew?.app)
        advanceUntilIdle()
        assertEquals(reads, api.treeReads)
    }

    @Test fun fakeHelperAppearsInListAndCatalogWithManifestOrder() = runTest(dispatcher) {
        val api = SourceApi()
        api.apps[api.a.id] = listOf("testing", "codex", "claude", "deepseek")
        api.manifests[api.a.id] = AgentCatalogSnapshot.BuiltinAgents + FixtureWorld.TESTING_AGENT
        val vm = signedIn(api)
        vm.select(api.a); advanceUntilIdle()
        // Ordered by manifest order (10, 20, 30, 99), not raw tree order.
        assertEquals(listOf("codex", "claude", "deepseek", "testing"), vm.state.value.knownApps())
        assertEquals("测试助手", vm.state.value.catalog.name("testing", java.util.Locale.CHINA))
        assertEquals("Test Helper", vm.state.value.catalog.name("testing", java.util.Locale.US))
        assertTrue(vm.state.value.chats.any { it.app == "testing" })
        // Can filter to the fake helper directly.
        vm.listDisplay(source = "testing"); advanceUntilIdle()
        assertEquals("testing", vm.state.value.listSource)
        assertTrue(vm.state.value.chats.isNotEmpty() && vm.state.value.chats.all { it.app == "testing" })
    }

    @Test fun unknownAssistantDoesNotImpersonateBuiltinsAndStaysReadOnly() = runTest(dispatcher) {
        val api = SourceApi()
        api.apps[api.a.id] = listOf("codex", "mystery_bot")
        api.manifests[api.a.id] = null // legacy /api/agents 404
        val vm = signedIn(api)
        vm.select(api.a); advanceUntilIdle()
        assertEquals(listOf("codex", "mystery_bot"), vm.state.value.knownApps())
        val catalog = vm.state.value.catalog
        assertEquals("mystery_bot", catalog.name("mystery_bot"))
        assertEquals("generic", catalog.icon("mystery_bot").key)
        assertEquals(AgentCatalogSnapshot.NeutralLight, catalog.badgeColor("mystery_bot"))
        assertFalse(catalog.can("mystery_bot") { it.new })
        assertFalse(catalog.can("mystery_bot") { it.stop })
        assertFalse(catalog.can("mystery_bot") { it.archive })
        assertTrue(catalog.sendModes("mystery_bot").isEmpty())
        // New conversation skips read-only unknown assistant.
        assertEquals(listOf("codex"), vm.state.value.newableApps())
    }

    @Test fun legacyComputerFallsBackOn404AndRefreshesWhenStatusVersionChanges() = runTest(dispatcher) {
        val api = SourceApi()
        api.manifests[api.a.id] = null // starts as old host (404)
        val vm = signedIn(api)
        vm.select(api.a); advanceUntilIdle()
        assertFalse(vm.state.value.catalog.fromServer)
        assertEquals(listOf("codex", "claude", "deepseek"), vm.state.value.catalog.order)
        // First status call records the old host version without re-fetching.
        vm.deviceCall("status"); advanceUntilIdle()
        val readsBefore = api.agentsReads
        // Host upgrades -> status returns a new version and /api/agents now returns testing.
        api.statusVersion = "0.27.0-dev.44"
        api.manifests[api.a.id] = AgentCatalogSnapshot.BuiltinAgents + FixtureWorld.TESTING_AGENT
        vm.deviceCall("status"); advanceUntilIdle()
        assertTrue(api.agentsReads > readsBefore)
        assertTrue(vm.state.value.catalog.fromServer)
        assertTrue("testing" in vm.state.value.catalog)
    }
}
