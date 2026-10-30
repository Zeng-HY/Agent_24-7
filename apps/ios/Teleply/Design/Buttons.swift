import SwiftUI

/// Our own buttons give a little under the finger (spec 3): 0.97 for about 100 ms, the send key 0.88; nothing
/// with Reduce Motion.
struct PressScaleStyle: ButtonStyle {
    var scale: CGFloat = 0.97

    func makeBody(configuration: Configuration) -> some View {
        PressScaled(configuration: configuration, scale: scale)
    }
}

private struct PressScaled: View {
    let configuration: ButtonStyleConfiguration
    let scale: CGFloat
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        configuration.label
            .scaleEffect(configuration.isPressed && !reduceMotion ? scale : 1)
            .animation(.easeOut(duration: 0.1), value: configuration.isPressed)
    }
}

/// A list row that takes the pressed colour while held (spec 3: #EEF0F4 light, #292929 dark).
struct RowPressStyle: ButtonStyle {
    var radius: CGFloat = 8
    var pressed = Palette.pressedRow

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .contentShape(Rectangle())
            .background(configuration.isPressed ? pressed : .clear, in: RoundedRectangle(cornerRadius: radius, style: .continuous))
    }
}

/// The web's pill buttons (Android PillButton): secondary is a light capsule with ink text, primary the filled
/// main button, text an accent word without a fill, danger the light red of 停止这一轮.
struct PillStyle: ButtonStyle {
    enum Kind { case secondary, primary, text, danger }

    var kind = Kind.secondary
    var minHeight: CGFloat = 44
    /// Takes the whole width it is given (a card's 提交回答, 执行计划).
    var wide = false

    func makeBody(configuration: Configuration) -> some View {
        Pill(configuration: configuration, kind: kind, minHeight: minHeight, wide: wide)
    }
}

private struct Pill: View {
    let configuration: ButtonStyleConfiguration
    let kind: PillStyle.Kind
    let minHeight: CGFloat
    let wide: Bool
    @Environment(\.isEnabled) private var isEnabled
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        configuration.label
            .buttonFont()
            .lineLimit(1)
            .foregroundStyle(ink)
            .padding(.horizontal, kind == .text ? 10 : 16)
            .frame(maxWidth: wide ? .infinity : nil, minHeight: minHeight)
            .background(fill, in: Capsule())
            .contentShape(Capsule())
            .opacity(isEnabled ? 1 : 0.35)
            .scaleEffect(configuration.isPressed && !reduceMotion ? 0.97 : 1)
            .animation(.easeOut(duration: 0.1), value: configuration.isPressed)
    }

    private var fill: Color {
        switch kind {
        case .secondary: return Palette.controlFill
        case .primary: return Palette.primaryFill
        case .text: return .clear
        case .danger: return Palette.stopFill
        }
    }

    private var ink: Color {
        switch kind {
        case .secondary: return Palette.ink
        case .primary: return Palette.onPrimary
        case .text: return Palette.accent
        case .danger: return Palette.stopInk
        }
    }
}

/// A round icon button inside a page (spec 2.4): system glass, 44 pt, about 22 pt icon. Title-bar buttons are
/// drawn by the navigation bar instead.
struct GlassIconButton: View {
    let symbol: String
    let label: String
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            Image(systemName: symbol)
                .font(.system(size: 17, weight: .medium))
                .frame(width: 30, height: 30)
        }
        .buttonStyle(.glass)
        .buttonBorderShape(.circle)
        .accessibilityLabel(Text(L(label)))
    }
}
