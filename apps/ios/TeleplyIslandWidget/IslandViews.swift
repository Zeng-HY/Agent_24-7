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
    /// On the Dynamic Island itself, always white: the island is black whatever the phone's appearance (0.6.3).
    static let islandInk = Color.white

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
/// time. 0.6.3: a first line counts them; a row opens that conversation (`teleply://open…`), the same check as a
/// tapped notification.
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
            if let line = IslandWords.aggregate(state) {
                Text(line)
                    .font(.system(size: 12, weight: .semibold))
                    .foregroundStyle(IslandPalette.islandInk)
                    .lineLimit(1)
                    .minimumScaleFactor(0.8)
            }
            if let peers {
                ForEach(peers, id: \.chat) { peer in
                    PeerRow(device: device, computer: computer, peer: peer)
                }
            } else if let peer = IslandWords.only(state) {
                PeerRow(device: device, computer: computer, peer: peer)
            } else {
                HStack(spacing: 7) {
                    BrandMark(size: 13)
                    Text(IslandWords.detail(state, now: Int(Date().timeIntervalSince1970)))
                        .font(.system(size: 12)).foregroundStyle(IslandPalette.islandInk).lineLimit(1)
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
    /// White on the black island; the lock-screen card's own ink on its white or dark background (0.6.3).
    var ink = IslandPalette.islandInk

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
                .foregroundStyle(ink)
                .lineLimit(1)
            Spacer(minLength: 6)
            trailing
                .frame(width: CGFloat(IslandMetrics.rowTimer), alignment: .trailing)
        }
        .frame(height: 24)
    }

    @ViewBuilder private var trailing: some View {
        switch peer.status ?? .working {
        case .working:
            Elapsed(since: peer.since)
                .font(.system(size: 13, weight: .medium))
                .foregroundStyle(ink)
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
        Group {
            if count >= 2 {
                aggregateCard  // 0.6.3: several conversations on this computer, counted and listed
            } else {
                singleCard
            }
        }
    }

    /// One conversation (or none left): the 0.6.2 card, its title and mark from the one peer when the relay sent it.
    private var singleCard: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 9) {
                mark
                Text(title)
                    .font(.system(size: 17, weight: .semibold))
                    .foregroundStyle(IslandPalette.ink)
                    .lineLimit(1)
                Spacer(minLength: 8)
                if let symbol = IslandWords.symbol(state.status ?? .working) {
                    Image(systemName: symbol)
                        .font(.system(size: 16, weight: .bold))
                        .foregroundStyle(IslandPalette.color(IslandWords.colorRole(state.status ?? .working),
                                                             app: peer?.app ?? attributes.app))
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

    /// Several conversations: the count line first, then up to three of them with title, state and timer (0.6.3).
    private var aggregateCard: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 9) {
                BrandMark(size: 24, dot: waiting)
                Text(IslandWords.aggregate(state) ?? "")
                    .font(.system(size: 17, weight: .semibold))
                    .foregroundStyle(IslandPalette.ink)
                    .lineLimit(1)
                    .minimumScaleFactor(0.8)
                Spacer(minLength: 8)
            }
            ForEach(peers.prefix(3), id: \.chat) { peer in
                PeerRow(device: attributes.device, computer: attributes.computer, peer: peer, ink: IslandPalette.ink)
            }
        }
    }

    private var peers: [IslandPeer] { state.peers ?? [] }
    private var count: Int { IslandWords.counts(state)?.total ?? peers.count }
    private var waiting: Bool { (state.waiting ?? 0) > 0 || state.status == .waiting }
    private var peer: IslandPeer? { IslandWords.only(state) ?? peers.first }

    @ViewBuilder private var mark: some View {
        if let app = peer?.app ?? (attributes.app.isEmpty ? nil : attributes.app) {
            IslandMark(app: app, size: 24, dot: waiting)
        } else {
            BrandMark(size: 24, dot: waiting)
        }
    }

    private var title: String {
        if let peer { return IslandWords.title(peer, computer: attributes.computer) }
        if !attributes.title.isEmpty { return attributes.title }
        if attributes.app.isEmpty { return "遥应 · \(attributes.computer)" }
        return "\(IslandWords.appName(attributes.app)) · \(attributes.computer)"
    }

    private var detailColor: Color {
        IslandPalette.color(IslandWords.colorRole(state.status ?? .working), app: peer?.app ?? attributes.app)
    }
}

/// A tiny card for .small: title, state and timer (Apple Watch's Smart Stack and CarPlay).
struct SmallCard: View {
    let attributes: IslandAttributes
    let state: IslandState

