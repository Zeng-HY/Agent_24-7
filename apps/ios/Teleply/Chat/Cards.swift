import SwiftUI
import TeleplyModel
import TeleplyState

/*
 * Cards of the timeline that are not plain messages, as the web draws them (remote.html renderPlan, renderNext,
 * renderTask, renderSubagent; codex-ui.js plan; Android CardsUi.kt): Claude's checklist, its next-step box and
 * proposed tasks, a DeepSeek subagent, and a plan Codex made in plan mode. Opaque, like the question cards. A button
 * presses the same one on the computer, one at a time; the computer refuses a press that comes too late.
 */

/// The web's .plan-card / .next-card / .task-card: 16 pt corners, a thin edge, the card colour.
struct TimelineCard<Content: View>: View {
    @ViewBuilder let content: () -> Content
    @Environment(\.colorScheme) private var scheme

    var body: some View {
        VStack(alignment: .leading, spacing: 0, content: content)
            .padding(.horizontal, 16)
            .padding(.vertical, 14)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(Palette.sheet, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
            .overlay(RoundedRectangle(cornerRadius: 16, style: .continuous).stroke(scheme == .dark ? Palette.controlBorder : Palette.line, lineWidth: 1))
            .padding(.top, 16)
    }
}

/// Claude's checklist (update_plan / TodoWrite): 进度 done / all, a ring per step, filled for the one under way,
/// ticked when done.
struct ChecklistCard: View {
    let message: Message

    var body: some View {
        let items = message.details["items"].array
        if !items.isEmpty {
            let done = items.filter { $0["status"].string() == "completed" }.count
            TimelineCard {
                Text("进度 \(done) / \(items.count)")
                    .captionFont()
                    .foregroundStyle(Palette.muted)
                    .padding(.bottom, 4)
                ForEach(Array(items.enumerated()), id: \.offset) { _, item in
                    let status = item["status"].string()
                    HStack(alignment: .top, spacing: 10) {
                        StepMark(status: status)
                            .padding(.top, 3)
                        Text(item["text"].string())
                            .smallBodyFont(status == "in_progress" ? .semibold : .regular)
                            .foregroundStyle(status == "completed" ? Palette.muted : Palette.ink)
                            .frame(maxWidth: .infinity, alignment: .leading)
                    }
                    .padding(.vertical, 5)
                }
            }
            .accessibilityElement(children: .ignore)
            .accessibilityLabel(Text("计划进度 \(done) / \(items.count)：" + items.map { $0["text"].string() + "，" + stepState($0["status"].string()) }.joined(separator: "；")))
        }
    }

    private func stepState(_ status: String) -> String {
        switch status {
        case "completed": return "已完成"
        case "in_progress": return "进行中"
        default: return "待做"
        }
    }
}

/// 16 pt: a dashed ring to do, a ring with a dot under way, a green disc with a tick done (web .plan-mark).
private struct StepMark: View {
    let status: String
    @Environment(\.colorScheme) private var scheme

    var body: some View {
        ZStack {
            switch status {
            case "completed":
                Circle().fill(Palette.success)
                Path { path in
                    path.move(to: CGPoint(x: 16 * 0.30, y: 16 * 0.52))
                    path.addLine(to: CGPoint(x: 16 * 0.45, y: 16 * 0.67))
                    path.addLine(to: CGPoint(x: 16 * 0.72, y: 16 * 0.36))
                }
                .stroke(.white, style: StrokeStyle(lineWidth: 1.8, lineCap: .round, lineJoin: .round))
            case "in_progress":
                Circle().inset(by: 0.75).stroke(Palette.accent, lineWidth: 1.5)
                Circle().inset(by: 3).fill(Palette.accent)
            default:
                Circle().inset(by: 0.75)
                    .stroke(scheme == .dark ? Palette.controlBorder : Color(red: 0xB4 / 255, green: 0xBC / 255, blue: 0xCB / 255),
                            style: StrokeStyle(lineWidth: 1.5, dash: [2.5, 2]))
            }
        }
        .frame(width: 16, height: 16)
        .accessibilityHidden(true)
    }
}

/// Claude's next-step box (its wrap_up, web renderNext): the recap, and while it waits on you its question and
/// buttons, the first the main one. A button presses the same one on the computer; done, the buttons give way to
/// what was done. An answered box keeps its recap only.
struct NextStepCard: View {
    let message: Message
    let model: AppModel

