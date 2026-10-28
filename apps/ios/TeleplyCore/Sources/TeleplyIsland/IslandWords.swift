import Foundation

/// Which of the app's colours an island part takes (Palette.swift; the extension holds copies in its assets).
public nonisolated enum IslandColorRole: String, Sendable, Equatable {
    /// The source's own colour (ClaudeTint, CodexTint, DeepSeekTint).
    case source
    /// 在等你: AskGo, as 等待你处理 in the list.
    case ask
    case success
    case danger
    /// 断开: Muted.
    case muted
}

/// The island's words and choices, kept here so they can be tested on this computer (handoff 5.4).
///
/// The design rule: short words the user already knows from 遥应's notifications (在干活、在等你、好了、出错停了、
/// 断开了), and nothing of the conversation.
public enum IslandWords {
    public static func appName(_ app: String) -> String {
        switch app {
        case "claude": return "Claude"
        case "deepseek": return "DeepSeek"
        default: return "Codex"
        }
    }

    /// The short state word (4 characters at most, for the compact island).
    public static func state(_ status: IslandStatus) -> String {
        switch status {
        case .working: return "在干活"
        case .waiting: return "在等你"
        case .done: return "好了"
        case .failed: return "出错停了"
        case .offline: return "断开了"
        case .limited: return "额度用完"
        }
    }

    /// The line under the title on the expanded island and the lock-screen card. `now` is Unix seconds.
    public static func detail(_ state: IslandState, now: Int) -> String {
        switch state.status ?? .working {
        case .working:
            return "在干活"
        case .waiting:
            return ask(state) ?? "在等你选"
        case .done:
            return "好了 · 用了 " + duration(now - state.turn)
        case .failed:
            return "出错停了"
        case .offline:
            return "断开了"
        case .limited:
            return "额度用完 · " + countdown((state.resets ?? now) - now) + " 后恢复"
        }
    }

    /// 方案二: what is being asked, in words that say nothing of the command itself.
    public static func ask(_ state: IslandState) -> String? {
        if let text = state.askText, !text.isEmpty { return text }
        if state.askType == "permission" { return "想运行一条命令" }
        if let choices = state.choices, choices > 0 { return "有 \(choices) 个选项等你选" }
        return "在等你选"
    }

    /// The right-hand part of the compact island; nil when the view draws a symbol or the timer instead.
    public static func compactTrailing(_ state: IslandState, now: Int) -> String? {
        switch state.status ?? .working {
        case .waiting: return "等你"
        case .offline: return "断开"
        case .limited: return compactCountdown((state.resets ?? now) - now)
        case .working, .done, .failed: return nil
        }
    }

    /// The SF Symbol for the compact right side and the minimal island: checkmark, !, or none.
    public static func symbol(_ status: IslandStatus) -> String? {
        switch status {
        case .done: return "checkmark"
        case .failed: return "exclamationmark"
        default: return nil
        }
    }

    /// 方案六: the small icon for what the computer is doing, as a symbol name.
    public static func stepSymbol(_ step: String?) -> String? {
        switch step {
        case "edit": return "pencil"
        case "run": return "terminal"
        case "search": return "magnifyingglass"
        case "read": return "doc.text"
        default: return nil
        }
    }

    public static func colorRole(_ status: IslandStatus) -> IslandColorRole {
        switch status {
        case .working: return .source
        case .waiting, .limited: return .ask
        case .done: return .success
        case .failed: return .danger
        case .offline: return .muted
        }
    }

    /// 方案三 A: the higher the number, the more of the island the system gives it. Working islands started later
    /// score higher (50 to 59); everything else has one score.
    public static func relevance(_ state: IslandState, now: Int) -> Double {
        switch state.status ?? .working {
        case .waiting: return 100
        case .limited: return 90
        case .failed: return 80
        case .offline: return 60
        case .working:
            let minutes = max(0, (now - state.turn) / 60)
            return Double(50 + max(0, min(9, 9 - minutes)))
        case .done: return 10
        }
    }

    /// After a working push's stale-date passes, the view adds 可能不是最新.
    public static func isStale(_ state: IslandState, now: Int, staleAfter: Int = 15 * 60) -> Bool {
        guard state.status == .working else { return false }
        return now - max(state.since, state.turn) > staleAfter
    }

