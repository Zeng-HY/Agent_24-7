import SwiftUI
import TeleplyModel

/// A source's own mark (spec 2.4, 4.2): Codex's cloud in ink, Claude's orange and DeepSeek's blue, from the
/// vector assets made out of Android Brand.kt.
struct SourceMark: View {
    let app: String
    var size: CGFloat = 18

    var body: some View {
        Image(asset)
            .renderingMode(.template)
            .resizable()
            .scaledToFit()
            .frame(width: size, height: size)
            .foregroundStyle(Palette.tint(app))
            .accessibilityHidden(true)
    }

    private var asset: String {
        switch app {
        case "claude": return "ClaudeMark"
        case "deepseek": return "DeepSeekMark"
        default: return "CodexMark"
        }
    }
}

/// The list's source badge (web .badge): the source name in 11 pt semibold white on its colour, 6 pt corners.
struct SourceBadge: View {
    let app: String

    var body: some View {
        Text(verbatim: Labels.sourceName(app))
            .scaledFont(11, .semibold, relativeTo: .caption2)
            .foregroundStyle(.white)
            .lineLimit(1)
            .fixedSize()
            .padding(.horizontal, 6)
            .padding(.vertical, 2)
            .background(Palette.badge(app), in: RoundedRectangle(cornerRadius: 6, style: .continuous))
    }
}

/// The Teleply mark and name (web .brand): 30 pt mark and 17 pt semibold name above 登录; 36 pt and 26 pt on
/// 我的电脑. #111113 on light, white on dark (spec 2.4).
struct BrandHeader: View {
    var home = false
    @ScaledMetric(relativeTo: .headline) private var smallMark: CGFloat = 30
    @ScaledMetric(relativeTo: .title) private var largeMark: CGFloat = 36

    var body: some View {
        HStack(spacing: home ? 12 : 10) {
            Image("TeleplyMark")
                .renderingMode(.template)
                .resizable()
                .scaledToFit()
                .frame(width: home ? largeMark : smallMark, height: home ? largeMark : smallMark)
            Text(verbatim: "Teleply")
                .scaledFont(home ? 26 : 17, .semibold, relativeTo: home ? .title : .headline)
                .tracking(home ? -0.7 : -0.3)
        }
        .foregroundStyle(Palette.brandInk)
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(Text(verbatim: "Teleply"))
        .accessibilityAddTraits(.isHeader)
    }
}

/// A full-width note under a title bar (web .connection-note / .notice; Android NoteBar): amber for the
/// connection, red for errors, plain for information, with an optional text button.
struct NoteBar: View {
    enum Tone { case connection, error, info }

    let text: String
    let tone: Tone
    var action: String?
    var actionEnabled = true
    var onAction: () -> Void = {}

    var body: some View {
        HStack(spacing: 10) {
            Image(systemName: tone == .info ? "info.circle" : "exclamationmark.triangle")
                .font(.system(size: 14, weight: .medium))
                .foregroundStyle(ink)
                .accessibilityHidden(true)
            Text(text)
                .noteFont()
                .foregroundStyle(ink)
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(.vertical, 8)
            if let action {
                Button(action, action: onAction)
                    .buttonStyle(PillStyle(kind: .text, minHeight: 36))
                    .disabled(!actionEnabled)
            }
        }
        .padding(.leading, 16)
        .padding(.trailing, 4)
        .frame(minHeight: 44)
        .background(fill)
        .accessibilityElement(children: .combine)
    }

    private var fill: Color {
        switch tone {
        case .connection: return Palette.noteFill
        case .error: return Palette.stopFill
        case .info: return Palette.panel
        }
    }

    private var ink: Color {
        switch tone {
        case .connection: return Palette.noteInk
        case .error: return Palette.danger
        case .info: return Palette.muted
        }
    }
}

/// A short line that comes and goes at the bottom (Android NoticeToast): 归档、恢复、复制… Taps dismiss it.
struct NoticeToast: View {
    let text: String?
    let dismiss: () -> Void

    var body: some View {
        ZStack {
            if let text {
                Text(text)
                    .smallBodyFont()
                    .foregroundStyle(Palette.page)
                    .multilineTextAlignment(.center)
                    .padding(.horizontal, 18)
                    .padding(.vertical, 10)
                    .background(Palette.ink.opacity(0.92), in: Capsule())
                    .padding(.horizontal, 24)
                    .onTapGesture(perform: dismiss)
                    .transition(.opacity.combined(with: .move(edge: .bottom)))
                    .accessibilityAddTraits(.isStaticText)
                    .task(id: text) {
                        AccessibilityNotification.Announcement(text).post()
                        try? await Task.sleep(for: .seconds(4))
                        if !Task.isCancelled { dismiss() }
                    }
            }
        }
        .animation(.easeOut(duration: 0.2), value: text)
    }
}