    var body: some View {
        let details = message.details
        let recap = details["recap"].string()
        let ask = details["ask"].string()
        let toolID = details["tool_id"].string()
        let status = model.workspace.cards["next:" + toolID] ?? ""
        if !details["open"].bool() {
            if !recap.isEmpty {
                Text(recap)
                    .scaledFont(14, relativeTo: .subheadline, lineHeight: 1.65)
                    .foregroundStyle(Palette.muted)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(.top, 12)
            }
        } else {
            TimelineCard {
                if !recap.isEmpty {
                    Text(recap)
                        .scaledFont(14, relativeTo: .subheadline, lineHeight: 1.65)
                        .foregroundStyle(Palette.muted)
                }
                if !ask.isEmpty {
                    Text(ask)
                        .scaledFont(15, .semibold, relativeTo: .callout, lineHeight: 1.6)
                        .foregroundStyle(Palette.ink)
                        .padding(.top, recap.isEmpty ? 0 : 10)
                        .accessibilityAddTraits(.isHeader)
                }
                let actions = details["actions"].array
                if status.hasPrefix("done:") {
                    CardNote(text: String(status.dropFirst(5)), color: Palette.accent)
                } else if !actions.isEmpty {
                    CardButtons(labels: actions.map { $0["label"].string() }, status: status, pressing: model.workspace.pressing) { index, label in
                        model.workspace.claudeButton(card: "next:" + toolID, route: "claude/next",
                                                     body: ["tool_id": .string(toolID), "index": .number(Double(index)), "label": .string(label)], label: label)
                    }
                    if status.hasPrefix("error:") { CardNote(text: String(status.dropFirst(6)), color: Palette.danger) }
                }
            }
        }
    }
}

/// A task Claude proposes in a card of its own (web renderTask): its title and brief (a tap shows all of it); 开始,
/// 在这里做 and 不要了 press the card's buttons on the computer (不要了 asks first). An offer asks on the computer only.
/// Once the computer shows the conversation without the card, it has been dealt with there and the buttons go.
struct TaskCard: View {
    let message: Message
    let raw: JSONValue
    let model: AppModel
    @State private var full = false
    @State private var dismissing = false

