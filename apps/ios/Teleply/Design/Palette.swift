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
}
