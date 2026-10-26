import SwiftUI
import TeleplyModel
import TeleplyState

/// One row above the list per first message under way and not on screen (web #newJobDock): its source, where it
/// stands and its first words. A tap opens its page, its conversation once made, or its sheet when something went
/// wrong.
struct NewJobDock: View {
    let model: AppModel

    var body: some View {
        let jobs = model.dockJobs
        if !jobs.isEmpty {
            VStack(spacing: 8) {
                ForEach(jobs) { job in
                    Button {
                        model.openJob(job)
                    } label: {
                        Text(newJobDock(job))
                            .noteFont()
                            .foregroundStyle(job.problem ? Palette.danger : Palette.muted)
                            .lineLimit(1)
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .padding(.horizontal, 14)
                            .padding(.vertical, 10)
                            .frame(minHeight: 44)
                            .background(Palette.sheet, in: RoundedRectangle(cornerRadius: 14, style: .continuous))
                            .overlay(RoundedRectangle(cornerRadius: 14, style: .continuous).stroke(Palette.line, lineWidth: 1))
                            .contentShape(RoundedRectangle(cornerRadius: 14, style: .continuous))
                    }
                    .buttonStyle(PressScaleStyle())
                }
            }
            .padding(.bottom, 8)
        }
    }
}

/// A new conversation's first message on its page, the line under it saying where it stands (web renderFirst). A
/// problem's line opens its sheet. Shown also after the page became the conversation, until the record has it.
struct NewFirstMessage: View {
    let text: String
    let status: String
    let problem: Bool
    var open: () -> Void = {}

    var body: some View {
        VStack(alignment: .trailing, spacing: 4) {
            UserBubble(message: Message(id: "new-first", role: "user", text: text.isEmpty ? "请查看这些图片或引用。" : text),
                       actions: MessageActions(select: { _ in }, expand: { _ in }, busy: false))
            if !status.isEmpty {
                Button(action: open) {
                    Text(status)
                        .captionFont()
                        .foregroundStyle(problem ? Palette.danger : Palette.muted)
                        .multilineTextAlignment(.trailing)
                        .padding(.trailing, 4)
                }
                .buttonStyle(.plain)
                .disabled(!problem)
                .accessibilityLabel(Text(problem ? status + "，打开处理" : status))
                .task(id: status) { AccessibilityNotification.Announcement(status).post() }
            }
        }
        .frame(maxWidth: .infinity, alignment: .trailing)
        .padding(.top, 20)
    }
}

/// 新建对话的结果 (web #newJobSheet): where a first message stands and what can be done: 核对结果, 继续发送 (the same
/// request, made once), 打开对话, 恢复草稿 (only one that did not go out), 移除 (the phone stops following it).
struct NewJobSheet: View {
    let model: AppModel
    let request: String
    @State private var removing = false
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        let job = model.jobs.current(request)
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 12) {
                    if let job {
                        let place = job.projectless ? "无项目" : (job.label.isEmpty ? lastPart(job.folder) : job.label)
                        let words = oneLine(job.text, limit: 40)
                        Text([Labels.sourceName(job.app), place, words.isEmpty ? "只有图片或引用" : words].filter { !$0.isEmpty }.joined(separator: " · "))
                            .noteFont()
                            .foregroundStyle(Palette.muted)
                        Text(newJobProgress(job))
                            .bodyFont()
                            .foregroundStyle(Palette.ink)
                            .task(id: newJobProgress(job)) { AccessibilityNotification.Announcement(newJobProgress(job)).post() }
                        ViewThatFits(in: .horizontal) {
                            HStack(spacing: 8) { actions(job) }
                            VStack(alignment: .leading, spacing: 8) { actions(job) }
                        }
                    } else {
                        Text("这一条已经处理过了。")
                            .bodyFont()
                            .foregroundStyle(Palette.ink)
                    }
                }
                .padding(.horizontal, 20)
                .padding(.vertical, 12)
                .frame(maxWidth: .infinity, alignment: .leading)
            }
            .navigationTitle("新建对话的结果")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button(role: .close) { dismiss() }
                }
            }
        }
        .presentationDetents([.medium, .large])
        .presentationBackground(Palette.sheet)
        .alert("移除这一条？", isPresented: $removing) {
            Button("取消", role: .cancel) {}
            Button("移除", role: .destructive) { if let job { model.removeJob(job) } }
        } message: {
            Text(removeNote(job))
        }
    }

    @ViewBuilder
    private func actions(_ job: NewJob) -> some View {
        if job.state != "accepted" {
            Button("核对结果") { model.checkJob(job) }
                .buttonStyle(PillStyle())
        }
        if job.retryable {
            Button("继续发送") { model.retryJob(job) }
                .buttonStyle(PillStyle(kind: .primary))
        }
        if !job.createdID.isEmpty {
            Button("打开对话") { model.openJobChat(job) }
                .buttonStyle(PillStyle())
        }
        if job.state == "failed" {
            Button("恢复草稿") { model.restoreJob(job) }
                .buttonStyle(PillStyle())
        }
        Button("移除") { removing = true }
            .buttonStyle(PillStyle(kind: .text))
    }

    private func removeNote(_ job: NewJob?) -> String {
        switch job?.state {
        case "failed": return "这条首条消息没发出去。移除后手机上不再留着它的内容。"
        case "accepted": return "对话已经建好，在对话列表里能找到。移除的只是这条提示。"
        default: return "移除只是手机不再跟踪这一条，不会重复发送。电脑上如果已经建好对话，会照常出现在对话列表里。"
        }
    }

    private func lastPart(_ path: String) -> String {
        path.split(whereSeparator: { $0 == "/" || $0 == "\\" }).last.map(String.init) ?? path
    }
}
