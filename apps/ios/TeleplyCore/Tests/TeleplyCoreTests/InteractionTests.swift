import Foundation
import Testing
@testable import TeleplyDemo
import TeleplyModel
@testable import TeleplyState

/// What the question bar says per source (Android ChatUi pendingCards).
struct PendingCardTests {
    @Test func codexListsItsPendingCardsOnly() {
        let raw = DemoData.parse(#"{"questions":[{"id":"a","status":"pending","questions":[{"id":"q","question":"选哪个？"}]},{"id":"b","status":"answered","questions":[]}]}"#)
        #expect(pendingCards(app: "codex", raw: raw) == [PendingCard(kind: "question", summary: "选哪个？")])
    }

    @Test func claudeHasItsPromptWithProgressAndItsPlanOptions() {
        let raw = DemoData.parse(#"{"prompt":{"title":"格式？","progress":"1/2"},"actions":[{"label":"执行","token":"t"}]}"#)
        #expect(pendingCards(app: "claude", raw: raw) == [PendingCard(kind: "choice", summary: "格式？", progress: "1/2"),
                                                          PendingCard(kind: "actions", summary: "计划与执行选项")])
    }

    @Test func deepseekPutsApprovalsFirstAndCountsEveryItemOnce() {
        let raw = DemoData.parse(#"{"interactions":[{"event":"approval/request","eventId":"e1","request":{"toolName":"shell"}},{"event":"user-questions/request","eventId":"e2","request":{"callId":"c1","questions":[{"id":"q","question":"哪个目录？"}]}}],"questions":[{"callId":"c1","questions":[]}]}"#)
        #expect(pendingCards(app: "deepseek", raw: raw) == [PendingCard(kind: "approval", summary: "批准这一步吗？ · shell", count: 2)])
        #expect(deepseekQuestionCards(raw).count == 1)
        #expect(deepseekQuestionEvent(raw, callId: "c1") == "e2")
        #expect(pendingCards(app: "deepseek", raw: [:]).isEmpty)
    }
}

/// Answering in the timeline on the local demo, through the whole app (Android ReaderUiScenarios card cases).
@MainActor
struct AnsweringTests {
    func demoConversation(_ title: String) async -> AppModel {
        let model = makeApp()
        model.openDemo()
        model.login(name: "x", password: "y")
        await model.settle()
        model.select(model.account!.devices[0])
        await model.settle()
        model.open(model.chats.first { $0.title == title }!)
        await model.settle()
        await model.conversation.settle()
        await model.workspace.settle()
        return model
    }

    /// Lets the refresh an action starts come back.
    func until(_ done: () -> Bool) async {
        for _ in 0..<2_000 where !done() { await Task.yield() }
    }

    @Test func aCodexAnswerIsKeptWhileChosenThenSubmittedOnce() async {
        let model = await demoConversation("只读问题记录")
        let workspace = model.workspace
        let card = model.conversation.control.raw["questions"].array[0]
        #expect(pendingCards(app: "codex", raw: model.conversation.control.raw).count == 1)
        let field = "answers:" + card["id"].string() + ":" + card["answer_revision"].string()
        workspace.edit(field, ["q1": ["方案A"]])
        await workspace.settle()
        #expect(workspace.saved[field]["q1"].array.map { $0.string() } == ["方案A"])
        workspace.action("codex/answer", ["question_id": card["id"], "answer_revision": card["answer_revision"], "answers": workspace.saved[field]])
        await workspace.settle()
        await until { model.conversation.control.raw["questions"].array.first?["status"].string() == "answered" }
        #expect(workspace.saved["pending_action"]["status"].string() == "done")
        #expect(workspace.saved["pending_action"]["route"].string() == "codex/answer")
        #expect(model.conversation.control.raw["questions"].array.first?["editable"].bool() == true)
        #expect(pendingCards(app: "codex", raw: model.conversation.control.raw).isEmpty)
    }

