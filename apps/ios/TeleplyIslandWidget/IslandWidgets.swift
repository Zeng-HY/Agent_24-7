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
    var body: some WidgetConfiguration {
        ActivityConfiguration(for: IslandAttributes.self) { context in
            LockScreenCard(attributes: context.attributes, state: context.state)
                .widgetURL(IslandURL.open(context.attributes.identity))
                .accessibilityElement(children: .combine)
                .accessibilityLabel(IslandWords.accessibility(app: context.attributes.app, state: context.state,
                                                              now: Int(Date().timeIntervalSince1970)))
        } dynamicIsland: { context in
            DynamicIsland {
                DynamicIslandExpandedRegion(.leading) {
                    HStack(spacing: 6) {
                        IslandMark(app: context.attributes.app, size: 16)
                        Text(title(context.attributes))
                            .font(.system(size: 13, weight: .semibold))
                            .lineLimit(1)
                    }
                }
                DynamicIslandExpandedRegion(.trailing) {
                    ExpandedTrailing(status: context.state.status ?? .working)
                }
                DynamicIslandExpandedRegion(.bottom) {
                    HStack(spacing: 6) {
                        Text(IslandWords.detail(context.state, now: Int(Date().timeIntervalSince1970)))
                            .font(.system(size: 13))
                            .lineLimit(1)
                        if context.state.status == .working || context.state.status == .offline {
                            Elapsed(since: context.state.since)
                                .font(.system(size: 13, weight: .medium))
                        }
                        if let step = IslandWords.stepSymbol(context.state.step) {
                            Image(systemName: step)
                                .font(.system(size: 12, weight: .medium))
                        }
                        if IslandWords.isStale(context.state, now: Int(Date().timeIntervalSince1970)) {
                            Text("可能不是最新")
                                .font(.system(size: 11))
                                .foregroundStyle(IslandPalette.muted)
                        }
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .foregroundStyle(IslandPalette.ink)
                }
            } compactLeading: {
                IslandMark(app: context.attributes.app, size: 17, dot: context.state.status == .waiting)
            } compactTrailing: {
                Trailing(app: context.attributes.app, state: context.state, size: 13, compact: true)
            } minimal: {
                Minimal(app: context.attributes.app, state: context.state)
            }
            .widgetURL(IslandURL.open(context.attributes.identity))
            .keylineTint(IslandPalette.color(IslandWords.colorRole(context.state.status ?? .working),
                                             app: context.attributes.app))
        }
        // StandBy, Apple Watch's Smart Stack and CarPlay draw the .small size (handoff 方案五).
        .supplementalActivityFamilies([.small])
    }

    private func title(_ attributes: IslandAttributes) -> String {
        attributes.title.isEmpty ? "\(IslandWords.appName(attributes.app)) · \(attributes.computer)" : attributes.title
    }
}
