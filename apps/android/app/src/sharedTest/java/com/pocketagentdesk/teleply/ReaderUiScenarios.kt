package com.pocketagentdesk.teleply

import androidx.compose.runtime.*
import androidx.compose.ui.test.*
import androidx.compose.ui.unit.dp
import androidx.compose.foundation.layout.requiredWidth
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import org.junit.Rule
import org.junit.Test

class UiMemoryStore:ReaderStore {
    override suspend fun preferences()=Preferences()
    override suspend fun setOrigin(origin:String)=Unit
    override suspend fun appearance(theme:String,dynamic:Boolean)=Unit
    override suspend fun selection(scope:String,device:String,chat:String,title:String)=Unit
}

/** UI scenarios on the local fixture, shared by the Robolectric (JVM) and device runs. No real service is contacted. */
abstract class ReaderUiScenarios {
    @Test fun questionSelectionIsLocalUntilExplicitSubmit() {
        launch();fixtureList();compose.onNodeWithText("原生阅读示例").performClick()
        compose.waitUntil(10000) { vm.workspace.state.value.ready && !vm.state.value.busy && vm.composer.state.value.control.questions }
        // Questions are answered in the timeline (spec 4.3), not in a separate panel.
        compose.onNodeWithTag("messages").performScrollToKey("interactions")
        compose.onNodeWithText("提交回答").performScrollTo().assertIsNotEnabled()
        compose.onNodeWithContentDescription("选择方案A").performScrollTo().performClick()
        compose.onNodeWithContentDescription("选择方案A").assertIsSelected().assertHeightIsAtLeast(48.dp)
        compose.runOnIdle { org.junit.Assert.assertNull(org.json.JSONObject(vm.workspace.state.value.saved).optJSONObject("pending_action")) }
        compose.onNodeWithText("提交回答").performScrollTo().performClick()
        compose.waitUntil(10000) { org.json.JSONObject(vm.workspace.state.value.saved).optJSONObject("pending_action")?.string("status")=="done" }
    }
    @Test fun newConversationOpensAtOnceAndBecomesItsConversation() {
        launch();fixtureList();compose.onNodeWithContentDescription("新建对话").performClick()
        // Usable at once (0.8, web): nothing waits on the computer's lists, and no progress bar shows.
        compose.waitUntil(10000) { vm.workspace.state.value.pane=="new" && vm.workspace.state.value.ready }
        compose.onNodeWithContentDescription("正在读取").assertDoesNotExist()
        // Like the web, a project not chosen yet starts as the first one the computer lists (spec 0.4 §4.4).
        compose.waitUntil(10000) { org.json.JSONObject(vm.workspace.state.value.saved).string("folder")=="D:/fixture" }
        compose.onNodeWithTag("new-message").performScrollTo().performTextInput("固定新建测试")
        compose.onNodeWithContentDescription("创建并发送").performScrollTo().performClick()
        // The sheet closes at once; the first message's page becomes the conversation once the computer made it.
        compose.waitUntil(10000) { vm.state.value.chat?.id=="fixture-new-1" && !vm.state.value.busy }
        compose.runOnIdle { org.junit.Assert.assertTrue(vm.state.value.messages.any { it.role=="user" && it.text=="固定新建测试" }) }
        compose.runOnIdle {
            org.junit.Assert.assertNull(vm.workspace.state.value.pane)
            org.junit.Assert.assertTrue(vm.jobs.jobs.value.isEmpty())
        }
        // Back in the list, the new conversation is there.
        compose.onNodeWithContentDescription("返回").performClick()
        compose.waitUntil(10000) { vm.state.value.screen==Screen.Chats && !vm.state.value.busy }
        compose.waitUntil(10000) { vm.state.value.chats.any { it.id=="fixture-new-1" } }
    }
    @Test fun firstMessageThatDidNotGoOutCanBeSentAgainOrRestored() {
        launch();fixtureList();compose.onNodeWithContentDescription("新建对话").performClick()
        compose.waitUntil(10000) { vm.workspace.state.value.pane=="new" && vm.workspace.state.value.ready }
        compose.waitUntil(10000) { org.json.JSONObject(vm.workspace.state.value.saved).string("folder").isNotBlank() }
        compose.onNodeWithTag("new-message").performScrollTo().performTextInput("测试失败")
        compose.onNodeWithContentDescription("创建并发送").performScrollTo().performClick()
        compose.waitUntil(10000) { vm.state.value.chat?.id?.startsWith("new:")==true && vm.jobs.jobs.value.singleOrNull()?.state=="failed" }
        // Its page says so, and the line opens what can be done.
        compose.onNodeWithText("没发出去 · 点击处理").performClick()
        compose.onNodeWithText("本地示例：电脑上的应用没有响应，首条消息没有发出").assertExists()
        compose.onNodeWithText("恢复草稿").assertExists()
        compose.onNodeWithText("继续发送").performClick()
        // Sent again as the same request: its page becomes the conversation.
        compose.waitUntil(10000) { vm.state.value.chat?.id?.startsWith("fixture-new-")==true && !vm.state.value.busy }
        compose.runOnIdle { org.junit.Assert.assertTrue(vm.jobs.jobs.value.isEmpty()) }
        // Another that fails goes back into the sheet with 恢复草稿.
        compose.onNodeWithContentDescription("返回").performClick()
        compose.waitUntil(10000) { vm.state.value.screen==Screen.Chats && !vm.state.value.busy }
        compose.onNodeWithContentDescription("新建对话").performClick()
        compose.waitUntil(10000) { vm.workspace.state.value.pane=="new" && vm.workspace.state.value.ready }
        compose.onNodeWithTag("new-message").performScrollTo().performTextInput("测试失败")
        compose.onNodeWithContentDescription("创建并发送").performScrollTo().performClick()
        compose.waitUntil(10000) { vm.jobs.jobs.value.singleOrNull()?.state=="failed" }
        compose.onNodeWithText("没发出去 · 点击处理").performClick()
        compose.onNodeWithText("恢复草稿").performClick()
        compose.waitUntil(10000) { vm.workspace.state.value.pane=="new" && org.json.JSONObject(vm.workspace.state.value.saved).string("first_message")=="测试失败" }
        compose.runOnIdle { org.junit.Assert.assertTrue(vm.jobs.jobs.value.isEmpty()) }
    }
    /** 10-27: Claude's question shows the option chosen on the computer, and no second card of its own buttons. */
    @Test fun claudeQuestionShowsTheChosenOptionAndNoPlanOptions() {
        launch();fixtureList();openChat("Claude 选项示例","claude-demo")
        compose.waitUntil(10000) { org.json.JSONObject(vm.composer.state.value.control.raw).has("actions") }
        compose.onNodeWithTag("messages").performScrollToKey("interactions")
        compose.onNodeWithContentDescription("选择简洁要点").performScrollTo().assertIsSelected()
        compose.onNodeWithContentDescription("选择完整段落").assertIsNotSelected()
        // The demo sends the buttons again as actions, as computers before dev.23 did: only the question shows.
        compose.onNodeWithText("计划与执行选项").assertDoesNotExist()
        compose.onNodeWithText("简洁要点 每条改动一行").assertDoesNotExist()
    }
    /** Windows dev.24's question card (10-27, as on the iPhone 0.5.2): a tick marked once, 提交 only once one is ticked, Other's hint. */
    @Test fun claudeQuestionReadsAsWindowsDev24LaysItOut() {
        launch();fixtureList();openChat("Claude 选项示例","claude-demo")
        fun prompt()=org.json.JSONObject(vm.composer.state.value.control.raw).optJSONObject("prompt")
        compose.waitUntil(10000) { prompt()!=null }
        compose.onNodeWithTag("messages").performScrollToKey("interactions")
        compose.onNodeWithText("要自己写答案的话，请在电脑上点「Other」填写。").performScrollTo().assertExists()
        // 跳过 goes on to the second question, which takes several; its first is ticked, "✓ " written before it.
        compose.onNodeWithText("跳过").performScrollTo().performClick()
        compose.waitUntil(10000) { prompt()?.string("progress")=="2 / 2" && !vm.workspace.state.value.busy }
        compose.runOnIdle { org.junit.Assert.assertEquals("✓ 升级步骤",prompt()!!.getJSONArray("choices").getJSONObject(0).string("label")) }
        compose.onNodeWithTag("messages").performScrollToKey("interactions")
        compose.onNodeWithContentDescription("选择升级步骤").performScrollTo().assertIsSelected()
        compose.onNodeWithText("✓ 升级步骤").assertDoesNotExist()
        compose.onNodeWithText("提交").assertIsEnabled()
        compose.onNodeWithText("上一题").assertIsEnabled()
        // Unticked, there is nothing to hand in: the computer gives 提交 no token.
        compose.onNodeWithContentDescription("选择升级步骤").performClick()
        compose.waitUntil(10000) { prompt()?.getJSONArray("choices")?.getJSONObject(0)?.optBoolean("pressed")==false && !vm.workspace.state.value.busy }
        compose.onNodeWithContentDescription("选择升级步骤").assertIsNotSelected()
        compose.onNodeWithText("提交").assertIsNotEnabled()
        compose.onNodeWithText("要自己写答案的话，请在电脑上点「Other」填写。").assertExists()
    }
    /** 10-27 (as on the iPhone 0.5.2): Codex's line naming a conversation it made is a button that opens it; one still being made says so. */
    @Test fun aConversationCodexMadeOpensFromItsButton() {
        launch();fixtureList();openChat("原生阅读示例","demo")
        compose.onNodeWithTag("messages").performScrollToKey("msg:m2b")
        compose.onNodeWithText("发布清单另开了一个对话来整理",substring=true).assertExists()
        compose.onNodeWithText("新对话正在准备中").assertExists()
        compose.onAllNodesWithText("::created-thread{threadId=\"${FixtureWorld.MADE_THREAD}\"}",substring=true).assertCountEquals(0)
        compose.onAllNodesWithText("clientThreadId",substring=true).assertCountEquals(0)
        compose.onNodeWithText("打开新建对话").performScrollTo().performClick()
        compose.waitUntil(10000) { vm.state.value.chat?.id==FixtureWorld.MADE_THREAD && !vm.state.value.busy }
        compose.onNodeWithText("整理发布清单").assertExists()
        compose.onNodeWithText("好的，这个对话只整理发布清单。").assertExists()
        compose.runOnIdle { org.junit.Assert.assertEquals("codex",vm.state.value.app);org.junit.Assert.assertNull(vm.state.value.error) }
    }
    /** 10-27 (as on the iPhone 0.5.3): pictures sent with a message show in it without the [图片] mark, two to a row, and open whole. */
    @Test fun picturesSentWithAMessageShowInItAndOpenWhole() {
        launch();fixtureList();openChat("Claude 选项示例","claude-demo")
        // Claude's send goes by its words and time.
        compose.onNodeWithTag("messages").performScrollToKey("msg:c1")
        compose.onNodeWithText("帮我把这次的发布说明整理一下。").assertExists()
        compose.onAllNodesWithText("[图片]",substring=true).assertCountEquals(0)
        compose.onNodeWithContentDescription("查看 发布说明截图.png").assertWidthIsEqualTo(110.dp).assertHeightIsEqualTo(100.dp)
        compose.waitUntil(10000) { vm.fixtureWorld!!.pictureReads==1 }
        compose.onNodeWithContentDescription("查看 发布说明截图.png").performClick()
        compose.waitUntil(10000) { compose.onAllNodesWithContentDescription("图片").fetchSemanticsNodes().isNotEmpty() }
        compose.runOnIdle { org.junit.Assert.assertEquals(2,vm.fixtureWorld!!.pictureReads) }
        compose.onNodeWithContentDescription("关闭").performClick()
        compose.waitUntil(10000) { compose.onAllNodesWithContentDescription("图片").fetchSemanticsNodes().isEmpty() }
        // The menu still has the message whole, its mark too.
        compose.onNodeWithText("帮我把这次的发布说明整理一下。").performTouchInput { longClick() }
        compose.onNodeWithText("选择文字").performClick()
        compose.onNodeWithText("[图片] 帮我把这次的发布说明整理一下。").assertExists()
        compose.onNodeWithText("复制全部").performClick()
        // Codex's send goes by the request id on its message: three pictures, two to a row.
        compose.onNodeWithContentDescription("返回").performClick()
        compose.waitUntil(10000) { vm.state.value.screen==Screen.Chats && !vm.state.value.busy }
        openChat("Codex 计划示例","plan-demo")
        compose.onNodeWithTag("messages").performScrollToKey("msg:p1")
        compose.onNodeWithText("先给我一个计划，确认后再改。").assertExists()
        val tops=listOf("界面草图.png","现有页面.png","参考.png").map { compose.onNodeWithContentDescription("查看 $it").fetchSemanticsNode().boundsInRoot.top }
        org.junit.Assert.assertEquals(tops[0],tops[1],0.5f);org.junit.Assert.assertTrue(tops[2]>tops[0])
    }
    @Test fun claudeModelMenuShowsTheKeptListAndReadsTheDesktopOnlyOnRefresh() {
        launch();fixtureList();openChat("Claude 选项示例","claude-demo")
        val world=vm.fixtureWorld!!
        compose.onNodeWithContentDescription("模型：Opus 4.7 · 高").performClick()
        compose.waitUntil(10000) { !vm.workspace.state.value.choicesBusy }
        // Never read before: the computer opens Claude's menus this once.
        compose.runOnIdle { org.junit.Assert.assertEquals(1,world.desktopMenuReads) }
        compose.onNodeWithText("Sonnet 4.6").performClick()
        compose.waitUntil(10000) { !vm.workspace.state.value.busy }
        // The state sent back with the pick shows at once; the list came back with it.
        compose.onNodeWithContentDescription("模型：Sonnet 4.6 · 高").assertExists()
        compose.onNodeWithContentDescription("模型：Sonnet 4.6 · 高").performClick()
        compose.onNodeWithText("Opus 4.7").assertExists()
        compose.waitUntil(10000) { !vm.workspace.state.value.choicesBusy }
        compose.runOnIdle { org.junit.Assert.assertEquals(1,world.desktopMenuReads) }
        // Only 刷新 has the computer read Claude's menus again.
        compose.onNodeWithText("刷新电脑上的列表").performClick()
        compose.waitUntil(10000) { !vm.workspace.state.value.choicesBusy }
        compose.runOnIdle { org.junit.Assert.assertEquals(2,world.desktopMenuReads) }
    }
    /** The desktop's six named levels (10-27) and a slider with a step of 0 open the model menu; it lists what it can. */
    @Test fun claudeModelMenuTakesNamedLevelsAndSlidersWithAndWithoutAStep() {
        launch();fixtureList();openChat("Claude 选项示例","claude-demo")
        val world=vm.fixtureWorld!!
        world.claudeEfforts=org.json.JSONArray("""[{"name":"Low"},{"name":"Medium Recommended"},{"name":"High"},{"name":"Extra"},{"name":"Max 3.5× or more usage"},{"name":"Ultracode"}]""")
        compose.onNodeWithContentDescription("模型：Opus 4.7 · 高").performClick()
        compose.waitUntil(10000) { !vm.workspace.state.value.choicesBusy }
        compose.onNodeWithText("推理强度").assertExists()
        compose.onNodeWithText("Ultracode").assertExists().assertIsNotSelected()
        // In the chip's words, each whole on one line (10-27: they were cut to "Med", "Hig").
        listOf("低","中","高","极高","最高","Ultracode").forEach(::assertWhole)
        // The iPhone quit here (0.5.0): one slider with a step of 0. No steps, the models stay.
        world.claudeEfforts=org.json.JSONArray("""[{"name":"Effort","type":"SliderControl","selected":true,"range":{"min":0,"max":5,"step":0,"value":0,"label":"Low"}}]""")
        compose.onNodeWithText("刷新电脑上的列表").performClick()
        compose.waitUntil(10000) { !vm.workspace.state.value.choicesBusy && org.json.JSONObject(vm.workspace.state.value.choices).optJSONObject("source_catalog")?.toString()?.contains("SliderControl")==true }
        compose.onNodeWithText("Ultracode").assertDoesNotExist()
        compose.onNodeWithText("推理强度").assertDoesNotExist()
        compose.onNodeWithText("Opus 4.7").assertExists()
        // A slider with a step: its steps, the current one chosen.
        world.claudeEfforts=org.json.JSONArray("""[{"name":"Effort","type":"SliderControl","selected":true,"range":{"min":0,"max":3,"step":1,"value":1,"label":"Medium","labels":{"0":"Low"}}}]""")
        compose.onNodeWithText("刷新电脑上的列表").performClick()
        compose.waitUntil(10000) { !vm.workspace.state.value.choicesBusy && org.json.JSONObject(vm.workspace.state.value.choices).optJSONObject("source_catalog")?.toString()?.contains("\"step\":1")==true }
        compose.onNodeWithText("中").assertIsSelected()
        compose.onNodeWithText("第 4 档").assertExists()
    }
    /** With large text the six levels no longer fit side by side: the row scrolls, and each name stays whole. */
    @Test fun claudeEffortNamesStayWholeWithLargeText() {
        launch(fontScale=1.6f);fixtureList();openChat("Claude 选项示例","claude-demo")
        vm.fixtureWorld!!.claudeEfforts=org.json.JSONArray("""[{"name":"Low"},{"name":"Medium Recommended"},{"name":"High"},{"name":"Extra"},{"name":"Max 3.5× or more usage"},{"name":"Ultracode"}]""")
        compose.onNodeWithContentDescription("模型：Opus 4.7 · 高").performClick()
        compose.waitUntil(10000) { !vm.workspace.state.value.choicesBusy }
        listOf("低","中","高","极高","最高","Ultracode").forEach(::assertWhole)
    }
    /** A label laid out whole on one line: as wide as its words, not cut by its segment. */
    protected fun assertWhole(label:String) {
        val layout=mutableListOf<androidx.compose.ui.text.TextLayoutResult>()
        compose.onNode(hasText(label),useUnmergedTree=true).fetchSemanticsNode().config[androidx.compose.ui.semantics.SemanticsActions.GetTextLayoutResult].action?.invoke(layout)
        layout.single().let { text ->
            org.junit.Assert.assertEquals(label,1,text.lineCount)
            org.junit.Assert.assertTrue(label,text.size.width>=text.multiParagraph.maxIntrinsicWidth-1f)
        }
    }
    /** 10-27: a Codex conversation not open on the computer says why, and its model chip opens it there. */
    @Test fun codexNotOpenOnTheComputerSaysWhyAndOpensFromTheChip() {
        launch();fixtureList();openChat("电脑上没打开的 Codex 对话",FixtureWorld.AWAY_CODEX)
        compose.waitUntil(10000) { org.json.JSONObject(vm.composer.state.value.control.raw).has("available") }
        compose.onNodeWithText("电脑端尚未打开这个对话，请从右上角菜单选择「电脑上打开」后重试").assertExists()
        compose.onNodeWithTag("composer").performTextInput("先别发")
        compose.onNodeWithContentDescription("发送").assertIsNotEnabled()
        compose.onNodeWithContentDescription("模式：普通执行").assertDoesNotExist()
        compose.onNodeWithContentDescription("电脑上打开这个对话").performClick()
        // Read again at once: the chips and the send button follow.
        compose.waitUntil(10000) { vm.composer.state.value.control.available }
        compose.onNodeWithContentDescription("模型：测试模型 · 中").assertExists()
        compose.onNodeWithContentDescription("模式：普通执行").assertExists()
        compose.onNodeWithText("电脑端尚未打开这个对话",substring=true).assertDoesNotExist()
        compose.onNodeWithContentDescription("发送").assertIsEnabled()
    }
    /** 10-27 (as on the iPhone): Codex's own notes are not shown; a file an answer links to opens its page, one not listed says why. */
    @Test fun answerFileLinksOpenTheirPageAndCodexNotesStayHidden() {
        launch();fixtureList();openChat("电脑上没打开的 Codex 对话",FixtureWorld.AWAY_CODEX)
        compose.onAllNodesWithText("MEMORY.md",substring=true).assertCountEquals(0)
        compose.onAllNodesWithText("codex-file-citation",substring=true).assertCountEquals(0)
        compose.onAllNodesWithText("链接未开放",substring=true).assertCountEquals(0)
        fun to(path:String):(androidx.compose.ui.text.AnnotatedString.Range<androidx.compose.ui.text.LinkAnnotation>)->Boolean = { (it.item as? androidx.compose.ui.text.LinkAnnotation.Url)?.url?.let(::fileLinkPath)==path }
        val answer=compose.onNodeWithText("整理好了",substring=true)
        answer.performFirstLinkClick(to("D:\\fixture\\会议录音.m4a"))
        compose.waitUntil(10000) { vm.workspace.state.value.error?.contains("不在电脑列出的对话文件里")==true }
        compose.onNodeWithText("这个文件不在电脑列出的对话文件里",substring=true).assertExists()
        answer.performFirstLinkClick(to("D:\\fixture\\说明.md"))
        compose.waitUntil(10000) { vm.workspace.state.value.pane=="file" && !vm.workspace.state.value.busy }
        compose.runOnIdle { org.junit.Assert.assertEquals("fixture-md",org.json.JSONObject(vm.workspace.state.value.data).string("id")) }
        compose.runOnIdle { vm.workspace.close() }
        // Codex's file citation is a link to its file.
        compose.onNodeWithText("logo.png").performFirstLinkClick(to("D:\\fixture\\images\\logo.png"))
        compose.waitUntil(10000) { vm.workspace.state.value.pane=="file" && !vm.workspace.state.value.busy }
        compose.runOnIdle { org.junit.Assert.assertEquals("fixture-png",org.json.JSONObject(vm.workspace.state.value.data).string("id")) }
    }
    /** 10-27 (web sendConv): Claude not shown on the computer reads its recorded names and takes the message all the same. */
    @Test fun claudeNotShownOnTheComputerNamesItsChipsAndSendsAllTheSame() {
        launch();fixtureList();openChat("电脑上没在显示的 Claude 对话",FixtureWorld.AWAY_CLAUDE)
        compose.waitUntil(10000) { org.json.JSONObject(vm.composer.state.value.control.raw).has("available") }
        compose.runOnIdle { org.junit.Assert.assertFalse(vm.composer.state.value.control.available) }
        compose.onNodeWithContentDescription("模型：Opus 5.5 · 高").assertExists()
        compose.onNodeWithContentDescription("模式：Auto").assertExists()
        compose.onNodeWithText("电脑上显示的不是此 Claude 会话",substring=true).assertDoesNotExist()
        compose.onNodeWithTag("composer").performTextInput("照样发出去")
        compose.onNodeWithContentDescription("发送").performClick()
        compose.waitUntil(15000) { vm.composer.state.value.submissions.firstOrNull()?.label=="已送达" }
        // The computer opened it to send it there.
        compose.waitUntil(10000) { vm.composer.state.value.control.available }
        compose.onNodeWithContentDescription("模型：Opus 5.5 · 高").assertExists()
    }
    @Test fun newConversationChoicesAreMenusOnOneSheet() {
        launch();fixtureList();compose.onNodeWithContentDescription("新建对话").performClick()
        compose.waitUntil(10000) { vm.workspace.state.value.pane=="new" && !vm.workspace.state.value.busy && vm.workspace.state.value.ready }
        compose.waitUntil(10000) { org.json.JSONObject(vm.workspace.state.value.saved).string("folder").isNotBlank() }
        // 项目 opens a menu from its row; 无项目 is the first choice.
        compose.onNode(hasContentDescription("项目：",substring=true)).performClick()
        compose.onNodeWithText("固定测试项目").assertExists()
        compose.onNodeWithText("无项目").performClick()
        compose.waitUntil(10000) { org.json.JSONObject(vm.workspace.state.value.saved).let { it.string("folder")=="" && it.string("projectless")=="1" } }
        // 模型与推理强度: a model, then one of its effort steps, each one tap.
        compose.onNode(hasContentDescription("模型与推理强度：",substring=true)).performClick()
        compose.onNodeWithText("测试模型").performClick()
        compose.waitUntil(10000) { org.json.JSONObject(vm.workspace.state.value.saved).string("new_model")=="fixture-model" }
        compose.onNode(hasContentDescription("模型与推理强度：测试模型",substring=true)).performClick()
        compose.onNodeWithText("中").performClick()
        compose.waitUntil(10000) { org.json.JSONObject(vm.workspace.state.value.saved).string("new_effort")=="medium" }
        compose.onNode(hasContentDescription("模型与推理强度：测试模型 · 中",substring=true)).assertExists()
    }
    @Test fun modelChipMenuBindsTheNextMessage() {
        launch();fixtureList();compose.onNodeWithText("原生阅读示例").performClick()
        compose.waitUntil(10000) { vm.workspace.state.value.ready && !vm.state.value.busy && vm.composer.state.value.control.available }
        compose.onNodeWithContentDescription("模型：测试模型 · 中").performClick()
        compose.onNodeWithText("推理强度").assertExists()
        compose.onNodeWithText("低").performClick()
        compose.waitUntil(10000) { org.json.JSONObject(vm.workspace.state.value.saved).optJSONObject("settings")?.string("effort")=="low" }
        compose.onNodeWithContentDescription("模型：测试模型 · 低").assertExists()
        compose.onNodeWithText("设置已绑定下一条消息，尚未发送").assertExists()
        compose.onNodeWithContentDescription("模式：普通执行").performClick()
        compose.onNodeWithText("计划").performClick()
        compose.waitUntil(10000) { org.json.JSONObject(vm.workspace.state.value.saved).optJSONObject("settings")?.string("mode")=="plan" }
        compose.onNodeWithContentDescription("模式：计划").assertExists()
    }
    @Test fun runtimePanelOpensFromTheRingAndTheMenu() {
        launch();fixtureList();compose.onNodeWithText("原生阅读示例").performClick()
        compose.waitUntil(10000) { vm.workspace.state.value.ready && !vm.state.value.busy }
        compose.onNodeWithContentDescription("上下文已用约 46%，查看会话状态").performClick()
        compose.onNodeWithContentDescription("上下文已用约 46%，已用11.8万，窗口25.8万").assertExists()
        compose.onNodeWithText("测试模型").assertExists()
        compose.onNodeWithText("来自会话记录",substring=true).assertExists()
        compose.onNodeWithText("暂无数据").assertDoesNotExist()
        // A tap outside closes it, as for menus.
        compose.onRoot().performTouchInput { click(androidx.compose.ui.geometry.Offset(24f,height-24f)) }
        compose.onNodeWithText("来自会话记录",substring=true).assertDoesNotExist()
        compose.onNodeWithContentDescription("对话菜单").performClick()
        compose.onNodeWithText("会话状态").performClick()
        compose.onNodeWithText("来自会话记录",substring=true).assertExists()
    }
    @Test fun htmlShowsAsPageWithItsSourceBeside() {
        launch();fixtureList();compose.onNodeWithText("原生阅读示例").performClick()
        compose.waitUntil(10000) { vm.workspace.state.value.ready && !vm.state.value.busy }
        compose.onNodeWithContentDescription("对话菜单").performClick()
        compose.onNodeWithText("对话文件").performClick();compose.waitUntil(10000) { !vm.workspace.state.value.busy }
        compose.onNodeWithText("安全预览.html").performClick();compose.waitUntil(10000) { vm.workspace.state.value.pane=="file" && !vm.workspace.state.value.busy }
        // The page fills the screen; its source, as text, and saving are under ⋯ (10-28, as WeChat).
        compose.onNodeWithContentDescription("网页预览：安全预览.html").assertExists()
        compose.onNodeWithText("<script>fetch(",substring=true).assertDoesNotExist()
        compose.onNodeWithContentDescription("文件菜单").performClick()
        compose.onNodeWithText("查看源码").performClick()
        compose.onNodeWithText("<script>fetch(",substring=true).assertExists()
        compose.onNodeWithContentDescription("文件菜单").performClick()
        compose.onNodeWithText("查看页面").assertExists()
        compose.onNodeWithText("保存到手机").assertHasClickAction()
    }
    /**
     * 10-28: Word and Excel are drawn on the phone from the file itself, with no PDF asked for; PowerPoint shows as the PDF
     * the computer's Office makes (10-27). The file fills the page; ⋯ takes the file itself throughout.
     */
    @Test fun wordAndExcelShowOnThePhoneAndPowerPointAsThePdf() {
        launch();fixtureList();compose.onNodeWithText("原生阅读示例").performClick()
        compose.waitUntil(10000) { vm.workspace.state.value.ready && !vm.state.value.busy }
        val world=vm.fixtureWorld!!;val office=kotlinx.coroutines.CompletableDeferred<Unit>();world.pdfGate=office
        compose.onNodeWithContentDescription("对话菜单").performClick()
        compose.onNodeWithText("对话文件").performClick();compose.waitUntil(10000) { !vm.workspace.state.value.busy }
        // Word and Excel: the file itself, at once, drawn here.
        for(name in listOf("发布说明.docx","预算表.xlsx")) {
            compose.runOnIdle { vm.workspace.panel("files") };compose.waitUntil(10000) { !vm.workspace.state.value.busy }
            compose.onNodeWithText(name).performScrollTo().performClick()
            compose.waitUntil(10000) { !vm.workspace.state.value.busy && vm.workspace.state.value.preview!=null }
            compose.runOnIdle { org.junit.Assert.assertEquals("phone",org.json.JSONObject(vm.workspace.state.value.data).string("preview")) }
            compose.onNodeWithText("正在用电脑上的 Office 转成 PDF…").assertDoesNotExist()
            compose.onNodeWithText("用其他应用打开").assertDoesNotExist()
            menuOffersTheFile()
        }
        compose.runOnIdle { org.junit.Assert.assertEquals(0,world.pdfReads) }
        // PowerPoint: while Office works on the computer, a short note, and the buttons already work on the file itself.
        compose.runOnIdle { vm.workspace.panel("files") };compose.waitUntil(10000) { !vm.workspace.state.value.busy }
        compose.onNodeWithText("季度汇报.pptx").performScrollTo().performClick()
        compose.waitUntil(10000) { vm.workspace.state.value.converting }
        compose.onNodeWithText("正在用电脑上的 Office 转成 PDF…").assertExists()
        menuOffersTheFile()
        compose.runOnIdle { office.complete(Unit) }
        compose.waitUntil(10000) { vm.workspace.state.value.preview!=null }
        compose.onNodeWithText("正在用电脑上的 Office 转成 PDF…").assertDoesNotExist()
        menuOffersTheFile()
        compose.runOnIdle { org.junit.Assert.assertEquals("pdf",org.json.JSONObject(vm.workspace.state.value.data).string("preview"));org.junit.Assert.assertEquals(1,world.pdfReads) }
    }
    /** The file page's ⋯ saves, shares and opens the file itself; a tap beside it closes it again. */
    private fun menuOffersTheFile() {
        compose.onNodeWithContentDescription("文件菜单").performClick()
        compose.onNodeWithText("保存到手机").assertIsEnabled()
        compose.onNodeWithText("系统分享").assertIsEnabled();compose.onNodeWithText("用其他应用打开").assertIsEnabled()
        compose.onRoot().performTouchInput { click(androidx.compose.ui.geometry.Offset(24f,height-24f)) }
        compose.onNodeWithText("保存到手机").assertDoesNotExist()
    }
    @Test fun claudeSendIsConfirmedFromItsRecord() {
        launch();fixtureList();openChat("Claude 下一步示例","claude-next")
        compose.onNodeWithTag("composer").performTextInput("再跑一遍测试")
        compose.onNodeWithContentDescription("发送").performClick()
        // Enter pressed on the computer is 已接收; Claude reading it, found in its record, is 已送达 (web chat/check).
        compose.waitUntil(15000) { vm.composer.state.value.submissions.firstOrNull()?.label=="已送达" }
        compose.onNodeWithText("已送达").assertExists()
        compose.onNodeWithText("待核对发送记录").assertDoesNotExist()
    }
    @Test fun claudeBoxHoldingOtherTextOffersToReplaceIt() {
        launch();fixtureList();openChat("Claude 下一步示例","claude-next")
        compose.onNodeWithTag("composer").performTextInput("测试电脑草稿")
        compose.onNodeWithContentDescription("发送").performClick()
        compose.waitUntil(10000) { vm.composer.state.value.submissions.firstOrNull()?.label=="未接收" }
        compose.onNodeWithText("上一条没发出去",substring=true).assertExists()
        compose.onNodeWithText("恢复草稿").assertExists()
        compose.onNodeWithContentDescription("换掉电脑上 Claude 输入框里的「e」，再发这条消息").performClick()
        compose.waitUntil(15000) { vm.composer.state.value.submissions.firstOrNull { it.label!=RemovedLabel }?.label=="已送达" }
        compose.runOnIdle {
            val sent=vm.composer.state.value.submissions.first { it.label=="已送达" }
            org.junit.Assert.assertEquals("e",org.json.JSONObject(sent.body).string("replace_draft"))
            org.junit.Assert.assertEquals("测试电脑草稿",sent.text)
        }
        compose.onNodeWithText("上一条没发出去",substring=true).assertDoesNotExist()
    }
    @Test fun claudeNextStepAndTaskButtonsPressOnTheComputer() {
        launch();fixtureList();openChat("Claude 下一步示例","claude-next")
        compose.onNodeWithText("来自其他对话").assertExists()
        compose.onNodeWithContentDescription("计划进度 2 / 4",substring=true).assertExists()
        compose.onNodeWithText("接着改说明文档").performScrollTo().performClick()
        compose.waitUntil(10000) { vm.workspace.state.value.cards["next:wrap-1"]?.startsWith("done:")==true }
        compose.onNodeWithText("本地示例：已在电脑上点了「接着改说明文档」").assertExists()
        compose.onNodeWithText("先停在这里").assertDoesNotExist()
        compose.onNodeWithText("开始").performScrollTo().performClick()
        compose.waitUntil(10000) { vm.workspace.state.value.cards["task:整理发布清单"]?.startsWith("done:")==true }
        compose.onNodeWithText("在这里做").assertDoesNotExist()
    }
    @Test fun codexPlanRunsInNormalMode() {
        launch();fixtureList();openChat("Codex 计划示例","plan-demo")
        compose.waitUntil(10000) { vm.composer.state.value.control.available }
        compose.onNodeWithText("待确认").performScrollTo().assertExists()
        compose.onNodeWithText("执行计划").performScrollTo().performClick()
        compose.waitUntil(10000) { vm.composer.state.value.submissions.firstOrNull()?.let { it.text=="执行计划" && it.label=="已接收" }==true }
        compose.runOnIdle {
            val body=org.json.JSONObject(vm.composer.state.value.submissions.first().body)
            org.junit.Assert.assertEquals("plan-item-1",body.string("plan_id"))
            org.junit.Assert.assertEquals("default",body.getJSONObject("settings").string("mode"))
        }
    }
    @Test fun archiveLeavesTheListAndUndoBringsItBack() {
        launch();fixtureList()
        compose.runOnIdle { vm.archive(vm.state.value.chats.first { it.id=="question" }) }
        compose.waitUntil(10000) { vm.state.value.chats.none { it.id=="question" } && vm.state.value.undo?.waiting==false }
        compose.onNodeWithText("对话已归档").assertExists()
        compose.onNodeWithText("撤销").performClick()
        compose.waitUntil(10000) { vm.state.value.chats.any { it.id=="question" } && vm.state.value.notice=="已恢复" }
        compose.onNodeWithText("对话已归档").assertDoesNotExist()
    }
    @Test fun archivedConversationsRestoreFromSettings() {
        launch();fixtureList()
        compose.runOnIdle { vm.archive(vm.state.value.chats.first { it.id=="plan-demo" }) }
        compose.waitUntil(10000) { vm.state.value.undo?.waiting==false }
        compose.runOnIdle { vm.settings() }
        compose.onNodeWithText("已归档对话").performScrollTo().performClick()
        compose.waitUntil(10000) { compose.onAllNodesWithContentDescription("恢复 Codex 计划示例").fetchSemanticsNodes().isNotEmpty() }
        compose.onNodeWithText("Codex 的可以恢复，也可以勾选后删除；删除后电脑上也找不回来。",substring=true).assertExists()
        compose.onNodeWithContentDescription("恢复 Codex 计划示例").performClick()
        compose.waitUntil(10000) { compose.onAllNodesWithText("已恢复，回到对话列表里了").fetchSemanticsNodes().isNotEmpty() }
        compose.runOnIdle { org.junit.Assert.assertFalse("codex:plan-demo" in vm.state.value.hidden) }
    }
    @Test fun childrenFoldUnderTheirConversation() {
        launch();fixtureList()
        listRow("▸ 子对话 3 个 · 1 个运行中").performClick()
        listRow("检查日志").assertExists()
        listRow("再显示 1 个（共 3 个）").performClick()
        compose.waitUntil(10000) { vm.state.value.moreKids.values.flatten().any { it.id=="ds-run-2" } }
        listRow("清理缓存（脚本）").assertExists()
        listRow("未分组的会话 ▸").performClick()
        listRow("整理下载目录（脚本）").assertExists()
        // A subagent's own record is not readable here: it opens the conversation that shows its card.
        listRow("检查日志").performClick()
        compose.waitUntil(10000) { vm.state.value.chat?.id=="deepseek-demo" && !vm.state.value.busy }
    }
    /** Notifications and voice on 设置; 诊断测速 under its 开发者选项 (0.9). */
    @Test fun ntfyAndVoiceInSettingsAndDiagnosticsUnderDeveloper() {
        launch();fixtureList();compose.runOnIdle { vm.settings() }
        // One switch (10-28): on, with whether the phone listens under it; no test button, no words.
        compose.waitUntil(10000) { compose.onAllNodesWithText("ntfy 通知").fetchSemanticsNodes().isNotEmpty() && !vm.state.value.busy }
        compose.waitUntil(10000) { runCatching { compose.onNodeWithText("ntfy 通知").assertIsEnabled() }.isSuccess }
        compose.onNodeWithText("ntfy 通知").performScrollTo().assertIsOff().performClick()
        compose.waitUntil(10000) { compose.onAllNodesWithText("手机连着").fetchSemanticsNodes().isNotEmpty() }
        compose.onNodeWithText("ntfy 通知").assertIsOn()
        compose.onNodeWithText("试推一条").assertDoesNotExist()
        compose.onNodeWithText("主题").assertExists()
        compose.onNodeWithText("录音后自动整理").performScrollTo().assertIsOn()
        compose.onNodeWithText("显示操作耗时").assertDoesNotExist()
        compose.onNodeWithText("开发者选项").performScrollTo().performClick()
        compose.waitUntil(10000) { vm.state.value.screen==Screen.Developer }
        compose.onNodeWithText("显示操作耗时").performScrollTo().performClick()
        compose.onNodeWithText("测一下连接").performScrollTo().performClick()
        compose.waitUntil(10000) { Diagnostics.records.value.size==3 }
        compose.onNodeWithText("连接请求 3/3",substring=true).performScrollTo().assertExists()
    }
    /** 0.9 (web account page): 我的电脑 renames and removes a computer from its ⋯; 退出登录 goes back to 登录. */
    @Test fun myComputersRenameRemoveAndSignOut() {
        launch();openDemo();compose.onNodeWithText("进入示例").performClick()
        compose.waitUntil(10000) { vm.state.value.screen==Screen.Devices && !vm.state.value.busy }
        compose.onNodeWithText("我的电脑").assertIsDisplayed()
        compose.onNodeWithContentDescription("连接测试电脑 A").assertHasClickAction()
        compose.onNodeWithContentDescription("离线电脑离线").assertIsNotEnabled()
        compose.onAllNodesWithContentDescription("管理电脑")[1].performClick()
        compose.onNodeWithText("重命名").performClick()
        compose.onNodeWithContentDescription("电脑名称").performTextReplacement("书房电脑")
        compose.onNodeWithText("确定").performClick()
        compose.waitUntil(10000) { vm.state.value.account?.devices?.any { it.label=="书房电脑" }==true && !vm.state.value.busy }
        compose.onNodeWithText("书房电脑").assertIsDisplayed()
        compose.onAllNodesWithContentDescription("管理电脑")[2].performClick()
        compose.onNodeWithText("移除").performClick()
        compose.onNodeWithText("移除这台电脑？").assertIsDisplayed()
        compose.onAllNodesWithText("移除").filterToOne(hasClickAction() and hasAnyAncestor(isDialog())).performClick()
        compose.waitUntil(10000) { vm.state.value.account?.devices?.size==2 && !vm.state.value.busy }
        compose.onNodeWithText("离线电脑").assertDoesNotExist()
        compose.onNodeWithContentDescription("账号菜单").performClick()
        compose.onNodeWithText("退出登录").performClick()
        compose.waitUntil(10000) { vm.state.value.screen==Screen.Login && vm.state.value.account==null && !vm.state.value.busy }
    }
    /** 0.9 (web sidebar): sources behind their marks and open, projects behind folders with ＋ and folded at first. */
    @Test fun sidebarShowsSourcesAndProjectsAndFolds() {
        launch();fixtureList();compose.onNodeWithContentDescription("打开导航").performClick()
        compose.waitUntil(10000) { vm.state.value.tree!="{}" }
        val codex=hasText("Codex") and hasAnyAncestor(hasTestTag("sidebar"))
        compose.onNode(codex and hasStateDescription("已展开")).assertExists()
        compose.onAllNodesWithContentDescription("在「测试项目」新建对话").onFirst().assertHasClickAction()
        compose.onNode(codex).performClick()
        compose.onNode(codex and hasStateDescription("已收起")).assertExists()
        compose.onNode(codex).performClick()
        compose.onNode(codex and hasStateDescription("已展开")).assertExists()
        openSidebarProject("固定测试项目")
        compose.onNodeWithTag("sidebar-tree").performScrollToNode(hasText("DeepSeek 批准示例"))
        compose.onNode(hasText("DeepSeek 批准示例") and hasAnyAncestor(hasTestTag("sidebar"))).assertExists()
    }
    /** Projects in the sidebar start folded (web): opens one to reach its conversations. */
    protected fun openSidebarProject(name:String) {
        compose.onNodeWithTag("sidebar-tree").performScrollToNode(hasText(name))
        compose.onNode(hasText(name) and hasAnyAncestor(hasTestTag("sidebar")) and hasStateDescription("已收起")).performClick()
    }
    @Test fun sidebarOpensAnotherSourceWithoutReusingChat() {
        launch();fixtureList();compose.onNodeWithContentDescription("打开导航").performClick()
        compose.waitUntil(10000) { vm.state.value.tree!="{}" }
        openSidebarProject("固定测试项目")
        compose.onNodeWithTag("sidebar-tree").performScrollToNode(hasText("DeepSeek 批准示例"))
        compose.onNode(hasText("DeepSeek 批准示例") and hasAnyAncestor(hasTestTag("sidebar"))).performClick()
        compose.waitUntil(10000) { vm.state.value.app=="deepseek" && vm.state.value.chat?.id=="deepseek-demo" && !vm.state.value.busy }
        compose.waitUntil(10000) { vm.composer.state.value.control.questions }
        compose.onNodeWithText("批准这一步吗？").assertExists()
        compose.runOnIdle { org.junit.Assert.assertTrue(vm.state.value.messages.none { it.id=="m1" }) }
    }
    /** 10-27 ("保持每次点开对话都在最新的地方"): a conversation opens at its latest messages, also after reading higher up. */
    @Test fun conversationsOpenAtTheLatestMessages() {
        launch();fixtureList()
        compose.onNodeWithTag("chat-search").performTextInput("performance")
        compose.onNodeWithTag("chat-search").performImeAction()
        compose.waitUntil(10000) { !vm.state.value.busy && vm.state.value.chats.singleOrNull()?.id=="performance" }
        repeat(2) {
            listRow("长会话性能示例").performClick()
            compose.waitUntil(10000) { vm.state.value.chat?.id=="performance" && vm.state.value.messages.size==200 && !vm.state.value.busy }
            compose.waitForIdle()
            org.junit.Assert.assertTrue("opens at the bottom",atBottom())
            compose.onNodeWithText("固定消息 200").assertExists()
            // Read higher up, then leave: the next opening is at the bottom again, not here.
            compose.onNodeWithTag("messages").performScrollToIndex(3)
            compose.onNodeWithText("固定消息 3").assertIsDisplayed()
            org.junit.Assert.assertFalse(atBottom())
            compose.onNodeWithContentDescription("返回").performClick()
            compose.waitUntil(10000) { vm.state.value.screen==Screen.Chats && !vm.state.value.busy }
        }
    }
    /** 加载更早消息 (web scroll-anchor.js): the message at the top stays where it was; the older ones come in above it. */
    @Test fun olderMessagesComeInAboveWithoutMovingThePage() {
        launch();fixtureList();openChat("原生阅读示例","demo")
        compose.onNodeWithTag("messages").performScrollToIndex(0)
        val first=compose.onNodeWithText("请展示原生 Markdown 阅读。")
        val top=first.fetchSemanticsNode().boundsInRoot.top
        compose.onNodeWithText("加载更早消息").performClick()
        compose.waitUntil(10000) { vm.state.value.messages.firstOrNull()?.id=="m0" && !vm.state.value.busy }
        compose.waitForIdle()
        org.junit.Assert.assertEquals(top,first.fetchSemanticsNode().boundsInRoot.top,2f)
    }
    /** 10-27: a Claude press whose reply was lost: 核对上次操作 reads Claude again, says what it found, and the line goes. */
    @Test fun aLostClaudePressIsCheckedFromTheStatusLine() {
        launch();fixtureList();openChat("Claude 选项示例","claude-demo")
        compose.onNodeWithTag("messages").performScrollToKey("interactions")
        compose.runOnIdle { vm.fixtureWorld!!.network=FixtureNetwork.Offline }
        compose.onNodeWithContentDescription("选择完整段落").performScrollTo().performClick()
        compose.waitUntil(10000) { org.json.JSONObject(vm.workspace.state.value.saved).optJSONObject("pending_action")?.string("status")=="unknown" && !vm.workspace.state.value.busy }
        compose.onNodeWithText("没收到电脑的回复，上次操作的结果还没确认；不会自动重试。").assertExists()
        compose.runOnIdle { vm.fixtureWorld!!.network=FixtureNetwork.Instant }
        compose.onNodeWithText("核对上次操作").performClick()
        compose.waitUntil(10000) { vm.workspace.state.value.result.isNotBlank() && !vm.workspace.state.value.checking }
        compose.onNodeWithText("电脑上的 Claude 还在等你选；上次那一下可能没送到，请再选一次。").assertExists()
        compose.onNodeWithText("核对上次操作").assertDoesNotExist()
        compose.onNodeWithText("上次操作的结果还没确认").assertDoesNotExist()
        // 示例网络 回复丢失: the computer takes 提交 and the reply is lost; afterwards nothing waits there any more.
        compose.onNodeWithText("跳过").performScrollTo().performClick()
        compose.waitUntil(10000) { org.json.JSONObject(vm.composer.state.value.control.raw).optJSONObject("prompt")?.string("progress")=="2 / 2" && !vm.workspace.state.value.busy }
        compose.runOnIdle { vm.fixtureWorld!!.network=FixtureNetwork.LostReply }
        compose.onNodeWithText("提交").performScrollTo().performClick()
        compose.waitUntil(10000) { org.json.JSONObject(vm.workspace.state.value.saved).optJSONObject("pending_action")?.string("status")=="unknown" && !vm.workspace.state.value.busy }
        compose.runOnIdle { vm.fixtureWorld!!.network=FixtureNetwork.Instant }
        compose.onNodeWithText("核对上次操作").performClick()
        compose.waitUntil(10000) { vm.workspace.state.value.result.isNotBlank() && !vm.workspace.state.value.checking }
        compose.onNodeWithText("电脑上已经没有在等的选项，上次的选择已处理。").assertExists()
        compose.onNodeWithText("核对上次操作").assertDoesNotExist()
    }
    /** The conversation can scroll no further down: the latest messages are on screen (the list's own reading of its end). */
    protected fun atBottom():Boolean {
        val range=compose.onNodeWithTag("messages").fetchSemanticsNode().config[androidx.compose.ui.semantics.SemanticsProperties.VerticalScrollAxisRange]
        return range.value()>=range.maxValue()
    }
    @Test fun composerKeepsDraftAcrossBackAndShowsReceipt() {
        launch();fixtureList()
        compose.onNodeWithText("原生阅读示例").performClick()
        compose.waitUntil(10000) { vm.composer.state.value.ready }
        compose.onNodeWithTag("composer").performTextInput("本地中文草稿")
        compose.onNodeWithContentDescription("返回").performClick()
        compose.waitUntil(10000) { vm.state.value.screen==Screen.Chats }
        compose.onNodeWithText("原生阅读示例").performClick()
        compose.waitUntil(10000) { vm.composer.state.value.ready && vm.composer.state.value.draft=="本地中文草稿" && vm.composer.state.value.control.available }
        compose.onNodeWithContentDescription("发送").performClick()
        compose.waitUntil(10000) { vm.composer.state.value.submissions.firstOrNull()?.label=="已接收" }
        compose.onNodeWithText("已接收").assertExists()
        compose.onNodeWithTag("composer").assertTextContains("")
        compose.onNodeWithText("批准",substring=false).assertDoesNotExist()
    }
    @get:Rule val compose=createComposeRule()
    protected lateinit var vm:ReaderViewModel
    protected lateinit var androidView:android.view.View
    protected fun launch(theme:String="light",fontScale:Float=1f,windowWidth:State<androidx.compose.ui.unit.Dp>?=null) {
        Diagnostics.setForTest(false)
        compose.setContent {
            androidView=androidx.compose.ui.platform.LocalView.current
            vm=viewModel(factory=object:ViewModelProvider.Factory {
                @Suppress("UNCHECKED_CAST") override fun <T:ViewModel> create(modelClass:Class<T>):T=ReaderViewModel(UiMemoryStore()) { FixtureApi() } as T
            })
            val s by vm.state.collectAsState()
            val density=androidx.compose.ui.platform.LocalDensity.current
            CompositionLocalProvider(androidx.compose.ui.platform.LocalDensity provides androidx.compose.ui.unit.Density(density.density,fontScale)) {
                TeleplyTheme(theme) { if(windowWidth!=null) androidx.compose.foundation.layout.Box(androidx.compose.ui.Modifier.requiredWidth(windowWidth.value)) { ReaderApp(s,vm) } else ReaderApp(s,vm) }
            }
        }
        compose.waitForIdle()
        // New conversations are looked at again at once here: the JVM run's main clock does not move by itself.
        vm.jobs.pause={}
    }
    /** A row of the list, scrolled into view first: the list composes only the rows on screen. */
    protected fun listRow(text:String):SemanticsNodeInteraction {
        compose.onNodeWithTag("chat-list").performScrollToNode(hasText(text))
        return compose.onNodeWithText(text)
    }
    protected fun openChat(title:String,id:String) {
        listRow(title).performClick()
        compose.waitUntil(10000) { vm.state.value.chat?.id==id && vm.composer.state.value.ready && vm.workspace.state.value.ready && !vm.state.value.busy }
    }
    /** The app opens on 登录 for the default service (0.9); the local demo is under 设置 → 开发者选项. */
    protected fun openDemo() {
        compose.waitUntil(10000) { vm.state.value.screen==Screen.Login && !vm.state.value.busy }
        compose.onNodeWithContentDescription("设置").performClick()
        compose.onNodeWithText("开发者选项").performScrollTo().performClick()
        compose.onNodeWithText("打开本地示例").performScrollTo().performClick()
        compose.waitUntil(10000) { vm.state.value.fixture && vm.state.value.screen==Screen.Login }
    }
    protected fun fixtureList(computer:String="测试电脑 A") {
        openDemo()
        compose.onNodeWithText("进入示例").performClick()
        compose.waitUntil(10000) { vm.state.value.screen==Screen.Devices && !vm.state.value.busy }
        compose.onNodeWithText("离线电脑").assertIsDisplayed()
        compose.onNodeWithText(computer).performClick()
        // The list and the computer's apps (0.9.1: the chips wait for those) are both in.
        compose.waitUntil(10000) { vm.state.value.screen==Screen.Chats && !vm.state.value.busy && vm.state.value.knownApps()!=null }
    }
    /** The source chips by their label: a selectable chip in the row (the list's badges carry the same names). */
    protected fun chip(label:String)=compose.onNode(hasText(label) and isSelectable() and hasAnyAncestor(hasTestTag("source-chips")))
    @Test fun computerWithoutClaudeOffersOnlyItsSourcesEverywhere() {
        launch();fixtureList("测试电脑 B")
        chip("全部").assertIsSelected();chip("Codex").assertExists();chip("DeepSeek").assertExists()
        chip("Claude").assertDoesNotExist()
        // ⋯ 列表显示 → 来源 lists the same apps.
        compose.onNodeWithContentDescription("列表显示选项").performClick()
        compose.onNodeWithText("来源").performClick()
        compose.onNodeWithText("全部应用").assertExists();compose.onNode(hasText("DeepSeek") and hasClickAction() and !hasAnyAncestor(hasTestTag("source-chips"))).assertExists()
        compose.onAllNodes(hasText("Claude") and hasClickAction()).assertCountEquals(0)
        compose.onNodeWithText("全部应用").performClick()
        compose.waitUntil(10000) { !vm.state.value.busy && vm.state.value.listSource=="all" }
        compose.runOnIdle { org.junit.Assert.assertEquals(listOf("codex","deepseek"),vm.state.value.knownApps()) }
        // 新建对话: the source switch has Codex and DeepSeek only, even when Claude was the last source used.
        compose.runOnIdle { vm.startNew("claude") }
        compose.waitUntil(10000) { vm.workspace.state.value.pane=="new" && vm.workspace.state.value.ready }
        compose.onNode(hasText("DeepSeek") and isSelectable()).assertExists()
        compose.onAllNodes(hasText("Claude") and isSelectable()).assertCountEquals(0)
        compose.runOnIdle { org.junit.Assert.assertEquals("codex",vm.workspace.state.value.key?.app) }
    }
    @Test fun sourceChipsScrollSidewaysAtFullWidth() {
        // A narrow phone with large text: the chips do not fit and must not be squeezed ("Deep").
        launch(fontScale=1.3f,windowWidth=mutableStateOf(320.dp));fixtureList()
        compose.onNodeWithTag("source-chips").assert(SemanticsMatcher.keyIsDefined(androidx.compose.ui.semantics.SemanticsProperties.HorizontalScrollAxisRange))
        val deepseek=chip("DeepSeek")
        deepseek.performScrollTo().assertIsDisplayed()
        // Its whole word is laid out on one line, nothing cut.
        val layout=mutableListOf<androidx.compose.ui.text.TextLayoutResult>()
        compose.onNode(hasText("DeepSeek") and hasAnyAncestor(hasTestTag("source-chips")),useUnmergedTree=true).fetchSemanticsNode().config[androidx.compose.ui.semantics.SemanticsActions.GetTextLayoutResult].action?.invoke(layout)
        // (Measured without a width limit, so compare with the word's own width rather than the overflow flag.)
        layout.single().let { text ->
            org.junit.Assert.assertTrue(text.size.width>=text.multiParagraph.maxIntrinsicWidth-1f)
            org.junit.Assert.assertEquals(1,text.lineCount);org.junit.Assert.assertFalse(text.didOverflowHeight)
        }
        deepseek.performClick()
        compose.waitUntil(10000) { !vm.state.value.busy && vm.state.value.listSource=="deepseek" }
        deepseek.assertIsSelected().assertIsDisplayed()
        // The ⋯ stays outside the scrolling and still opens its menu.
        compose.onNodeWithContentDescription("列表显示选项").assertIsDisplayed().performClick()
        compose.onNodeWithText("分组").assertExists()
    }
    @Test fun slowOrBrokenComputerNeverShowsAllSources() {
        launch();openDemo()
        compose.onNodeWithText("进入示例").performClick()
        compose.waitUntil(10000) { vm.state.value.screen==Screen.Devices && !vm.state.value.busy }
        compose.runOnIdle { vm.fixtureWorld!!.network=FixtureNetwork.Offline }
        compose.onNodeWithText("测试电脑 B").performClick()
        compose.waitUntil(10000) { vm.state.value.sources.failed!=null }
        // Not reachable: 全部 and why, with 重试; no Claude, and not three chips pretending.
        chip("全部").assertExists();chip("Claude").assertDoesNotExist();chip("Codex").assertDoesNotExist()
        compose.onNodeWithText("读不到这台电脑的应用 · 重试").assertHasClickAction()
        compose.runOnIdle { vm.fixtureWorld!!.network=FixtureNetwork.Instant }
        compose.onNodeWithText("读不到这台电脑的应用 · 重试").performClick()
        compose.waitUntil(10000) { vm.state.value.knownApps()==listOf("codex","deepseek") }
        chip("Codex").assertExists();chip("DeepSeek").assertExists();chip("Claude").assertDoesNotExist()
    }
    @Test fun fixtureNavigationPaginationAndBack() {
        launch();fixtureList()
        listRow("加载更多对话").performClick()
        compose.waitUntil(10000) { !vm.state.value.busy && vm.state.value.chats.size==10 }
        listRow("原生阅读示例").performClick()
        compose.waitUntil(10000) { vm.state.value.screen==Screen.Reading && !vm.state.value.busy }
        compose.onNodeWithContentDescription("返回").assertHasClickAction().performClick()
        compose.waitUntil(10000) { vm.state.value.screen==Screen.Chats }
        compose.onNodeWithTag("chat-search").assertIsDisplayed()
    }
    @Test fun sourceChipsFilterTheMixedList() {
        launch();fixtureList()
        compose.runOnIdle { org.junit.Assert.assertEquals(setOf("codex","claude","deepseek"),vm.state.value.chats.map { it.app }.toSet()) }
        compose.onNode(hasText("Claude") and isSelectable()).performClick()
        compose.waitUntil(10000) { !vm.state.value.busy && vm.state.value.listSource=="claude" }
        compose.runOnIdle { org.junit.Assert.assertTrue(vm.state.value.chats.isNotEmpty() && vm.state.value.chats.all { it.app=="claude" }) }
        compose.onNodeWithContentDescription("列表显示选项").performClick()
        compose.onNodeWithText("状态").performClick()
        compose.onNodeWithText("运行中").performClick()
        compose.waitUntil(10000) { !vm.state.value.busy && vm.state.value.listStatus=="running" }
        compose.onNodeWithText("没有找到对话").assertIsDisplayed()
        compose.onNodeWithText("清除筛选").performClick()
        compose.waitUntil(10000) { !vm.state.value.busy && vm.state.value.listSource=="all" && vm.state.value.listStatus=="all" && vm.state.value.chats.size==9 }
    }
    @Test fun lightLargeTextHasReachableServiceAndSettings() {
        launch("light",2f)
        compose.waitUntil(10000) { vm.state.value.screen==Screen.Login && !vm.state.value.busy }
        // Only the account and the password on 登录 (0.9). The gear opens 设置; the service address and the demo are
        // not there but under its 开发者选项, and 返回 comes back the same way.
        compose.onNodeWithText("服务地址").assertDoesNotExist()
        compose.onNodeWithContentDescription("设置").performClick()
        compose.onNodeWithText("跟随系统").performScrollTo().assertIsDisplayed()
        compose.onNodeWithText("深色").performScrollTo().assertHasClickAction()
        compose.onNodeWithText("服务地址").assertDoesNotExist()
        compose.onNodeWithText("打开本地示例").assertDoesNotExist()
        compose.onNodeWithText("开发者选项").performScrollTo().performClick()
        compose.onNodeWithText("服务地址").performScrollTo().assertHasClickAction()
        compose.onNodeWithText("打开本地示例").performScrollTo().assertHasClickAction()
        compose.onNodeWithContentDescription("返回").performClick()
        compose.waitUntil(10000) { vm.state.value.screen==Screen.Settings }
        compose.onNodeWithContentDescription("返回").performClick()
        compose.waitUntil(10000) { vm.state.value.screen==Screen.Login }
    }
    @Test fun darkEmptyAndFailureHavePersistentMeaning() {
        launch("dark");fixtureList()
        compose.onNodeWithTag("chat-search").performTextInput("nothing-matches")
        compose.onNodeWithTag("chat-search").performImeAction()
        compose.waitUntil(10000) { !vm.state.value.busy && vm.state.value.query=="nothing-matches" && vm.state.value.chats.isEmpty() }
        compose.onNodeWithText("没有找到对话").assertIsDisplayed()
        compose.onNodeWithTag("chat-search").performTextClearance()
        compose.onNodeWithTag("chat-search").performTextInput("error")
        compose.onNodeWithTag("chat-search").performImeAction()
        compose.waitUntil(10000) { vm.state.value.error!=null }
        compose.onNodeWithText("电脑已离线，请稍后刷新电脑列表。").assertIsDisplayed()
        compose.onNodeWithText("重试").assertHasClickAction()
    }
    @Test fun loadingIsAnnouncedAndCommandsAreAbsent() {
        compose.setContent {
            val model=remember { ReaderViewModel(UiMemoryStore()) { FixtureApi() } }
            TeleplyTheme { ReaderApp(ReaderState(screen=Screen.Chats,busy=true),model) }
        }
        // The line shows once a read lasts past 400 ms (0.8: quick reads do not flash it).
        compose.onNodeWithContentDescription("正在读取").assertDoesNotExist()
        compose.mainClock.advanceTimeBy(500)
        compose.onNodeWithContentDescription("正在读取").assertExists()
        compose.onNodeWithText("发送",substring=false).assertDoesNotExist()
        compose.onNodeWithText("批准",substring=false).assertDoesNotExist()
        compose.onNodeWithText("新建会话",substring=false).assertDoesNotExist()
    }
}
