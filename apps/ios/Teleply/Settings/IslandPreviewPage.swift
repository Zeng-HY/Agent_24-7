import SwiftUI
import TeleplyIsland

/// 设置 → 开发者选项 → 灵动岛样子 (handoff 5.4): the island's states as near to their real sizes as a page can draw
/// them, so the look can be discussed before a build reaches the phone. The real island is Apple's; this is a sketch.
struct IslandPreviewPage: View {
    private let now = Int(Date().timeIntervalSince1970)

    private struct Sample: Identifiable {
        let id: String
        let status: IslandStatus
        let state: IslandState
        var caption: String { IslandWords.state(status) }
    }

    /// 0.6.3's list samples: three conversations, one of them waiting.
    private var several: [IslandPeer] {
        [IslandPeer(app: "deepseek", chat: "c3", title: "选方案", state: "waiting", since: now - 30, turn: now - 200),
         IslandPeer(app: "codex", chat: "c2", title: "跑测试", state: "working", since: now - 200, turn: now - 200),
         IslandPeer(app: "claude", chat: "c1", title: "改登录页", state: "working", since: now - 300, turn: now - 300)]
    }

    private var samples: [Sample] {
        [
            Sample(id: "working", status: .working, state: IslandState(status: .working, since: now - 271, turn: now - 271)),
            Sample(id: "waiting", status: .waiting, state: IslandState(status: .waiting, since: now - 30, turn: now - 180,
                                                                      askType: "permission", choices: 2)),
            Sample(id: "done", status: .done, state: IslandState(status: .done, since: now - 5, turn: now - 377)),
            Sample(id: "failed", status: .failed, state: IslandState(status: .failed, since: now - 20, turn: now - 300)),
            Sample(id: "offline", status: .offline, state: IslandState(status: .offline, since: now - 185, turn: now - 400)),
            Sample(id: "limited", status: .limited, state: IslandState(status: .limited, since: now - 30, turn: now - 300,
                                                                      resets: now + 7985)),
            // 0.6.3: one island for the whole computer
            Sample(id: "several-working", status: .working,
                   state: IslandState(status: .working, since: now - 200, turn: now - 200,
                                      peers: Array(several.suffix(2)), working: 2, waiting: 0)),
            Sample(id: "several-waiting", status: .waiting,
                   state: IslandState(status: .waiting, since: now - 30, turn: now - 200, peers: several,
                                      working: 2, waiting: 1)),
        ]
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 24) {
                Text("真机上遥应一台电脑一个岛；同时有几个对话时，紧凑样子显示个数。这里是各种状态的样子，尺寸是按苹果的规格近似画的。")
                    .noteFont()
                    .foregroundStyle(Palette.muted)

                // 0.6.2: the lock-screen card first, drawn in both lights on a neutral stage so the white card is
                // visible against it. The real card sits on the lock screen's wallpaper; this is a sketch.
                section("锁屏卡片 · 浅色") {
                    VStack(spacing: 12) {
                        ForEach(samples) { sample in
                            LockCardPreview(status: sample.status, state: sample.state, now: now, scheme: .light)
                        }
                    }
                    .padding(10)
                    .background(Color(white: 0.84), in: RoundedRectangle(cornerRadius: 26, style: .continuous))
                }

                section("锁屏卡片 · 深色") {
                    VStack(spacing: 12) {
                        ForEach(samples) { sample in
                            LockCardPreview(status: sample.status, state: sample.state, now: now, scheme: .dark)
                        }
                    }
                    .padding(10)
                    .background(Color(white: 0.24), in: RoundedRectangle(cornerRadius: 26, style: .continuous))
                }

                section("紧凑（灵动岛）") {
                    LazyVGrid(columns: [GridItem(.adaptive(minimum: 132), spacing: 10)], alignment: .leading, spacing: 10) {
                        ForEach(samples) { sample in
                            VStack(spacing: 4) {
                                CompactPreview(status: sample.status, state: sample.state)
                                Text(IslandWords.compactCount(sample.state) ?? sample.caption)
                                    .captionFont().foregroundStyle(Palette.muted)
                            }
                        }
                    }
                }

                section("展开（长按）") {
                    VStack(spacing: 12) {
                        ForEach(samples) { sample in
                            ExpandedPreview(status: sample.status, state: sample.state, now: now)
                        }
                    }
                }
            }
            .padding(16)
        }
        .background(Palette.page)
        .navigationTitle("灵动岛样子")
        .navigationBarTitleDisplayMode(.inline)
    }

    private func section<Content: View>(_ title: String, @ViewBuilder content: () -> Content) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            Text(title).smallBodyFont().foregroundStyle(Palette.ink)
            content()
        }
    }
}

