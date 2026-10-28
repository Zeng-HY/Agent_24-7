import SwiftUI
import TeleplyDemo
import TeleplyModel
import TeleplyState

/// 设置 (spec 4.6; Android SettingsScreen): a full sheet with deeper pages in it. Only what users set, top to bottom:
/// 对话 (已归档对话), 外观, 手机通知, 语音输入, the system permissions, 账号, 关于遥应; 开发者选项 at the bottom holds the
/// service address, the local demo and diagnostics. Without a computer there is no 对话, 手机通知 or 语音输入.
struct SettingsView: View {
    let model: AppModel
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            List {
                if model.device != nil {
                    Section("对话") {
                        NavigationLink("已归档对话") { ArchivedView(model: model) }
                    }
                    .listRowBackground(Palette.controlFill)
                }
                Section("外观") {
                    AppearanceChoice(selection: model.theme) { model.setAppearance($0) }
                        .listRowBackground(Color.clear)
                        .listRowInsets(EdgeInsets())
                }
                if model.device != nil {
                    NotifySection(model: model)
                    VoiceSection(model: model)
                }
                PermissionSection()
                if model.account != nil {
                    Section("账号") {
                        Button("我的电脑") {
                            dismiss()
                            model.showComputers()
                        }
                        .foregroundStyle(Palette.ink)
                        if !model.fixture {
                            Button("退出登录", role: .destructive) {
                                dismiss()
                                model.logout()
                            }
                        }
                    }
                    .listRowBackground(Palette.controlFill)
                }
                Section("关于遥应") {
                    LabeledContent("遥应", value: AppVersion.short)
                    NavigationLink("开源组件") { LicencesView() }
                }
                .listRowBackground(Palette.controlFill)
                Section {
                    NavigationLink("开发者选项") { DeveloperView(model: model) }
                }
                .listRowBackground(Palette.controlFill)
            }
            .scrollContentBackground(.hidden)
            .background(Palette.page)
            .navigationTitle("设置")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button(role: .close) { dismiss() }
                }
            }
        }
        .tint(Palette.accent)
        .presentationBackground(Palette.page)
        // A new service starts over like a fresh launch (spec 4.6): the sheet makes way for it.
        .onChange(of: model.origin) { dismiss() }
    }
}

/// 开源组件: what the app is built from and where the marks come from (spec 11).
/// 外观 (web segmented choice; Android SegmentedChoice): one capsule track with a thumb that slides to the choice, each
/// choice as tall as a list row (user 10-28: "浅色深色的控件不够大，那个滑动按钮调大一些，跟常规切换的大小差不多即可").
private struct AppearanceChoice: View {
    let selection: String
    let choose: (String) -> Void
    @Environment(\.colorScheme) private var scheme
    @Namespace private var thumb
    private static let choices = [("system", "跟随系统"), ("light", "浅色"), ("dark", "深色")]

    var body: some View {
        HStack(spacing: 0) {
            ForEach(Self.choices, id: \.0) { value, label in
                let chosen = value == selection
                Button {
                    withAnimation(.spring(response: 0.3, dampingFraction: 0.85)) { choose(value) }
                } label: {
                    Text(label)
                        .font(.body.weight(chosen ? .semibold : .regular))
                        .foregroundStyle(chosen ? Palette.ink : Palette.muted)
                        .lineLimit(1)
                        .frame(maxWidth: .infinity, minHeight: 44)
                        .background {
                            if chosen {
                                Capsule()
                                    .fill(scheme == .dark ? Color(red: 0x38 / 255, green: 0x38 / 255, blue: 0x3A / 255) : .white)
                                    .shadow(color: .black.opacity(scheme == .dark ? 0 : 0.1), radius: 3, y: 1)
                                    .matchedGeometryEffect(id: "thumb", in: thumb)
                            }
                        }
                        .contentShape(Capsule())
                }
                .buttonStyle(.plain)
                .accessibilityAddTraits(chosen ? [.isSelected] : [])
            }
        }
        .padding(4)
        .background(Palette.controlFill, in: Capsule())
    }
}

private struct LicencesView: View {
    var body: some View {
        ScrollView {
            Text("Markdown 解析用苹果维护的 swift-markdown 0.9.0（Apache-2.0）和 swift-cmark 0.9.0（BSD-2-Clause）。Claude、DeepSeek 图形来自 Simple Icons（CC0），Codex 图形来自 SVG Logos（CC0）；这些标志归各自公司所有。")
                .bodyFont()
                .foregroundStyle(Palette.ink)
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(20)
        }
        .background(Palette.page)
        .navigationTitle("开源组件")
        .navigationBarTitleDisplayMode(.inline)
    }
}

/// 开发者选项 (spec 4.6; Android DeveloperScreen): for building and looking into problems, out of users' way. Where
/// the app connects, the local demo, 诊断测速, 诊断记录 and what this build is.
struct DeveloperView: View {
    let model: AppModel
    @Environment(Chrome.self) private var chrome
    @State private var speed = SpeedLog.shared
    @State private var network = DemoHolder.shared.network
    @State private var probing = false

