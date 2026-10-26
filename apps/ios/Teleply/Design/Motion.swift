import SwiftUI

/// The web's --ease, cubic-bezier(.2,.8,.2,1).
extension Animation {
    static func teleplyEase(_ duration: Double) -> Animation { .timingCurve(0.2, 0.8, 0.2, 1, duration: duration) }
}

/// The account page's entrance (web .rise, spec 5): 14 pt up out of a 6 pt blur into place over 700 ms,
/// [index] × 70 ms after the first part. A new [key] plays it again (a form switched, a computer added). With
/// Reduce Motion only a short fade is left.
private struct Rise: ViewModifier {
    let index: Int
    let key: AnyHashable
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var shown = false

    func body(content: Content) -> some View {
        content
            .opacity(shown ? 1 : 0)
            .offset(y: shown || reduceMotion ? 0 : 14)
            .blur(radius: shown || reduceMotion ? 0 : 6)
            .task(id: key) {
                var still = Transaction()
                still.disablesAnimations = true
                withTransaction(still) { shown = false }
                if !reduceMotion, index > 0 {
                    try? await Task.sleep(for: .milliseconds(70 * index))
                }
                withAnimation(reduceMotion ? .easeOut(duration: 0.08) : .teleplyEase(0.7)) { shown = true }
            }
    }
}

extension View {
    func rise(_ index: Int, key: AnyHashable = 0) -> some View {
        modifier(Rise(index: index, key: key))
    }
}

/// The thin line under a title bar while a page reads (spec 5): it shows only when the wait lasts past 400 ms,
/// so a quick read does not flash it. No made-up percentage: a short accent stretch runs across.
struct DelayedProgressLine: View {
    let busy: Bool
    @State private var shown = false

    var body: some View {
        ZStack {
            if busy && shown {
                RunningBar()
                    .accessibilityElement()
                    .accessibilityLabel(Text("正在读取"))
            }
        }
        .frame(maxWidth: .infinity)
        .frame(height: 2)
        .task(id: busy) {
            guard busy else {
                shown = false
                return
            }
            try? await Task.sleep(for: .milliseconds(400))
            if !Task.isCancelled { shown = true }
        }
    }
}

private struct RunningBar: View {
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var phase: CGFloat = -0.4

    var body: some View {
        GeometryReader { geometry in
            if reduceMotion {
                Rectangle().fill(Palette.accent.opacity(0.6))
            } else {
                Capsule()
                    .fill(Palette.accent)
                    .frame(width: geometry.size.width * 0.4)
                    .offset(x: geometry.size.width * phase)
            }
        }
        .clipped()
        .onAppear {
            guard !reduceMotion else { return }
            withAnimation(.linear(duration: 1.1).repeatForever(autoreverses: false)) { phase = 1 }
        }
    }
}
