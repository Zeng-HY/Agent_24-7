import QuickLook
import SwiftUI
import TeleplyModel
import TeleplyState
import UIKit

/// A run of process steps that folds under its first step's header (design language §8; Android TimelineItem).
struct ProcessGroup: Equatable {
    let key: String
    let steps: Int
    /// The run is the current turn's and the source is working on it: it starts open.
    let live: Bool
    /// The run ends in a question or approval waiting for an answer.
    let waiting: Bool
}

/// What a message is in the timeline, in the order Android decides it.
enum TimelineRole {
    case user
    case checklist
    case next
    case task
    case subagent
    case codexPlan(JSONValue)
    case process(ProcessGroup, first: Bool)
    case question(approval: Bool)
    case event
    case answer(afterUser: Bool)
}

/// Process steps: tool records, and commentary or thinking that is not a question or an approval.
func isProcess(_ message: Message) -> Bool {
    message.role == "tool" || message.role == "assistant" && ["commentary", "thinking"].contains(message.phase)
        && !message.kind.contains("question") && !message.kind.contains("approval")
}

/// Every message's role, computed once per change of the page (a long conversation has hundreds).
func timelineRoles(_ messages: [Message], app: String, raw: JSONValue, running: Bool, asking: Bool) -> [TimelineRole] {
    let count = messages.count
    var runOf = [Int: (start: Int, end: Int)]()
    var start = 0
    while start < count {
        guard isProcess(messages[start]) else {
            start += 1
            continue
        }
        var end = start
        while end + 1 < count, isProcess(messages[end + 1]) { end += 1 }
        for index in start...end { runOf[index] = (start, end) }
        start = end + 1
    }
    let lastUser = messages.lastIndex { $0.role == "user" } ?? -1
    return messages.enumerated().map { index, message in
        switch message.role {
        case "user": return .user
        case "plan": return .checklist
        case "next": return .next
        case "task": return .task
        case "subagent": return .subagent
        default: break
        }
        if app == "codex", let plan = codexPlan(raw, for: message) { return .codexPlan(plan) }
        if let run = runOf[index] {
            let last = run.start > lastUser && messages[(run.end + 1)...].allSatisfy { isProcess($0) || $0.role == "event" }
            let group = ProcessGroup(key: messages[run.start].id, steps: run.end - run.start + 1, live: running && last, waiting: asking && last)
            return .process(group, first: index == run.start)
        }
        if message.kind.contains("question") || message.kind.contains("approval") { return .question(approval: message.kind.contains("approval")) }
        if message.role == "event" { return .event }
        return .answer(afterUser: index > 0 && messages[index - 1].role == "user")
    }
}

/// What a message's long press and buttons can do on the page.
struct MessageActions {
    var select: (Message) -> Void
    var expand: (Message) -> Void
    /// 本轮差异 of a step that changed files: the diff page by its reference.
    var diff: (String) -> Void = { _ in }
    /// 查看成果文件 under a DeepSeek deliverables message: 对话文件 for that message, by its id.
    var files: (String) -> Void = { _ in }
    /// 打开新建对话 under a Codex reply that made a conversation: that conversation, by its id.
    var thread: (String) -> Void = { _ in }
    /// A picture sent with a message: its small copy, or the whole one (true), as a file on this phone.
    var picture: (SentPicture, Bool) async -> URL? = { _, _ in nil }
    /// A message's whole words, read from the computer first when the page cut it short (复制 · 选择文字 · 分享).
    var whole: (Message, @escaping (Message) -> Void) -> Void = { message, use in use(message) }
    /// 分享 of words read just now: the system share sheet.
    var share: (String) -> Void = { _ in }
    var busy: Bool
}

/// One message in the timeline (spec 4.3; Android TimelineItem).
struct TimelineItem: View {
    let model: AppModel
    let message: Message
    let role: TimelineRole
    let raw: JSONValue
    /// The label of the send from this phone that became this message (已送达…), shown under the bubble.
    var receipt: String?
    /// Pictures sent with a user message, as the computer kept them.
    var pictures: [SentPicture] = []
    @Binding var folds: [String: Bool]
    let actions: MessageActions

