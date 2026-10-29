import Foundation

/// The words the pages show for sources, states, times and counts, as the web and Android write them.
public enum Labels {
    /// Set once at launch from the iPhone language; tests keep Chinese.
    nonisolated(unsafe) public static var language = "zh-Hans"
    static var english: Bool { language.hasPrefix("en") }

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
        case "running": return english ? "● Running" : "● 运行中"
        case "waiting": return english ? "Waiting for you" : "等待你处理"
        case "idle": return english ? "Idle" : "空闲"
        case "stopped": return english ? "Stopped" : "已停止"
        case "failed": return english ? "Failed" : "失败"
        default: return english ? "Unknown" : "状态不明"
        }
    }

    /// Web ago(): 刚刚, N 分钟前, 今天 HH:MM, 昨天 HH:MM, M-D HH:MM; nothing for no time.
    public static func ago(_ milliseconds: Int64, now: Date = Date(), calendar: Calendar = .current) -> String {
        guard milliseconds > 0 else { return "" }
        let date = Date(timeIntervalSince1970: Double(milliseconds) / 1000)
        let seconds = Int(now.timeIntervalSince(date))
        if seconds < 60 { return english ? "Just now" : "刚刚" }
        if seconds < 3_600 { return english ? "\(seconds / 60) min ago" : "\(seconds / 60) 分钟前" }
        let parts = calendar.dateComponents([.month, .day, .hour, .minute], from: date)
        let hhmm = String(format: "%02d:%02d", parts.hour ?? 0, parts.minute ?? 0)
        if calendar.isDate(date, inSameDayAs: now) { return (english ? "Today " : "今天 ") + hhmm }
        if let yesterday = calendar.date(byAdding: .day, value: -1, to: now), calendar.isDate(date, inSameDayAs: yesterday) { return (english ? "Yesterday " : "昨天 ") + hhmm }
        return "\(parts.month ?? 0)-\(parts.day ?? 0) \(hhmm)"
    }

    /// Token counts: 16.9万 from ten thousand on, one decimal, no ".0" (Android wan).
    public static func wan(_ value: Int64) -> String {
        guard value >= 10_000 else { return String(value) }
        let text = String(format: "%.1f", Double(value) / 10_000)
        return (text.hasSuffix(".0") ? String(text.dropLast(2)) : text) + (english ? "K" : "万")
    }

    /// Reasoning effort in Chinese, as 会话状态 shows it.
    public static func effort(_ value: String) -> String {
        switch value.lowercased() {
        case "minimal": return english ? "Minimal" : "极低"
        case "low": return english ? "Low" : "低"
        case "medium": return english ? "Medium" : "中"
        case "high": return english ? "High" : "高"
        case "xhigh", "max": return english ? "Extra high" : "极高"
        default: return value
        }
    }
}
