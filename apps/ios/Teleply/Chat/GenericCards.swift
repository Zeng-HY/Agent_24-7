import SwiftUI
import TeleplyModel
import TeleplyState

/// A new assistant's own approval or question card (docs §五; handoff 3.4; web static/generic-ui.js). The layout is
/// `generic.v1`: the title, the detail and the questions all come from the control state, the answer goes to
/// `POST /api/agents/<id>/answer`. Whether it can be answered now comes from the state's `capabilities_now` (the
/// manifest's capabilities are only the default); a card with `expires_at` 0 waits as long as the computer does, so
/// nothing here counts down or folds away on its own.
struct GenericQuestionCard: View {
    let model: AppModel
    let card: JSONValue
    @State private var expanded = false

    var body: some View {
        let app = model.conversation.key?.app ?? model.app
        let caps = model.capabilities(app)
        let approval = card["kind"].string() == "approval"
        let questions = card["questions"].array
        let identity = "generic-answers:" + card["id"].string() + ":" + card["answer_revision"].string()
        let answers = model.workspace.saved[identity]
        let blocked = blockedReason(caps: caps, approval: approval)
        let busy = model.workspace.busy
        // One question, one choice and no words of one's own: a tap on an option answers at once (the web's direct).
        let direct = !approval && questions.count == 1
            && !questions[0]["isMultiple"].bool() && !questions[0]["isOther"].bool() && !questions[0]["isSecret"].bool()
        QuestionCard {
            CardTitle(text: genericCardTitle(card, app: app), tag: approval ? "批准" : "")
            detail
            if approval {
                approvalChoices(questions.first ?? [:], answers: answers, identity: identity, blocked: blocked, busy: busy)
            } else {
                ForEach(Array(questions.enumerated()), id: \.offset) { _, question in
                    GenericQuestion(question: question, answers: answers, enabled: !busy && blocked.isEmpty,
                                    direct: direct) { next in
                        model.workspace.edit(identity, next)
                    } submit: { next in
                        submit(app: app, answers: next, blocked: blocked)
                    }
                }
                if !direct {
                    Button(busy ? "提交中…" : "提交") {
                        submit(app: app, answers: answers.isObject ? answers : [:], blocked: blocked)
                    }
                    .buttonStyle(PillStyle(kind: .primary, wide: true))
                    .disabled(busy || !blocked.isEmpty || !allAnswered(questions, answers))
                }
            }
            if !blocked.isEmpty {
                Text(blocked)
                    .noteFont()
                    .foregroundStyle(Palette.muted)
            }
            if let error = model.workspace.error {
                Text(error)
                    .noteFont()
                    .foregroundStyle(Palette.danger)
            }
        }
    }

    /// The command or the files the card is about: monospaced, the first 12 lines, the rest behind 展开全部.
    @ViewBuilder
    private var detail: some View {
        let text = card["detail"].string()
        if !text.isEmpty {
            let lines = text.components(separatedBy: "\n")
            let shown = expanded ? lines : Array(lines.prefix(12))
            Text(shown.joined(separator: "\n"))
                .codeFont()
                .foregroundStyle(Palette.ink)
                .textSelection(.enabled)
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(10)
                .background(Palette.panel, in: RoundedRectangle(cornerRadius: 10, style: .continuous))
            if lines.count > 12 {
                Button(expanded ? "收起" : "展开全部 \(lines.count) 行") { expanded.toggle() }
                    .buttonStyle(PillStyle(kind: .text, minHeight: 36))
            }
        }
    }

    /// A批准 card's choices: one tap sends it, as the desktop's own card does.
    @ViewBuilder
    private func approvalChoices(_ question: JSONValue, answers: JSONValue, identity: String, blocked: String, busy: Bool) -> some View {
        let id = question["id"].string()
        let selected = answers[id].array.map { $0.string() }
        Text(question["question"].string())
            .scaledFont(15, .medium, relativeTo: .callout, lineHeight: 1.6)
            .foregroundStyle(Palette.ink)
        ForEach(Array(question["options"].array.enumerated()), id: \.offset) { _, option in
            let label = option["label"].string()
            OptionCard(title: label, detail: option["description"].string(),
                       selected: selected.contains(label), enabled: !busy && blocked.isEmpty) {
                var next = answers.object
                next[id] = .array([.string(label)])
                model.workspace.edit(identity, .object(next))
                submit(app: model.conversation.key?.app ?? model.app, answers: .object(next), blocked: blocked)
            }
        }
    }