    var body: some View {
        switch role {
        case .user:
            VStack(alignment: .trailing, spacing: 0) {
                OriginLabel(message: message)
                    .padding(.trailing, 4)
                UserBubble(message: message, actions: actions, receipt: receipt, pictures: pictures)
            }
            .frame(maxWidth: .infinity, alignment: .trailing)
            .padding(.top, 20)
        case .checklist:
            ChecklistCard(message: message)
        case .next:
            NextStepCard(message: message, model: model)
        case .task:
            TaskCard(message: message, raw: raw, model: model)
        case .subagent:
            SubagentCard(message: message)
        case .codexPlan(let plan):
            CodexPlanCard(plan: plan, model: model)
        case .process(let group, let first):
            let open = folds[group.key] ?? group.live
            VStack(alignment: .leading, spacing: 0) {
                if first {
                    ProcessHeader(group: group, open: open) {
                        withAnimation(.easeOut(duration: 0.2)) { folds[group.key] = !open }
                    }
                }
                if open {
                    HStack(spacing: 0) {
                        Rectangle().fill(Palette.line).frame(width: 3)
                            .padding(.leading, 7)
                        ProcessStep(message: message, diff: actions.diff)
                            .padding(.leading, 12)
                            .padding(.vertical, 4)
                    }
                    .fixedSize(horizontal: false, vertical: true)
                    .transition(.opacity)
                }
            }
            .padding(.top, first ? 16 : 0)
        case .question(let approval):
            VStack(alignment: .leading, spacing: 4) {
                Text(approval ? "批准请求" : "问题")
                    .captionFont(.medium)
                    .foregroundStyle(Palette.askGo)
                MarkdownView(source: message.text)
            }
            .padding(.top, 16)
        case .event:
            Text(message.text)
                .captionFont()
                .foregroundStyle(Palette.muted)
                .multilineTextAlignment(.center)
                .frame(maxWidth: .infinity)
                .padding(.top, 12)
        case .answer(let afterUser):
            AnswerBlock(message: message, actions: actions)
                .padding(.top, afterUser ? 20 : 16)
        }
    }
}

/// The fold's header: a light chevron and "处理过程 · N 步" (正在处理 while live, 需要你回答 while waiting).
private struct ProcessHeader: View {
    let group: ProcessGroup
    let open: Bool
    let toggle: () -> Void

    var body: some View {
        Button(action: toggle) {
            HStack(spacing: 6) {
                Image(systemName: "chevron.right")
                    .font(.system(size: 12, weight: .semibold))
                    .foregroundStyle(Palette.muted)
                    .rotationEffect(.degrees(open ? 90 : 0))
                Text((group.waiting ? "需要你回答" : group.live ? "正在处理" : "处理过程") + " · \(group.steps) 步")
                    .processFont()
                    .foregroundStyle(group.waiting ? Palette.askGo : Palette.muted)
            }
            .frame(minHeight: 36)
            .padding(.trailing, 8)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .accessibilityValue(Text(open ? "已展开" : "已收起"))
    }
}

/// One step: a tool with its mark (✓ done, ◌ running, ∅ nothing found, · otherwise), 失败 when it failed and the
/// files it changed; commentary and thinking as grey text.
private struct ProcessStep: View {
    let message: Message
    let diff: (String) -> Void

    var body: some View {
        if message.role == "tool" {
            VStack(alignment: .leading, spacing: 0) {
                HStack(alignment: .firstTextBaseline, spacing: 8) {
                    let title = message.details["title"].string()
                    Text(mark + " " + (title.isEmpty ? message.text : title))
                        .processFont()
                        .foregroundStyle(Palette.ink.opacity(0.85))
                        .lineLimit(3)
                        .frame(maxWidth: .infinity, alignment: .leading)
                    if message.status == "failed" {
                        Text("失败")
                            .captionFont()
                            .foregroundStyle(Palette.danger)
                    }
                }
                // 本轮差异 opens the diff page; a change without a reference has no record to show (B12).
                ForEach(Array(message.details["changes"].array.enumerated()), id: \.offset) { _, change in
                    let ref = change["ref"].string()
                    Button {
                        diff(ref)
                    } label: {
                        Text("本轮差异：" + change["path"].string())
                            .processFont()
                            .foregroundStyle(ref.isEmpty ? Palette.muted : Palette.accent)
                            .multilineTextAlignment(.leading)
                            .padding(.vertical, 4)
                            .contentShape(Rectangle())
                    }
                    .buttonStyle(.plain)
                    .disabled(ref.isEmpty)
                    .padding(.top, 4)
                }
            }
        } else {
            Text(message.text)
                .processFont()
                .foregroundStyle(Palette.muted)
                .frame(maxWidth: .infinity, alignment: .leading)
        }
    }

