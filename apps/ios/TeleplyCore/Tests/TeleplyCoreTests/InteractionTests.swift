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

    /// The plan options are the question's own buttons, so they show only without a question (web askParts); before
    /// Windows dev.23 the PC sent both, and both apps drew a second card of raw button names.
    @Test func claudeHasItsPromptWithProgressOrElseItsPlanOptions() {
        let both = DemoData.parse(#"{"prompt":{"title":"格式？","progress":"1/2","choices":[{"label":"要点","pressed":true}]},"actions":[{"name":"要点 1","token":"t"}]}"#)
        #expect(pendingCards(app: "claude", raw: both) == [PendingCard(kind: "choice", summary: "格式？", progress: "1/2")])
        let bare = DemoData.parse(#"{"prompt":{},"actions":[{"label":"执行","token":"t"}]}"#)
        #expect(!claudeAsks(bare))
        #expect(pendingCards(app: "claude", raw: bare) == [PendingCard(kind: "actions", summary: "计划与执行选项")])
        #expect(pendingCards(app: "claude", raw: DemoData.parse(#"{"prompt":{"nav":[{"name":"Submit"}]}}"#)).map(\.kind) == ["choice"])
        #expect(pendingCards(app: "claude", raw: [:]).isEmpty)
    }

    /// Windows dev.24 writes "✓ " before a ticked option of a question that takes several, for apps that do not show
    /// `pressed`; shown chosen here, it goes. The PC's Other is a part of its own, never true (the demo said true).
    @Test func aTickedClaudeOptionIsMarkedOnceAndOtherIsAPart() {
        #expect(claudeChoiceLabel(DemoData.parse(#"{"label":"✓ 要点","pressed":true}"#)) == "要点")
        #expect(claudeChoiceLabel(DemoData.parse(#"{"label":"✓ 完成","pressed":false}"#)) == "✓ 完成")
        #expect(claudeChoiceLabel(DemoData.parse(#"{"label":"段落","pressed":null}"#)) == "段落")
        #expect(claudeTakesOther(DemoData.parse(#"{"other":{"name":"Other","token":"t"}}"#)))
        #expect(claudeTakesOther(DemoData.parse(#"{"other":true}"#)))
        #expect(!claudeTakesOther(DemoData.parse(#"{"other":null}"#)))
        #expect(!claudeTakesOther([:]))
    }

    @Test func deepseekPutsApprovalsFirstAndCountsEveryItemOnce() {
        let raw = DemoData.parse(#"{"interactions":[{"event":"approval/request","eventId":"e1","request":{"toolName":"shell"}},{"event":"user-questions/request","eventId":"e2","request":{"callId":"c1","questions":[{"id":"q","question":"哪个目录？"}]}}],"questions":[{"callId":"c1","questions":[]}]}"#)
        #expect(pendingCards(app: "deepseek", raw: raw) == [PendingCard(kind: "approval", summary: "批准这一步吗？ · shell", count: 2)])
        #expect(deepseekQuestionCards(raw).count == 1)
        #expect(deepseekQuestionEvent(raw, callId: "c1") == "e2")
        #expect(pendingCards(app: "deepseek", raw: [:]).isEmpty)
    }

    /// The trap behind the 0.5.0 crash (10-27): in `c ? value : nil` the nil is JSONValue.null, a value `if let`
    /// binds. A question event without a request object is dropped, not kept as null.
    @Test func aBareNilInATernaryIsJSONNullSoEventsWithoutARequestAreDropped() {
        func pick(_ yes: Bool) -> JSONValue? {
            let value = JSONValue.string("x")
            return yes ? value : nil
        }
        #expect(pick(false) == .some(.null))
        let raw = DemoData.parse(#"{"interactions":[{"event":"user-questions/request","eventId":"e1","request":"broken"},{"event":"user-questions/request","eventId":"e2","request":{"callId":"c2","questions":[]}}]}"#)
        #expect(deepseekQuestionCards(raw).map { $0["callId"].string() } == ["c2"])
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

    /// Lets the action and the state read it starts come back.
    func until(_ model: AppModel) async {
        await model.workspace.settle()
        await model.conversation.settle()
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
        await until(model)
        #expect(workspace.saved["pending_action"]["status"].string() == "done")
        #expect(workspace.saved["pending_action"]["route"].string() == "codex/answer")
        #expect(model.conversation.control.raw["questions"].array.first?["editable"].bool() == true)
        #expect(pendingCards(app: "codex", raw: model.conversation.control.raw).isEmpty)
    }

    @Test func claudeChoicesAreTappedOnTheComputerAndMoveTheQuestionOn() async {
        let model = await demoConversation("Claude 选项示例")
        #expect(model.conversation.control.raw["prompt"]["progress"].string() == "1/2")
        model.workspace.action("claude/choose", ["token": "t-choice-1"])
        await until(model)
        #expect(model.conversation.control.raw["prompt"]["nav"].array.first?["label"].string() == "提交")
        model.workspace.action("claude/choose", ["token": "t-nav-submit"])
        await until(model)
        #expect(pendingCards(app: "claude", raw: model.conversation.control.raw).isEmpty)
    }

    /// 打开新建对话 under a Codex reply (user 10-27): the conversation it made is read, then opened.
    @Test func aConversationCodexMadeOpensFromItsButton() async {
        let model = await demoConversation("只读问题记录")
        model.openCreated("fixture-made")
        await model.settle()
        #expect(model.chat?.id == "fixture-made")
        #expect(model.app == "codex")
        #expect(model.error == nil)
        #expect(!model.messages.isEmpty)
    }

    @Test func aDeepSeekApprovalIsDecidedAndTheCardGoes() async {
        let model = await demoConversation("DeepSeek 批准示例")
        #expect(pendingCards(app: "deepseek", raw: model.conversation.control.raw).first?.kind == "approval")
        model.workspace.action("deepseek/approval", ["event_id": "e-approval-1", "choice": "allowed-once"])
        await until(model)
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
        await until(model)
        #expect(workspace.cards["task:整理发布清单"] == "done:本地示例：已在电脑上开始了，新对话会出现在列表里")
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
