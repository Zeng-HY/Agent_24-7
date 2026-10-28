import SwiftUI
import TeleplyIsland

/// 设置 → 开发者选项 → 灵动岛样子 (handoff 5.4): the island's states as near to their real sizes as a page can draw
/// them, so the look can be discussed before a build reaches the phone. The real island is Apple's; this is a sketch.
struct IslandPreviewPage: View {
    private let now = Int(Date().timeIntervalSince1970)

    private struct Sample: Identifiable {
        let status: IslandStatus
        let state: IslandState
        var id: String { status.rawValue }
    }

    private var samples: [Sample] {
        [
            Sample(status: .working, state: IslandState(status: .working, since: now - 271, turn: now - 271)),
            Sample(status: .waiting, state: IslandState(status: .waiting, since: now - 30, turn: now - 180,
                                                       askType: "permission", choices: 2)),
            Sample(status: .done, state: IslandState(status: .done, since: now - 5, turn: now - 377)),
            Sample(status: .failed, state: IslandState(status: .failed, since: now - 20, turn: now - 300)),
            Sample(status: .offline, state: IslandState(status: .offline, since: now - 185, turn: now - 400)),
            Sample(status: .limited, state: IslandState(status: .limited, since: now - 30, turn: now - 300,
                                                       resets: now + 7985)),
        ]
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 24) {
                Text("真机上灵动岛一次只显示最要紧的一个；这里是各种状态的样子，尺寸是按苹果的规格近似画的。")
                    .noteFont()
                    .foregroundStyle(Palette.muted)

                section("紧凑（灵动岛）") {
                    LazyVGrid(columns: [GridItem(.adaptive(minimum: 132), spacing: 10)], alignment: .leading, spacing: 10) {
                        ForEach(samples) { sample in
                            VStack(spacing: 4) {
                                CompactPreview(status: sample.status, state: sample.state)
                                Text(IslandWords.state(sample.status)).captionFont().foregroundStyle(Palette.muted)
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

                section("锁屏卡片") {
                    VStack(spacing: 12) {
                        ForEach(samples) { sample in
                            LockCardPreview(status: sample.status, state: sample.state, now: now)
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

/// The compact island: about 126 × 37 points, black, mark on the left and at most four characters on the right.
private struct CompactPreview: View {
    let status: IslandStatus
    let state: IslandState

    var body: some View {
        HStack(spacing: 0) {
            SourceMark(app: "claude", size: 15)
            Spacer(minLength: 0)
            trailing
        }
        .padding(.horizontal, 10)
        .frame(width: 126, height: 37)
        .background(Color.black, in: Capsule())
        .environment(\.colorScheme, .dark)
    }

    @ViewBuilder private var trailing: some View {
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

/// The expanded island: title row and one line under it, about 340 points wide.
private struct ExpandedPreview: View {
    let status: IslandStatus
    let state: IslandState
    let now: Int

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 8) {
                SourceMark(app: "claude", size: 16)
                Text("Claude · 我的电脑").font(.system(size: 13, weight: .semibold)).lineLimit(1)
                Spacer(minLength: 8)
                trailing
            }
            Text(IslandWords.detail(state, now: now)).font(.system(size: 13)).foregroundStyle(.white)
                .lineLimit(1)
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

/// The lock-screen card: follows the system's appearance, about the width of the screen minus its margins.
private struct LockCardPreview: View {
    let status: IslandStatus
    let state: IslandState
    let now: Int

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
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
        .padding(14)
        .background(Palette.panel, in: RoundedRectangle(cornerRadius: 20, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: 20, style: .continuous).stroke(Palette.line, lineWidth: 0.5))
    }
}
