import SwiftUI
import TeleplyState

/// 登录 (spec 4.8; web #auth; Android LoginPage): the mark and name, 登录, 邮箱或账号, 密码 and the button. The
/// service is the default one, so there is nothing else to fill in; the gear opens 设置, where 开发者选项 holds
/// the service address and the local demo. The password is used once and never kept.
struct LoginView: View {
    let model: AppModel
    @Environment(Chrome.self) private var chrome
    @Environment(\.openURL) private var openURL
    @State private var name = ""
    @State private var password = ""

    private var ready: Bool {
        model.fixture || !name.trimmingCharacters(in: .whitespaces).isEmpty && !password.isEmpty
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
        .onDisappear { password = "" }
    }

    private var form: some View {
        VStack(spacing: 0) {
            BrandHeader()
                .frame(maxWidth: .infinity)
                .rise(0)
            Text(model.fixture ? L("本地示例") : L("登录"))
                .scaledFont(30, .semibold, relativeTo: .largeTitle)
                .tracking(-0.8)
                .foregroundStyle(AccountPalette.ink)
                .frame(maxWidth: .infinity, alignment: .leading)
                .accessibilityAddTraits(.isHeader)
                .padding(.top, 44)
                .rise(1, key: model.fixture)
            Group {
                if model.fixture {
                    Text("示例无需真实账号或密码，数据都是固定的，不连接真实服务。")
                        .scaledFont(15, relativeTo: .callout, lineHeight: 1.6)
                        .foregroundStyle(AccountPalette.muted)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .rise(2, key: model.fixture)
                } else {
                    VStack(spacing: 12) {
                        AccountField(label: "邮箱或账号", text: $name, content: .username, keyboard: .emailAddress)
                            .rise(2)
                        AccountField(label: "密码", text: $password, password: true, content: .password, submit: .go, onSubmit: submit)
                            .rise(3)
                    }
                }
            }
            .padding(.top, 30)
            Button(model.fixture ? L("进入示例") : L("登录"), action: submit)
                .buttonStyle(AccountButtonStyle(busy: model.busy && model.screen == .login))
                .disabled(!ready || model.busy)
                .padding(.top, 22)
                .rise(4, key: model.fixture)
            links
                .padding(.top, 16)
                .rise(5, key: model.fixture)
            AccountMessage(
                text: model.error ?? (model.expired ? "登录已失效，请重新登录；回到原来的位置。" : nil),
                error: model.error != nil,
                action: offline ? "重试" : nil,
                onAction: model.retry
            )
        }
    }

    @ViewBuilder
    private var links: some View {
        HStack(spacing: 28) {
            if model.fixture {
                AccountTextButton(title: "返回登录") { model.back() }
            } else if model.emailEnabled {
                // Signing up and resetting by email belong to the web page; the phone hands over to it.
                AccountTextButton(title: "忘记密码？") { openURL(model.origin.url("/account")) }
                AccountTextButton(title: "创建账号") { openURL(model.origin.url("/account")) }
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
        let typed = password
        password = ""
        model.login(name: model.fixture ? "fixture" : name, password: model.fixture ? "fixture" : typed)
    }
}
