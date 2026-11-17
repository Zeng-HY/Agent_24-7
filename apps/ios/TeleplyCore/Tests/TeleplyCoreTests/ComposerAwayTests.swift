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

    /// Claude's effort levels in the model menu by the chip's words (user 10-27: the desktop's six names were cut to
    /// "Med", "Hig" in the menu's row), as Android does; a slider's steps by the names learnt, else 第 N 档 (web).
    @Test func claudeEffortLevelsGoByTheChipsWords() {
        let desktop = ["Low", "Medium Recommended", "High", "Extra", "Max 3.5× or more usage", "Ultracode"]
        #expect(desktop.map(claudeEffortLabel) == ["低", "中", "高", "极高", "最高", "Ultracode"])
        #expect([" High ", "中", "Turbo mode", ""].map(claudeEffortLabel) == ["高", "中", "Turbo", ""])
        let range = state(#"{"min":0,"max":4,"step":1,"value":2,"label":"High","labels":{"0":"Low"}}"#)
        #expect((0...4).map { claudeStepLabel(range, value: Double($0), index: $0) } == ["低", "第 2 档", "高", "第 4 档", "第 5 档"])
        #expect(claudeStepLabel(state(#"{"min":0,"max":1,"step":1,"label":"High"}"#), value: 0, index: 0) == "第 1 档")
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

    /// 11-17: the computer's reason replaces an older "已打开" result; errors, the local note and 待核对 keep their
    /// places (Android statusLineText test).
    @Test func theComputersReasonComesBeforeAnOlderResult() {
        let reason = "电脑端尚未打开这个对话，请从右上角菜单选择「电脑上打开」后重试"
        // An old 电脑上打开 result is still kept from before: the computer's reason wins.
        #expect(statusLineText(chatError: nil, workspaceError: nil, note: "", result: "电脑上已打开「x」，可以发了", unknown: false, away: reason, receipt: nil) == reason)
        // No reason from the computer: the result shows as before.
        #expect(statusLineText(chatError: nil, workspaceError: nil, note: "", result: "电脑上已打开「x」", unknown: false, away: nil, receipt: nil) == "电脑上已打开「x」")
        // Errors first; the note and 待核对 in their places; the receipt last, and not "送达状态待确认".
        #expect(statusLineText(chatError: "出错了", workspaceError: nil, note: "", result: "", unknown: false, away: reason, receipt: nil) == "出错了")
        #expect(statusLineText(chatError: nil, workspaceError: "工作区出错", note: "", result: "", unknown: false, away: reason, receipt: nil) == "工作区出错")
        #expect(statusLineText(chatError: nil, workspaceError: nil, note: "草稿已存", result: "", unknown: false, away: reason, receipt: nil) == "草稿已存")
        #expect(statusLineText(chatError: nil, workspaceError: nil, note: "", result: "", unknown: true, away: reason, receipt: nil) == "上次操作的结果还没确认")
        #expect(statusLineText(chatError: nil, workspaceError: nil, note: "", result: "", unknown: false, away: nil, receipt: "已送达") == "已送达")
        #expect(statusLineText(chatError: nil, workspaceError: nil, note: "", result: "", unknown: false, away: reason, receipt: "送达状态待确认") == reason)
        #expect(statusLineText(chatError: nil, workspaceError: nil, note: "", result: "", unknown: false, away: nil, receipt: "未接收") == nil)
        #expect(statusLineText(chatError: nil, workspaceError: nil, note: "", result: "", unknown: false, away: nil, receipt: nil) == nil)
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
