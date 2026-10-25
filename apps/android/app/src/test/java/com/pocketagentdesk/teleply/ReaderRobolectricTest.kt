package com.pocketagentdesk.teleply
import org.junit.runner.RunWith
import org.junit.Test
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import org.robolectric.annotation.GraphicsMode
import androidx.compose.ui.test.*
import androidx.compose.ui.graphics.asAndroidBitmap
import java.io.File
import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.unit.dp
@RunWith(RobolectricTestRunner::class)
@Config(sdk=[35],qualifiers="w412dp-h892dp-xxhdpi",application=android.app.Application::class)
@GraphicsMode(GraphicsMode.Mode.NATIVE)
class ReaderRobolectricTest:ReaderUiScenarios() {
    @Test @Config(qualifiers="w1200dp-h800dp-xhdpi") fun resizingMovesReaderWithoutDiscardingDraftOrAnchor() {
        val width=mutableStateOf(1200.dp);launch(windowWidth=width);fixtureList()
        compose.onNodeWithText("原生阅读示例").performClick();compose.waitUntil(10000) { !vm.state.value.busy && vm.composer.state.value.ready }
        compose.onNodeWithTag("composer").performTextInput("窗口切换草稿")
        compose.onNodeWithTag("messages").performScrollToIndex(1)
        compose.runOnIdle { vm.saveAnchor("m1",0);width.value=700.dp }
        compose.onNodeWithTag("two-pane").assertDoesNotExist()
        compose.onNodeWithText("请展示原生 Markdown 阅读。").assertIsDisplayed()
        org.junit.Assert.assertEquals("窗口切换草稿",vm.composer.state.value.draft)
        compose.runOnIdle { width.value=1200.dp }
        compose.onNodeWithTag("two-pane").assertExists()
        compose.onNodeWithText("请展示原生 Markdown 阅读。").assertIsDisplayed()
        org.junit.Assert.assertEquals("窗口切换草稿",vm.composer.state.value.draft)
    }
    @Test @Config(qualifiers="w1200dp-h800dp-xhdpi") fun wideWindowUsesListAndDetail() {
        launch();fixtureList();compose.onNodeWithText("原生阅读示例").performClick()
        compose.waitUntil(10000) { vm.state.value.screen==Screen.Reading && !vm.state.value.busy }
        compose.onNodeWithTag("two-pane").assertExists();compose.onNodeWithTag("composer").assertExists()
        capture("phase4-wide-jvm")
    }
    @Test @Config(qualifiers="w1200dp-h800dp-xhdpi") fun largeTextFallsBackWithoutLosingDraft() {
        launch("dark",2f);fixtureList();compose.onNodeWithText("原生阅读示例").performClick()
        compose.waitUntil(10000) { vm.composer.state.value.ready }
        compose.onNodeWithTag("two-pane").assertDoesNotExist()
        compose.onNodeWithTag("composer").performTextInput("大字草稿")
        compose.onNodeWithContentDescription("发送").assertIsDisplayed()
    }
    private fun capture(name:String) {
        compose.waitForIdle()
        compose.runOnIdle {
            val view=androidView.rootView
            val bitmap=android.graphics.Bitmap.createBitmap(view.width,view.height,android.graphics.Bitmap.Config.ARGB_8888)
            view.draw(android.graphics.Canvas(bitmap))
            val file=File("build/ui-evidence/$name.png");file.parentFile?.mkdirs()
            file.outputStream().use { bitmap.compress(android.graphics.Bitmap.CompressFormat.PNG,100,it) }
            bitmap.recycle()
        }
    }
    @Test fun lightFixtureEvidence() {
        launch();compose.waitUntil(10000) { vm.state.value.screen==Screen.Login && !vm.state.value.busy };capture("01-login-light-jvm")
        openDemo();capture("02-login-fixture-jvm")
        compose.onNodeWithText("进入示例").performClick()
        compose.waitUntil(10000) { vm.state.value.screen==Screen.Devices && !vm.state.value.busy };capture("03-devices-jvm")
        compose.onNodeWithText("测试电脑 A").performClick()
        compose.waitUntil(10000) { vm.state.value.screen==Screen.Chats && !vm.state.value.busy };capture("04-chats-jvm")
        compose.onNodeWithText("原生阅读示例").performClick()
        compose.waitUntil(10000) { vm.state.value.screen==Screen.Reading && !vm.state.value.busy };compose.onNodeWithTag("messages").performScrollToIndex(0);capture("05-reading-light-jvm")
        compose.onNodeWithTag("messages").performTouchInput { swipeUp() };capture("06-code-table-jvm")
    }
    @Test fun darkLargeTextEvidence() {
        launch("dark",2f)
        compose.waitUntil(10000) { vm.state.value.screen==Screen.Login && !vm.state.value.busy }
        compose.onNodeWithContentDescription("设置").performClick()
        capture("07-settings-dark-large-jvm")
        compose.onNodeWithText("开发者选项").performScrollTo().performClick()
        compose.waitUntil(10000) { vm.state.value.screen==Screen.Developer }
        capture("09-developer-dark-large-jvm")
    }
    @Test fun nativeLoginFieldsEvidence() {
        launch()
        compose.runOnIdle { vm.connect("https://fixture.example.invalid") }
        compose.waitUntil(10000) { vm.state.value.screen==Screen.Login && !vm.state.value.busy }
        // As the web account page: the account and the password, nothing about the service.
        compose.onNodeWithText("邮箱或账号",substring=false).assertIsDisplayed()
        compose.onNodeWithText("密码",substring=false).assertIsDisplayed()
        compose.onNode(hasText("登录") and hasClickAction()).assertIsNotEnabled()
        compose.onNodeWithText("服务地址").assertDoesNotExist()
        capture("08-native-login-jvm")
    }

}