    private var now: Int { Int(Date().timeIntervalSince1970) }

    private var peers: [IslandPeer] { state.peers ?? [] }
    private var count: Int { IslandWords.counts(state)?.total ?? peers.count }
    private var waiting: Bool { (state.waiting ?? 0) > 0 || state.status == .waiting }

    private var title: String {
        if let peer = IslandWords.only(state) ?? peers.first { return IslandWords.title(peer, computer: attributes.computer) }
        if !attributes.title.isEmpty { return attributes.title }
        return attributes.app.isEmpty ? "遥应 · \(attributes.computer)"
            : "\(IslandWords.appName(attributes.app)) · \(attributes.computer)"
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 5) {
            if count >= 2, let line = IslandWords.aggregate(state) {
                // 0.6.3: several conversations — the count, not one timer, is what the watch shows.
                Text(line)
                    .font(.system(size: 13, weight: .semibold))
                    .foregroundStyle(IslandPalette.ink)
                    .lineLimit(2)
                    .minimumScaleFactor(0.8)
                HStack(spacing: 6) {
                    BrandMark(size: 18, dot: waiting)
                    Text("\(count) 个对话")
                        .font(.system(size: 15, weight: .semibold))
                        .foregroundStyle(IslandPalette.ink)
                }
            } else {
                Text(title)
                    .font(.system(size: 13, weight: .semibold))
                    .foregroundStyle(IslandPalette.ink)
                    .lineLimit(1)
                HStack(spacing: 6) {
                    if let app = peers.first?.app ?? (attributes.app.isEmpty ? nil : attributes.app) {
                        IslandMark(app: app, size: 18, dot: waiting)
                    } else {
                        BrandMark(size: 18, dot: waiting)
                    }
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
                                                             app: peers.first?.app ?? attributes.app))
                }
            }
        }
    }
}

/// The timer, which ticks by itself (no push needed). Its width is capped so a long reading cannot push the title
/// out of the expanded list or the lock-screen card (0.6.2).
struct Elapsed: View {
    let since: Int

    var body: some View {
        Text(timerInterval: Date(timeIntervalSince1970: TimeInterval(since))...Date.distantFuture, countsDown: false)
            .monospacedDigit()
            .lineLimit(1)
            .minimumScaleFactor(0.8)
            .frame(maxWidth: CGFloat(IslandMetrics.rowTimer), alignment: .trailing)
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
                .minimumScaleFactor(0.8)
        } else {
            Text("0:00").monospacedDigit().lineLimit(1).minimumScaleFactor(0.8)
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
            if let text = IslandWords.compactCount(state) {  // 0.6.3: several conversations, counted
                Text(text)
                    .font(.system(size: size, weight: .semibold))
                    .foregroundStyle((state.waiting ?? 0) > 0 ? IslandPalette.ask : IslandPalette.islandInk)
            } else {
                switch state.status ?? .working {
                case .working:
                    Elapsed(since: state.since)
                        .font(.system(size: size, weight: .medium))
                        .foregroundStyle(IslandPalette.islandInk)
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
        }
        .lineLimit(1)
        .minimumScaleFactor(0.8)
        .multilineTextAlignment(.trailing)
        // The compact island's right side is pinned (0.6.2): Apple's timer would otherwise ask for the widest reading
        // it could ever show and stretch the island across the top of the screen.
        .frame(width: compact ? CGFloat(IslandMetrics.compactTrailing) : nil, alignment: .trailing)
        .frame(maxWidth: compact ? nil : CGFloat(IslandMetrics.rowTimer), alignment: .trailing)
    }
}

/// The minimal island: the mark, with a dot or a symbol when there is room for a meaning but not for words.
struct Minimal: View {
    let app: String
    let state: IslandState

    private var total: Int { IslandWords.counts(state)?.total ?? 0 }

    var body: some View {
        HStack(spacing: 2) {
            BrandMark(size: 16, dot: (state.waiting ?? 0) > 0 || state.status == .waiting)
                .opacity(state.status == .offline ? 0.55 : 1)
            if total >= 2 {  // 0.6.3: how many conversations are behind this circle
                Text("\(total)")
                    .font(.system(size: 10, weight: .bold))
                    .monospacedDigit()
                    .foregroundStyle(IslandPalette.islandInk)
            } else if let symbol = IslandWords.symbol(state.status ?? .working) {
                Image(systemName: symbol)
                    .font(.system(size: 10, weight: .bold))
                    .foregroundStyle(IslandPalette.color(IslandWords.colorRole(state.status ?? .working), app: app))
            }
        }
    }
}