    /// Why this card cannot be answered now: the state's own reason for the missing capability, or 已过时.
    private func blockedReason(caps: AgentCapabilities, approval: Bool) -> String {
        let capability = approval ? "approve" : "answer"
        if caps.flag(capability) != true {
            let note = model.capabilityNote(capability)
            return note.isEmpty ? "请在电脑上处理" : note
        }
        let expires = card["expires_at"].int64()
        if expires > 0, Int64(Date().timeIntervalSince1970 * 1000) > expires { return "已过时，请在电脑上处理" }
        return ""
    }

    /// Every question has an answer: a chosen option, or words of one's own.
    private func allAnswered(_ questions: [JSONValue], _ answers: JSONValue) -> Bool {
        questions.allSatisfy { question in
            let given = answers[question["id"].string()].array.map { $0.string().trimmingCharacters(in: .whitespacesAndNewlines) }
            return given.contains { !$0.isEmpty }
        }
    }

    /// POST /api/agents/<id>/answer (handoff 3.4): the card's id, this request's id and every question's answer;
    /// nothing is cleared on failure, so the choices stay for another try.
    private func submit(app: String, answers: JSONValue, blocked: String) {
        guard blocked.isEmpty, !model.workspace.busy else { return }
        var body: [String: JSONValue] = ["question_id": card["id"], "answers": answers.isObject ? answers : [:]]
        let revision = card["answer_revision"].string()
        if !revision.isEmpty { body["answer_revision"] = .string(revision) }
        model.workspace.action("generic/answer", .object(body))
    }
}

/// One question of a generic card: its header and words, the options (single or several), and a field for one's own
/// answer when the computer allows it (`isOther`) or when it must not be shown (`isSecret`).
private struct GenericQuestion: View {
    let question: JSONValue
    let answers: JSONValue
    let enabled: Bool
    let direct: Bool
    let change: (JSONValue) -> Void
    let submit: (JSONValue) -> Void

    var body: some View {
        let id = question["id"].string()
        let options = question["options"].array
        let labels = options.map { $0["label"].string() }
        let multiple = question["isMultiple"].bool()
        let selected = answers[id].array.map { $0.string() }
        let typed = selected.filter { !labels.contains($0) }.joined(separator: "\n")
        let header = question["header"].string()
        if !header.isEmpty, header != question["question"].string() {
            Text(header)
                .noteFont()
                .foregroundStyle(Palette.muted)
        }
        Text(question["question"].string())
            .scaledFont(15, .medium, relativeTo: .callout, lineHeight: 1.6)
            .foregroundStyle(Palette.ink)
        ForEach(Array(options.enumerated()), id: \.offset) { _, option in
            let label = option["label"].string()
            OptionCard(title: label, detail: option["description"].string(), selected: selected.contains(label),
                       enabled: enabled, multiple: multiple) {
                if direct {
                    update(id, [label])
                    submit(updated(id, [label]))
                    return
                }
                let next = multiple ? (selected.contains(label) ? selected.filter { $0 != label } : selected + [label]) : [label]
                update(id, next)
            }
        }
        if question["isOther"].bool() || question["isSecret"].bool() {
            ownAnswer(id: id, typed: typed, secret: question["isSecret"].bool(), labels: labels, multiple: multiple, selected: selected)
        } else if options.isEmpty, !direct {
            Text("这一题没有可选的答案，请在电脑上回答。")
                .noteFont()
                .foregroundStyle(Palette.muted)
        }
    }

    @ViewBuilder
    private func ownAnswer(id: String, typed: String, secret: Bool, labels: [String], multiple: Bool, selected: [String]) -> some View {
        let binding = Binding<String>(
            get: { typed },
            set: { text in
                // Writing words replaces a single choice and goes beside several (the web's answerOf).
                let kept = multiple ? selected.filter { labels.contains($0) } : []
                let words = text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ? [] : [text]
                update(id, kept + words)
            })
        Group {
            if secret {
                SecureField("", text: binding, prompt: Text("写下答案（只用于这一次提交）").foregroundStyle(Palette.muted))
            } else {
                TextField("", text: binding, prompt: Text("也可以自己填写").foregroundStyle(Palette.muted), axis: .vertical)
                    .lineLimit(1...4)
            }
        }
        .fieldBox(multiline: !secret)
        .disabled(!enabled)
        .accessibilityLabel(Text("自己填写：" + question["question"].string()))
    }

    private func updated(_ id: String, _ values: [String]) -> JSONValue {
        var next = answers.object
        next[id] = .array(values.map(JSONValue.string))
        return .object(next)
    }

    private func update(_ id: String, _ values: [String]) {
        change(updated(id, values))
    }
}