    @Test func claudeChoicesAreTappedOnTheComputerAndMoveTheQuestionOn() async {
        let model = await demoConversation("Claude 选项示例")
        #expect(model.conversation.control.raw["prompt"]["progress"].string() == "1/2")
        model.workspace.action("claude/choose", ["token": "t-choice-1"])
        await model.workspace.settle()
        await until { model.conversation.control.raw["prompt"]["progress"].string() == "2/2" }
        #expect(model.conversation.control.raw["prompt"]["nav"].array.first?["label"].string() == "提交")
        model.workspace.action("claude/choose", ["token": "t-nav-submit"])
        await model.workspace.settle()
        await until { !model.conversation.control.raw["prompt"].isObject }
        #expect(pendingCards(app: "claude", raw: model.conversation.control.raw).isEmpty)
    }

    @Test func aDeepSeekApprovalIsDecidedAndTheCardGoes() async {
        let model = await demoConversation("DeepSeek 批准示例")
        #expect(pendingCards(app: "deepseek", raw: model.conversation.control.raw).first?.kind == "approval")
        model.workspace.action("deepseek/approval", ["event_id": "e-approval-1", "choice": "allowed-once"])
        await model.workspace.settle()
        await until { deepseekApprovals(model.conversation.control.raw).isEmpty }
        #expect(deepseekApprovals(model.conversation.control.raw).isEmpty)
        #expect(model.conversation.control.running)
    }

    @Test func aNextStepButtonIsPressedOnceAndALatePressIsRefused() async {
        let model = await demoConversation("Claude 下一步示例")
        let workspace = model.workspace
        workspace.claudeButton(card: "next:wrap-1", route: "claude/next", body: ["tool_id": "wrap-1", "index": 0, "label": "接着改说明文档"], label: "接着改说明文档")
        #expect(workspace.pressing)
        await workspace.settle()
        #expect(workspace.cards["next:wrap-1"] == "done:本地示例：已在电脑上点了「接着改说明文档」")
        #expect(!workspace.pressing)
        workspace.claudeButton(card: "next:again", route: "claude/next", body: ["tool_id": "wrap-1", "index": 1, "label": "先停在这里"], label: "先停在这里")
        await workspace.settle()
        #expect(workspace.cards["next:again"]?.hasPrefix("error:") == true)
    }

    @Test func aTaskCardIsDealtWithOnceAndTheComputerSaysSo() async {
        let model = await demoConversation("Claude 下一步示例")
        let workspace = model.workspace
        workspace.claudeButton(card: "task:整理发布清单", route: "claude/task", body: ["title": "整理发布清单", "button": "start"], label: "开始")
        await workspace.settle()
        #expect(workspace.cards["task:整理发布清单"] == "done:本地示例：已在电脑上开始了，新对话会出现在列表里")
        await until { model.conversation.control.raw["tasks"].array.isEmpty }
        #expect(model.conversation.control.raw["tasks"].array.isEmpty)
    }

    @Test func aCodexPlanIsCarriedOutInNormalModeAndStopsBeingReady() async {
        let model = await demoConversation("Codex 计划示例")
        #expect(model.conversation.control.raw["plan"]["ready"].bool())
        model.conversation.executePlan("plan-item-1")
        await model.conversation.settle()
        let body = jsonValue(model.conversation.submissions.first!.body)
        #expect(body["plan_id"].string() == "plan-item-1")
        #expect(body["settings"]["mode"].string() == "default")
        #expect(!model.conversation.control.raw["plan"]["ready"].bool())
    }

    @Test func answersCannotChangeWhileAnActionIsWithTheComputer() async {
        let model = await demoConversation("只读问题记录")
        let workspace = model.workspace
        workspace.action("claude/choose", ["token": ""])
        workspace.edit("answers:x", ["q": ["A"]])
        await workspace.settle()
        #expect(workspace.error == "桌面选项已变化，请刷新")
        #expect(workspace.saved["answers:x"].isNull)
        workspace.edit("answers:x", ["q": ["B"]])
        await workspace.settle()
        #expect(workspace.saved["answers:x"]["q"].array.map { $0.string() } == ["B"])
    }
}
