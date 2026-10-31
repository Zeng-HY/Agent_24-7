import SwiftUI
import TeleplyModel
import TeleplyState

/// 登录 (spec 4.8; web #auth; Android LoginPage): the mark and name, 登录, 邮箱或账号, 密码 and the button. The
/// service is the default one, so there is nothing else to fill in; the gear opens 设置, where 开发者选项 holds
/// the service address and the local demo. While the service sends email, 创建账号 and 忘记密码 are forms of this same
/// page, as on the web (relay_account.js FORMS; nothing leaves for Safari): 注册 → 输入验证码, 发送验证码 → 重置密码, the
/// typed email carried from one to the next. Passwords are used once and never kept.
struct LoginView: View {
    let model: AppModel
    @Environment(Chrome.self) private var chrome
    @State private var name = ""
    @State private var password = ""
    /// The 验证码 field; the model keeps what counts (AppModel.enterCode) and empties it after a refusal.
    @State private var code = ""

    private var mode: AccountForms.Mode { model.fixture ? .login : model.forms.mode }

    private var ready: Bool {
        if model.fixture { return true }
        let typed = !name.trimmingCharacters(in: .whitespaces).isEmpty
        switch mode {
        case .login, .register: return typed && !password.isEmpty
        case .forgot: return typed
        case .verify: return model.forms.code.count == 6
        case .reset: return model.forms.code.count == 6 && !password.isEmpty
        }
    }

    var body: some View {
        GeometryReader { geometry in
            ScrollView {
                form
                    .frame(maxWidth: 380)
                    .padding(.top, max(48, geometry.size.height * 0.11))
                    .padding(.bottom, 32)
                    .padding(.horizontal, 24)
                    .frame(maxWidth: .infinity)
            }
            .scrollDismissesKeyboard(.interactively)
            .scrollBounceBehavior(.basedOnSize)
        }
        .background(AccountPalette.page.ignoresSafeArea())
        .overlay(alignment: .topTrailing) {
            if !model.fixture {
                GlassIconButton(symbol: "gearshape", label: "设置") { chrome.settings = true }
                    .padding(.trailing, 12)
                    .padding(.top, 4)
            }
        }
        .onChange(of: model.origin) { name = "" }
        // A password belongs to its form; the code follows the model, which empties it after a refusal or a resend.
        .onChange(of: model.forms.mode) { password = "" }
        .onChange(of: model.forms.code) { if code != model.forms.code { code = model.forms.code } }
        .onChange(of: code) {
            let digits = AccountInput.code(code)
            if digits != code { code = digits } else if digits != model.forms.code { model.enterCode(digits) }
        }
        .onDisappear { password = "" }
    }

    private var form: some View {
        VStack(spacing: 0) {
            BrandHeader()
                .frame(maxWidth: .infinity)
                .rise(0)
            Text(title)
                .scaledFont(30, .semibold, relativeTo: .largeTitle)
                .tracking(-0.8)
                .foregroundStyle(AccountPalette.ink)
                .frame(maxWidth: .infinity, alignment: .leading)
                .accessibilityAddTraits(.isHeader)
                .padding(.top, 44)
                .rise(1, key: formKey)
            if mode == .verify || mode == .reset {
                // Where the code went (web .sent-to).
                Text(verbatim: model.forms.email)
                    .scaledFont(15, relativeTo: .callout)
                    .foregroundStyle(AccountPalette.muted)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(.top, 8)
                    .rise(1, key: formKey)
            }
            Group {
                if model.fixture {
                    Text("示例无需真实账号或密码，数据都是固定的，不连接真实服务。")
                        .scaledFont(15, relativeTo: .callout, lineHeight: 1.6)
                        .foregroundStyle(AccountPalette.muted)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .rise(2, key: formKey)
                } else {
                    fields
                }
            }
            .padding(.top, 30)
            Button(button, action: submit)
                .buttonStyle(AccountButtonStyle(busy: model.busy && model.screen == .login))
                .disabled(!ready || model.busy)
                .padding(.top, 22)
                .rise(4, key: formKey)
            if mode == .verify || mode == .reset {
                ResendButton(model: model)
                    .padding(.top, 16)
                    .rise(5, key: formKey)
            }
            links
                .padding(.top, 16)
                .rise(5, key: formKey)
            AccountMessage(
                text: model.error ?? model.forms.said ?? (model.expired && mode == .login ? "登录已失效，请重新登录；回到原来的位置。" : nil),
                error: model.error != nil,
                action: offline ? "重试" : nil,
                onAction: model.retry
            )
        }
    }

    /// The entrance plays again when the form changes (web reveal on setMode).
    private var formKey: String { model.fixture ? "fixture" : mode.rawValue }

