import AVFoundation
import Speech
import SwiftUI
import TeleplyModel
import TeleplyState

/// 设置 → 手机通知 (spec 4.6, 7; web notify-ui.js as an iPhone shows it): Bark only. Paste its address and send one
/// to try; once on, 试推一条 and 关掉; the last outcomes under it. The computer pushes when a turn ends, through
/// Apple's push service, without this app open.
struct NotifySection: View {
    let model: AppModel
    @State private var state: JSONValue?
    @State private var address = ""
    @State private var busy = false
    @State private var note: String?

    var body: some View {
        Section {
            if let state {
                if state["configured"].bool() {
                    LabeledContent("已开", value: state["server"].string())
                    Button("试推一条") { call("notify/test", ["channel": "bark"]) }
                        .disabled(busy)
                    Button("关掉", role: .destructive) { call("notify", ["address": ""]) }
                        .disabled(busy)
                } else {
                    TextField("", text: $address, prompt: Text("粘贴 Bark 的推送地址").foregroundStyle(Palette.muted))
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                        .keyboardType(.URL)
                        .accessibilityLabel(Text("Bark 的推送地址"))
                    Button("保存并试推一条") {
                        guard !address.trimmingCharacters(in: .whitespaces).isEmpty else {
                            note = "先把 Bark 的推送地址贴进来"
                            return
                        }
                        call("notify", ["address": .string(address)])
                    }
                    .disabled(busy)
                }
            } else {
                Text("正在读取电脑上的通知设置…")
                    .foregroundStyle(Palette.muted)
            }
        } header: {
            Text("手机通知")
        } footer: {
            VStack(alignment: .leading, spacing: 6) {
                if let state {
                    Text(state["configured"].bool() ? "对话做完时推到这部手机。正在用这台电脑、或手机正开着那个对话时不推。"
                        : "对话做完时推到这部手机。先在 iPhone 上装 Bark，在它首页复制 https://api.day.app/ 开头的地址，贴在上面。")
                    let recent = state["recent"].array.prefix(3).map { $0["time"].string() + " " + $0["text"].string() }
                    if !recent.isEmpty { Text("最近：" + recent.joined(separator: "\n")) }
                }
                if let note {
                    Text(note)
                        .task(id: note) { AccessibilityNotification.Announcement(note).post() }
                }
            }
        }
        .listRowBackground(Palette.controlFill)
        .task(id: model.device?.id) { await load() }
    }

    private func load() async {
        do {
            state = try await model.deviceCall("notify")
        } catch {
            note = describe(error)
        }
    }

    private func call(_ route: String, _ body: JSONValue) {
        guard !busy else { return }
        busy = true
        Task {
            do {
                let reply = try await model.deviceCall(route, body: body)
                note = reply["text"].string().isEmpty ? "好了" : reply["text"].string()
                address = ""
            } catch {
                note = describe(error)
            }
            await load()
            busy = false
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
            NavigationLink("语音词典") { VoiceTermsView(model: model) }
                .disabled(available == false)
        } header: {
            Text("语音输入")
        } footer: {
            Text(available == false ? "这台电脑没开语音：麦克风会改用 iPhone 自带的识别，结果同样只放进输入框。"
                : "录音交给电脑上的语音服务识别，不保存在手机上；识别出的文字只放进输入框，不会自动发送。")
        }
        .listRowBackground(Palette.controlFill)
        .tint(Palette.accent)
        .task(id: model.device?.id) { available = await model.voiceAvailable() }
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
    @Environment(\.scenePhase) private var scenePhase

    var body: some View {
        let _ = tick
        Section {
            row("麦克风", microphone)
            row("语音识别", speech)
            row("相机", camera)
        } header: {
            Text("系统权限")
        } footer: {
            Text("录音、iPhone 自带的语音识别和拍照要用到。点一行到系统设置里遥应这一页去改。")
        }
        .listRowBackground(Palette.controlFill)
        .onChange(of: scenePhase) { if scenePhase == .active { tick += 1 } }
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
