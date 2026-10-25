package com.pocketagentdesk.nativepreview
import org.junit.runner.RunWith
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.compose.ui.test.*
import androidx.compose.ui.graphics.asAndroidBitmap
import androidx.test.platform.app.InstrumentationRegistry
import org.junit.Test
@RunWith(AndroidJUnit4::class)
class ReaderDeviceTest:ReaderUiScenarios() {
    @Test fun shareChooserCancellationDoesNotClaimDelivery() {
        launch();fixtureList();compose.onNodeWithText("原生阅读示例").performClick()
        compose.waitUntil(10000) { vm.workspace.state.value.ready && !vm.state.value.busy }
        compose.onNodeWithContentDescription("对话菜单").performClick()
        compose.onNodeWithText("对话文件").performClick();compose.waitUntil(10000) { !vm.workspace.state.value.busy }
        compose.onNodeWithText("安全预览.html").performClick();compose.waitUntil(10000) { vm.workspace.state.value.pane=="file" && !vm.workspace.state.value.busy }
        compose.onNodeWithText("系统分享").performScrollTo().performClick()
        compose.waitUntil(10000) { !vm.workspace.state.value.busy }
        val automation=InstrumentationRegistry.getInstrumentation().uiAutomation
        automation.waitForIdle(500,5000)
        android.os.ParcelFileDescriptor.AutoCloseInputStream(automation.executeShellCommand("input keyevent 4")).use { it.readBytes() }
        compose.waitForIdle();compose.onNodeWithText("系统分享").assertExists()
        org.junit.Assert.assertTrue(vm.workspace.state.value.result.contains("选择器"))
        org.junit.Assert.assertFalse(vm.workspace.state.value.result.contains("分享完成"))
    }
    @Test fun fixtureSettingsNeverEnablesRealBackgroundWatch() {
        launch();fixtureList();compose.onNodeWithContentDescription("打开导航").performClick()
        compose.onNodeWithContentDescription("设置").performClick()
        compose.onNodeWithText("本地示例不会启用真实后台任务").performScrollTo().assertIsDisplayed()
        compose.onNodeWithText("关注当前会话状态").assertDoesNotExist()
    }
    @Test fun documentPickerCancelPreservesOrdinaryDraft() {
        launch();fixtureList();compose.onNodeWithText("原生阅读示例").performClick()
        compose.waitUntil(10000) { vm.workspace.state.value.ready && !vm.state.value.busy }
        compose.onNodeWithTag("composer").performTextInput("保留原草稿")
        compose.onNodeWithContentDescription("添加附件或引用").performClick()
        compose.onNodeWithText("手机文件").performClick()
        val automation=InstrumentationRegistry.getInstrumentation().uiAutomation
        automation.waitForIdle(500,5000)
        android.os.ParcelFileDescriptor.AutoCloseInputStream(automation.executeShellCommand("input keyevent 4")).use { it.readBytes() }
        compose.waitForIdle();compose.onNodeWithTag("composer").assertExists()
        org.junit.Assert.assertEquals("保留原草稿",vm.composer.state.value.draft)
        org.junit.Assert.assertTrue(org.json.JSONObject(vm.workspace.state.value.saved).rows("uploads") { it }.isEmpty())
    }
    @Test fun phase3QuestionEvidence() {
        launch();fixtureList();compose.onNodeWithText("原生阅读示例").performClick()
        compose.waitUntil(10000) { vm.workspace.state.value.ready && !vm.state.value.busy && vm.composer.state.value.control.questions }
        compose.onNodeWithTag("messages").performScrollToKey("interactions")
        compose.onNodeWithContentDescription("选择方案A").performScrollTo().performClick()
        compose.onNodeWithText("提交回答").performScrollTo().assertIsEnabled()
        val context=InstrumentationRegistry.getInstrumentation().targetContext
        java.io.File(context.getExternalFilesDir(null),"phase3-question-fixture.png").outputStream().use { compose.onRoot().captureToImage().asAndroidBitmap().compress(android.graphics.Bitmap.CompressFormat.PNG,100,it) }
    }
    @Test fun rapidKeyboardInputAndBackPreserveDraft() {
        launch();fixtureList()
        compose.onNodeWithText("原生阅读示例").performClick()
        compose.waitUntil(10000) { vm.composer.state.value.ready && vm.composer.state.value.control.available }
        compose.onNodeWithTag("composer").performClick()
        compose.onNodeWithTag("composer").assertIsFocused()
        compose.waitUntil(10000) { androidx.core.view.ViewCompat.getRootWindowInsets(androidView)?.isVisible(androidx.core.view.WindowInsetsCompat.Type.ime())==true }
        val automation=InstrumentationRegistry.getInstrumentation().uiAutomation
        fun shell(command:String) { android.os.ParcelFileDescriptor.AutoCloseInputStream(automation.executeShellCommand(command)).use { it.readBytes() } }
        // Insets can become visible before the IME finishes establishing its input connection.
        automation.waitForIdle(500,5000)
        shell("input text Teleply%srapid%skeyboard%sinput%skeeps%sthe%scursor.")
        compose.waitForIdle()
        org.junit.Assert.assertEquals("native keyboard input", "Teleply rapid keyboard input keeps the cursor.",vm.composer.state.value.draft)
        shell("input keyevent 4")
        compose.waitUntil(10000) { androidx.core.view.ViewCompat.getRootWindowInsets(androidView)?.isVisible(androidx.core.view.WindowInsetsCompat.Type.ime())==false }
        org.junit.Assert.assertEquals(Screen.Reading,vm.state.value.screen)
        org.junit.Assert.assertEquals("Teleply rapid keyboard input keeps the cursor.",vm.composer.state.value.draft)
    }
    @Test fun phase2FixtureScreenshotAndLargeText() {
        launch("dark",1.5f);fixtureList()
        compose.onNodeWithText("原生阅读示例").performClick()
        compose.waitUntil(10000) { vm.composer.state.value.ready && vm.composer.state.value.control.available }
        compose.onNodeWithTag("composer").performTextInput("固定示例：中文草稿与提交回执")
        compose.onNodeWithContentDescription("发送").assertIsDisplayed()
        val context=InstrumentationRegistry.getInstrumentation().targetContext
        val file=java.io.File(context.getExternalFilesDir(null),"phase2-fixture-dark-large.png")
        file.outputStream().use { compose.onRoot().captureToImage().asAndroidBitmap().compress(android.graphics.Bitmap.CompressFormat.PNG,100,it) }
        compose.onNodeWithContentDescription("发送").performClick()
        compose.waitUntil(10000) { vm.composer.state.value.submissions.firstOrNull()?.label=="已接收" }
        compose.onNodeWithText("停止这一轮").assertHasClickAction()
    }
}
