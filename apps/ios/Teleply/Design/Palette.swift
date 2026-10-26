import SwiftUI

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

    /// The source marks (web sidebar .mark; Android Brand.kt).
    static func tint(_ app: String) -> Color {
        switch app {
        case "claude": return Color("ClaudeTint")
        case "deepseek": return Color("DeepSeekTint")
        default: return Color("CodexTint")
        }
    }

    /// The list badges (web remote.html .badge).
    static func badge(_ app: String) -> Color {
        switch app {
        case "claude": return Color("ClaudeTint")
        case "deepseek": return Color("DeepSeekTint")
        default: return codexBadge
        }
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
