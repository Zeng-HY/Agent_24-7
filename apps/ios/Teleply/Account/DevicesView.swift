import SwiftUI
import TeleplyModel
import TeleplyState

/// 我的电脑 (spec 4.8; web #signed; Android DevicesPage): the mark and name on the left, then the computers, each
/// with 在线 or 离线, 连接 and ⋯ (重命名, 移除). The heading's ⋯ has 刷新, 设置 and 退出登录. Read again every 15 s
/// while shown (the model does that).
struct DevicesView: View {
    let model: AppModel
    @Environment(Chrome.self) private var chrome
    @State private var renaming: Computer?
    @State private var removing: Computer?
    @State private var connecting: String?

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 0) {
                HStack(spacing: 8) {
                    if model.device != nil {
                        GlassIconButton(symbol: "chevron.backward", label: "返回") { model.back() }
                    }
                    BrandHeader(home: true)
                        .rise(0)
                }
                if model.fixture {
                    Text(L("本地示例 · 固定数据 · 未连接真实服务"))
                        .scaledFont(13, relativeTo: .footnote)
                        .foregroundStyle(AccountPalette.muted)
                        .padding(.top, 8)
                }
                HStack {
                    Text("我的电脑")
                        .scaledFont(24, .semibold, relativeTo: .title2)
                        .tracking(-0.5)
                        .foregroundStyle(AccountPalette.ink)
                        .accessibilityAddTraits(.isHeader)
                    Spacer(minLength: 8)
                    Menu {
                        Button("刷新", systemImage: "arrow.clockwise") { model.showComputers() }
                        Button("设置", systemImage: "gearshape") { chrome.settings = true }
                        Section {
                            Button("退出登录", systemImage: "rectangle.portrait.and.arrow.right", role: .destructive) { model.logout() }
                        }
                    } label: {
                        Image(systemName: "ellipsis")
                            .font(.system(size: 17, weight: .medium))
                            .foregroundStyle(AccountPalette.ink)
                            .frame(width: 44, height: 44)
                            .contentShape(Rectangle())
                    }
                    .accessibilityLabel(Text("账号菜单"))
                }
                .padding(.top, 32)
                .rise(1)
                VStack(spacing: 10) {
                    ForEach(Array(devices.enumerated()), id: \.element.id) { index, device in
                        DeviceRow(device: device, current: device.id == model.device?.id,
                                  busy: connecting == device.id && model.busy,
                                  connect: { connect(device) },
                                  rename: { renaming = device },
                                  remove: { removing = device })
                            .rise(2 + min(index, 8), key: device.id)
                    }
                }
                .padding(.top, 20)
                if devices.isEmpty && !model.busy {
                    Text("暂无电脑")
                        .scaledFont(15, relativeTo: .callout)
                        .foregroundStyle(AccountPalette.muted)
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 28)
                }
                AccountMessage(text: model.error, error: true)
            }
            .frame(maxWidth: 440)
            .padding(.horizontal, 24)
            .padding(.top, 28)
            .padding(.bottom, 32)
            .frame(maxWidth: .infinity)
        }
        .background(AccountPalette.page.ignoresSafeArea())
        .refreshable {
            model.showComputers()
            await model.settle()
        }
        .onChange(of: model.busy) { if !model.busy { connecting = nil } }
        .sheet(item: $renaming) { device in
            RenameSheet(device: device) { label in model.renameDevice(device, label: label) }
        }
        .alert("移除这台电脑？", isPresented: removingShown, presenting: removing) { device in
            Button("取消", role: .cancel) {}
            Button("移除", role: .destructive) { model.removeDevice(device) }
        } message: { device in
            Text("撤销「\(device.label)」的远程访问，不删除电脑上的文件。")
        }
    }

    private var devices: [Computer] { model.account?.devices ?? [] }

    private var removingShown: Binding<Bool> {
        Binding(get: { removing != nil }, set: { if !$0 { removing = nil } })
    }

    private func connect(_ device: Computer) {
        connecting = device.id
        model.select(device)
    }
}

/// One computer (web #devices li): its name, 在线 with a green dot or 离线, 连接 (or a greyed 离线) and ⋯.
private struct DeviceRow: View {
    let device: Computer
    let current: Bool
    let busy: Bool
    let connect: () -> Void
    let rename: () -> Void
    let remove: () -> Void

    @Environment(\.dynamicTypeSize) private var typeSize

