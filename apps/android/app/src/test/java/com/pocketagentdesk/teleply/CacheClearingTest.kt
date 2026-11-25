package com.pocketagentdesk.teleply

import java.io.File
import java.nio.file.Files
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.UnconfinedTestDispatcher
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import org.junit.After
import org.junit.Assert.*
import org.junit.Before
import org.junit.Test

/** §7: 退出登录 leaves no answer thumb or kept original behind on this phone. */
@OptIn(ExperimentalCoroutinesApi::class)
class CacheClearingTest {
    private val dispatcher = UnconfinedTestDispatcher()

    @Before fun setup() { Dispatchers.setMain(dispatcher) }
    @After fun cleanup() { Dispatchers.resetMain() }

    @Test fun signingOutClearsEverythingKept() = runTest(dispatcher) {
        val caches = Files.createTempDirectory("teleply-signout").toFile()
        try {
            File(caches, "$ThumbCacheFolder/pc-a").mkdirs()
            File(caches, "$FileCacheFolder/pc-a").mkdirs()
            val vm = ReaderViewModel(TestStore(), apiFactory = { FixtureApi() })
            vm.mediaDir = caches
            vm.logout()
            advanceUntilIdle()
            assertFalse(File(caches, ThumbCacheFolder).exists())
            assertFalse(File(caches, FileCacheFolder).exists())
        } finally {
            caches.deleteRecursively()
        }
    }
}
