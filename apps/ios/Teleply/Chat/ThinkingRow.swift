import SwiftUI
import TeleplyIsland

/// 0.6.4: the line where the answer will appear while the source works, like the GPT app's "正在思考". Its timer
/// starts at the turn's recorded start (never at the phone's clock) and ticks by itself without a push. The width is
/// pinned so a longer reading cannot push the rest of the page around (the 0.6.2 timer lesson).
struct ThinkingRow: View {
    /// edit | run | search | read, when the computer says; "" means it is thinking; compact while it compacts (0.6.6).
    let step: String
    /// Unix seconds; 0 when the computer did not say, and then no timer is shown.
    let started: Int

    var body: some View {
        HStack(spacing: 7) {
            Image(systemName: "ellipsis.bubble")
                .font(.system(size: 13, weight: .medium))
                .foregroundStyle(Palette.muted)
            if started > 0 {
                TimelineView(.periodic(from: Date.now, by: 1)) { context in
                    Text(IslandWords.thinkingLine(step: step,
                                                  started: started,
                                                  now: Int(context.date.timeIntervalSince1970)))
                        .monospacedDigit()
                        .lineLimit(1)
                        .minimumScaleFactor(0.85)
                        .frame(width: 210, alignment: .leading)
                }
            } else {
                Text(verbatim: IslandWords.thinkingWords(step: step))
                    .lineLimit(1)
            }
            Spacer(minLength: 0)
        }
        .noteFont()
        .foregroundStyle(Palette.muted)
        .padding(.top, 14)
        .accessibilityElement(children: .combine)
    }
}
