import SwiftUI
import TeleplyModel
import TeleplyState

/*
 * Questions and approvals answered in the timeline (spec 4.3; user 2026-10-24; Android ChatUi InlineCards): all
 * three sources answer in cards after the messages, where the source asked (a question ends its turn). Choosing is
 * not answering (B07): only 提交回答, 拒绝, 仅允许本次 and 提交答案 send, and a choice scrolled away stays chosen.
 * Claude's options are tapped on its desktop at once, the way the web does.
 */

/// One card the timeline shows for what waits on an answer.
enum InlineCard: Identifiable {
    case codex(JSONValue)
    case claudePrompt(JSONValue)
    case claudeActions([JSONValue])
    case deepseekApproval(JSONValue)
    case deepseekQuestion(JSONValue)

    var id: String {
        switch self {
        case .codex(let card): return "codex:" + card["id"].string() + ":" + card["answer_revision"].string()
        case .claudePrompt: return "claude-prompt"
        case .claudeActions: return "claude-actions"
        case .deepseekApproval(let event): return "approval:" + event["eventId"].string()
        case .deepseekQuestion(let card): return "question:" + card["callId"].string()
        }
    }
}

/// The cards of a source's state: Codex's pending ones and answered ones it lets you change; Claude's desktop
/// question and its plan options; DeepSeek's approvals, then its questions.
func inlineCards(app: String, raw: JSONValue) -> [InlineCard] {
    switch app {
    case "claude":
        var cards: [InlineCard] = []
        if raw["prompt"].isObject { cards.append(.claudePrompt(raw["prompt"])) }
        if !raw["actions"].array.isEmpty { cards.append(.claudeActions(raw["actions"].array)) }
        return cards
    case "deepseek":
        return deepseekApprovals(raw).map(InlineCard.deepseekApproval) + deepseekQuestionCards(raw).map(InlineCard.deepseekQuestion)
    default:
        return raw["questions"].array.filter { $0["status"].string() == "pending" || $0["editable"].bool() }.map(InlineCard.codex)
    }
}

/// One card in the timeline, drawn per kind.
struct InlineCardView: View {
    let model: AppModel
    let card: InlineCard

    var body: some View {
        switch card {
        case .codex(let question): CodexQuestionCard(model: model, card: question)
        case .claudePrompt(let prompt): ClaudePromptCard(model: model, prompt: prompt)
        case .claudeActions(let actions): ClaudeActionsCard(model: model, actions: actions)
        case .deepseekApproval(let event): DeepSeekApprovalCard(model: model, event: event)
        case .deepseekQuestion(let question): DeepSeekQuestionCard(model: model, card: question)
        }
    }
}

/// The web's .codex-card: 20 pt corners, a thin edge, a light shadow.
struct QuestionCard<Content: View>: View {
    @ViewBuilder let content: () -> Content
    @Environment(\.colorScheme) private var scheme

    var body: some View {
        VStack(alignment: .leading, spacing: 10, content: content)
            .padding(16)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(Palette.sheet, in: RoundedRectangle(cornerRadius: 20, style: .continuous))
            .overlay(RoundedRectangle(cornerRadius: 20, style: .continuous).stroke(scheme == .dark ? Palette.controlBorder : Palette.line, lineWidth: 1))
            .shadow(color: Palette.ink.opacity(scheme == .dark ? 0 : 0.025), radius: 6, y: 2)
    }
}

/// A card's title, with a small grey tag in code letters after it (DeepSeek's tool name).
struct CardTitle: View {
    let text: String
    var tag = ""

    var body: some View {
        HStack(spacing: 8) {
            Text(text)
                .headingFont()
                .foregroundStyle(Palette.ink)
                .accessibilityAddTraits(.isHeader)
            if !tag.isEmpty {
                Text(tag)
                    .scaledFont(12, .medium, design: .monospaced, relativeTo: .caption)
                    .foregroundStyle(Palette.muted)
                    .lineLimit(1)
                    .padding(.horizontal, 8)
                    .padding(.vertical, 2)
                    .background(Palette.controlFill, in: RoundedRectangle(cornerRadius: 6, style: .continuous))
            }
        }
    }
}

/// Where a submitted answer stands (正在电脑上点选…, 答案结果待核对), read out once when it changes.
struct CardStatus: View {
    let text: String

