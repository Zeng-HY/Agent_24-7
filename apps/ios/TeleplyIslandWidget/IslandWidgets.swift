import ActivityKit
import SwiftUI
import TeleplyIsland
import WidgetKit

/// 遥应's Live Activity (handoff 5): one island per conversation turn. The app starts it on this phone; the relay
/// updates it with pushes; this extension draws it in the Dynamic Island, on the lock screen, in StandBy and (as
/// `.small`) on Apple Watch and CarPlay.
///
/// The extension has no network and no shared storage: everything it shows comes from the attributes, the state and
/// its own copy of the source marks and colours.
@main
struct IslandWidgets: WidgetBundle {
    var body: some Widget {
        IslandLiveActivity()
    }
}

struct IslandLiveActivity: Widget {
    init() { IslandWords.language = Locale.current.language.languageCode?.identifier == "en" ? "en" : "zh-Hans" }

    var body: some WidgetConfiguration {
        ActivityConfiguration(for: IslandAttributes.self) { context in
            LockScreenCard(attributes: context.attributes, state: context.state)
                .widgetURL(openURL(context))
                .accessibilityElement(children: .combine)
                .accessibilityLabel(IslandWords.accessibility(app: context.attributes.app, state: context.state,
                                                              now: Int(Date().timeIntervalSince1970),
                                                              computer: context.attributes.computer))
        } dynamicIsland: { context in
            DynamicIsland {
                DynamicIslandExpandedRegion(.leading) {
                    HStack(spacing: 6) {
                        BrandMark(size: 15)
                        Text("遥应").font(.system(size: 13, weight: .semibold))
                    }
                    // 0.6.3: the expanded island's top corners used to clip the mark and this word (user 10-28).
                    .padding(.leading, 6)
                    .padding(.top, 3)
                }
                DynamicIslandExpandedRegion(.trailing) {
                    Text("\(IslandWords.counts(context.state)?.total ?? context.state.peers?.count ?? 1)")
                        .font(.system(size: 12, weight: .medium))
                        .monospacedDigit()
                        .fixedSize()
                        .padding(.trailing, 10)
                        .padding(.top, 3)
                        .foregroundStyle(IslandPalette.muted)
                        .accessibilityLabel("\(IslandWords.counts(context.state)?.total ?? context.state.peers?.count ?? 1) 个对话")
                }
                DynamicIslandExpandedRegion(.bottom) {
                    PeerList(device: context.attributes.device, state: context.state,
                             computer: context.attributes.computer)
                }
            } compactLeading: {
                BrandMark(size: 17, dot: (context.state.waiting ?? 0) > 0 || context.state.status == .waiting)
            } compactTrailing: {
                Trailing(app: context.attributes.app, state: context.state, size: 13, compact: true)
            } minimal: {
                Minimal(app: context.attributes.app, state: context.state)
            }
            .widgetURL(openURL(context))
            .keylineTint(IslandPalette.color(IslandWords.colorRole(context.state.status ?? .working),
                                             app: context.state.peers?.first?.app ?? context.attributes.app))
        }
        // StandBy, Apple Watch's Smart Stack and CarPlay draw the .small size (handoff 方案五).
        .supplementalActivityFamilies([.small])
    }

    /// A tap opens the conversation that wants the user: the one on screen's own island, or the first on a computer's
    /// island (waiting ones come first in the relay's list).
    private func openURL(_ context: ActivityViewContext<IslandAttributes>) -> URL? {
        if !context.attributes.chat.isEmpty { return IslandURL.open(context.attributes.identity) }
        // 0.6.5: a computer's card opens the list filtered to running conversations; a row still opens its own.
        return IslandURL.list(device: context.attributes.device, status: "running")
    }
}