    var body: some View {
        List {
            Section {
                NavigationLink {
                    ServiceAddressView(model: model)
                } label: {
                    LabeledContent("服务地址", value: model.fixture ? "本地示例" : String(model.origin.header.dropFirst("https://".count)))
                }
                if !model.serverVersion.isEmpty {
                    LabeledContent("服务版本", value: model.serverVersion)
                }
            } header: {
                Text("服务")
            } footer: {
                Text("给开发和排查问题用，平常用不到。")
            }
            Section("本地示例") {
                if model.fixture {
                    LabeledContent("正在使用本地示例", value: "固定数据")
                    Picker("示例网络", selection: $network) {
                        ForEach(DemoNetwork.allCases, id: \.self) { value in
                            Text(value.label).tag(value)
                        }
                    }
                    .pickerStyle(.segmented)
                    .onChange(of: network) { DemoHolder.shared.network = network }
                } else {
                    Button {
                        dismissAll()
                        model.openDemo()
                    } label: {
                        VStack(alignment: .leading, spacing: 2) {
                            Text("打开本地示例").foregroundStyle(Palette.ink)
                            Text("固定数据，不连接真实服务").captionFont().foregroundStyle(Palette.muted)
                        }
                    }
                }
            }
            // 0.6.0 以前只放在这里，且只给试岛用（handoff 1、2）: 试一下灵动岛 needs no relay; 让中转改一下 proves
            // the APNs key accepts the Live Activity topic (3.5). From 0.6.0 the user's switch moves to 手机通知.
            Section {
                Button("试一下灵动岛") { Task { await model.islandDemo() } }
                    .disabled(model.island.working)
                Button("让中转改一下") { Task { await model.islandRelayTest() } }
                    .disabled(model.island.working || model.fixture)
                if model.island.demo != nil {
                    Button("关掉试的岛") { Task { await model.islandDemoEnd() } }
                        .disabled(model.island.working)
                }
                if model.island.enabled == false {
                    Text("系统里关了遥应的实时活动：到系统设置 → 遥应 里打开。")
                        .noteFont()
                        .foregroundStyle(Palette.muted)
                }
                if let note = model.island.note {
                    Text(note).noteFont().foregroundStyle(Palette.muted)
                }
            } header: {
                Text("灵动岛")
            } footer: {
                Text("试验用。岛出现在灵动岛、锁屏和待机显示里，锁屏看得最清楚。")
            }
            Section {
                Toggle("显示操作耗时", isOn: Binding(get: { speed.enabled }, set: { speed.setEnabled($0) }))
                Button("测一下连接") { probe() }
                    .disabled(!speed.enabled || probing || model.device == nil)
                Button("清空记录") { speed.clear() }
                    .disabled(speed.records.isEmpty)
                if !speed.records.isEmpty || speed.enabled {
                    Text(speed.records.isEmpty ? "暂无记录" : speed.records.joined(separator: "\n\n"))
                        .noteFont()
                        .foregroundStyle(Palette.muted)
                }
            } header: {
                Text("诊断测速")
            }
            Section {
                NavigationLink("最近的请求") { RecordsView() }
                ShareLink(item: DiagnosticsExport(), preview: SharePreview("遥应诊断记录")) {
                    Text("导出诊断记录")
                }
            } header: {
                Text("诊断记录")
            } footer: {
                Text("包括最近的请求（方法、路径、状态、耗时，不含内容和登录凭据）、应用自己的记录和系统收集的崩溃报告。")
            }
            Section {
                LabeledContent("版本", value: AppVersion.display)
                LabeledContent("包名", value: Bundle.main.bundleIdentifier ?? "com.pocketagentdesk.teleply")
            } header: {
                Text("这个版本")
            } footer: {
                Text("新版本由 TestFlight 提醒和安装。")
            }
        }
        .scrollContentBackground(.hidden)
        .background(Palette.page)
        .navigationTitle("开发者选项")
        .navigationBarTitleDisplayMode(.inline)
        .task { await model.islandReadEnabled() }
    }

    /// 打开本地示例 starts over on the demo: the sheet goes first (this page's own dismiss would only go back).
    private func dismissAll() {
        chrome.settings = false
    }

    /// 测一下连接: three status reads of the computer, each timed (web).
    private func probe() {
        probing = true
        Task {
            for index in 1...3 {
                guard speed.enabled else { break }
                let start = ContinuousClock.now
                let result = await model.checkStatus()
                speed.add("连接请求 \(index)/3", elapsed: ContinuousClock.now - start, result: result)
            }
            probing = false
        }
    }
}

/// 最近的请求: 诊断记录 as it stands, newest last.
private struct RecordsView: View {
    var body: some View {
        let lines = DiagnosticsLog.shared.recent
        ScrollView {
            Text(lines.isEmpty ? "暂无记录" : lines.joined(separator: "\n"))
                .scaledFont(12, design: .monospaced, relativeTo: .caption)
                .foregroundStyle(Palette.ink)
                .textSelection(.enabled)
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(16)
        }
        .defaultScrollAnchor(.bottom)
        .background(Palette.page)
        .navigationTitle("最近的请求")
        .navigationBarTitleDisplayMode(.inline)
    }
}