    var body: some View {
        Text(text)
            .noteFont()
            .foregroundStyle(Palette.accent)
            .task(id: text) { AccessibilityNotification.Announcement(text).post() }
    }
}

/// An option (web .option-card): 14 pt corners and a thin edge; chosen, the accent edge on the selected colour. One
/// choice shows a round mark, several a rounded box. The whole card is one control.
struct OptionCard: View {
    let title: String
    var detail = ""
    let selected: Bool
    var enabled = true
    var multiple = false
    let action: () -> Void
    @Environment(\.colorScheme) private var scheme

    var body: some View {
        Button(action: action) {
            HStack(alignment: .top, spacing: 10) {
                mark
                    .padding(.top, 2)
                VStack(alignment: .leading, spacing: 2) {
                    Text(title)
                        .smallBodyFont()
                        .foregroundStyle(Palette.ink)
                    if !detail.isEmpty {
                        Text(detail)
                            .noteFont()
                            .foregroundStyle(Palette.muted)
                    }
                }
                .multilineTextAlignment(.leading)
                .frame(maxWidth: .infinity, alignment: .leading)
            }
            .padding(12)
            .frame(minHeight: 56)
            .background(selected ? Palette.selectedFill : Palette.sheet, in: RoundedRectangle(cornerRadius: 14, style: .continuous))
            .overlay(RoundedRectangle(cornerRadius: 14, style: .continuous).stroke(selected ? Palette.accent : Palette.line, lineWidth: 1))
            .contentShape(RoundedRectangle(cornerRadius: 14, style: .continuous))
            .opacity(enabled || selected ? 1 : 0.5)
        }
        .buttonStyle(PressScaleStyle())
        .disabled(!enabled)
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(Text(detail.isEmpty ? title : title + "，" + detail))
        .accessibilityAddTraits(selected ? [.isButton, .isSelected] : .isButton)
    }

    @ViewBuilder
    private var mark: some View {
        let ring = scheme == .dark ? Palette.controlBorder : Color(red: 0xC9 / 255, green: 0xCE / 255, blue: 0xD8 / 255)
        if multiple {
            RoundedRectangle(cornerRadius: 5, style: .continuous)
                .fill(selected ? Palette.accent : .clear)
                .overlay(RoundedRectangle(cornerRadius: 5, style: .continuous).stroke(selected ? Palette.accent : ring, lineWidth: 1))
                .overlay {
                    if selected {
                        Image(systemName: "checkmark")
                            .font(.system(size: 11, weight: .bold))
                            .foregroundStyle(Palette.onAccent)
                    }
                }
                .frame(width: 18, height: 18)
        } else {
            Circle()
                .strokeBorder(selected ? Palette.accent : ring, lineWidth: selected ? 5 : 1)
                .frame(width: 18, height: 18)
        }
    }
}

/// The action waiting on [route] in a conversation's saved workspace, when there is one.
private func pendingAction(_ saved: JSONValue, _ route: String) -> JSONValue? {
    let action = saved["pending_action"]
    return action.isObject && action["route"].string() == route ? action : nil
}

/// The labels chosen for one question.
private func chosen(_ answers: JSONValue, _ id: String) -> [String] {
    answers[id].array.map { $0.string() }
}

// MARK: Codex

/// Codex's questions (web codex-ui.js): each question in turn in one card, then 提交回答. Answered, the card folds to
/// one line where it was; Codex lets some be changed (修改答案).
private struct CodexQuestionCard: View {
    let model: AppModel
    let card: JSONValue
    @State private var editing = false

