package com.pocketagentdesk.teleply

import kotlinx.coroutines.*
import kotlinx.coroutines.test.*
import org.junit.*
import org.junit.Assert.*

/**
 * A computer answering the list as chat_history.py does: only the states it knows, the rows of that state in its order,
 * [size] at a time, each page starting after the end of the one before (the cursor here is that row's id).
 */
private class ListApi(private val size: Int = 2) : TestApi() {
    var rows = listOf<Chat>()
    val asked = mutableListOf<Pair<String, String?>>()
    override suspend fun chatList(device: String, app: String, query: String, cursor: String?, sort: String, status: String): Page<Chat> {
        asked += status to cursor
        if (status !in setOf("all", "running", "waiting", "idle")) throw ServiceFailure(400, detail = "状态筛选无效")
        val order = compareBy<Chat>({ -(if (sort == "created") it.created else it.updated) }, { it.app }, { it.id })
        val shown = rows.filter { status == "all" || it.status == status }.sortedWith(order)
        val rest = if (cursor == null) shown else shown.filter { order.compare(it, rows.first { r -> r.id == cursor }) > 0 }
        val more = rest.size > size
        return Page(rest.take(size), if (more) rest[size - 1].id else null, more)
    }
}

@OptIn(ExperimentalCoroutinesApi::class)
class ListFilterTest {
    private val dispatcher = StandardTestDispatcher()
    @Before fun setup() { Dispatchers.setMain(dispatcher) }
    @After fun cleanup() { Dispatchers.resetMain() }

    /** A row for each letter, newest first. */
    private fun rows(names: String, status: String = "running") = names.mapIndexed { i, name -> Chat("$name", "$name", status = status, app = "codex", updated = 1000L - i) }
    private fun ended(rows: List<Chat>, names: String) = rows.map { if (it.id in names) it.copy(status = "idle") else it }
    private fun ids(vm: ReaderViewModel) = vm.state.value.chats.joinToString("") { it.id }

    private suspend fun TestScope.onComputer(api: ListApi): ReaderViewModel {
        val vm = ReaderViewModel(TestStore()) { api }; advanceUntilIdle()
        vm.connect("https://example.invalid"); advanceUntilIdle()
        vm.login("fixture", "test"); advanceUntilIdle()
        vm.select(api.a); advanceUntilIdle()
        return vm
    }

    /** The read made every 10 s while the list is in front. */
    private fun TestScope.nextRead(vm: ReaderViewModel) {
        vm.live(true); advanceTimeBy(10_000); runCurrent(); vm.live(false); runCurrent()
    }

    /** 11-02 (as iOS): a conversation that ended is not in a running-only list any more; kept, it said 运行中 for hours. */
    @Test fun aRowThatEndedLeavesAListOfOneState() = runTest(dispatcher) {
        val api = ListApi(); api.rows = rows("ab")
        val vm = onComputer(api)
        vm.listDisplay(status = "running"); advanceUntilIdle()
        assertEquals("ab", ids(vm))
        api.rows = ended(api.rows, "b")
        nextRead(vm)
        assertEquals("a", ids(vm))
        assertFalse(vm.state.value.listMore)
    }

    /** 加载更多 is not taken back at the next read: 已结束 could not be read past its first page. */
    @Test fun thePagesReadPastTheFirstStayInAListOfOneState() = runTest(dispatcher) {
        val api = ListApi(); api.rows = rows("abcde", "idle")
        val vm = onComputer(api)
        vm.listDisplay(status = "idle"); advanceUntilIdle()
        vm.moreChats(); advanceUntilIdle()
        assertEquals("abcd", ids(vm))
        nextRead(vm)
        assertEquals("abcd", ids(vm))
        assertEquals("d", vm.state.value.listCursor)
        assertTrue(vm.state.value.listMore)
        vm.moreChats(); advanceUntilIdle()
        assertEquals("idle" to "d", api.asked.last())
        assertEquals("abcde", ids(vm))
    }

    @Test fun aRowThatLeftItsStateGoesEvenWithLaterPagesRead() = runTest(dispatcher) {
        val api = ListApi(); api.rows = rows("abcdef")
        val vm = onComputer(api)
        vm.listDisplay(status = "running"); advanceUntilIdle()
        vm.moreChats(); advanceUntilIdle()
        assertEquals("abcd", ids(vm))
        api.rows = ended(api.rows, "b")
        nextRead(vm)
        assertEquals("acd", ids(vm))
        assertEquals("d", vm.state.value.listCursor)
        vm.moreChats(); advanceUntilIdle()
        assertEquals("acdef", ids(vm))
    }

