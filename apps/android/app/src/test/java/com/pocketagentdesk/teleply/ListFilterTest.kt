package com.pocketagentdesk.teleply

import kotlinx.coroutines.*
import kotlinx.coroutines.test.*
import org.junit.*
import org.junit.Assert.*

/** A computer answering the list as chat_history.py does: only the states it knows, the rows of that state, [size] at a time. */
private class ListApi(private val size: Int = 2) : TestApi() {
    var rows = listOf<Chat>()
    val asked = mutableListOf<Pair<String, String?>>()
    override suspend fun chatList(device: String, app: String, query: String, cursor: String?, sort: String, status: String): Page<Chat> {
        asked += status to cursor
        if (status !in setOf("all", "running", "waiting", "idle")) throw ServiceFailure(400, detail = "状态筛选无效")
        val shown = rows.filter { status == "all" || it.status == status }
        val start = cursor?.toInt() ?: 0
        val more = start + size < shown.size
        return Page(shown.drop(start).take(size), if (more) "${start + size}" else null, more)
    }
}

@OptIn(ExperimentalCoroutinesApi::class)
class ListFilterTest {
    private val dispatcher = StandardTestDispatcher()
    @Before fun setup() { Dispatchers.setMain(dispatcher) }
    @After fun cleanup() { Dispatchers.resetMain() }

    private fun chat(id: String, status: String = "running") = Chat(id, id, status = status, app = "codex")
    private fun ids(vm: ReaderViewModel) = vm.state.value.chats.map { it.id }

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
        val api = ListApi(); api.rows = listOf(chat("a"), chat("b"))
        val vm = onComputer(api)
        vm.listDisplay(status = "running"); advanceUntilIdle()
        assertEquals(listOf("a", "b"), ids(vm))
        api.rows = listOf(chat("a"), chat("b", "idle"))
        nextRead(vm)
        assertEquals(listOf("a"), ids(vm))
        assertFalse(vm.state.value.listMore)
    }

    /** In a list of one state the rows and where the next page starts both follow the first page: 加载更多 reads on from there. */
    @Test fun aListOfOneStateFollowsItsFirstPage() = runTest(dispatcher) {
        val api = ListApi(); api.rows = ('a'..'e').map { chat("$it") }
        val vm = onComputer(api)
        vm.listDisplay(status = "running"); advanceUntilIdle()
        vm.moreChats(); advanceUntilIdle()
        assertEquals(listOf("a", "b", "c", "d"), ids(vm))
        assertEquals("4", vm.state.value.listCursor)
        nextRead(vm)
        assertEquals(listOf("a", "b"), ids(vm))
        assertEquals("2", vm.state.value.listCursor)
        assertTrue(vm.state.value.listMore)
        vm.moreChats(); advanceUntilIdle()
        assertEquals("running" to "2", api.asked.last())
        assertEquals(listOf("a", "b", "c", "d"), ids(vm))
    }

    /** The whole list as before: a row the first page leaves out may be on a later page, and where the next page starts stays. */
    @Test fun theWholeListKeepsThePagesReadPastTheFirst() = runTest(dispatcher) {
        val api = ListApi(); api.rows = ('a'..'e').map { chat("$it") }
        val vm = onComputer(api)
        vm.moreChats(); advanceUntilIdle()
        assertEquals(listOf("a", "b", "c", "d"), ids(vm))
        api.rows = listOf(chat("n")) + api.rows
        nextRead(vm)
        assertEquals(listOf("n", "a", "b", "c", "d"), ids(vm))
        assertEquals("4", vm.state.value.listCursor)
        assertTrue(vm.state.value.listMore)
    }

    /** 11-02: 已结束 sent done, which the computer refuses (状态筛选无效). */
    @Test fun everyStateOnTheMenuIsOneTheComputerTakes() = runTest(dispatcher) {
        val api = ListApi(); api.rows = listOf(chat("r"), chat("w", "waiting"), chat("i", "idle"))
        val vm = onComputer(api)
        for ((value, label) in ListStates) {
            vm.listDisplay(status = value); advanceUntilIdle()
            assertNull(label, vm.state.value.error)
        }
        vm.listDisplay(status = ListStates.first { it.second == "已结束" }.first); advanceUntilIdle()
        assertEquals(listOf("i"), ids(vm))
    }

    /** The demo computer takes the same value: its 已结束 is the rows that finished, not all of them. */
    @Test fun theDemosEndedListHasOnlyFinishedRows() = runTest(dispatcher) {
        val api = FixtureApi(); val device = api.world.devices.first().id
        val all = api.chatList(device, "all", "", null, "updated", "all").items
        val ended = api.chatList(device, "all", "", null, "updated", ListStates.first { it.second == "已结束" }.first).items
        assertTrue(ended.isNotEmpty() && ended.size < all.size)
        assertTrue(ended.all { it.status in setOf("idle", "stopped", "failed") })
    }
}