    var body: some View {
        let workspace = model.workspace
        let questions = card["questions"].array
        if card["status"].string() != "pending" && !editing {
            HStack(spacing: 4) {
                Text("已答 · " + (questions.first?["question"].string() ?? ""))
                    .processFont()
                    .foregroundStyle(Palette.muted)
                    .lineLimit(1)
                    .frame(maxWidth: .infinity, alignment: .leading)
                if card["editable"].bool() {
                    Button("修改答案") { editing = true }
                        .buttonStyle(PillStyle(kind: .text, minHeight: 36))
                }
            }
            .padding(.leading, 12)
            .padding(.trailing, 4)
            .padding(.vertical, 4)
            .frame(minHeight: 44)
            .background(Palette.panel, in: RoundedRectangle(cornerRadius: 12, style: .continuous))
        } else {
            let identity = "answers:" + card["id"].string() + ":" + card["answer_revision"].string()
            let answers = workspace.saved[identity]
            let sent = pendingAction(workspace.saved, "codex/answer")
            QuestionCard {
                CardTitle(text: "Codex 想问你")
                ForEach(Array(questions.enumerated()), id: \.offset) { _, question in
                    ChoiceQuestion(question: question, answers: answers, multiple: question["isMultiple"].bool(), enabled: !workspace.busy) { next in
                        workspace.edit(identity, next)
                    }
                }
                if let sent, sent["body"]["question_id"].string() == card["id"].string(), sent["status"].string() == "done" {
                    CardStatus(text: "答案已提交，等 Codex 接着做")
                }
                if let error = workspace.error {
                    Text(error)
                        .noteFont()
                        .foregroundStyle(Palette.danger)
                }
                Button("提交回答") {
                    workspace.action("codex/answer", ["question_id": card["id"], "answer_revision": card["answer_revision"],
                                                      "answers": answers.isObject ? answers : [:]])
                    editing = false
                }
                .buttonStyle(PillStyle(kind: .primary, wide: true))
                .disabled(workspace.busy || questions.isEmpty || !questions.allSatisfy { !chosen(answers, $0["id"].string()).isEmpty })
            }
        }
    }
}

/// One question with its options and a box for words of your own (自由回答): words replace a single choice and go
/// beside several.
private struct ChoiceQuestion: View {
    let question: JSONValue
    let answers: JSONValue
    let multiple: Bool
    let enabled: Bool
    let change: (JSONValue) -> Void

    var body: some View {
        let id = question["id"].string()
        let options = question["options"].array
        let labels = options.map { $0["label"].string() }
        let selected = chosen(answers, id)
        Text(question["question"].string())
            .scaledFont(15, .medium, relativeTo: .callout, lineHeight: 1.6)
            .foregroundStyle(Palette.ink)
        ForEach(Array(options.enumerated()), id: \.offset) { _, option in
            let label = option["label"].string()
            OptionCard(title: label, detail: option["description"].string(), selected: selected.contains(label), enabled: enabled, multiple: multiple) {
                update(id, multiple ? (selected.contains(label) ? selected.filter { $0 != label } : selected + [label]) : [label])
            }
        }
        let own = Binding<String>(
            get: { selected.filter { !labels.contains($0) }.joined(separator: "\n") },
            set: { text in
                let kept = multiple ? selected.filter { labels.contains($0) } : []
                update(id, kept + (text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ? [] : [text]))
            })
        TextField("", text: own, prompt: Text("自由回答").foregroundStyle(Palette.muted), axis: .vertical)
            .lineLimit(1...4)
            .fieldBox(multiline: true)
            .disabled(!enabled)
            .accessibilityLabel(Text("自由回答：" + question["question"].string()))
    }

    private func update(_ id: String, _ values: [String]) {
        var next = answers.object
        next[id] = .array(values.map(JSONValue.string))
        change(.object(next))
    }
}

// MARK: Claude

/// Claude's question as its desktop shows it (web claude-ui.js): a tap on an option taps it on the computer; with
/// several questions the computer's own 下一题 and 提交 go on.
private struct ClaudePromptCard: View {
    let model: AppModel
    let prompt: JSONValue

    var body: some View {
        let workspace = model.workspace
        let title = prompt["title"].string()
        let progress = prompt["progress"].string()
        let tapping = workspace.busy && pendingAction(workspace.saved, "claude/choose") != nil
        QuestionCard {
            CardTitle(text: (title.isEmpty ? "Claude 想问你" : title) + (progress.isEmpty ? "" : "（\(progress)）"))
            ForEach(Array(prompt["choices"].array.enumerated()), id: \.offset) { _, choice in
                let token = choice["token"].string()
                OptionCard(title: choice["label"].string(), detail: choice["description"].string(), selected: false,
                           enabled: !workspace.busy && !token.isEmpty) {
                    workspace.action("claude/choose", ["token": .string(token)])
                }
            }
            if tapping { CardStatus(text: "正在电脑上点选…") }
            let nav = prompt["nav"].array
            if !nav.isEmpty {
                HStack(spacing: 8) {
                    ForEach(Array(nav.enumerated()), id: \.offset) { _, item in
                        let label = item["label"].string()
                        Button(label.isEmpty ? item["name"].string() : label) {
                            workspace.action("claude/choose", ["token": item["token"]])
                        }
                        .buttonStyle(PillStyle(kind: item["name"].string() == "submit" ? .primary : .secondary))
                        .disabled(workspace.busy || item["token"].string().isEmpty)
                    }
                }
            }
            if prompt["other"].bool() {
                Text("要自己写答案的话，请在电脑上点「Other」填写。")
                    .noteFont()
                    .foregroundStyle(Palette.muted)
            }
        }
    }
}