/// The compact island: about 126 × 37 points, black; 遥应's mark on the left, a fixed-width right side (0.6.2) so the
/// island does not grow with the timer.
private struct CompactPreview: View {
    let status: IslandStatus
    let state: IslandState

    var body: some View {
        HStack(spacing: 0) {
            Image("TeleplyMark")
                .renderingMode(.template)
                .resizable()
                .scaledToFit()
                .frame(width: 15, height: 15)
                .foregroundStyle(.white)
            Spacer(minLength: 0)
            trailing
                .lineLimit(1)
                .minimumScaleFactor(0.8)
                .multilineTextAlignment(.trailing)
                .frame(width: CGFloat(IslandMetrics.compactTrailing), alignment: .trailing)
        }
        .padding(.horizontal, 10)
        .frame(width: 126, height: 37)
        .background(Color.black, in: Capsule())
        .environment(\.colorScheme, .dark)
    }

    @ViewBuilder private var trailing: some View {
        if let count = IslandWords.compactCount(state) {
            Text(count)
                .font(.system(size: 13, weight: .semibold))
                .foregroundStyle((state.waiting ?? 0) > 0 ? Palette.askGo : .white)
        } else {
            switch status {
            case .working:
                Text("4:31").font(.system(size: 13, weight: .medium)).monospacedDigit().foregroundStyle(.white)
            case .waiting:
                Text("等你").font(.system(size: 13, weight: .semibold)).foregroundStyle(Palette.askGo)
            case .done:
                Image(systemName: "checkmark").font(.system(size: 13, weight: .bold)).foregroundStyle(Palette.success)
            case .failed:
                Image(systemName: "exclamationmark").font(.system(size: 13, weight: .bold)).foregroundStyle(Palette.danger)
            case .offline:
                Text("断开").font(.system(size: 13, weight: .medium)).foregroundStyle(Palette.muted)
            case .limited:
                Text("2:13").font(.system(size: 13, weight: .medium)).monospacedDigit().foregroundStyle(Palette.askGo)
            }
        }
    }
}

/// The expanded island: title row and one line under it, about 340 points wide.
private struct ExpandedPreview: View {
    let status: IslandStatus
    let state: IslandState
    let now: Int

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            if let counts = IslandWords.counts(state), counts.total >= 2 {
                HStack(spacing: 8) {
                    Image("TeleplyMark")
                        .renderingMode(.template)
                        .resizable()
                        .scaledToFit()
                        .frame(width: 15, height: 15)
                    Text(IslandWords.aggregate(state) ?? "")
                        .font(.system(size: 13, weight: .semibold)).lineLimit(1)
                    Spacer(minLength: 8)
                }
                ForEach(Array((state.peers ?? []).prefix(3)), id: \.chat) { peer in
                    HStack(spacing: 8) {
                        SourceMark(app: peer.app, size: 13)
                        Text(peer.title.isEmpty ? IslandWords.appName(peer.app) : peer.title)
                            .font(.system(size: 12)).lineLimit(1)
                        Spacer(minLength: 8)
                        Text(peer.status == .waiting ? "等你" : "4:31")
                            .font(.system(size: 12, weight: .medium))
                            .foregroundStyle(peer.status == .waiting ? Palette.askGo : .white)
                    }
                }
            } else {
                HStack(spacing: 8) {
                    SourceMark(app: "claude", size: 16)
                    Text("Claude · 我的电脑").font(.system(size: 13, weight: .semibold)).lineLimit(1)
                    Spacer(minLength: 8)
                    trailing
                }
                Text(IslandWords.detail(state, now: now)).font(.system(size: 13)).foregroundStyle(.white)
                    .lineLimit(1)
            }
        }
        .padding(14)
        .frame(width: 340, alignment: .leading)
        .background(Color.black, in: RoundedRectangle(cornerRadius: 26, style: .continuous))
        .environment(\.colorScheme, .dark)
        .foregroundStyle(.white)
    }

    @ViewBuilder private var trailing: some View {
        switch status {
        case .working, .offline:
            Text("4:31").font(.system(size: 14, weight: .medium)).monospacedDigit()
        case .waiting:
            Text("等你").font(.system(size: 14, weight: .semibold)).foregroundStyle(Palette.askGo)
        case .done:
            Image(systemName: "checkmark").font(.system(size: 14, weight: .bold)).foregroundStyle(Palette.success)
        case .failed:
            Image(systemName: "exclamationmark").font(.system(size: 14, weight: .bold)).foregroundStyle(Palette.danger)
        case .limited:
            Text("2:13:05").font(.system(size: 14, weight: .medium)).monospacedDigit().foregroundStyle(Palette.askGo)
        }
    }
}