    private var mark: String {
        switch message.status {
        case "running": return "◌"
        case "no_matches": return "∅"
        case "completed": return "✓"
        default: return "·"
        }
    }
}

/// The user's message (web .bub.user): accent with white text on light; #1E1E1E with #EEEEEE text and a #333 edge
/// on dark; 20 pt corners, 10 / 16 pt padding, at most 88% wide.
struct UserBubble: View {
    let message: Message
    let actions: MessageActions
    var receipt: String?
    /// Still being sent: shown lighter (Android sending).
    var sending = false
    /// Pictures sent with it, from the computer's copies (web codex-ui.js renderImages).
    var pictures: [SentPicture] = []
    @Environment(\.colorScheme) private var scheme

    var body: some View {
        VStack(alignment: .trailing, spacing: 4) {
            bubble
                .opacity(sending ? 0.6 : 1)
            if let receipt, receipt != removedLabel {
                Text(receipt)
                    .captionFont()
                    .foregroundStyle(receipt == "送达状态待确认" ? Palette.warning : Palette.muted)
                    .padding(.trailing, 4)
            }
        }
        .frame(maxWidth: .infinity, alignment: .trailing)
    }

    private var bubble: some View {
        let dark = scheme == .dark
        // With its pictures shown, their [图片] mark goes from the words.
        let words = pictures.isEmpty ? message.text : picturedWords(message.text) ?? message.text
        return TrailingFraction(fraction: 0.88) {
            VStack(alignment: .leading, spacing: 8) {
                if !words.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                    MarkdownView(source: words,
                                 look: MarkdownLook(link: dark ? Palette.accent : .white, code: dark ? Palette.codeFill : .white.opacity(0.18)),
                                 fill: false)
                        .foregroundStyle(Palette.onBubble)
                        .fixedSize(horizontal: false, vertical: true)
                }
                if !pictures.isEmpty {
                    SentPictureGrid(pictures: pictures, load: actions.picture)
                }
                // A long message the page cut short: 展开全文 inside the bubble (web .bub.user .message-actions).
                if message.truncated {
                    Button { actions.expand(message) } label: {
                        Text(expandLabel(message))
                            .captionFont()
                            .foregroundStyle(Palette.onBubble)
                            .padding(.horizontal, 10)
                            .frame(minHeight: 44)
                            .background(Palette.onBubble.opacity(0.18), in: Capsule())
                            .contentShape(Capsule())
                    }
                    .buttonStyle(.plain)
                    .disabled(actions.busy)
                    .opacity(actions.busy ? 0.35 : 1)
                }
            }
            .padding(.horizontal, 16)
            .padding(.vertical, 10)
            .background(Palette.bubble, in: RoundedRectangle(cornerRadius: 20, style: .continuous))
            .overlay(RoundedRectangle(cornerRadius: 20, style: .continuous).stroke(Palette.bubbleEdge, lineWidth: 1))
            .contentShape(.contextMenuPreview, RoundedRectangle(cornerRadius: 20, style: .continuous))
            .contextMenu { MessageMenu(message: message, actions: actions, shown: { $0 }) }
        }
    }
}

/// Pictures sent with a message, from the computer's copies (web .sent-images): 110 × 100 with 14 pt corners, two to
/// a row; a tap opens the whole picture in Quick Look.
private struct SentPictureGrid: View {
    let pictures: [SentPicture]
    let load: (SentPicture, Bool) async -> URL?
    @State private var looking: URL?

    var body: some View {
        let rows = stride(from: 0, to: pictures.count, by: 2).map { Array(pictures[$0..<min($0 + 2, pictures.count)]) }
        VStack(alignment: .leading, spacing: 8) {
            ForEach(Array(rows.enumerated()), id: \.offset) { _, row in
                HStack(spacing: 8) {
                    ForEach(row) { picture in
                        SentPictureTile(picture: picture, load: load) { looking = $0 }
                    }
                }
            }
        }
        .quickLookPreview($looking)
    }
}

private struct SentPictureTile: View {
    let picture: SentPicture
    let load: (SentPicture, Bool) async -> URL?
    let open: (URL) -> Void
    @State private var image: UIImage?
    @State private var opening = false

