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
    /** The page drawn anew for another window width goes back where it stood (in memory, for the same read). */
    @Test @Config(qualifiers="w1200dp-h800dp-xhdpi") fun resizingMovesReaderWithoutDiscardingDraftOrPlace() {
        val width=mutableStateOf(1200.dp);launch(windowWidth=width);fixtureList()
        compose.onNodeWithText("原生阅读示例").performClick();compose.waitUntil(10000) { !vm.state.value.busy && vm.composer.state.value.ready }
        compose.onNodeWithTag("composer").performTextInput("窗口切换草稿")
        compose.onNodeWithTag("messages").performScrollToIndex(1)
        compose.runOnIdle { width.value=700.dp }
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
    /**
     * 11-16: a frame every 200 ms must not pull a reader who scrolled up; the pill goes back to the newest, and a send
     * after reading above follows the bottom again (iOS ConversationView has the same rules).
     */
    @Test fun readingAboveHoldsItsPlaceWhileFramesArrive() {
        var seq = 0L
        var made = 0
        var streams = 0
        // The frames are handed in from the test, as the live stream would, so nothing waits on a clock.
        val frames = kotlinx.coroutines.flow.MutableSharedFlow<LiveFrame>(extraBufferCapacity = 16)
        val streaming = object : ReadApi by FixtureApi() {
            override fun forSource(app: String): ReadApi = this
            override fun events(device: String, chat: String): kotlinx.coroutines.flow.Flow<LiveFrame> {
                streams += 1
                return frames
            }
        }
        launch(api = { streaming });fixtureList()
        compose.onNodeWithTag("chat-search").performTextInput("performance")
        compose.onNodeWithTag("chat-search").performImeAction()
        compose.waitUntil(10000) { !vm.state.value.busy && vm.state.value.chats.singleOrNull()?.id=="performance" }
        openChat("长会话性能示例","performance")
        compose.waitUntil(10000) { streams > 0 }
        compose.waitUntil(10000) { vm.state.value.messages.size >= 200 && !vm.state.value.busy }
        fun frame() {
            made += 1;seq += 1
            compose.runOnIdle { frames.tryEmit(LiveFrame(seq, false, listOf(Message("stream-$made", "assistant", "新输出第 $made 条")), null)) }
        }
        val before = vm.state.value.messages.size
        // Reading above: the frames that keep arriving leave the page where it is.
        compose.onNodeWithTag("messages").performTouchInput { swipeDown() }
        compose.waitForIdle()
        org.junit.Assert.assertFalse(atBottom())
        val held = scrollValue()
        repeat(3) { frame() }
        compose.waitUntil(10000) { vm.state.value.messages.size > before }
        compose.waitForIdle()
        org.junit.Assert.assertFalse(atBottom())
        org.junit.Assert.assertEquals(held, scrollValue(), 2f)
        // The pill says there is more below; it goes back to the newest.
        compose.onNodeWithContentDescription("有新消息，回到底部").assertExists().performClick()
        compose.waitUntil(10000) { atBottom() }
        // A send after reading above follows the bottom again.
        compose.onNodeWithTag("messages").performTouchInput { swipeDown() }
        compose.waitForIdle()
        org.junit.Assert.assertFalse(atBottom())
        compose.onNodeWithTag("composer").performTextInput("边看边发")
        compose.onNodeWithContentDescription("发送").performClick()
        compose.waitUntil(10000) { atBottom() }
    }
    private fun scrollValue():Float {
        val range=compose.onNodeWithTag("messages").fetchSemanticsNode().config[androidx.compose.ui.semantics.SemanticsProperties.VerticalScrollAxisRange]
        return range.value()
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
    /** 设置 → 关于遥应 → 隐私政策 opens the policy in the phone's browser, as 登录's links open the web account page. */
    @Test fun privacyPolicyOpensInTheBrowser() {
        launch();compose.waitUntil(10000) { vm.state.value.screen==Screen.Login && !vm.state.value.busy }
        compose.onNodeWithContentDescription("设置").performClick()
        compose.onNodeWithText("隐私政策").performScrollTo().performClick()
        val opened=org.robolectric.Shadows.shadowOf(androidx.test.core.app.ApplicationProvider.getApplicationContext<android.app.Application>()).nextStartedActivity
        org.junit.Assert.assertEquals(android.content.Intent.ACTION_VIEW,opened.action)
        org.junit.Assert.assertEquals("https://pocketagentdesk.com/privacy",opened.dataString)
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
    /** 第二批 A3：通用布局的助手在时间线里画批准卡和提问卡，点按钮后按统一地址答复，请求体正确。 */
    @Test fun genericCardsAnswerThroughTheUnifiedRoute() {
        launch();fixtureList();openChat("测试对话 B","test-waiting")
        compose.waitUntil(10000) { vm.composer.state.value.control.raw.contains("approval-7") }
        compose.onNodeWithTag("messages").performScrollToKey("interactions")
        // 横条用卡片的 title（A3），卡片里也有同一句。
        compose.onNodeWithContentDescription("测试助手想运行命令，去处理").assertExists()
        compose.onAllNodesWithText("测试助手想运行命令").onFirst().assertExists()
        compose.onNodeWithText("npm test",substring=true).assertExists()
        compose.onNodeWithText("允许一次").performScrollTo().performClick()
        compose.waitUntil(10000) { vm.fixtureWorld!!.testingAnswers.size==1 }
        val approval=vm.fixtureWorld!!.testingAnswers.first()
        org.junit.Assert.assertEquals("approval-7",approval.string("question_id"))
        org.junit.Assert.assertEquals("[\"允许一次\"]",approval.getJSONObject("answers").getJSONArray("decision").toString())
        org.junit.Assert.assertFalse(approval.has("answer_revision"))   // 空的原样不带
        compose.waitUntil(10000) { !vm.composer.state.value.control.raw.contains("approval-7") }
        // 提问卡：两题，第一题单选带手写、第二题多选；选完点「提交」。
        compose.onNodeWithTag("messages").performScrollToKey("interactions")
        compose.onNodeWithText("选方案").assertExists()
        compose.onNodeWithContentDescription("选择方案 A").performScrollTo().performClick()
        compose.onNodeWithContentDescription("选择a.py").performScrollTo().performClick()
        compose.onNodeWithText("提交").performScrollTo().performClick()
        compose.waitUntil(10000) { vm.fixtureWorld!!.testingAnswers.size==2 }
        val question=vm.fixtureWorld!!.testingAnswers[1]
        org.junit.Assert.assertEquals("question-8",question.string("question_id"))
        org.junit.Assert.assertEquals("rev-1",question.string("answer_revision"))
        org.junit.Assert.assertEquals("[\"方案 A\"]",question.getJSONObject("answers").getJSONArray("plan").toString())
        org.junit.Assert.assertEquals("[\"a.py\"]",question.getJSONObject("answers").getJSONArray("files").toString())
    }
    /** 第二批 A3：此刻不能批准时按钮灰掉，原因写在卡片里。 */
    @Test fun aGenericApprovalThatCannotHappenNowIsGreyedWithTheReason() {
        launch();fixtureList()
        vm.fixtureWorld!!.testingApproveBlocked="这台电脑的测试助手暂时不能批准"
        openChat("测试对话 B","test-waiting")
        compose.waitUntil(10000) { vm.composer.state.value.control.raw.contains("approval-7") }
        compose.onNodeWithTag("messages").performScrollToKey("interactions")
        compose.onNodeWithText("允许一次").performScrollTo().assertIsNotEnabled()
        compose.onNodeWithText("这台电脑的测试助手暂时不能批准").assertExists()
    }
    /** 第二批 A2：控制态里有 capabilities_now 时，Codex 输入区的模式按钮只看此刻 settings。 */
    @Test fun codexModeChipFollowsCapabilitiesNow() {
        launch();fixtureList()
        vm.fixtureWorld!!.codexCapsNow=org.json.JSONObject("""{"settings":["model","effort"],"send_modes":["send","steer","queue"]}""")
        openChat("原生阅读示例","demo")
        compose.waitUntil(10000) { vm.composer.state.value.control.available }
        compose.onNodeWithContentDescription("模式：普通执行").assertDoesNotExist()
        compose.onNodeWithContentDescription("模型：测试模型 · 中").assertExists()
        // 没有 capabilities_now 的老电脑：模式按钮照旧（Codex 布局）。
        compose.onNodeWithContentDescription("返回").performClick()
        compose.waitUntil(10000) { vm.state.value.screen==Screen.Chats && !vm.state.value.busy }
        vm.fixtureWorld!!.codexCapsNow=null
        openChat("原生阅读示例","demo")
        compose.waitUntil(10000) { vm.composer.state.value.control.available }
        compose.onNodeWithContentDescription("模式：普通执行").assertExists()
    }

}