    /// "6 分 12 秒", "12 秒", "1 小时 3 分".
    public static func duration(_ seconds: Int) -> String {
        let total = max(0, seconds)
        if total < 60 { return "\(total) 秒" }
        if total < 3600 {
            let minutes = total / 60, rest = total % 60
            return rest == 0 ? "\(minutes) 分" : "\(minutes) 分 \(rest) 秒"
        }
        let hours = total / 3600, minutes = total % 3600 / 60
        return minutes == 0 ? "\(hours) 小时" : "\(hours) 小时 \(minutes) 分"
    }

    /// "2:13:05" (an hour or more), "13:05" (less). For 额度用完 and the compact limited island.
    public static func countdown(_ seconds: Int) -> String {
        let total = max(0, seconds)
        let hours = total / 3600, minutes = total % 3600 / 60, rest = total % 60
        if hours > 0 { return String(format: "%d:%02d:%02d", hours, minutes, rest) }
        return String(format: "%d:%02d", minutes, rest)
    }

    /// The compact island has room for about four characters; an hour or more drops the seconds.
    public static func compactCountdown(_ seconds: Int) -> String {
        let total = max(0, seconds)
        return total >= 3600 ? String(format: "%d:%02d", total / 3600, total % 3600 / 60)
            : String(format: "%d:%02d", total / 60, total % 60)
    }

    /// One sentence for VoiceOver, e.g. "Claude 在干活，已经 4 分 31 秒".
    public static func accessibility(app: String, state: IslandState, now: Int) -> String {
        if let line = aggregate(state) { return "遥应，" + line }
        let name = appName(app), word = self.state(state.status ?? .working), elapsed = duration(now - state.since)
        switch state.status ?? .working {
        case .working, .offline, .failed:
            return "\(name)\(word)，已经 \(elapsed)"
        case .waiting:
            return "\(name)\(word)，" + (ask(state) ?? "")
        case .done:
            return "\(name)好了，用了 " + duration(now - state.turn)
        case .limited:
            return "\(name)额度用完，" + countdown((state.resets ?? now) - now) + " 后恢复"
        }
    }

    // MARK: 0.6.3：一台电脑一个岛

    /// How many conversations of this computer the island counts; nil on a 0.6.2 island that names one conversation.
    public static func counts(_ state: IslandState) -> (working: Int, waiting: Int, total: Int)? {
        guard state.working != nil || state.waiting != nil else { return nil }
        let working = max(0, state.working ?? 0), waiting = max(0, state.waiting ?? 0)
        return (working, waiting, working + waiting)
    }

    /// The compact island's right side when several conversations are counted: "3个工作中" / "2个等你定". nil when
    /// one or none runs, where the timer or the state mark says it better.
    public static func compactCount(_ state: IslandState) -> String? {
        guard let counts = counts(state) else { return nil }
        if counts.waiting > 0 { return "\(counts.waiting)个等你定" }
        if counts.working >= 2 { return "\(counts.working)个工作中" }
        return nil
    }

    /// The expanded island's and the lock-screen card's first line: "3 个对话工作中 · 1 个等你定"; nil when nothing
    /// is running or waiting.
    public static func aggregate(_ state: IslandState) -> String? {
        guard let counts = counts(state), counts.total > 0 else { return nil }
        var parts: [String] = []
        if counts.working > 0 { parts.append("\(counts.working) 个对话工作中") }
        if counts.waiting > 0 { parts.append("\(counts.waiting) 个对话等你定") }
        return parts.joined(separator: " · ")
    }

    /// The one conversation a one-conversation island shows: its peer, when the relay sent the list.
    public static func only(_ state: IslandState) -> IslandPeer? {
        guard let counts = counts(state), counts.total == 1 else { return nil }
        return state.peers?.first
    }

    /// A conversation's title on the island: its own, or 模型 · 电脑 when it has none.
    public static func title(_ peer: IslandPeer, computer: String) -> String {
        peer.title.isEmpty ? "\(appName(peer.app)) · \(computer)" : peer.title
    }
}
