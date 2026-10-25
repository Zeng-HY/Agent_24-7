package com.pocketagentdesk.teleply

import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.createAndroidComposeRule
import androidx.lifecycle.ViewModelProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import org.json.JSONObject
import org.junit.Rule
import org.junit.Test
import org.junit.Assert.*
import org.junit.Assume.assumeTrue
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class RealCreationUiTest {
    @get:Rule val compose=createAndroidComposeRule<MainActivity>()
    @Test fun createThroughNativeFormAndReadBackActualConversation() {
        assumeTrue(InstrumentationRegistry.getArguments().getString("teleplyAllowCreate")=="true")
        lateinit var vm:ReaderViewModel
        compose.runOnIdle { vm=ViewModelProvider(compose.activity)[ReaderViewModel::class.java] }
        compose.waitUntil(30000) { !vm.state.value.busy }
        assertNotNull("Native login must already be valid",vm.state.value.account)
        compose.runOnIdle { if(vm.state.value.screen==Screen.Reading) vm.back() }
        compose.waitUntil(30000) { vm.state.value.screen==Screen.Chats && !vm.state.value.busy }
        compose.runOnIdle { if(vm.state.value.app!="codex") vm.switchSource("codex") }
        compose.waitUntil(30000) { vm.state.value.app=="codex" && !vm.state.value.busy && vm.workspace.state.value.ready }
        compose.onNodeWithContentDescription("新建对话").performClick()
        // 0.8: the sheet opens at once; a first message becomes a job followed outside the sheet (web 10-16).
        compose.waitUntil(30000) { vm.workspace.state.value.pane=="new" && vm.workspace.state.value.ready }
        val prior=JSONObject(vm.workspace.state.value.saved)
        val prompt="Teleply authorized native creation UI test. Reply only PHASE3_NATIVE_NEW_OK. Do not use tools, read or modify any files, or message other chats."
        assertTrue("Do not overwrite an unrelated creation draft",prior.string("first_message").let { it.isBlank() || it==prompt })
        // Keep the test conversation out of real projects, as before 0.4 made the last project the default.
        compose.runOnIdle { vm.workspace.chooseFolder("",true) }
        compose.onNodeWithTag("new-message").performScrollTo().performTextReplacement(prompt)
        compose.onNodeWithContentDescription("创建并发送").performScrollTo().performClick()
        // The job's page shows at once and becomes the conversation once the computer made it.
        compose.waitUntil(30000) { vm.jobs.jobs.value.any { JSONObject(it.body).string("text")==prompt } || vm.state.value.chat?.id?.startsWith("new:")==false }
        val deadline=System.currentTimeMillis()+120000
        while(System.currentTimeMillis()<deadline && vm.state.value.chat?.id?.startsWith("new:")!=false) {
            vm.jobs.jobs.value.find { JSONObject(it.body).string("text")==prompt }?.let { job -> if(job.state=="failed") fail("Creation failed; preserve original request for diagnosis: "+job.pending) }
            Thread.sleep(1000)
        }
        compose.waitUntil(30000) { vm.state.value.chat?.id?.startsWith("new:")==false && !vm.state.value.busy }
        val id=vm.state.value.chat!!.id
        assertEquals("codex",vm.state.value.app)
        println("TELEPLY_NATIVE_CREATED_TEST_THREAD=$id")
        compose.waitUntil(60000) { vm.state.value.messages.any { it.role=="assistant" && it.text.contains("PHASE3_NATIVE_NEW_OK") } }
    }
}
