import AVFoundation
import Speech
import SwiftUI
import TeleplyModel
import TeleplyState

/// 设置 → 手机通知 (spec 4.6, 7; plan "Teleply - iOS 原生推送方案"): one green switch for 遥应通知, this phone's own
/// notifications through Apple's push service, kept by the service for the whole account (AppModel+Push). Nothing else
/// (user 10-28: "苹果端这里不要保留什么bark了，手机通知也就是简单的绿色开关即可，也不用说明文字"): a line under it only
/// when something went wrong. Turned off in the system's settings, the switch opens 遥应's page there.
struct NotifySection: View {
    let model: AppModel
    @Environment(\.scenePhase) private var scenePhase

    var body: some View {
        let push = model.push
        Section {
            Toggle("遥应通知", isOn: Binding(get: { push.phase == .on }, set: { switchTo($0) }))
                .tint(.green)
                .disabled(push.working || push.phase == .checking || push.phase == .unavailable)
            Toggle("灵动岛", isOn: Binding(get: { model.island.wanted }, set: { on in
                Task { await model.islandSetWanted(on) }
            }))
            .tint(.green)
            .disabled(push.phase != .on || model.island.working)
        } header: {
            Text("手机通知")
        } footer: {
            if let note = push.note {
                Text(note)
                    .task(id: note) { AccessibilityNotification.Announcement(note).post() }
            } else if push.phase == .unavailable {
                Text("服务器还没开通遥应通知")
            }
        }
        .listRowBackground(Palette.controlFill)
        .task { await model.pushRefresh() }
        // back from the system's settings, where the switch may have changed
        .onChange(of: scenePhase) { if scenePhase == .active { Task { await model.pushRefresh() } } }
    }

    private func switchTo(_ on: Bool) {
        if on && model.push.phase == .denied {
            if let url = URL(string: UIApplication.openNotificationSettingsURLString) { UIApplication.shared.open(url) }
            return
        }
        Task {
            if on { await model.pushTurnOn() } else { await model.pushTurnOff() }
            await model.islandLaunch()  // 0.6.0: a fresh install follows 遥应通知
        }
    }
}

/// 设置 → 语音输入 (spec 4.6; web voice-ui.js): 录音后自动整理 and 语音词典, both of the computer's voice service.
/// A computer with voice turned off leaves the microphone to the phone's own recogniser, and this says so.
struct VoiceSection: View {
    let model: AppModel
    @State private var tidy = VoiceSettings.tidy
    @State private var available: Bool?

    var body: some View {
        Section {
            Toggle(isOn: $tidy) {
                VStack(alignment: .leading, spacing: 2) {
                    Text("录音后自动整理")
                    Text("电脑识别出文字后，再把口语整理成书面语；可以撤销。")
                        .captionFont()
                        .foregroundStyle(Palette.muted)
                }
            }
            .disabled(available == false)
            .onChange(of: tidy) { VoiceSettings.tidy = tidy }
            .task(id: model.device?.id) { available = await model.voiceAvailable() }
            NavigationLink("语音词典") { VoiceTermsView(model: model) }
                .disabled(available == false)
        } header: {
            Text("语音输入")
        } footer: {
            Text(available == false ? "这台电脑没开语音：麦克风会改用 iPhone 自带的识别，结果同样只放进输入框。"
                : "录音交给电脑上的语音服务识别，不保存在手机上；识别出的文字只放进输入框，不会自动发送。")
        }
        .listRowBackground(Palette.controlFill)
        // Green, as 遥应通知's switch above and as iOS draws one.
        .tint(.green)
    }
}

/// 语音词典 (web voiceTermsSheet): one word a line, kept on the computer, so its recogniser gets them right.
struct VoiceTermsView: View {
    let model: AppModel
    @State private var text: String?
    @State private var busy = false
    @State private var note: String?
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            TextEditor(text: Binding(get: { text ?? "" }, set: { text = $0 }))
                .bodyFont()
                .scrollContentBackground(.hidden)
                .padding(10)
                .frame(minHeight: 240)
                .background(Palette.sheet, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
                .overlay(RoundedRectangle(cornerRadius: 16, style: .continuous).stroke(Palette.line, lineWidth: 1))
                .disabled(text == nil || busy)
                .accessibilityLabel(Text("语音词典，每行一个词"))
            Text("每行一个词，存在电脑上。")
                .noteFont()
                .foregroundStyle(Palette.muted)
            if let note {
                Text(note)
                    .noteFont()
                    .foregroundStyle(Palette.muted)
                    .task(id: note) { AccessibilityNotification.Announcement(note).post() }
            }
            Button("保存") { save() }
                .buttonStyle(PillStyle(kind: .primary, wide: true))
                .disabled(text == nil || busy)
            Spacer(minLength: 0)
        }
        .padding(20)
        .background(Palette.page)
        .navigationTitle("语音词典")
        .navigationBarTitleDisplayMode(.inline)
        .task {
            do {
                text = try await model.deviceCall("voice/terms")["text"].string()
            } catch {
                note = "没读到词典：" + describe(error)
                text = ""
            }
        }
    }

    private func save() {
        busy = true
        Task {
            do {
                let reply = try await model.deviceCall("voice/terms", body: ["text": .string(text ?? "")])
                note = "已保存，\(reply["count"].int64()) 个词"
                try? await Task.sleep(for: .milliseconds(600))
                dismiss()
            } catch {
                note = describe(error)
            }
            busy = false
        }
    }
}

/// The system permissions the app asks for (spec 4.6): where each stands; a tap opens 遥应's page in Settings.
struct PermissionSection: View {
    @State private var tick = 0
    @State private var notifications = "…"
    @Environment(\.scenePhase) private var scenePhase

    var body: some View {
        let _ = tick
        Section {
            row("通知", notifications)
                .task(id: tick) { notifications = await notificationStatus() }
            row("麦克风", microphone)
                .onChange(of: scenePhase) { if scenePhase == .active { tick += 1 } }
            row("语音识别", speech)
            row("相机", camera)
        } header: {
            Text("系统权限")
        }
        .listRowBackground(Palette.controlFill)
    }

    /// Read from the system each time (it can only be changed there); the others are read as the rows draw.
    private func notificationStatus() async -> String {
        switch await SystemPush().permission() {
        case .allowed: return "已允许"
        case .denied: return "未允许"
        case .notAsked: return "还没问过"
        }
    }

    private func row(_ name: String, _ value: String) -> some View {
        Button {
            if let url = URL(string: UIApplication.openSettingsURLString) { UIApplication.shared.open(url) }
        } label: {
            LabeledContent(name, value: value)
                .foregroundStyle(Palette.ink)
        }
        .accessibilityHint(Text("打开系统设置"))
    }

    private var microphone: String {
        switch AVAudioApplication.shared.recordPermission {
        case .granted: return "已允许"
        case .denied: return "未允许"
        default: return "还没问过"
        }
    }

    private var speech: String {
        switch SFSpeechRecognizer.authorizationStatus() {
        case .authorized: return "已允许"
        case .denied, .restricted: return "未允许"
        default: return "还没问过"
        }
    }

    private var camera: String {
        switch AVCaptureDevice.authorizationStatus(for: .video) {
        case .authorized: return "已允许"
        case .denied, .restricted: return "未允许"
        default: return "还没问过"
        }
    }
}