    var body: some View {
        let details = message.details
        let title = details["title"].string()
        let brief = details["brief"].string()
        let offer = details["offer"].bool()
        let tasks = raw["tasks"]
        let settled = raw["on_screen"].bool() && !tasks.isNull && !tasks.array.contains { $0.string() == title }
        let status = model.workspace.cards["task:" + title] ?? ""
        TimelineCard {
            Text(offer ? "Claude 问要不要新开一个对话" : "Claude 提议新开一个任务")
                .captionFont()
                .foregroundStyle(Palette.muted)
                .padding(.bottom, 6)
            Text(title)
                .scaledFont(15, .semibold, relativeTo: .callout, lineHeight: 1.6)
                .foregroundStyle(Palette.ink)
                .accessibilityAddTraits(.isHeader)
            if !brief.isEmpty {
                Button {
                    full.toggle()
                } label: {
                    Text(brief)
                        .scaledFont(13, relativeTo: .footnote, lineHeight: 1.6)
                        .foregroundStyle(Palette.muted)
                        .lineLimit(full ? nil : 3)
                        .multilineTextAlignment(.leading)
                        .frame(maxWidth: .infinity, alignment: .leading)
                }
                .buttonStyle(.plain)
                .padding(.top, 6)
                .accessibilityValue(Text(full ? "已展开" : "已收起"))
            }
            if offer {
                CardNote(text: "要在电脑上选「New session」或「Do it here」。", color: Palette.muted)
            } else if status.hasPrefix("done:") {
                // What this phone just did there says more than that it was dealt with (开始 adds where it goes).
                CardNote(text: String(status.dropFirst(5)), color: Palette.accent)
            } else if settled {
                CardNote(text: "电脑上已经处理过了：开始了、在这里做了，或者关掉了。", color: Palette.muted)
            } else {
                let kinds = ["start", "here", "dismiss"]
                CardButtons(labels: ["开始", "在这里做", "不要了"], status: status, pressing: model.workspace.pressing) { index, label in
                    if kinds[index] == "dismiss" {
                        dismissing = true
                    } else {
                        model.workspace.claudeButton(card: "task:" + title, route: "claude/task", body: ["title": .string(title), "button": .string(kinds[index])], label: label)
                    }
                }
                if status.hasPrefix("error:") { CardNote(text: String(status.dropFirst(6)), color: Palette.danger) }
            }
        }
        .alert("不要这个任务了？", isPresented: $dismissing) {
            Button("留着", role: .cancel) {}
            Button("不要了", role: .destructive) {
                model.workspace.claudeButton(card: "task:" + title, route: "claude/task", body: ["title": .string(title), "button": "dismiss"], label: "不要了")
            }
        } message: {
            Text("电脑上的这张卡片也会关掉，任务不会开始。")
        }
    }
}

/// A card's buttons, the first the main one; the one being pressed says so (开始…). One press at a time.
private struct CardButtons: View {
    let labels: [String]
    let status: String
    let pressing: Bool
    let press: (Int, String) -> Void

    var body: some View {
        ViewThatFits(in: .horizontal) {
            HStack(spacing: 8) { buttons }
            VStack(alignment: .leading, spacing: 8) { buttons }
        }
        .padding(.top, 12)
        .disabled(pressing)
    }

    private var buttons: some View {
        ForEach(Array(labels.enumerated()), id: \.offset) { index, label in
            Button(status == "pressing:" + label ? label + "…" : label) { press(index, label) }
                .buttonStyle(PillStyle(kind: index == 0 ? .primary : .secondary, minHeight: 40))
                .accessibilityLabel(Text("在电脑上点「\(label)」"))
        }
    }
}

private struct CardNote: View {
    let text: String
    let color: Color

    var body: some View {
        Text(text)
            .noteFont()
            .foregroundStyle(color)
            .padding(.top, 10)
            .task(id: text) { AccessibilityNotification.Announcement(text).post() }
    }
}

/// A subagent this conversation opened (web renderSubagent): it only reports, it does not open.
struct SubagentCard: View {
    let message: Message
    @Environment(\.colorScheme) private var scheme

    var body: some View {
        let details = message.details
        let running = details["status"].string() == "running"
        let done = details["status"].string() == "done"
        let label = details["label"].string().isEmpty ? details["child"].string() : details["label"].string()
        HStack(spacing: 8) {
            Circle().fill(running ? Palette.accent : Palette.muted).frame(width: 8, height: 8)
            Text("子智能体 · " + label)
                .scaledFont(14, relativeTo: .subheadline)
                .foregroundStyle(Palette.ink)
                .frame(maxWidth: .infinity, alignment: .leading)
            if running || done {
                Text(running ? "运行中" : "已完成")
                    .captionFont()
                    .foregroundStyle(Palette.muted)
            }
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 10)
        .background(running ? Palette.selectedFill : Palette.panel, in: RoundedRectangle(cornerRadius: 14, style: .continuous))
        .overlay {
            RoundedRectangle(cornerRadius: 14, style: .continuous)
                .inset(by: 0.5)
                .stroke(running ? Palette.accent.opacity(0.35) : (scheme == .dark ? Palette.controlBorder : Palette.line),
                        style: StrokeStyle(lineWidth: 1, dash: [4, 3]))
        }
        .padding(.top, 12)
        .accessibilityElement(children: .combine)
    }
}

/// "来自其他对话" above a message forwarded from another conversation (web .message-origin).
struct OriginLabel: View {
    let message: Message

