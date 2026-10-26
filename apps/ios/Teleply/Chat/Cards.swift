import SwiftUI
import TeleplyModel

/*
 * Cards of the timeline that are not plain messages, as the web draws them (remote.html renderPlan, renderNext,
 * renderTask, renderSubagent; codex-ui.js plan; Android CardsUi.kt): Claude's checklist, its next-step box and
 * proposed tasks, a DeepSeek subagent, and a plan Codex made in plan mode. Opaque, like the question cards. In
 * 0.2.0 they only show; their buttons work from 0.4.0 (plan phase 3).
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
/// buttons, the first the main one. An answered box keeps its recap only.
struct NextStepCard: View {
    let message: Message

    var body: some View {
        let details = message.details
        let recap = details["recap"].string()
        let ask = details["ask"].string()
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
                if !actions.isEmpty {
                    CardButtons(labels: actions.map { $0["label"].string() })
                }
            }
        }
    }
}

/// A task Claude proposes in a card of its own (web renderTask): its title and brief (a tap shows all of it), and
/// 开始, 在这里做 and 不要了; an offer asks on the computer only. Once the computer shows the conversation without
/// the card, it has been dealt with there.
struct TaskCard: View {
    let message: Message
    let raw: JSONValue
    @State private var full = false

    var body: some View {
        let details = message.details
        let title = details["title"].string()
        let brief = details["brief"].string()
        let offer = details["offer"].bool()
        let tasks = raw["tasks"]
        let settled = raw["on_screen"].bool() && !tasks.isNull && !tasks.array.contains { $0.string() == title }
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
            } else if settled {
                CardNote(text: "电脑上已经处理过了：开始了、在这里做了，或者关掉了。", color: Palette.muted)
            } else {
                CardButtons(labels: ["开始", "在这里做", "不要了"])
            }
        }
    }
}

/// A card's buttons as they will be, the first the main one; they work from 0.4.0 (plan phase 3).
private struct CardButtons: View {
    let labels: [String]

    var body: some View {
        ViewThatFits(in: .horizontal) {
            HStack(spacing: 8) { buttons }
            VStack(alignment: .leading, spacing: 8) { buttons }
        }
        .padding(.top, 12)
        .disabled(true)
        .accessibilityHint(Text("在手机上操作要等 0.4.0，现在请在电脑上处理"))
    }

    private var buttons: some View {
        ForEach(Array(labels.enumerated()), id: \.offset) { index, label in
            Button(label) {}
                .buttonStyle(PillStyle(kind: index == 0 ? .primary : .secondary, minHeight: 40))
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
    return message.id == id || message.details["source_id"].string() == id ? plan : nil
}

/// A plan Codex made in plan mode (web codex-ui.js renderCard plan): 计划 · 待确认 with a preview, 展开完整计划,
/// then 执行计划 and 继续修改. An older plan folds into 历史计划.
struct CodexPlanCard: View {
    let plan: JSONValue
    @State private var open = false
    @State private var full = false
    @Environment(\.colorScheme) private var scheme

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
            VStack(alignment: .leading, spacing: 10) {
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
                    Button("执行计划") {}
                        .buttonStyle(PillStyle(kind: .primary))
                        .frame(maxWidth: .infinity)
                    Button("继续修改") {}
                        .buttonStyle(PillStyle())
                        .frame(maxWidth: .infinity)
                }
                .disabled(true)
                .accessibilityHint(Text("在手机上操作要等 0.4.0，现在请在电脑上处理"))
            }
            .padding(16)
            .background(Palette.sheet, in: RoundedRectangle(cornerRadius: 20, style: .continuous))
            .overlay(RoundedRectangle(cornerRadius: 20, style: .continuous).stroke(scheme == .dark ? Palette.controlBorder : Palette.line, lineWidth: 1))
            .shadow(color: Palette.ink.opacity(scheme == .dark ? 0 : 0.025), radius: 6, y: 2)
            .padding(.top, 16)
        }
    }
}