    var body: some View {
        Button {
            guard !opening else { return }
            opening = true
            Task {
                if let whole = await load(picture, true) { open(whole) }
                opening = false
            }
        } label: {
            // The picture fills the tile and is cut to it, so it neither grows the tile nor reaches past it.
            Color.clear
                .frame(width: 110, height: 100)
                .overlay {
                    if let image {
                        Image(uiImage: image)
                            .resizable()
                            .scaledToFill()
                    } else {
                        Image(systemName: "photo")
                            .font(.system(size: 20))
                            .foregroundStyle(Palette.onBubble.opacity(0.7))
                    }
                }
                .overlay {
                    if opening {
                        ProgressView()
                            .tint(Palette.onBubble)
                    }
                }
                .background(Palette.onBubble.opacity(0.18))
                .clipShape(RoundedRectangle(cornerRadius: 14, style: .continuous))
                .contentShape(RoundedRectangle(cornerRadius: 14, style: .continuous))
        }
        .buttonStyle(.plain)
        .accessibilityLabel(Text("查看 " + picture.name))
        // Drawn small from the computer's copy, away from the screen.
        .task(id: picture.id) {
            guard image == nil, let small = await load(picture, false) else { return }
            image = await UIImage(contentsOfFile: small.path)?.byPreparingThumbnail(ofSize: CGSize(width: 220, height: 200))
        }
    }
}

/// An answer: open text, no card (web .bub.assistant). Its long-press preview shows only the first lines.
private struct AnswerBlock: View {
    let message: Message
    let actions: MessageActions

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            OriginLabel(message: message)
            MarkdownView(source: message.text)
                .contentShape(Rectangle())
                .contextMenu {
                    // Copied and shared as shown, without Codex's own notes.
                    MessageMenu(message: message, actions: actions, shown: { MarkdownReader.tidy($0) })
                } preview: {
                    MarkdownView(source: message.text)
                        .foregroundStyle(Palette.ink)
                        .padding(16)
                        .frame(width: 320, alignment: .topLeading)
                        .frame(maxHeight: 360, alignment: .top)
                        .clipped()
                        .background(Palette.page)
                }
            // A conversation the reply made (web remote.html renderAssistantText): a button each under the text.
            ForEach(Array(MarkdownReader.createdThreads(message.text).enumerated()), id: \.offset) { _, thread in
                if thread.ready {
                    Button { actions.thread(thread.id) } label: {
                        Label("打开新建对话", systemImage: "bubble.left.and.bubble.right")
                            .buttonFont()
                            .foregroundStyle(Palette.selectedInk)
                            .padding(.horizontal, 14)
                            .frame(minHeight: 44)
                            .background(Palette.selectedFill, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
                    }
                    .buttonStyle(.plain)
                    .disabled(actions.busy)
                    .padding(.top, 12)
                } else {
                    Text("新对话正在准备中")
                        .noteFont()
                        .foregroundStyle(Palette.muted)
                        .padding(.top, 12)
                }
            }
            // The files DeepSeek presented as the turn's result (Android 1.0.2), to open or save.
            if message.kind == "deliverables" {
                Button("查看成果文件", systemImage: "doc.on.doc") { actions.files(message.id) }
                    .buttonStyle(PillStyle(kind: .text))
            }
            if message.truncated {
                Button(expandLabel(message)) { actions.expand(message) }
                    .buttonStyle(PillStyle(kind: .text))
                    .disabled(actions.busy)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

/// 复制 · 选择文字 · 分享 (web message menu, static/reading-ui.js): a message the page cut short is read whole first.
private struct MessageMenu: View {
    let message: Message
    let actions: MessageActions
    /// The words as copied and shared: an answer's without Codex's own notes.
    let shown: (String) -> String

    var body: some View {
        Button("复制", systemImage: "doc.on.doc") {
            actions.whole(message) { UIPasteboard.general.string = shown($0.text) }
        }
        Button("选择文字", systemImage: "selection.pin.in.out") { actions.select(message) }
        if message.truncated {
            Button("分享", systemImage: "square.and.arrow.up") {
                actions.whole(message) { actions.share(shown($0.text)) }
            }
        } else {
            ShareLink(item: shown(message.text)) {
                Label("分享", systemImage: "square.and.arrow.up")
            }
        }
    }
}

/// Places its one view at the trailing edge, at most [fraction] of the offered width (the bubble's 88%).
struct TrailingFraction: Layout {
    let fraction: CGFloat

    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        guard let view = subviews.first else { return .zero }
        let width = proposal.width ?? .infinity
        let limit = width.isFinite ? width * fraction : nil
        let size = view.sizeThatFits(ProposedViewSize(width: limit, height: nil))
        return CGSize(width: width.isFinite ? width : size.width, height: size.height)
    }

    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        guard let view = subviews.first else { return }
        let size = view.sizeThatFits(ProposedViewSize(width: bounds.width * fraction, height: nil))
        view.place(at: CGPoint(x: bounds.maxX - size.width, y: bounds.minY), proposal: ProposedViewSize(size))
    }
}
