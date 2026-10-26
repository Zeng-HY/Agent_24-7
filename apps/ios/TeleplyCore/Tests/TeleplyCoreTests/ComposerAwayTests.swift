import Foundation
import Testing
import TeleplyModel
@testable import TeleplyState

/// The composer when the computer shows another conversation (user 10-27, via the push session): the computer's
/// reason in the status line, 电脑上打开 on the model chip, Claude's message sent all the same, and Claude's chips
/// named from what was recorded (web claude-ui.js paint).
@MainActor
struct ComposerAwayTests {
    let device = String(repeating: "a", count: 32)

    func state(_ text: String) -> JSONValue {
        (try? JSONValue.parse(Data(text.utf8))) ?? [:]
    }

    @Test func claudeChipsUseTheRecordedNamesWhenTheDesktopShowsNone() {
        let recorded = state(#"{"available":false,"recorded_label":"Opus 5.5","settings":{"model":"claude-opus-5-5","effort":"xhigh","mode":"default"}}"#)
        let labels = chipLabels(app: "claude", raw: recorded, saved: [:])
        #expect(labels.model == "Opus 5.5 · 极高")
        #expect(labels.mode == "Manual")
        #expect(!labels.plan)
        let shown = state(#"{"available":true,"model_label":"Opus 5.5","effort_label":"High","mode_label":"Plan mode","settings":{"model":"claude-opus-5-5"}}"#)
        let open = chipLabels(app: "claude", raw: shown, saved: [:])
        #expect(open.model == "Opus 5.5 · High")
        #expect(open.mode == "计划模式" && open.plan)
        let blank = chipLabels(app: "claude", raw: [:], saved: [:])
        #expect(blank.model == "模型" && blank.mode == "普通执行" && !blank.plan)
    }

    @Test func theModelChipOpensTheConversationOnlyWhenItIsAway() {
        let codexAway = state(#"{"available":false,"reason":"电脑端尚未打开这个对话，请从右上角菜单选择「电脑上打开」后重试"}"#)
        #expect(chipAway(app: "codex", raw: codexAway))
        #expect(awayReason(app: "codex", raw: codexAway) == "电脑端尚未打开这个对话，请从右上角菜单选择「电脑上打开」后重试")
        #expect(!chipAway(app: "codex", raw: state(#"{"available":true}"#)))
        #expect(awayReason(app: "codex", raw: state(#"{"available":true}"#)) == nil)
        // Not read yet: nothing to say.
        #expect(!chipAway(app: "codex", raw: [:]))
        #expect(awayReason(app: "codex", raw: [:]) == nil)
        #expect(awayReason(app: "codex", raw: state(#"{"available":false}"#)) == "电脑上没有打开这个对话；点「电脑上打开」后再发")
        // Claude with a recorded model keeps its menus and sends; with nothing recorded it opens on the computer.
        let claudeRecorded = state(#"{"available":false,"reason":"电脑上显示的不是此 Claude 会话；请点击「电脑上打开」","settings":{"model":"opus"}}"#)
        #expect(!chipAway(app: "claude", raw: claudeRecorded))
        #expect(awayReason(app: "claude", raw: claudeRecorded) == nil)
        let claudeBlank = state(#"{"available":false,"reason":"电脑上显示的不是此 Claude 会话；请点击「电脑上打开」"}"#)
        #expect(chipAway(app: "claude", raw: claudeBlank))
        #expect(awayReason(app: "claude", raw: claudeBlank) == "电脑上显示的不是此 Claude 会话；请点击「电脑上打开」")
        #expect(!chipAway(app: "deepseek", raw: state(#"{"available":false}"#)))
    }

    func conversation(_ app: String, _ computer: CommandComputer) -> (ChatModel, ChatKey) {
        let key = ChatKey(scope: "account", device: device, app: app, chat: "chat")
        let model = ChatModel(pacer: IdlePacer(), store: LocalStore(folder: temporaryFolder()), newID: { UUID().uuidString }, now: { 1_000 })
        model.bind(key, client: RelayClient(origin: .default, transport: computer), clientGeneration: 0, active: true, synthetic: false) { _, _ in }
        return (model, key)
    }

    @Test func claudesMessageGoesWhileTheComputerShowsAnotherConversation() async {
        let computer = CommandComputer(available: false)
        await computer.gate.open()
        let (model, _) = conversation("claude", computer)
        for _ in 0..<2_000 where !(model.ready && model.control.raw.has("available")) { await Task.yield() }
        #expect(!model.control.available)
        model.edit("照样发出去")
        model.send()
        await model.settleSends()
        #expect(await computer.counts.sends == 1)
    }

    @Test func codexWaitsUntilItIsOpenOnTheComputer() async {
        let computer = CommandComputer(available: false)
        await computer.gate.open()
        let (model, _) = conversation("codex", computer)
        for _ in 0..<2_000 where !(model.ready && model.control.raw.has("available")) { await Task.yield() }
        model.edit("先别发")
        model.send()
        await model.settleSends()
        #expect(await computer.counts.sends == 0)
        #expect(model.draft == "先别发")
    }
}
