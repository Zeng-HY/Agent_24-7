import ActivityKit
import SwiftUI
import TeleplyIsland
import WidgetKit

/// The extension's copy of the app's colours (Palette.swift; ci-check.sh compares the copies). The Dynamic Island is
/// always black, so the island uses each colour's dark value; the lock-screen card follows the system's appearance.
enum IslandPalette {
    static let claude = Color("ClaudeTint")
    static let codex = Color("CodexTint")
    static let deepseek = Color("DeepSeekTint")
    static let ask = Color("AskGo")
    static let success = Color("Success")
    static let danger = Color("Danger")
    static let muted = Color("Muted")
    static let ink = Color("Ink")

    static func source(_ app: String) -> Color {
        switch app {
        case "claude": return claude
        case "deepseek": return deepseek
        default: return codex
        }
    }

    static func color(_ role: IslandColorRole, app: String) -> Color {
        switch role {
        case .source: return source(app)
        case .ask: return ask
        case .success: return success
        case .danger: return danger
        case .muted: return muted
        }
    }
}

/// The source's mark, as in the app (Design/Marks.swift), from the extension's own copy of the assets.
struct IslandMark: View {
    let app: String
    var size: CGFloat = 18
    /// 在等你: the small orange dot at its corner (the minimal island has no room for words).
    var dot = false

    var body: some View {
        Image(asset)
            .renderingMode(.template)
            .resizable()
            .scaledToFit()
            .frame(width: size, height: size)
            .foregroundStyle(IslandPalette.source(app))
            .overlay(alignment: .bottomTrailing) {
                if dot {
                    Circle()
                        .fill(IslandPalette.ask)
                        .frame(width: size * 0.34, height: size * 0.34)
                        .offset(x: size * 0.1, y: size * 0.1)
                }
            }
            .accessibilityHidden(true)
    }

    private var asset: String {
        switch app {
        case "claude": return "ClaudeMark"
        case "deepseek": return "DeepSeekMark"
        default: return "CodexMark"
        }
    }
}

/// The lock-screen card (and the .small size StandBy, Apple Watch and CarPlay show).
struct LockScreenCard: View {
    let attributes: IslandAttributes
    let state: IslandState
    @Environment(\.activityFamily) private var family

    private var now: Int { Int(Date().timeIntervalSince1970) }

    var body: some View {
        Group {
            if family == .small {
                SmallCard(attributes: attributes, state: state)
            } else {
                fullCard
            }
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 10)
    }

    private var fullCard: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(spacing: 8) {
                IslandMark(app: attributes.app, size: 20, dot: state.status == .waiting)
                Text(title)
                    .font(.system(size: 15, weight: .semibold))
                    .foregroundStyle(IslandPalette.ink)
                    .lineLimit(1)
                Spacer(minLength: 8)
                if let symbol = IslandWords.symbol(state.status ?? .working) {
                    Image(systemName: symbol)
                        .font(.system(size: 14, weight: .bold))
                        .foregroundStyle(IslandPalette.color(IslandWords.colorRole(state.status ?? .working),
                                                             app: attributes.app))
                }
            }
            HStack(spacing: 6) {
                Text(IslandWords.detail(state, now: now))
                    .font(.system(size: 13))
                    .foregroundStyle(detailColor)
                    .lineLimit(1)
                if state.status == .working || state.status == .offline || state.status == nil {
                    Elapsed(since: state.since)
                        .font(.system(size: 13, weight: .medium))
                        .foregroundStyle(IslandPalette.ink)
                }
                if IslandWords.isStale(state, now: now) {
                    Text("可能不是最新")
                        .font(.system(size: 11))
                        .foregroundStyle(IslandPalette.muted)
                }
            }
        }
    }

    private var title: String {
        attributes.title.isEmpty ? "\(IslandWords.appName(attributes.app)) · \(attributes.computer)" : attributes.title
    }

    private var detailColor: Color {
        IslandPalette.color(IslandWords.colorRole(state.status ?? .working), app: attributes.app)
    }
}

