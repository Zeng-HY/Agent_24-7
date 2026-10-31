import SwiftUI
import TeleplyModel

/// Where a conversation's model and context come from (Android runtimeOf): Claude's from the desktop (the state's
/// runtime), the others from the session record (the page's runtime), with the state's as a fallback. 0.6.6: DeepSeek's
/// state carries its context, read every 2.5 s (its live stream gets the numbers only once), so that one leads.
func runtimeOf(app: String, control: JSONValue, page: JSONValue) -> JSONValue {
    let fromControl = control["runtime"]
    if app == "claude", fromControl.isObject { return fromControl }
    if app == "deepseek", fromControl["context_state"].string() == "available" { return fromControl }
    return page.isObject && !page.object.isEmpty ? page : fromControl
}

/// The context percentage the ring shows; nil while there is none.
func contextPercent(_ runtime: JSONValue) -> Int? {
    guard runtime["context_state"].string() == "available", runtime.has("percent") else { return nil }
    return min(100, max(0, Int(runtime["percent"].double().rounded())))
}

/// Context usage ring (web .ctx-ring; spec 4.3): 26 pt, 3 pt stroke, the percentage inside at 9 pt (it does not
/// grow with the text size, so the large content viewer shows it); amber from 80%.
struct ContextRing: View {
    let percent: Int
    let action: () -> Void

    var body: some View {
        let warn = percent >= 80
        Button(action: action) {
            ZStack {
                Circle().stroke(Palette.line, lineWidth: 3)
                Circle()
                    .trim(from: 0, to: CGFloat(percent) / 100)
                    .stroke(warn ? Palette.warning : Palette.muted, lineWidth: 3)
                    .rotationEffect(.degrees(-90))
                Text(verbatim: "\(percent)")
                    .font(.system(size: 9, weight: .semibold))
                    .foregroundStyle(Palette.muted)
            }
            .frame(width: 26, height: 26)
            .frame(width: 36, height: 36)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .accessibilityLabel(Text(verbatim: "上下文已用约 \(percent)%，查看会话状态"))
        .accessibilityShowsLargeContentViewer {
            Label {
                Text(verbatim: "上下文 \(percent)%")
            } icon: {
                Image(systemName: "gauge.with.dots.needle.33percent")
            }
        }
    }
}

/// 会话状态 (spec 4.3): from the ring as a popover. Context first, as one big number with a bar and the token
/// counts; then model and effort as two tiles; then one line on where the numbers come from and how fresh they are.
struct RuntimePanel: View {
    let app: String
    let control: JSONValue
    let runtime: JSONValue
    @Environment(\.colorScheme) private var scheme

    var body: some View {
        Group {
            if runtime.object.isEmpty {
                Text("这个会话还没有可显示的状态。")
                    .noteFont()
                    .foregroundStyle(Palette.muted)
                    .padding(18)
            } else {
                content
            }
        }
        .frame(width: 300, alignment: .leading)
    }

