import SwiftUI

/// A text box inside a page or a card (web .field; Android TeleplyTextField): the card colour, a thin edge that
/// turns accent while typing, 16 pt corners.
struct FieldBox: ViewModifier {
    var focused = false
    var multiline = false

    func body(content: Content) -> some View {
        content
            .bodyFont()
            .foregroundStyle(Palette.ink)
            .tint(Palette.accent)
            .padding(.horizontal, 14)
            .padding(.vertical, multiline ? 12 : 0)
            .frame(minHeight: 48)
            .background(Palette.sheet, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
            .overlay(RoundedRectangle(cornerRadius: 16, style: .continuous).stroke(focused ? Palette.accent : Palette.line, lineWidth: 1))
    }
}

extension View {
    func fieldBox(focused: Bool = false, multiline: Bool = false) -> some View {
        modifier(FieldBox(focused: focused, multiline: multiline))
    }
}
