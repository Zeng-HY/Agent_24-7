import SwiftUI
import TeleplyModel
import UIKit

/// The web's colour values (remote.html :root, static/theme.css) as asset-catalog colours with a light and a
/// dark value each (spec 2.2). Views take colours by role, never a grey of their own.
enum Palette {
    static let page = Color("Page")
    static let panel = Color("Panel")
    static let controlFill = Color("ControlFill")
    static let sheet = Color("Sheet")
    static let line = Color("Line")
    static let controlBorder = Color("ControlBorder")
    static let ink = Color("Ink")
    static let muted = Color("Muted")
    static let accent = Color("Accent")
    static let onAccent = Color("OnAccent")
    static let selectedFill = Color("SelectedFill")
    static let selectedInk = Color("SelectedInk")
    static let success = Color("Success")
    static let warning = Color("Warning")
    static let danger = Color("Danger")
    static let questionDot = Color("QuestionDot")
    static let stopFill = Color("StopFill")
    static let stopInk = Color("StopInk")
    static let pressedRow = Color("PressedRow")
    /// The Teleply mark and name: #111113 on light, white on dark (spec 2.4).
    static let brandInk = Color("BrandInk")
    /// A filled main button and its text: ink on light like the web account page; #2563EB with white text on
    /// dark, where the web's #8AB4FF looked too pale on a real iPhone (user, 2026-10-26; spec 2.2).
    static let primaryFill = Color("PrimaryFill")
    static let onPrimary = Color("OnPrimary")

    // Android Theme.kt values the spec table leaves out.
    /// 等待你处理 in the list and the question bar's 去选择 ›.
    static let askGo = Color("AskGo")
    static let noteFill = Color("NoteFill")
    static let noteInk = Color("NoteInk")
    /// The user's bubble: accent with white text on light; #1E1E1E with a #333 edge on dark (web .bub.user).
    static let bubble = Color("Bubble")
    static let onBubble = Color("OnBubble")
    static let bubbleEdge = Color("BubbleEdge")
    static let codeFill = Color("CodeFill")
    static let codeEdge = Color("CodeEdge")
    /// Behind the sidebar.
    static let scrim = Color("Scrim")
    static let groupPressed = Color("GroupPressed")
    static let codexBadge = Color("CodexBadge")
    /// The lock-screen card's own background and system-action colour (0.6.2): white on light, dark on dark, like the
    /// lock screen's notifications. The island extension keeps identical copies; ci-check.sh compares them.
    static let cardBackground = Color("CardBackground")
    static let cardForeground = Color("CardForeground")

    /// The source marks (web sidebar .mark; Android Brand.kt). The three keep their own asset colours; any other
    /// assistant takes the colour its computer's manifest gives, or the neutral grey (handoff 3.3).
    static func tint(_ app: String) -> Color {
        switch app {
        case "codex": return Color("CodexTint")
        case "claude": return Color("ClaudeTint")
        case "deepseek": return Color("DeepSeekTint")
        default: return agentColor(app)
        }
    }

    /// The list badges (web remote.html .badge).
    static func badge(_ app: String) -> Color {
        switch app {
        case "claude": return Color("ClaudeTint")
        case "deepseek": return Color("DeepSeekTint")
        case "codex": return codexBadge
        default: return color(hex: AgentCatalogSnapshot.current.badgeColor(app)) ?? muted
        }
    }

    /// A new assistant's mark colour, light and dark, from its manifest; the neutral grey when it gave none.
    private static func agentColor(_ app: String) -> Color {
        let catalog = AgentCatalogSnapshot.current
        guard let light = color(hex: catalog.color(app)), let dark = color(hex: catalog.color(app, dark: true)) else { return muted }
        return Color(uiColor: UIColor(dynamicProvider: { traits in
            UIColor(traits.userInterfaceStyle == .dark ? dark : light)
        }))
    }

    /// `#RRGGBB` or `#AARRGGBB` as a colour; nil when it is neither (the computer's value is never trusted).
    static func color(hex: String) -> Color? {
        var digits = hex.trimmingCharacters(in: .whitespaces)
        if digits.hasPrefix("#") { digits.removeFirst() }
        guard digits.count == 6 || digits.count == 8, let value = UInt32(digits, radix: 16) else { return nil }
        return Color(.sRGB,
                     red: Double((value >> 16) & 0xFF) / 255,
                     green: Double((value >> 8) & 0xFF) / 255,
                     blue: Double(value & 0xFF) / 255,
                     opacity: digits.count == 8 ? Double((value >> 24) & 0xFF) / 255 : 1)
    }
}

/// The account pages' own colours (relay_account.css; Android AccountColors). Their filled button is
/// [Palette.primaryFill], as everywhere on iOS.
enum AccountPalette {
    static let page = Palette.page
    static let ink = Color("AccountInk")
    static let soft = Color("AccountSoft")
    static let muted = Color("AccountMuted")
    static let danger = Color("AccountDanger")
    static let edge = Color("AccountEdge")
    static let online = Color("AccountOnline")
    static let hint = Color("AccountHint")
}
