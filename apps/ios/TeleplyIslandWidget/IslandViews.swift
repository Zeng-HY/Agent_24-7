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
    /// The lock-screen card is white on light and dark on dark, like the lock screen's own notifications (0.6.2,
    /// user 10-28): the same colour the card's system action (its ✕) takes.
    static let cardBackground = Color("CardBackground")
    static let cardForeground = Color("CardForeground")

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

/// 遥应's own mark, white on the island. The compact island and the minimal circle show this instead of a model's mark
/// (user 10-28): the model marks are in the long-press list, one per conversation.
struct BrandMark: View {
    var size: CGFloat = 17
    var dot = false

    var body: some View {
        Image("TeleplyMark")
            .renderingMode(.template)
            .resizable()
            .scaledToFit()
            .frame(width: size, height: size)
            .foregroundStyle(.white)
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
}

/// The long-press list: every conversation still working or waiting on this computer, with its model, title and
/// time. A row opens that conversation (`teleply://open…`), the same check as a tapped notification.
struct PeerList: View {
    let device: String
    let state: IslandState
    let computer: String

    private var peers: [IslandPeer]? {
        guard let peers = state.peers, !peers.isEmpty else { return nil }
        return peers
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 5) {
            if let peers {
                ForEach(peers, id: \.chat) { peer in
                    PeerRow(device: device, computer: computer, peer: peer)
                }
            } else {
                HStack(spacing: 7) {
                    BrandMark(size: 13)
                    Text(IslandWords.detail(state, now: Int(Date().timeIntervalSince1970)))
                        .font(.system(size: 12)).foregroundStyle(IslandPalette.ink).lineLimit(1)
                    Spacer(minLength: 6)
                    Trailing(app: "", state: state, size: 11, compact: true)
                }
                .frame(height: 20)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

private struct PeerRow: View {
    let device: String
    let computer: String
    let peer: IslandPeer

    private var title: String {
        if peer.title.isEmpty { return IslandWords.appName(peer.app) + " · " + computer }
        return peer.title
    }

    var body: some View {
        if let url = IslandURL.open(device: device, app: peer.app, chat: peer.chat), !peer.chat.isEmpty {
            Link(destination: url) { row }
        } else {
            row
        }
    }

    private var row: some View {
        HStack(spacing: 7) {
            if peer.app.isEmpty {
                BrandMark(size: 15)
            } else {
                IslandMark(app: peer.app, size: 15)
            }
            Text(title)
                .font(.system(size: 14))
                .foregroundStyle(IslandPalette.ink)
                .lineLimit(1)
            Spacer(minLength: 6)
            trailing
        }
        .frame(height: 24)
    }

    @ViewBuilder private var trailing: some View {
        switch peer.status ?? .working {
        case .working:
            Elapsed(since: peer.since)
                .font(.system(size: 13, weight: .medium))
                .foregroundStyle(IslandPalette.ink)
        case .waiting:
            Text("等你").font(.system(size: 13, weight: .semibold)).foregroundStyle(IslandPalette.ask)
        case .done:
            Image(systemName: "checkmark").font(.system(size: 13, weight: .bold)).foregroundStyle(IslandPalette.success)
        case .failed:
            Image(systemName: "exclamationmark").font(.system(size: 13, weight: .bold)).foregroundStyle(IslandPalette.danger)
        case .offline, .limited:
            Text(IslandWords.state(peer.status ?? .working))
                .font(.system(size: 13, weight: .medium)).foregroundStyle(IslandPalette.muted)
        }
    }
}

/// The lock-screen card (and the .small size StandBy, Apple Watch and CarPlay show). It is white on light and dark on
/// dark, like a notification on the lock screen (0.6.2, user 10-28); the Dynamic Island itself stays black.
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
        .padding(.horizontal, 16)
        .padding(.vertical, 14)
        .activityBackgroundTint(IslandPalette.cardBackground)
        .activitySystemActionForegroundColor(IslandPalette.cardForeground)
    }

    private var fullCard: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 9) {
                IslandMark(app: attributes.app, size: 24, dot: state.status == .waiting)
                Text(title)
                    .font(.system(size: 17, weight: .semibold))
                    .foregroundStyle(IslandPalette.ink)
                    .lineLimit(1)
                Spacer(minLength: 8)
                if let symbol = IslandWords.symbol(state.status ?? .working) {
                    Image(systemName: symbol)
                        .font(.system(size: 16, weight: .bold))
                        .foregroundStyle(IslandPalette.color(IslandWords.colorRole(state.status ?? .working),
                                                             app: attributes.app))
                }
            }
            HStack(spacing: 7) {
                Text(IslandWords.detail(state, now: now))
                    .font(.system(size: 15))
                    .foregroundStyle(detailColor)
                    .lineLimit(1)
                if state.status == .working || state.status == .offline || state.status == nil {
                    Elapsed(since: state.since)
                        .font(.system(size: 15, weight: .medium))
                        .foregroundStyle(IslandPalette.ink)
                }
                if IslandWords.isStale(state, now: now) {
                    Text("可能不是最新")
                        .font(.system(size: 12))
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

/// A tiny card for .small: title, state and timer (Apple Watch's Smart Stack and CarPlay).
struct SmallCard: View {
    let attributes: IslandAttributes
    let state: IslandState

    private var now: Int { Int(Date().timeIntervalSince1970) }

    private var title: String {
        attributes.title.isEmpty ? "\(IslandWords.appName(attributes.app)) · \(attributes.computer)" : attributes.title
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 5) {
            Text(title)
                .font(.system(size: 13, weight: .semibold))
                .foregroundStyle(IslandPalette.ink)
                .lineLimit(1)
            HStack(spacing: 6) {
                IslandMark(app: attributes.app, size: 18, dot: state.status == .waiting)
                Text(IslandWords.state(state.status ?? .working))
                    .font(.system(size: 15, weight: .semibold))
                    .foregroundStyle(IslandPalette.ink)
            }
            if state.status == .working || state.status == .offline || state.status == nil {
                Elapsed(since: state.since)
                    .font(.system(size: 22, weight: .medium))
                    .foregroundStyle(IslandPalette.ink)
            } else if let symbol = IslandWords.symbol(state.status ?? .working) {
                Image(systemName: symbol)
                    .font(.system(size: 20, weight: .bold))
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

/// The expanded island's top-right corner: only a state mark, because 在干活 and its timer belong on the line under
/// the title (handoff 5.4).
struct ExpandedTrailing: View {
    let status: IslandStatus

    var body: some View {
        switch status {
        case .done:
            Image(systemName: "checkmark")
                .font(.system(size: 15, weight: .bold))
                .foregroundStyle(IslandPalette.success)
        case .failed:
            Image(systemName: "exclamationmark")
                .font(.system(size: 15, weight: .bold))
                .foregroundStyle(IslandPalette.danger)
        case .waiting:
            Text("等你")
                .font(.system(size: 15, weight: .semibold))
                .foregroundStyle(IslandPalette.ask)
        case .working, .offline, .limited:
            EmptyView()
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
            BrandMark(size: 16, dot: state.status == .waiting)
                .opacity(state.status == .offline ? 0.55 : 1)
            if let symbol = IslandWords.symbol(state.status ?? .working) {
                Image(systemName: symbol)
                    .font(.system(size: 10, weight: .bold))
                    .foregroundStyle(IslandPalette.color(IslandWords.colorRole(state.status ?? .working), app: app))
            }
        }
    }
}