    private var title: LocalizedStringKey {
        if model.fixture { return "本地示例" }
        switch mode {
        case .login: return "登录"
        case .register: return "创建账号"
        case .verify: return "输入验证码"
        case .forgot: return "忘记密码"
        case .reset: return "重置密码"
        }
    }

    private var button: LocalizedStringKey {
        if model.fixture { return "进入示例" }
        switch mode {
        case .login: return "登录"
        case .register: return "注册"
        case .verify: return "验证"
        case .forgot: return "发送验证码"
        case .reset: return "保存密码"
        }
    }

    /// Each form's fields (web FORMS): the email field is the same one throughout, so what was typed carries over.
    @ViewBuilder
    private var fields: some View {
        VStack(spacing: 12) {
            switch mode {
            case .login:
                AccountField(label: "邮箱或账号", text: $name, content: .username, keyboard: .emailAddress)
                    .rise(2, key: formKey)
                AccountField(label: "密码", text: $password, password: true, content: .password, submit: .go, onSubmit: submit)
                    .rise(3, key: formKey)
            case .register:
                AccountField(label: "邮箱", text: $name, content: .username, keyboard: .emailAddress)
                    .rise(2, key: formKey)
                AccountField(label: "密码（至少 12 位）", text: $password, password: true, content: .newPassword, submit: .go, onSubmit: submit)
                    .rise(3, key: formKey)
            case .verify:
                AccountField(label: "验证码", text: $code, content: .oneTimeCode, keyboard: .numberPad, submit: .go, onSubmit: submit)
                    .rise(2, key: formKey)
            case .forgot:
                AccountField(label: "邮箱", text: $name, content: .username, keyboard: .emailAddress, submit: .go, onSubmit: submit)
                    .rise(2, key: formKey)
            case .reset:
                AccountField(label: "验证码", text: $code, content: .oneTimeCode, keyboard: .numberPad)
                    .rise(2, key: formKey)
                AccountField(label: "新密码（至少 12 位）", text: $password, password: true, content: .newPassword, submit: .go, onSubmit: submit)
                    .rise(3, key: formKey)
            }
        }
    }

    /// Web .links: 忘记密码？ and 创建账号 under 登录 while the service sends email (else 暂未开放注册), 返回登录 under
    /// the other forms and the demo.
    @ViewBuilder
    private var links: some View {
        HStack(spacing: 28) {
            if model.fixture {
                AccountTextButton(title: "返回登录") { model.back() }
            } else if mode != .login {
                AccountTextButton(title: "返回登录") { model.showForm(.login) }
            } else if model.emailEnabled {
                AccountTextButton(title: "忘记密码？") { model.showForm(.forgot) }
                AccountTextButton(title: "创建账号") { model.showForm(.register) }
            } else {
                Text("暂未开放注册")
                    .scaledFont(14, relativeTo: .subheadline)
                    .foregroundStyle(AccountPalette.hint)
                    .padding(.horizontal, 12)
                    .padding(.vertical, 10)
            }
        }
        .frame(maxWidth: .infinity)
    }

    /// The service could not be reached at all: 重试 starts over.
    private var offline: Bool {
        (model.error?.hasPrefix("连不上服务器") ?? false) && model.account == nil
    }

    private func submit() {
        guard ready, !model.busy else { return }
        if model.fixture {
            model.login(name: "fixture", password: "fixture")
            return
        }
        let typed = password
        switch mode {
        case .login:
            password = ""
            model.login(name: name, password: typed)
        case .register: model.register(email: name, password: typed)
        case .verify: model.verify()
        case .forgot: model.forgot(email: name)
        case .reset: model.resetPassword(password: typed)
        }
    }
}

/// 重新发送 under 输入验证码 and 重置密码 (web #resend): while the relay says to wait it counts down, 重新发送（N）.
private struct ResendButton: View {
    let model: AppModel

    var body: some View {
        if model.forms.resendAt != nil {
            TimelineView(.periodic(from: .now, by: 1)) { context in
                button(wait: model.forms.resendWait(at: context.date))
            }
        } else {
            button(wait: 0)
        }
    }

    private func button(wait: Int) -> some View {
        Button {
            model.resend()
        } label: {
            if wait > 0 { Text("重新发送（\(wait)）") } else { Text("重新发送") }
        }
        .scaledFont(14, relativeTo: .subheadline)
        .foregroundStyle(AccountPalette.muted)
        .padding(.horizontal, 12)
        .padding(.vertical, 10)
        .contentShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
        .disabled(wait > 0 || model.forms.resending)
        .frame(maxWidth: .infinity)
    }
}
