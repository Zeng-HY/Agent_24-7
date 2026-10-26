import SwiftUI
import TeleplyModel

/// A row's state colour (Android ChatRow): running green, waiting orange, failed red, unknown amber.
func statusColor(_ status: String) -> Color {
    switch status {
    case "running": return Palette.success
    case "waiting": return Palette.askGo
    case "failed": return Palette.danger
    case "unknown", "": return Palette.warning
    default: return Palette.muted
    }
}

/// Web .conv row (static/reading-ui.js; Android ChatRow): source badge, title, time; state and folder; one line
/// of preview. A group row (未分组的会话) says how many sessions it holds and folds them ([open]); a child found
/// by search says whose it is.
struct ChatRow: View {
    let chat: Chat
    var first = false
    var open: Bool?

    @Environment(\.colorScheme) private var scheme
    @Environment(\.dynamicTypeSize) private var typeSize

    var body: some View {
        // At the largest text sizes the parts take their own lines instead of cutting the title (spec 2.3).
        let large = typeSize.isAccessibilitySize
        let ago = Labels.ago(chat.updated)
        VStack(alignment: .leading, spacing: 0) {
            if !first {
                Rectangle()
                    .fill(scheme == .dark ? Palette.line : Palette.panel)
                    .frame(height: 1)
            }
            VStack(alignment: .leading, spacing: 6) {
                if large {
                    if !chat.app.isEmpty { SourceBadge(app: chat.app) }
                    title.lineLimit(3)
                    if !ago.isEmpty { time(ago) }
                } else {
                    HStack(spacing: 8) {
                        if !chat.app.isEmpty { SourceBadge(app: chat.app) }
                        title
                            .lineLimit(1)
                            .frame(maxWidth: .infinity, alignment: .leading)
                        if !ago.isEmpty { time(ago) }
                    }
                }
                let state = Text(Labels.status(chat.status))
                    .noteFont(chat.status == "running" || chat.status == "waiting" ? .semibold : .regular)
                    .foregroundStyle(statusColor(chat.status))
                if large {
                    state
                    if !detail.isEmpty {
                        Text(String(detail.dropFirst(3)))
                            .noteFont()
                            .foregroundStyle(Palette.muted)
                            .lineLimit(3)
                    }
                } else {
                    HStack(spacing: 0) {
                        state
                            .lineLimit(1)
                            .fixedSize()
                        if !detail.isEmpty {
                            Text(detail)
                                .noteFont()
                                .foregroundStyle(Palette.muted)
                                .lineLimit(1)
                        }
                    }
                }
                if !chat.preview.isEmpty {
                    Text(chat.preview)
                        .smallBodyFont()
                        .foregroundStyle(Palette.muted)
                        .lineLimit(large ? 2 : 1)
                }
            }
            .padding(.horizontal, 4)
            .padding(.vertical, 14)
        }
        .contentShape(Rectangle())
        .accessibilityElement(children: .combine)
        .accessibilityValue(Text(open.map { $0 ? "已展开" : "已收起" } ?? ""))
    }

    private var title: some View {
        Text(chat.title + (open.map { $0 ? " ▾" : " ▸" } ?? ""))
            .bodyFont(.semibold)
            .foregroundStyle(Palette.ink)
    }

    private func time(_ ago: String) -> some View {
        Text(ago)
            .captionFont()
            .foregroundStyle(Palette.muted)
            .lineLimit(1)
    }

    private var detail: String {
        var text: String
        if chat.group {
            text = " · \(chat.childCount) 个" + (chat.childRunning > 0 ? "，\(chat.childRunning) 个运行中" : "")
        } else if chat.kind == "subagent" {
            text = " · 子智能体"
        } else if !chat.folder.isEmpty {
            text = " · " + chat.folder
        } else {
            text = ""
        }
        if !chat.kind.isEmpty {
            text += chat.parentTitle.isEmpty ? " · 未分组" : " · 属于「\(chat.parentTitle)」"
        }
        return text
    }
}

/// 子对话 N 个 · M 个运行中, or 收起子对话 (web .conv-fold): folds a row's children under it.
struct FoldRow: View {
    let open: Bool
    let count: Int
    let running: Int
    let toggle: () -> Void

    var body: some View {
        Button(action: toggle) {
            Text((open ? "▾ 收起子对话" : "▸ 子对话 \(count) 个") + (running > 0 ? " · \(running) 个运行中" : ""))
                .noteFont(.medium)
                .foregroundStyle(Palette.accent)
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(.leading, 16)
                .padding(.top, 2)
                .padding(.bottom, 12)
        }
        .buttonStyle(RowPressStyle())
        .accessibilityValue(Text(open ? "已展开" : "已收起"))
    }
}

/// A child under its conversation (web .conv-child): a line on the left, its title, state and time.
struct ChildRow: View {
    let chat: Chat

    var body: some View {
        HStack(spacing: 0) {
            RoundedRectangle(cornerRadius: 1)
                .fill(Palette.line)
                .frame(width: 2)
                .padding(.leading, 11)
                .padding(.vertical, 8)
            VStack(alignment: .leading, spacing: 2) {
                HStack(spacing: 8) {
                    Text(chat.title)
                        .scaledFont(15, .medium, relativeTo: .callout)
                        .foregroundStyle(Palette.ink)
                        .lineLimit(1)
                        .frame(maxWidth: .infinity, alignment: .leading)
                    let ago = Labels.ago(chat.updated)
                    if !ago.isEmpty {
                        Text(ago)
                            .captionFont()
                            .foregroundStyle(Palette.muted)
                            .lineLimit(1)
                    }
                }
                HStack(spacing: 0) {
                    Text(Labels.status(chat.status))
                        .captionFont()
                        .foregroundStyle(chat.status == "unknown" || chat.status.isEmpty ? Palette.muted : statusColor(chat.status))
                    if chat.kind == "subagent" {
                        Text(" · 子智能体")
                            .captionFont()
                            .foregroundStyle(Palette.muted)
                    }
                }
            }
            .padding(.leading, 11)
            .padding(.trailing, 4)
            .padding(.vertical, 9)
        }
        .fixedSize(horizontal: false, vertical: true)
        .contentShape(Rectangle())
        .accessibilityElement(children: .combine)
    }
}
