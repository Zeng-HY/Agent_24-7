import Foundation

/// The words the pages show for sources, states, times and counts, as the web and Android write them.
public enum Labels {
    public static func sourceName(_ app: String) -> String {
        switch app {
        case "codex": return "Codex"
        case "claude": return "Claude"
        case "deepseek": return "DeepSeek"
        default: return app
        }
    }

    /// A list row's state (Android statusLabel).
    public static func status(_ status: String) -> String {
        switch status {
        case "running": return "● 运行中"
        case "waiting": return "等待你处理"
        case "idle": return "空闲"
        case "stopped": return "已停止"
        case "failed": return "失败"
        default: return "状态不明"
        }
    }

    /// Web ago(): 刚刚, N 分钟前, 今天 HH:MM, 昨天 HH:MM, M-D HH:MM; nothing for no time.
    public static func ago(_ milliseconds: Int64, now: Date = Date(), calendar: Calendar = .current) -> String {
        guard milliseconds > 0 else { return "" }
        let date = Date(timeIntervalSince1970: Double(milliseconds) / 1000)
        let seconds = Int(now.timeIntervalSince(date))
        if seconds < 60 { return "刚刚" }
        if seconds < 3_600 { return "\(seconds / 60) 分钟前" }
        let parts = calendar.dateComponents([.month, .day, .hour, .minute], from: date)
        let hhmm = String(format: "%02d:%02d", parts.hour ?? 0, parts.minute ?? 0)
        if calendar.isDate(date, inSameDayAs: now) { return "今天 \(hhmm)" }
        if let yesterday = calendar.date(byAdding: .day, value: -1, to: now), calendar.isDate(date, inSameDayAs: yesterday) { return "昨天 \(hhmm)" }
        return "\(parts.month ?? 0)-\(parts.day ?? 0) \(hhmm)"
    }

    /// Token counts: 16.9万 from ten thousand on, one decimal, no ".0" (Android wan).
    public static func wan(_ value: Int64) -> String {
        guard value >= 10_000 else { return String(value) }
        let text = String(format: "%.1f", Double(value) / 10_000)
        return (text.hasSuffix(".0") ? String(text.dropLast(2)) : text) + "万"
    }

    /// Reasoning effort in Chinese, as 会话状态 shows it.
    public static func effort(_ value: String) -> String {
        switch value.lowercased() {
        case "minimal": return "极低"
        case "low": return "低"
        case "medium": return "中"
        case "high": return "高"
        case "xhigh", "max": return "极高"
        default: return value
        }
    }
}