    /** A newer row takes the first page's place: the last one there has not left its state, it is on the next page. */
    @Test fun aRowPushedOffTheFirstPageStays() = runTest(dispatcher) {
        val api = ListApi(); api.rows = rows("abcde")
        val vm = onComputer(api)
        vm.listDisplay(status = "running"); advanceUntilIdle()
        assertEquals("ab", ids(vm))
        api.rows = listOf(Chat("n", "n", status = "running", app = "codex", updated = 2000)) + api.rows
        nextRead(vm)
        assertEquals("nab", ids(vm))
        assertEquals("b", vm.state.value.listCursor)
        vm.moreChats(); advanceUntilIdle()
        assertEquals("nabcd", ids(vm))
    }

    @Test fun rowsPastTheFirstPageGoOnceTheListFitsOnIt() = runTest(dispatcher) {
        val api = ListApi(); api.rows = rows("abcde")
        val vm = onComputer(api)
        vm.listDisplay(status = "running"); advanceUntilIdle()
        vm.moreChats(); advanceUntilIdle()
        assertEquals("abcd", ids(vm))
        api.rows = ended(api.rows, "cde")
        nextRead(vm)
        assertEquals("ab", ids(vm))
        assertNull(vm.state.value.listCursor)
        assertFalse(vm.state.value.listMore)
    }

    /** Sorted by 创建时间, that order says which rows come after the first page: here newly active ones still do. */
    @Test fun sortedByCreationThatOrderDecidesWhatStays() = runTest(dispatcher) {
        val api = ListApi()
        api.rows = listOf(50L to 1L, 40L to 2L, 30L to 99L, 20L to 98L, 10L to 3L).mapIndexed { i, (created, updated) -> Chat("abcde"[i].toString(), "x", status = "idle", app = "codex", updated = updated, created = created) }
        val vm = onComputer(api)
        vm.listDisplay(sort = "created", status = "idle"); advanceUntilIdle()
        vm.moreChats(); advanceUntilIdle()
        assertEquals("abcd", ids(vm))
        nextRead(vm)
        assertEquals("abcd", ids(vm))
    }

    /** The whole list as before: a row the first page leaves out may be on a later page, and where the next page starts stays. */
    @Test fun theWholeListKeepsThePagesReadPastTheFirst() = runTest(dispatcher) {
        val api = ListApi(); api.rows = rows("abcde")
        val vm = onComputer(api)
        vm.moreChats(); advanceUntilIdle()
        assertEquals("abcd", ids(vm))
        api.rows = listOf(Chat("n", "n", status = "running", app = "codex", updated = 2000)) + api.rows
        nextRead(vm)
        assertEquals("nabcd", ids(vm))
        assertEquals("d", vm.state.value.listCursor)
        assertTrue(vm.state.value.listMore)
    }

    /** 11-02: 已结束 sent done, which the computer refuses (状态筛选无效). */
    @Test fun everyStateOnTheMenuIsOneTheComputerTakes() = runTest(dispatcher) {
        val api = ListApi(); api.rows = rows("r") + rows("w", "waiting") + rows("i", "idle")
        val vm = onComputer(api)
        for ((value, label) in ListStates) {
            vm.listDisplay(status = value); advanceUntilIdle()
            assertNull(label, vm.state.value.error)
        }
        vm.listDisplay(status = ListStates.first { it.second == "已结束" }.first); advanceUntilIdle()
        assertEquals("i", ids(vm))
    }

    /** The demo computer takes the same value: its 已结束 is the rows that finished; only that list has its second page. */
    @Test fun theDemoAnswersTheSameStates() = runTest(dispatcher) {
        val api = FixtureApi(); val device = api.world.devices.first().id
        val all = api.chatList(device, "all", "", null, "updated", "all").items
        val ended = api.chatList(device, "all", "", null, "updated", ListStates.first { it.second == "已结束" }.first)
        assertTrue(ended.items.isNotEmpty() && ended.items.size < all.size)
        assertTrue(ended.items.all { it.status in setOf("idle", "stopped", "failed") })
        assertTrue(ended.hasMore)
        assertFalse(api.chatList(device, "all", "", null, "updated", "running").hasMore)
        assertTrue(all.all { it.created == it.updated })
    }
}