/// The lock-screen card: drawn once in light and once in dark (0.6.2), white or dark like the lock screen's own
/// notifications, about the width of the screen minus its margins.
private struct LockCardPreview: View {
    let status: IslandStatus
    let state: IslandState
    let now: Int
    let scheme: ColorScheme

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            if let counts = IslandWords.counts(state), counts.total >= 2 {
                HStack(spacing: 8) {
                    Image("TeleplyMark")
                        .renderingMode(.template)
                        .resizable()
                        .scaledToFit()
                        .frame(width: 18, height: 18)
                        .foregroundStyle(Palette.ink)
                    Text(IslandWords.aggregate(state) ?? "")
                        .font(.system(size: 15, weight: .semibold)).foregroundStyle(Palette.ink).lineLimit(1)
                    Spacer(minLength: 8)
                }
                ForEach(Array((state.peers ?? []).prefix(3)), id: \.chat) { peer in
                    HStack(spacing: 7) {
                        SourceMark(app: peer.app, size: 15)
                        Text(peer.title.isEmpty ? IslandWords.appName(peer.app) : peer.title)
                            .font(.system(size: 13)).foregroundStyle(Palette.ink).lineLimit(1)
                        Spacer(minLength: 6)
                        Text(peer.status == .waiting ? "等你" : "4:31")
                            .font(.system(size: 13, weight: .medium))
                            .foregroundStyle(peer.status == .waiting ? Palette.askGo : Palette.ink)
                    }
                }
            } else {
                HStack(spacing: 8) {
                    SourceMark(app: "claude", size: 20)
                    Text("Claude · 我的电脑").font(.system(size: 15, weight: .semibold)).foregroundStyle(Palette.ink).lineLimit(1)
                    Spacer(minLength: 8)
                    if let symbol = IslandWords.symbol(status) {
                        Image(systemName: symbol).font(.system(size: 14, weight: .bold))
                            .foregroundStyle(IslandWords.colorRole(status) == .success ? Palette.success
                                             : IslandWords.colorRole(status) == .danger ? Palette.danger : Palette.muted)
                    }
                }
                HStack(spacing: 6) {
                    Text(IslandWords.detail(state, now: now)).font(.system(size: 13))
                        .foregroundStyle(IslandWords.colorRole(status) == .muted ? Palette.muted : Palette.ink)
                        .lineLimit(1)
                    if status == .working || status == .offline {
                        Text("4:31").font(.system(size: 13, weight: .medium)).monospacedDigit().foregroundStyle(Palette.ink)
                    }
                }
            }
        }
        .padding(14)
        .background(Palette.cardBackground, in: RoundedRectangle(cornerRadius: 20, style: .continuous))
        .environment(\.colorScheme, scheme)
    }
}