    var body: some View {
        if message.details["origin"].string() == "other_chat" {
            Text("来自其他对话")
                .captionFont()
                .foregroundStyle(Palette.muted)
                .padding(.bottom, 4)
        }
    }
}

/// The plan Codex keeps in its state, when [message] is the plan's own record.
func codexPlan(_ raw: JSONValue, for message: Message) -> JSONValue? {
    let plan = raw["plan"]
    guard plan.isObject else { return nil }
    let id = plan["id"].string()
    guard !id.isEmpty, !plan["text"].string().isEmpty else { return nil }
    // Not `c ? plan : nil`: that nil is JSONValue.null, which made every message of the conversation a plan card.
    guard message.id == id || message.details["source_id"].string() == id else { return nil }
    return plan
}

/// A plan Codex made in plan mode (web codex-ui.js renderCard plan): 计划 · 待确认 with a preview, 展开完整计划;
/// 执行计划 carries it out in normal mode, 继续修改 keeps plan mode and puts the cursor in the box. An older plan
/// folds into 历史计划.
struct CodexPlanCard: View {
    let plan: JSONValue
    let model: AppModel
    @State private var open = false
    @State private var full = false

    var body: some View {
        if !plan["ready"].bool() {
            VStack(alignment: .leading, spacing: 0) {
                Button {
                    withAnimation(.easeOut(duration: 0.2)) { open.toggle() }
                } label: {
                    HStack(spacing: 6) {
                        Image(systemName: "chevron.right")
                            .font(.system(size: 12, weight: .semibold))
                            .rotationEffect(.degrees(open ? 90 : 0))
                        Text("历史计划")
                            .processFont()
                    }
                    .foregroundStyle(Palette.muted)
                    .frame(minHeight: 36)
                    .padding(.trailing, 8)
                }
                .buttonStyle(.plain)
                .accessibilityValue(Text(open ? "已展开" : "已收起"))
                if open {
                    MarkdownView(source: plan["text"].string())
                        .padding(.top, 8)
                }
            }
            .padding(.top, 16)
        } else {
            let chat = model.conversation
            QuestionCard {
                HStack(spacing: 8) {
                    Text("计划")
                        .headingFont()
                        .foregroundStyle(Palette.ink)
                        .accessibilityAddTraits(.isHeader)
                    Text("待确认")
                        .captionFont(.medium)
                        .foregroundStyle(Palette.selectedInk)
                        .padding(.horizontal, 8)
                        .padding(.vertical, 2)
                        .background(Palette.selectedFill, in: RoundedRectangle(cornerRadius: 6, style: .continuous))
                }
                MarkdownView(source: plan["text"].string())
                    .frame(maxHeight: full ? nil : 260, alignment: .top)
                    .clipped()
                Button(full ? "收起计划" : "展开完整计划") { full.toggle() }
                    .buttonStyle(PillStyle(kind: .text, minHeight: 36))
                HStack(spacing: 8) {
                    Button("执行计划") { chat.executePlan(plan["id"].string()) }
                        .buttonStyle(PillStyle(kind: .primary, wide: true))
                        .disabled(chat.submitting || !chat.control.available || chat.control.running)
                    Button("继续修改") {
                        let current = chat.control.raw["settings"].isObject ? chat.control.raw["settings"] : [:]
                        let bound = model.workspace.saved["settings"]
                        var settings = (bound.isObject ? bound : current).object
                        settings["mode"] = "plan"
                        model.workspace.selectSettings(.object(settings), expected: current)
                        chat.focusInput(hint: "写下需要调整的地方…")
                    }
                    .buttonStyle(PillStyle(wide: true))
                    .disabled(chat.submitting)
                }
            }
            .padding(.top, 16)
        }
    }
}