    var body: some View {
        // At the largest text sizes the buttons go under the name instead of squeezing it (spec 2.3).
        Group {
            if typeSize.isAccessibilitySize {
                VStack(alignment: .leading, spacing: 10) {
                    name
                    HStack(spacing: 8) {
                        connectButton
                        Spacer(minLength: 0)
                        manage
                    }
                }
            } else {
                HStack(spacing: 8) {
                    name.frame(maxWidth: .infinity, alignment: .leading)
                    connectButton
                    manage
                }
            }
        }
        .padding(.leading, 20)
        .padding(.trailing, 8)
        .padding(.vertical, 14)
        .background(AccountPalette.soft, in: RoundedRectangle(cornerRadius: 22, style: .continuous))
        .contentShape(RoundedRectangle(cornerRadius: 22, style: .continuous))
        .onTapGesture { if device.connectable && !busy { connect() } }
    }

    private var name: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(device.label)
                .scaledFont(16, .semibold, relativeTo: .body)
                .foregroundStyle(AccountPalette.ink)
                .lineLimit(typeSize.isAccessibilitySize ? 4 : 2)
            HStack(spacing: 7) {
                if device.connectable {
                    Circle().fill(AccountPalette.online).frame(width: 7, height: 7)
                }
                Text((device.connectable ? L("在线") : L("离线")) + (current ? L(" · 当前") : ""))
                    .scaledFont(13, relativeTo: .footnote)
                    .foregroundStyle(AccountPalette.muted)
            }
        }
    }

    private var connectButton: some View {
        let online = device.connectable
        return Button(action: connect) {
            ZStack {
                if busy {
                    ProgressView().tint(Palette.onPrimary)
                } else {
                    Text(online ? L("连接") : L("离线"))
                        .scaledFont(14, .medium, relativeTo: .subheadline)
                        .foregroundStyle(online ? Palette.onPrimary : AccountPalette.muted)
                }
            }
            .padding(.horizontal, 18)
            .frame(minHeight: 40)
            .background {
                if online {
                    Capsule().fill(Palette.primaryFill)
                } else {
                    Capsule().fill(AccountPalette.soft).overlay(Capsule().stroke(Palette.line, lineWidth: 1))
                }
            }
            .contentShape(Capsule())
        }
        .buttonStyle(PressScaleStyle())
        .disabled(!online || busy)
        .accessibilityLabel(Text(online ? L("连接") + device.label : device.label + L("离线")))
    }

    private var manage: some View {
        Menu {
            Button("重命名", systemImage: "pencil", action: rename)
            Section {
                Button("移除", systemImage: "trash", role: .destructive, action: remove)
            }
        } label: {
            Image(systemName: "ellipsis")
                .font(.system(size: 17, weight: .medium))
                .foregroundStyle(AccountPalette.ink)
                .frame(width: 44, height: 44)
                .contentShape(Rectangle())
        }
        .accessibilityLabel(Text("管理电脑"))
    }
}

/// 管理电脑 (web dialog): a sheet with the name field, 取消 and 确定.
private struct RenameSheet: View {
    let device: Computer
    let save: (String) -> Void
    @State private var label: String
    @Environment(\.dismiss) private var dismiss

    init(device: Computer, save: @escaping (String) -> Void) {
        self.device = device
        self.save = save
        _label = State(initialValue: device.label)
    }

    var body: some View {
        NavigationStack {
            VStack(spacing: 16) {
                AccountField(label: "电脑名称", text: $label, submit: .done, onSubmit: done)
                HStack(spacing: 10) {
                    Button("取消") { dismiss() }
                        .buttonStyle(PillStyle())
                        .frame(maxWidth: .infinity)
                    Button("确定", action: done)
                        .buttonStyle(PillStyle(kind: .primary))
                        .frame(maxWidth: .infinity)
                        .disabled(label.trimmingCharacters(in: .whitespaces).isEmpty)
                }
                Spacer(minLength: 0)
            }
            .padding(.horizontal, 20)
            .padding(.top, 8)
            .navigationTitle("管理电脑")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button(role: .close) { dismiss() }
                }
            }
        }
        .presentationDetents([.height(220)])
        .presentationBackground(Palette.sheet)
    }

    private func done() {
        let trimmed = label.trimmingCharacters(in: .whitespaces)
        guard !trimmed.isEmpty else { return }
        dismiss()
        save(trimmed)
    }
}
