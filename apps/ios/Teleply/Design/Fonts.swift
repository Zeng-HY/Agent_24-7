import SwiftUI

/// The web's sizes in points that grow with the system text size (spec 2.1, 2.3): at the default text size a
/// view gets the web's size, and it scales the way [relativeTo] does. [lineHeight] is the web's line-height
/// factor (1.7 for answers), a multiple of the point size like CSS.
private struct ScaledFont: ViewModifier {
    @ScaledMetric private var size: CGFloat
    private let weight: Font.Weight
    private let design: Font.Design
    private let lineHeight: CGFloat?

    init(size: CGFloat, weight: Font.Weight, design: Font.Design, relativeTo style: Font.TextStyle, lineHeight: CGFloat?) {
        _size = ScaledMetric(wrappedValue: size, relativeTo: style)
        self.weight = weight
        self.design = design
        self.lineHeight = lineHeight
    }

    func body(content: Content) -> some View {
        if let lineHeight {
            content
                .font(.system(size: size, weight: weight, design: design))
                .lineHeight(.multiple(factor: lineHeight))
        } else {
            content.font(.system(size: size, weight: weight, design: design))
        }
    }
}

extension View {
    func scaledFont(_ size: CGFloat, _ weight: Font.Weight = .regular, design: Font.Design = .default,
                    relativeTo style: Font.TextStyle = .body, lineHeight: CGFloat? = nil) -> some View {
        modifier(ScaledFont(size: size, weight: weight, design: design, relativeTo: style, lineHeight: lineHeight))
    }
}

/// Spec 2.3's sizes by use, so pages name the use instead of repeating numbers.
extension View {
    /// 列表页大标题"对话" 20/600.
    func titleFont() -> some View { scaledFont(20, .semibold, relativeTo: .title3) }
    /// 会话页标题 17/600; sheet titles.
    func chatTitleFont() -> some View { scaledFont(17, .semibold, relativeTo: .headline) }
    /// Card and sheet section titles 16/600.
    func headingFont() -> some View { scaledFont(16, .semibold, relativeTo: .callout) }
    /// Row titles and plain body text 16, line height 1.5.
    func bodyFont(_ weight: Font.Weight = .regular) -> some View { scaledFont(16, weight, relativeTo: .body, lineHeight: 1.5) }
    /// Answers and user messages 16, line height 1.7 (web .bub).
    func readingFont() -> some View { scaledFont(16, relativeTo: .body, lineHeight: 1.7) }
    /// The process area, tool records and question history 14, line height 1.55.
    func processFont() -> some View { scaledFont(14, relativeTo: .subheadline, lineHeight: 1.55) }
    /// Secondary body text 14.
    func smallBodyFont(_ weight: Font.Weight = .regular) -> some View { scaledFont(14, weight, relativeTo: .subheadline, lineHeight: 1.5) }
    /// Buttons 14/500.
    func buttonFont() -> some View { scaledFont(14, .medium, relativeTo: .subheadline) }
    /// Notes and helper text 13 (Android note).
    func noteFont(_ weight: Font.Weight = .regular) -> some View { scaledFont(13, weight, relativeTo: .footnote, lineHeight: 1.46) }
    /// Times, meta lines and small labels 12.
    func captionFont(_ weight: Font.Weight = .regular) -> some View { scaledFont(12, weight, relativeTo: .caption) }
    /// Code 13 monospaced, line height 1.6 (web .code-wrap pre).
    func codeFont() -> some View { scaledFont(13, design: .monospaced, relativeTo: .footnote, lineHeight: 1.6) }
}
