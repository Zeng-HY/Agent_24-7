package com.pocketagentdesk.nativepreview

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
    override suspend fun position(scope:String,device:String,chat:String):ReadingPosition?=null
    override suspend fun save(position:ReadingPosition)=Unit
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
        // A page that runs no script and loads nothing from the network; the source, as text, one tap away.
        compose.onNodeWithContentDescription("网页预览：安全预览.html").assertExists()
        compose.onNodeWithText("<script>fetch(",substring=true).assertDoesNotExist()
        compose.onNodeWithText("查看源码").performClick()
        compose.onNodeWithText("<script>fetch(",substring=true).assertExists()
        compose.onNodeWithText("保存到手机").performScrollTo().assertHasClickAction()
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
        compose.waitUntil(10000) { compose.onAllNodesWithText("打开并试推一条").fetchSemanticsNodes().isNotEmpty() }
        compose.onNodeWithText("打开并试推一条").performScrollTo().performClick()
        compose.waitUntil(10000) { compose.onAllNodesWithText("已开 · ntfy").fetchSemanticsNodes().isNotEmpty() }
        compose.onNodeWithText("试推一条").performScrollTo().assertHasClickAction()
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
    protected fun fixtureList() {
        openDemo()
        compose.onNodeWithText("进入示例").performClick()
        compose.waitUntil(10000) { vm.state.value.screen==Screen.Devices && !vm.state.value.busy }
        compose.onNodeWithText("离线电脑").assertIsDisplayed()
        compose.onNodeWithText("测试电脑 A").performClick()
        compose.waitUntil(10000) { vm.state.value.screen==Screen.Chats && !vm.state.value.busy }
    }
    @Test fun fixtureNavigationPaginationAndBack() {
        launch();fixtureList()
        listRow("加载更多对话").performClick()
        compose.waitUntil(10000) { !vm.state.value.busy && vm.state.value.chats.size==8 }
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
        compose.waitUntil(10000) { !vm.state.value.busy && vm.state.value.listSource=="all" && vm.state.value.listStatus=="all" && vm.state.value.chats.size==7 }
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
