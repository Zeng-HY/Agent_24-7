import SwiftUI

/*
 * The opening pages' parts as the web's account page (relay_account.html/.css; Android AccountUi.kt): fields that
 * lift their label and light up when typed in, one strong button that gives a little under the finger and spins
 * while it waits, small grey text buttons, and the message line under the form.
 */

/// A field with its label inside that lifts and shrinks when typed in (web .field): 60 pt, 18 pt corners, grey;
/// white with a soft shadow while typed in on light. The password field has 显示 / 隐藏 at its end.
struct AccountField: View {
    let label: String
    @Binding var text: String
    var password = false
    var content: UITextContentType?
    var keyboard: UIKeyboardType = .default
    var submit: SubmitLabel = .next
    var onSubmit: () -> Void = {}

    @FocusState private var focused: Bool
    @State private var shown = false
    @Environment(\.colorScheme) private var scheme

    var body: some View {
        let lifted = focused || !text.isEmpty
        let lit = focused && scheme == .light
        ZStack(alignment: .topLeading) {
            Text(LK(label))
                .scaledFont(16, relativeTo: .body)
                .foregroundStyle(focused ? AccountPalette.ink : AccountPalette.muted)
                .scaleEffect(lifted ? 0.75 : 1, anchor: .topLeading)
                .offset(y: lifted ? -11 : 0)
                .padding(.leading, 18)
                .padding(.top, 19)
                .allowsHitTesting(false)
                .accessibilityHidden(true)
            HStack(spacing: 0) {
                field
                    .padding(.leading, 18)
                    .padding(.trailing, password ? 4 : 18)
                    .padding(.top, 25)
                    .padding(.bottom, 9)
                if password {
                    Button(shown ? "隐藏" : "显示") { shown.toggle() }
                        .scaledFont(13, relativeTo: .footnote)
                        .foregroundStyle(AccountPalette.muted)
                        .padding(.horizontal, 12)
                        .frame(minHeight: 44)
                        .contentShape(Rectangle())
                        .accessibilityLabel(Text(shown ? "隐藏密码" : "显示密码"))
                        .padding(.trailing, 8)
                }
            }
        }
        .frame(minHeight: 60)
        .background {
            RoundedRectangle(cornerRadius: 18, style: .continuous)
                .fill(lit ? Color.white : AccountPalette.soft)
                .shadow(color: .black.opacity(lit ? 0.09 : 0), radius: 12, y: 6)
        }
        .overlay(RoundedRectangle(cornerRadius: 18, style: .continuous).stroke(AccountPalette.edge, lineWidth: 1))
        .contentShape(RoundedRectangle(cornerRadius: 18, style: .continuous))
        .onTapGesture { focused = true }
        .animation(.teleplyEase(0.3), value: lifted)
        .animation(.teleplyEase(0.3), value: focused)
    }

    @ViewBuilder
    private var field: some View {
        Group {
            if password && !shown {
                SecureField("", text: $text)
            } else {
                TextField("", text: $text)
            }
        }
        .focused($focused)
        .scaledFont(16, relativeTo: .body)
        .foregroundStyle(AccountPalette.ink)
        .tint(AccountPalette.ink)
        .textInputAutocapitalization(.never)
        .autocorrectionDisabled()
        .keyboardType(keyboard)
        .textContentType(content)
        .submitLabel(submit)
        .onSubmit(onSubmit)
        .accessibilityLabel(Text(LK(label)))
    }
}

/// The page's one strong button (web .primary): 56 pt, 18 pt corners, a shadow on light; gives to 0.98 when
/// pressed and spins while busy. Filled with the iOS main-button colour (spec 2.2).
struct AccountButtonStyle: ButtonStyle {
    var busy = false

    func makeBody(configuration: Configuration) -> some View {
        AccountButtonBody(configuration: configuration, busy: busy)
    }
}

private struct AccountButtonBody: View {
    let configuration: ButtonStyleConfiguration
    let busy: Bool
    @Environment(\.isEnabled) private var isEnabled
    @Environment(\.colorScheme) private var scheme
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        let pressed = configuration.isPressed
        let raised = scheme == .light && isEnabled
        ZStack {
            if busy {
                ProgressView()
                    .tint(Palette.onPrimary)
            } else {
                configuration.label
                    .scaledFont(16, .semibold, relativeTo: .body)
                    .tracking(0.2)
                    .foregroundStyle(Palette.onPrimary)
            }
        }
        .frame(maxWidth: .infinity, minHeight: 56)
        .background {
            RoundedRectangle(cornerRadius: 18, style: .continuous)
                .fill(Palette.primaryFill.opacity(isEnabled || busy ? 1 : 0.45))
                .shadow(color: .black.opacity(raised ? (pressed ? 0.12 : 0.2) : 0), radius: pressed ? 4 : 9, y: pressed ? 3 : 7)
        }
        .contentShape(RoundedRectangle(cornerRadius: 18, style: .continuous))
        .scaleEffect(pressed && !reduceMotion ? 0.98 : 1)
        .animation(.teleplyEase(0.25), value: pressed)
    }
}

/// A small grey button under the form (web .text-button).
struct AccountTextButton: View {
    let title: String
    let action: () -> Void

    var body: some View {
        Button(LK(title), action: action)
            .scaledFont(14, relativeTo: .subheadline)
            .foregroundStyle(AccountPalette.muted)
            .padding(.horizontal, 12)
            .padding(.vertical, 10)
            .contentShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
    }
}

/// The line under a page (web #message): errors in red; a change comes up out of a blur. The app's own lines are
/// looked up in the string catalog; the relay's words come translated already (Hints) or as they are.
struct AccountMessage: View {
    let text: String?
    let error: Bool
    var action: String?
    var onAction: () -> Void = {}

    var body: some View {
        if let text, !text.isEmpty {
            VStack(spacing: 0) {
                Text(LK(text))
                    .scaledFont(14, relativeTo: .subheadline, lineHeight: 1.7)
                    .foregroundStyle(error ? AccountPalette.danger : AccountPalette.muted)
                    .multilineTextAlignment(.center)
                    .padding(.horizontal, 8)
                if let action {
                    AccountTextButton(title: action, action: onAction)
                }
            }
            .frame(maxWidth: .infinity)
            .padding(.top, 24)
            .rise(0, key: text)
            .task(id: text) { AccessibilityNotification.Announcement(L(text)).post() }
        }
    }
}
