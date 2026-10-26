import SwiftUI

/// A page's one main action as a filled capsule (spec 3 主操作). The button owns its text colour, so a
/// foreground style set on the surrounding text cannot grey it out (0.1.0 build 1 on a real iPhone).
struct PrimaryCapsuleStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        PrimaryCapsule(configuration: configuration)
    }
}

private struct PrimaryCapsule: View {
    let configuration: ButtonStyleConfiguration

    // Spec 3: buttons 14 pt / 500, a 44 pt touch target, pressed scale 0.97 for about 100 ms.
    @ScaledMetric(relativeTo: .subheadline) private var textSize: CGFloat = 14
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @Environment(\.isEnabled) private var isEnabled

    var body: some View {
        configuration.label
            .font(.system(size: textSize, weight: .medium))
            .foregroundStyle(Palette.onPrimary)
            .padding(.horizontal, 22)
            .frame(minHeight: 44)
            .background(Palette.primaryFill, in: Capsule())
            .contentShape(Capsule())
            .opacity(isEnabled ? 1 : 0.4)
            .scaleEffect(configuration.isPressed && !reduceMotion ? 0.97 : 1)
            .animation(.easeOut(duration: 0.1), value: configuration.isPressed)
    }
}