/// 服务地址 (spec 4.6): the default service needs nothing typed. Another HTTPS service, or back to the default one;
/// only a service that answers is taken, and the app then starts over on it.
private struct ServiceAddressView: View {
    let model: AppModel
    @State private var address: String

    init(model: AppModel) {
        self.model = model
        _address = State(initialValue: model.fixture ? "" : model.origin.header)
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 12) {
                Text("一般不用改：默认连接 Teleply 的服务。自己部署了账号服务时，在这里填它的 HTTPS 根地址。")
                    .bodyFont()
                    .foregroundStyle(Palette.muted)
                TextField("", text: $address, prompt: Text(verbatim: ServiceOrigin.defaultAddress).foregroundStyle(Palette.muted))
                    .bodyFont()
                    .keyboardType(.URL)
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
                    .submitLabel(.go)
                    .onSubmit(connect)
                    .padding(.horizontal, 14)
                    .frame(minHeight: 48)
                    .background(Palette.sheet, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
                    .overlay(RoundedRectangle(cornerRadius: 16, style: .continuous).stroke(Palette.line, lineWidth: 1))
                    .accessibilityLabel(Text("服务地址"))
                Button("连接这个服务", action: connect)
                    .buttonStyle(PillStyle(kind: .primary))
                    .frame(maxWidth: .infinity)
                    .disabled(model.busy || address.trimmingCharacters(in: .whitespaces).isEmpty)
                if model.origin != .default {
                    Button("恢复默认服务") { model.connect(ServiceOrigin.defaultAddress) }
                        .buttonStyle(PillStyle())
                        .frame(maxWidth: .infinity)
                        .disabled(model.busy)
                }
                if let error = model.error {
                    Text(error)
                        .noteFont()
                        .foregroundStyle(Palette.danger)
                }
            }
            .padding(20)
        }
        .background(Palette.page)
        .navigationTitle("服务地址")
        .navigationBarTitleDisplayMode(.inline)
    }

    private func connect() {
        guard !model.busy, !address.trimmingCharacters(in: .whitespaces).isEmpty else { return }
        model.connect(address)
    }
}

/// 诊断测速 (web; Android Diagnostics): while it is on, operations that carry a message or a file are timed (from
/// 0.3.0) and 测一下连接 times three status reads. The switch is kept on this phone; the last ten records live in
/// memory only.
@Observable
final class SpeedLog {
    static let shared = SpeedLog()
    private(set) var enabled = UserDefaults.standard.bool(forKey: "teleply.diagnostics.speed")
    private(set) var records: [String] = []
    /// The newest record to show for a moment where the user is (web: a toast), with a serial to tell repeats apart.
    private(set) var shown: (serial: Int, text: String, ok: Bool)?
    @ObservationIgnored private var serial = 0

    func setEnabled(_ on: Bool) {
        enabled = on
        records = []
        UserDefaults.standard.set(on, forKey: "teleply.diagnostics.speed")
    }

    func clear() {
        records = []
    }

    /// "连接请求 1/3：0.412 秒 · 成功", as the web writes it. [notify] ones also show for a moment.
    func add(_ label: String, elapsed: Duration, result: String, notify: Bool = false) {
        guard enabled else { return }
        let seconds = Double(elapsed.components.seconds) + Double(elapsed.components.attoseconds) / 1e18
        let time = Date().formatted(.dateTime.hour(.twoDigits(amPM: .omitted)).minute(.twoDigits).second(.twoDigits))
        let text = label + "：" + String(format: "%.3f", seconds) + " 秒 · " + result
        records = Array(([time + " " + text] + records).prefix(10))
        if notify {
            serial += 1
            shown = (serial, text, ["成功", "请求完成"].contains(result))
        }
    }

    func hide(_ serial: Int) {
        if shown?.serial == serial { shown = nil }
    }
}

/// Each timed operation shown for a moment at the top while 显示操作耗时 is on (web toast; Android DiagnosticToast):
/// dark for a request done, red otherwise.
struct SpeedToast: View {
    @State private var speed = SpeedLog.shared

    var body: some View {
        ZStack {
            if let shown = speed.shown {
                Text(shown.text)
                    .scaledFont(13, relativeTo: .footnote)
                    .foregroundStyle(.white)
                    .padding(.horizontal, 16)
                    .padding(.vertical, 10)
                    .background(shown.ok ? Color(white: 0.07, opacity: 0.9) : Color(red: 0.73, green: 0.11, blue: 0.11, opacity: 0.9),
                                in: RoundedRectangle(cornerRadius: 14, style: .continuous))
                    .padding(.horizontal, 24)
                    .transition(.opacity)
                    .task(id: shown.serial) {
                        AccessibilityNotification.Announcement(shown.text).post()
                        try? await Task.sleep(for: .milliseconds(2_800))
                        speed.hide(shown.serial)
                    }
            }
        }
        .animation(.easeOut(duration: 0.2), value: speed.shown?.serial)
        .allowsHitTesting(false)
    }
}