/// 计划与执行选项 (Claude in plan mode): each option a button, tapped on the computer.
private struct ClaudeActionsCard: View {
    let model: AppModel
    let actions: [JSONValue]

    var body: some View {
        let workspace = model.workspace
        QuestionCard {
            CardTitle(text: "计划与执行选项")
            ForEach(Array(actions.enumerated()), id: \.offset) { _, action in
                let label = action["label"].string()
                Button(label.isEmpty ? action["name"].string() : label) {
                    workspace.action("claude/choose", ["token": action["token"]])
                }
                .buttonStyle(PillStyle(wide: true))
                .disabled(workspace.busy || action["token"].string().isEmpty)
            }
        }
    }
}

// MARK: DeepSeek

/// An approval (web deepseek-ui.js): 批准这一步吗？ with the tool, what it will do in code letters, then 拒绝 and
/// 仅允许本次; once only, the same operation asks again later.
private struct DeepSeekApprovalCard: View {
    let model: AppModel
    let event: JSONValue

    var body: some View {
        let workspace = model.workspace
        let request = event["request"]
        let eventID = event["eventId"].string()
        let reason = request["reason"].string()
        let display = request["displayReason"].string()
        let operation = reason.isEmpty ? display : reason
        let sent = pendingAction(workspace.saved, "deepseek/approval")
        QuestionCard {
            CardTitle(text: "批准这一步吗？", tag: request["toolName"].string())
            if !display.isEmpty && display != operation {
                Text(display)
                    .scaledFont(15, relativeTo: .callout, lineHeight: 1.6)
                    .foregroundStyle(Palette.ink)
            }
            if !operation.isEmpty {
                CodePanel(label: "要做的操作", code: operation, copyLabel: "复制要做的操作")
            }
            if let sent, sent["body"]["event_id"].string() == eventID, sent["status"].string() == "unknown" {
                CardStatus(text: "处理结果待核对")
            }
            HStack(spacing: 8) {
                Button("拒绝") { workspace.action("deepseek/approval", ["event_id": .string(eventID), "choice": "rejected"]) }
                    .buttonStyle(PillStyle(wide: true))
                Button("仅允许本次") { workspace.action("deepseek/approval", ["event_id": .string(eventID), "choice": "allowed-once"]) }
                    .buttonStyle(PillStyle(kind: .primary, wide: true))
            }
            .disabled(workspace.busy)
            Text("只放行这一次；以后同样的操作还会再问。")
                .captionFont()
                .foregroundStyle(Palette.muted)
        }
    }
}

/// DeepSeek's questions: each in turn with its options and 补充回答（可不填）, then 提交答案.
private struct DeepSeekQuestionCard: View {
    let model: AppModel
    let card: JSONValue

    var body: some View {
        let workspace = model.workspace
        let callID = card["callId"].string()
        let identity = "deepseek-answers:" + callID
        let answers = workspace.saved[identity]
        let questions = card["questions"].array
        let sent = pendingAction(workspace.saved, "deepseek/answer")
        QuestionCard {
            CardTitle(text: "DeepSeek 想问你")
            ForEach(Array(questions.enumerated()), id: \.offset) { _, question in
                DeepSeekQuestion(question: question, answers: answers, enabled: !workspace.busy) { next in workspace.edit(identity, next) }
            }
            if let sent, sent["body"]["call_id"].string() == callID, sent["status"].string() == "unknown" {
                CardStatus(text: "答案结果待核对")
            }
            Button("提交答案") {
                var body: [String: JSONValue] = ["call_id": .string(callID), "answers": .array(questions.map { question in
                    let id = question["id"].string()
                    return ["id": .string(id), "selected": .array(chosen(answers, id).map(JSONValue.string)), "custom": .string(answers["custom:" + id].string())]
                })]
                let event = deepseekQuestionEvent(model.conversation.control.raw, callId: callID)
                if !event.isEmpty { body["event_id"] = .string(event) }
                workspace.action("deepseek/answer", .object(body))
            }
            .buttonStyle(PillStyle(kind: .primary, wide: true))
            .disabled(workspace.busy || questions.isEmpty || !questions.allSatisfy { question in
                let id = question["id"].string()
                return !chosen(answers, id).isEmpty || !answers["custom:" + id].string().trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            })
        }
    }
}