    private var content: some View {
        let state = runtime["context_state"].string()
        let percent = contextPercent(runtime)
        let ink = (percent ?? 0) >= 80 ? Palette.warning : Palette.ink
        let used = runtime["used_tokens"].int64()
        let window = runtime["context_window"].int64()
        // Without the window only the last request's size is known (web: 最近输入 N tokens).
        let counts = used > 0 && window > 0 ? "已用\(Labels.wan(used)) · 窗口\(Labels.wan(window))"
            : used > 0 && state == "partial" ? "最近输入 \(Labels.wan(used)) tokens · 窗口大小未知" : nil
        let effort = effortShown
        return VStack(alignment: .leading, spacing: 0) {
            VStack(alignment: .leading, spacing: 0) {
                HStack(alignment: .lastTextBaseline, spacing: 0) {
                    if let percent {
                        Text(verbatim: "\(percent)")
                            .font(.system(size: 32, weight: .semibold))
                            .foregroundStyle(ink)
                        Text(verbatim: "%")
                            .font(.system(size: 18, weight: .semibold))
                            .foregroundStyle(ink)
                            .padding(.leading, 1)
                    } else {
                        Text(contextText(state))
                            .font(.system(size: 20, weight: .semibold))
                            .foregroundStyle(Palette.muted)
                    }
                    Text("上下文")
                        .noteFont()
                        .foregroundStyle(Palette.muted)
                        .padding(.leading, 8)
                }
                if let percent {
                    ProgressView(value: Double(percent), total: 100)
                        .progressViewStyle(.linear)
                        .tint(percent >= 80 ? Palette.warning : Palette.accent)
                        .padding(.top, 10)
                }
                if let counts {
                    Text(counts)
                        .noteFont()
                        .foregroundStyle(Palette.muted)
                        .padding(.top, 8)
                }
            }
            .accessibilityElement(children: .ignore)
            .accessibilityLabel(Text((percent.map { "上下文已用约 \($0)%" } ?? "上下文" + contextText(state)) + (counts.map { "，" + $0.replacingOccurrences(of: " · ", with: "，") } ?? "")))
            HStack(spacing: 8) {
                tile("模型", modelLabel(runtime["model"].string()), nil)
                tile("推理强度", effort.isEmpty ? "暂无" : Labels.effort(effort), Labels.effort(effort) != effort ? effort : nil)
            }
            .padding(.top, 14)
            Text(footer(percent: percent))
                .captionFont()
                .foregroundStyle(Palette.muted)
                .padding(.top, 12)
        }
        .padding(.horizontal, 18)
        .padding(.top, 14)
        .padding(.bottom, 12)
    }

    private func tile(_ label: String, _ value: String, _ original: String?) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(label)
                .captionFont()
                .foregroundStyle(Palette.muted)
            HStack(alignment: .lastTextBaseline, spacing: 4) {
                Text(value)
                    .scaledFont(15, .semibold, relativeTo: .callout)
                    .foregroundStyle(Palette.ink)
                    .lineLimit(2)
                if let original {
                    Text(original)
                        .scaledFont(11, .medium, relativeTo: .caption2)
                        .foregroundStyle(Palette.muted)
                        .lineLimit(1)
                }
            }
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 10)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(scheme == .dark ? Color.white.opacity(0.08) : Color.black.opacity(0.04),
                    in: RoundedRectangle(cornerRadius: 14, style: .continuous))
        .accessibilityElement(children: .combine)
    }

    private func contextText(_ state: String) -> String {
        switch state {
        case "waiting": return "等待更新"
        case "partial": return "数据不全"
        default: return "暂无数据"
        }
    }

    /// The effort the record names; for Claude, when it names none, what the desktop shows or keeps as its setting
    /// (10-26: the context label was not read, and the effort went with it while the chip showed High).
    private var effortShown: String {
        let recorded = runtime["effort"].string()
        guard recorded.isEmpty, app == "claude" else { return recorded }
        let shown = control["effort_label"].string()
        return shown.isEmpty ? control["settings"]["effort"].string() : shown
    }

    /// The model's display name: Claude's desktop label, Codex's catalog name, otherwise the id.
    private func modelLabel(_ id: String) -> String {
        if app == "claude", !control["model_label"].string().isEmpty { return control["model_label"].string() }
        let named = control["catalog"]["models"].array.first { $0["id"].string() == id }?["name"].string() ?? ""
        if !named.isEmpty { return named }
        return id.isEmpty ? "暂无" : id
    }

    private func footer(percent: Int?) -> String {
        let seconds = max(runtime["model_time"].int64(), runtime["usage_time"].int64())
        let ago = seconds > 0 ? Labels.ago(seconds > 10_000_000_000 ? seconds : seconds * 1000) : ""
        let fresh: String? = ago.isEmpty ? nil : ago == "刚刚" ? "刚刚更新" : ago.hasSuffix("前") ? ago + "更新" : ago + " 更新"
        return [app == "claude" ? "来自电脑上的 Claude" : "来自会话记录", fresh, percent != nil ? "比例是估算值" : nil]
            .compactMap { $0 }
            .joined(separator: " · ")
    }
}