/// A tiny card for .small: the same words, without the title.
struct SmallCard: View {
    let attributes: IslandAttributes
    let state: IslandState

    private var now: Int { Int(Date().timeIntervalSince1970) }

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack(spacing: 6) {
                IslandMark(app: attributes.app, size: 18, dot: state.status == .waiting)
                Text(IslandWords.state(state.status ?? .working))
                    .font(.system(size: 14, weight: .semibold))
                    .foregroundStyle(IslandPalette.ink)
            }
            if state.status == .working || state.status == .offline || state.status == nil {
                Elapsed(since: state.since)
                    .font(.system(size: 20, weight: .medium))
                    .foregroundStyle(IslandPalette.ink)
            } else if let symbol = IslandWords.symbol(state.status ?? .working) {
                Image(systemName: symbol)
                    .font(.system(size: 18, weight: .bold))
                    .foregroundStyle(IslandPalette.color(IslandWords.colorRole(state.status ?? .working),
                                                         app: attributes.app))
            }
        }
    }
}

/// The timer, which ticks by itself (no push needed).
struct Elapsed: View {
    let since: Int

    var body: some View {
        Text(timerInterval: Date(timeIntervalSince1970: TimeInterval(since))...Date.distantFuture, countsDown: false)
            .monospacedDigit()
            .lineLimit(1)
    }
}

/// 额度用完: counts down to when the quota comes back.
struct Countdown: View {
    let until: Int

    var body: some View {
        let now = Date()
        if until > Int(now.timeIntervalSince1970) {
            Text(timerInterval: now...Date(timeIntervalSince1970: TimeInterval(until)), countsDown: true)
                .monospacedDigit()
                .lineLimit(1)
        } else {
            Text("0:00").monospacedDigit()
        }
    }
}

/// The right-hand side of the compact island (compact: true) or of the expanded island.
struct Trailing: View {
    let app: String
    let state: IslandState
    var size: CGFloat
    var compact = false

    private var now: Int { Int(Date().timeIntervalSince1970) }

    var body: some View {
        Group {
            switch state.status ?? .working {
            case .working:
                Elapsed(since: state.since)
                    .font(.system(size: size, weight: .medium))
                    .foregroundStyle(IslandPalette.ink)
            case .offline:
                if compact {
                    Text("断开")
                        .font(.system(size: size, weight: .medium))
                        .foregroundStyle(IslandPalette.muted)
                } else {
                    Elapsed(since: state.since)
                        .font(.system(size: size, weight: .medium))
                        .foregroundStyle(IslandPalette.muted)
                }
            case .waiting:
                Text("等你")
                    .font(.system(size: size, weight: .semibold))
                    .foregroundStyle(IslandPalette.ask)
            case .limited:
                Countdown(until: state.resets ?? now)
                    .font(.system(size: size, weight: .medium))
                    .foregroundStyle(IslandPalette.ask)
            case .done:
                Image(systemName: "checkmark")
                    .font(.system(size: size, weight: .bold))
                    .foregroundStyle(IslandPalette.success)
            case .failed:
                Image(systemName: "exclamationmark")
                    .font(.system(size: size, weight: .bold))
                    .foregroundStyle(IslandPalette.danger)
            }
        }
        .lineLimit(1)
        .frame(minWidth: size * 1.6, alignment: .trailing)
    }
}

/// The minimal island: the mark, with a dot or a symbol when there is room for a meaning but not for words.
struct Minimal: View {
    let app: String
    let state: IslandState

    var body: some View {
        HStack(spacing: 2) {
            IslandMark(app: app, size: 16, dot: state.status == .waiting)
                .opacity(state.status == .offline ? 0.55 : 1)
            if let symbol = IslandWords.symbol(state.status ?? .working) {
                Image(systemName: symbol)
                    .font(.system(size: 10, weight: .bold))
                    .foregroundStyle(IslandPalette.color(IslandWords.colorRole(state.status ?? .working), app: app))
            }
        }
    }
}