private struct DeepSeekQuestion: View {
    let question: JSONValue
    let answers: JSONValue
    let enabled: Bool
    let change: (JSONValue) -> Void

    var body: some View {
        let id = question["id"].string()
        let multiple = question["multiSelect"].bool()
        let selected = chosen(answers, id)
        Text(question["question"].string())
            .scaledFont(15, .medium, relativeTo: .callout, lineHeight: 1.6)
            .foregroundStyle(Palette.ink)
        ForEach(Array(question["options"].array.enumerated()), id: \.offset) { _, option in
            let label = option["label"].string()
            OptionCard(title: label, detail: option["description"].string(), selected: selected.contains(label), enabled: enabled, multiple: multiple) {
                var next = answers.object
                let values = multiple ? (selected.contains(label) ? selected.filter { $0 != label } : selected + [label]) : [label]
                next[id] = .array(values.map(JSONValue.string))
                change(.object(next))
            }
        }
        let custom = Binding<String>(
            get: { answers["custom:" + id].string() },
            set: { text in
                var next = answers.object
                next["custom:" + id] = .string(text)
                change(.object(next))
            })
        TextField("", text: custom, prompt: Text("补充回答（可不填）").foregroundStyle(Palette.muted), axis: .vertical)
            .lineLimit(1...4)
            .fieldBox(multiline: true)
            .disabled(!enabled)
            .accessibilityLabel(Text("补充回答：" + question["question"].string()))
    }
}

// MARK: The question bar

/// Above the input card while something waits (spec 4.3): an orange dot, the question in one line, the web's 去选择 ›
/// or 去处理 ›. A tap goes to the first card in the timeline. After Codex took an answer: 答案已提交，等 Codex 接着做
/// with 刷新 ›.
struct AskBar: View {
    let model: AppModel
    let onAsk: () -> Void

    var body: some View {
        let app = model.conversation.key?.app ?? model.app
        let cards = pendingCards(app: app, raw: model.conversation.control.raw)
        if let first = cards.first {
            let codexSent = app == "codex" && pendingAction(model.workspace.saved, "codex/answer")?["status"].string() == "done"
            let line: (summary: String, go: String) = codexSent ? ("答案已提交，等 Codex 接着做", "刷新 ›")
                : app == "deepseek" ? (first.summary + (first.count > 1 ? "（共 \(first.count) 项）" : ""), "去处理 ›")
                : app == "claude" ? (first.summary + (first.progress.isEmpty ? "" : "（\(first.progress)）"), "去选择 ›")
                : (first.summary, "去选择 ›")
            Button {
                if codexSent { model.conversation.refreshControl() } else { onAsk() }
            } label: {
                HStack(spacing: 10) {
                    ZStack {
                        Circle().fill(Palette.questionDot.opacity(0.22)).frame(width: 14, height: 14)
                        Circle().fill(Palette.questionDot).frame(width: 8, height: 8)
                    }
                    .frame(width: 16, height: 16)
                    Text(line.summary)
                        .noteFont()
                        .foregroundStyle(Palette.noteInk)
                        .lineLimit(1)
                        .frame(maxWidth: .infinity, alignment: .leading)
                    Text(line.go)
                        .noteFont(.semibold)
                        .foregroundStyle(Palette.askGo)
                }
                .padding(.horizontal, 14)
                .frame(minHeight: 44)
                .background(Palette.noteFill, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
                .contentShape(RoundedRectangle(cornerRadius: 16, style: .continuous))
            }
            .buttonStyle(PressScaleStyle())
            .accessibilityLabel(Text(line.summary + "，" + line.go.replacingOccurrences(of: " ›", with: "")))
        }
    }
}
