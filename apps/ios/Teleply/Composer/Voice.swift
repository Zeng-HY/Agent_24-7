import AVFoundation
import Speech
import SwiftUI
import TeleplyModel
import TeleplyState

/// 录音后自动整理 (设置 → 语音输入): on unless turned off; kept on this phone (web voice-ui.js).
enum VoiceSettings {
    static var tidy: Bool {
        get { UserDefaults.standard.object(forKey: "teleply.voice.tidy") as? Bool ?? true }
        set { UserDefaults.standard.set(newValue, forKey: "teleply.voice.tidy") }
    }
}

/// The microphone, 16 kHz mono 16-bit for the computer's recogniser, and the raw buffers for the phone's own. Runs
/// on the audio thread: what it hands over goes to the main actor by the callers' own hop.
nonisolated final class VoiceCapture: @unchecked Sendable {
    private let engine = AVAudioEngine()

    func start(samples: @escaping @Sendable ([Int16]) -> Void, buffers: (@Sendable (AVAudioPCMBuffer) -> Void)? = nil) throws {
        let session = AVAudioSession.sharedInstance()
        try session.setCategory(.record, mode: .measurement, options: [.duckOthers])
        try session.setActive(true)
        let input = engine.inputNode
        let format = input.outputFormat(forBus: 0)
        guard format.sampleRate > 0, let target = AVAudioFormat(commonFormat: .pcmFormatInt16, sampleRate: Double(voiceRate), channels: 1, interleaved: true),
              let converter = AVAudioConverter(from: format, to: target) else { throw ReadFailure("没拿到麦克风") }
        input.installTap(onBus: 0, bufferSize: 4_096, format: format) { buffer, _ in
            buffers?(buffer)
            let capacity = AVAudioFrameCount(Double(buffer.frameLength) * target.sampleRate / format.sampleRate) + 32
            guard let out = AVAudioPCMBuffer(pcmFormat: target, frameCapacity: capacity) else { return }
            var given = false
            var failure: NSError?
            converter.convert(to: out, error: &failure) { _, status in
                if given {
                    status.pointee = .noDataNow
                    return nil
                }
                given = true
                status.pointee = .haveData
                return buffer
            }
            guard failure == nil, let channel = out.int16ChannelData, out.frameLength > 0 else { return }
            samples(Array(UnsafeBufferPointer(start: channel[0], count: Int(out.frameLength))))
        }
        engine.prepare()
        try engine.start()
    }

    func stop() {
        engine.inputNode.removeTap(onBus: 0)
        engine.stop()
        try? AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation)
    }
}

/// A line above the box about voice, with one thing to do: 换云端识别, 撤销, 填到这里.
struct VoicePill: Equatable {
    let text: String
    var action: String?
    var error = false
    var hideAfter: Duration = .zero
    let serial = UUID()

    static func == (a: VoicePill, b: VoicePill) -> Bool { a.serial == b.serial }
}

/// Voice input (spec 4.3; web voice-ui.js; Android PcVoice). Through the computer: while you talk, a quarter second
/// of audio goes to its recogniser at a time and the words show in the card as they come; ✓ (or letting go after
/// holding) puts them where the cursor was, and with 录音后自动整理 the computer then tidies them, which 撤销 undoes.
/// When the computer loses the recording, all of it goes to its cloud recogniser instead. A computer with voice
/// turned off leaves the phone's own recogniser. Nothing is ever sent by itself, and no audio is kept.
@Observable
final class VoiceInput {
    enum Mode { case idle, press, hold, recording, finishing }

    private(set) var mode = Mode.idle
    private(set) var heard = ""
    private(set) var partial = ""
    private(set) var seconds = 0
    var cancelArmed = false
    var pill: VoicePill?
    private(set) var levels: [Float] = []
    /// Whether the computer in use has its voice service; nil until asked.
    private(set) var computer: Bool?
    var active: Bool { mode != .idle }

    @ObservationIgnored private var session: Session?
    @ObservationIgnored private var busy = false
    @ObservationIgnored private var pillAction: (() -> Void)?

    /// One recording: where its words go, and what was said.
    private final class Session {
        let model: AppModel
        let chat: ChatKey
        let app: String
        let title: String
        let folder: String
        let start: Int
        let end: Int
        let phone: Bool
        var all: [Int16] = []
        var queue: [Int16] = []
        var sid: String?
        var local = true
        var stopping = false
        var capturing = false
        let capture = VoiceCapture()
        var sender: Task<Void, Never>?
        var request: SFSpeechAudioBufferRecognitionRequest?
        var recognition: SFSpeechRecognitionTask?
        var finalText: String?

        init(model: AppModel, chat: ChatKey, start: Int, end: Int, phone: Bool) {
            self.model = model
            self.chat = chat
            app = chat.app
            title = model.chat?.title ?? ""
            folder = model.chat?.folder ?? ""
            self.start = start
            self.end = end
            self.phone = phone
        }
    }

    /// Asks once per computer whether it has its voice on.
    func check(_ model: AppModel) async {
        computer = nil
        computer = await model.voiceAvailable()
    }

    func runPill() {
        let action = pillAction
        pill = nil
        pillAction = nil
        action?()
    }

    private func show(_ text: String, action: String? = nil, error: Bool = false, hideAfter: Duration = .zero, run: (() -> Void)? = nil) {
        pill = VoicePill(text: text, action: action, error: error, hideAfter: hideAfter)
        pillAction = run
    }

    // MARK: Recording

    /// Starts listening for [model]'s open conversation; [start]…[end] is the cursor or selection, in characters.
    func begin(_ model: AppModel, start: Int, end: Int) {
        guard !active, !busy, let chat = model.conversation.key else { return }
        let phone = computer == false
        let s = Session(model: model, chat: chat, start: start, end: end, phone: phone)
        session = s
        mode = .press
        heard = ""
        partial = ""
        seconds = 0
        levels = []
        cancelArmed = false
        pill = nil
        if phone {
            startPhone(s)
            return
        }
        // The computer starts listening while the phone does; without it, the cloud gets the whole recording.
        Task { [weak self] in
            do {
                let started = try await model.voiceCall("voice/stream/start", query: [("tidy", VoiceSettings.tidy ? "1" : "0")])
                let sid = started["sid"].string()
                s.sid = sid.isEmpty ? nil : sid
                if s.sid == nil {
                    s.local = false
                } else if self?.session === s {
                    self?.send(s)
                } else {
                    self?.cancelOnComputer(s)
                }
            } catch {
                s.local = false
            }
        }
        startCapture(s, buffers: nil)
    }

    /// A short tap: it keeps listening until ✓.
    func toTap() { if mode == .press { mode = .recording } }
    func toHold() { if mode == .press { mode = .hold } }

    private func startCapture(_ s: Session, buffers: (@Sendable (AVAudioPCMBuffer) -> Void)?) {
        do {
            try s.capture.start(samples: { [weak self] samples in
                Task { @MainActor in self?.feed(s, samples) }
            }, buffers: buffers)
            s.capturing = true
        } catch {
            drop(s)
            show("没拿到麦克风，可以继续打字", error: true, hideAfter: .seconds(6))
        }
    }

    private func feed(_ s: Session, _ samples: [Int16]) {
        guard session === s, !s.stopping else { return }
        s.all += samples
        if !s.phone { s.queue += samples }
        levels.append(voiceLevel(samples))
        if levels.count > 160 { levels.removeFirst(levels.count - 160) }
        seconds = s.all.count / voiceRate
        if s.all.count >= 300 * voiceRate { finish() }
    }

    /// Pieces go to the computer one request at a time; what piles up meanwhile goes in the next one.
    private func send(_ s: Session) {
        s.sender = Task { [weak self] in
            while !Task.isCancelled {
                var piece: [Int16] = []
                if s.queue.count >= 4_000 || s.stopping && !s.queue.isEmpty {
                    piece = Array(s.queue.prefix(9 * voiceRate))
                    s.queue.removeFirst(piece.count)
                }
                if piece.isEmpty {
                    if s.stopping && !s.capturing { break }
                    try? await Task.sleep(for: .milliseconds(60))
                    continue
                }
                do {
                    let reply = try await s.model.voiceCall("voice/stream/chunk", query: [("sid", s.sid)], audio: pcmBytes(piece))
                    if self?.session === s {
                        self?.heard = reply["final"].string()
                        self?.partial = reply["partial"].string()
                    }
                } catch {
                    // The computer lost this recording: the cloud gets all of it at the end.
                    s.local = false
                    break
                }
            }
        }
    }

    /// ✓, or letting go after holding: the words go where the cursor was.
    func finish() {
        guard let s = session, mode != .finishing, mode != .idle else { return }
        s.stopping = true
        mode = .finishing
        busy = true
        s.capture.stop()
        s.capturing = false
        if s.phone {
            finishPhone(s)
            return
        }
        Task { [weak self] in
            guard let self else { return }
            defer { self.busy = false }
            if s.all.count < voiceRate / 2 {
                self.cancelOnComputer(s)
                self.end()
                self.show("太短了，没听到", hideAfter: .seconds(2))
                return
            }
            do {
                var text = ""
                var raw = ""
                var tidied = false
                var source = "local"
                if s.local, s.sid != nil { await s.sender?.value }
                if s.local, let sid = s.sid {
                    text = try await s.model.voiceCall("voice/stream/end", query: [("sid", sid)])["text"].string()
                } else {
                    source = "cloud"
                    let reply = try await s.model.voiceCall("voice", query: self.query(s), audio: wavBytes(s.all), type: "audio/wav")
                    text = reply["text"].string()
                    raw = reply["raw"].string().trimmingCharacters(in: .whitespacesAndNewlines)
                    tidied = reply["tidied"].bool()
                }
                text = text.trimmingCharacters(in: .whitespacesAndNewlines)
                self.end()
                if text.isEmpty {
                    if source == "local" {
                        self.show("没听清", action: "换云端识别", hideAfter: .seconds(7)) { [weak self] in self?.cloudAgain(s) }
                    } else {
                        self.show("没听清", hideAfter: .seconds(4))
                    }
                    return
                }
                self.place(s, text, raw: raw, tidied: tidied, cloud: source == "cloud")
            } catch {
                self.end()
                self.show("没转成文字", action: s.all.isEmpty ? nil : "换云端识别", error: true, hideAfter: .seconds(10)) { [weak self] in self?.cloudAgain(s) }
            }
        }
    }

    /// ✕ or sliding up: the recording goes; the computer is told to drop it.
    func cancel() {
        guard let s = session else { return }
        drop(s)
        cancelOnComputer(s)
    }

    private func drop(_ s: Session) {
        s.stopping = true
        if s.capturing { s.capture.stop() }
        s.capturing = false
        s.sender?.cancel()
        s.recognition?.cancel()
        end()
        session = nil
    }

    private func end() {
        mode = .idle
        heard = ""
        partial = ""
        levels = []
        cancelArmed = false
    }

    private func cancelOnComputer(_ s: Session) {
        guard let sid = s.sid else { return }
        Task { _ = try? await s.model.voiceCall("voice/stream/cancel", query: [("sid", sid)]) }
    }

    private func query(_ s: Session) -> [(String, String?)] {
        [("tidy", VoiceSettings.tidy ? "1" : "0"), ("app", s.app), ("title", String(s.title.prefix(120))), ("folder", String(s.folder.prefix(120)))]
    }

    // MARK: The words in the draft

    private func place(_ s: Session, _ text: String, raw: String, tidied: Bool, cloud: Bool) {
        let chat = s.model.conversation
        if chat.key != s.chat {
            show("对话已经换了", action: "填到这里", hideAfter: .seconds(12)) {
                if let key = chat.key { _ = chat.insertVoice(key, text, start: chat.draft.count) }
            }
            return
        }
        guard let placed = chat.insertVoice(s.chat, text, start: s.start, end: s.end) else { return }
        if cloud {
            if tidied && !raw.isEmpty && raw != text {
                tidiedPill(s, VoicePlacement(at: placed.at, text: placed.text, raw: raw, draft: placed.draft))
            } else {
                pill = nil
            }
            return
        }
        if VoiceSettings.tidy && !s.phone { tidyIn(s, placed) }
    }

    private func tidyIn(_ s: Session, _ placed: VoicePlacement) {
        show("整理中…")
        Task { [weak self] in
            do {
                let draft = Array(s.model.conversation.draft)
                let upTo = min(placed.at, draft.count)
                let existing = String(draft[max(0, upTo - 400)..<upTo])
                let reply = try await s.model.deviceCall("voice/tidy", body: ["text": .string(placed.raw), "app": .string(s.app), "title": .string(s.title),
                                                                             "folder": .string(s.folder), "existing": .string(existing)])
                guard let self, !self.active else { return }
                let text = reply["text"].string().trimmingCharacters(in: .whitespacesAndNewlines)
                guard !text.isEmpty, text != placed.text, let swapped = s.model.conversation.swapVoice(s.chat, placed, with: text) else {
                    self.pill = nil
                    return
                }
                self.tidiedPill(s, VoicePlacement(at: swapped.at, text: swapped.text, raw: placed.raw, draft: swapped.draft))
            } catch {
                guard let self, !self.active else { return }
                self.show("整理没成功，保留原话", error: true, hideAfter: .milliseconds(3_500))
            }
        }
    }

    private func tidiedPill(_ s: Session, _ placed: VoicePlacement) {
        show("已整理", action: "撤销", hideAfter: .seconds(5)) {
            _ = s.model.conversation.swapVoice(s.chat, placed, with: placed.raw)
        }
    }

    /// The phone still has the recording: the computer's cloud recogniser tries it.
    private func cloudAgain(_ s: Session) {
        guard !busy, !active else { return }
        busy = true
        show("云端识别中…")
        Task { [weak self] in
            defer { self?.busy = false }
            do {
                let reply = try await s.model.voiceCall("voice", query: self?.query(s) ?? [], audio: wavBytes(s.all), type: "audio/wav")
                guard let self else { return }
                let text = reply["text"].string().trimmingCharacters(in: .whitespacesAndNewlines)
                if text.isEmpty {
                    self.show("云端也没听清", hideAfter: .seconds(4))
                    return
                }
                let chat = s.model.conversation
                guard chat.key == s.chat, let placed = chat.insertVoice(s.chat, text, start: chat.draft.count) else {
                    self.show("对话已经换了", hideAfter: .seconds(4))
                    return
                }
                let raw = reply["raw"].string().trimmingCharacters(in: .whitespacesAndNewlines)
                if reply["tidied"].bool() && !raw.isEmpty && raw != text {
                    self.tidiedPill(s, VoicePlacement(at: placed.at, text: placed.text, raw: raw, draft: placed.draft))
                } else {
                    self.pill = nil
                }
            } catch {
                self?.show("云端识别没成功", error: true, hideAfter: .seconds(5))
            }
        }
    }

    // MARK: The phone's own recogniser (the computer's voice is off)

    private func startPhone(_ s: Session) {
        guard let recognizer = SFSpeechRecognizer(locale: Locale(identifier: "zh-CN")), recognizer.isAvailable else {
            drop(s)
            show("iPhone 的语音识别现在用不了，可以继续打字", error: true, hideAfter: .seconds(6))
            return
        }
        let request = SFSpeechAudioBufferRecognitionRequest()
        request.shouldReportPartialResults = true
        if recognizer.supportsOnDeviceRecognition { request.requiresOnDeviceRecognition = true }
        s.request = request
        // The recogniser answers on a queue of its own: only plain words cross to the main actor.
        s.recognition = recognizer.recognitionTask(with: request) { @Sendable [weak self] result, error in
            let text = result?.bestTranscription.formattedString
            let done = result?.isFinal == true || error != nil
            Task { @MainActor in self?.heardOnPhone(s, text: text, done: done) }
        }
        show(recognizer.supportsOnDeviceRecognition ? "这台电脑没开语音，用 iPhone 自带的识别" : "这台电脑没开语音，用 iPhone 自带的识别（可能联网）")
        // The request takes audio from any thread (Speech framework).
        nonisolated(unsafe) let feed = request
        startCapture(s) { buffer in feed.append(buffer) }
    }

    private func heardOnPhone(_ s: Session, text: String?, done: Bool) {
        guard session === s else { return }
        if let text {
            s.finalText = text
            if mode != .finishing { partial = text }
        }
        if done && mode == .finishing { settlePhone(s) }
    }

    private func finishPhone(_ s: Session) {
        s.request?.endAudio()
        // The recogniser says its last word shortly after the audio ends; it gets two seconds.
        Task { [weak self] in
            try? await Task.sleep(for: .seconds(2))
            if let self, self.session === s, self.mode == .finishing { self.settlePhone(s) }
        }
    }

    private func settlePhone(_ s: Session) {
        guard session === s else { return }
        session = nil
        busy = false
        let text = (s.finalText ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        s.recognition?.cancel()
        end()
        if text.isEmpty {
            show("没听清", hideAfter: .seconds(4))
            return
        }
        pill = nil
        place(s, text, raw: text, tidied: false, cloud: false)
    }
}

/// What has been heard so far, in the card in place of the text box (web .rec-text): the settled words, then the
/// guess in grey.
struct VoiceLive: View {
    let voice: VoiceInput

    var body: some View {
        ScrollView {
            Group {
                if voice.heard.isEmpty && voice.partial.isEmpty {
                    Text(voice.mode == .finishing ? "正在出字…" : "正在听…")
                        .foregroundStyle(Palette.muted)
                } else {
                    Text(voice.heard).foregroundStyle(Palette.ink) + Text(voice.partial).foregroundStyle(Palette.muted)
                }
            }
            .bodyFont()
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .defaultScrollAnchor(.bottom)
        .frame(minHeight: 28, maxHeight: 180)
        .fixedSize(horizontal: false, vertical: true)
        .padding(.horizontal, 10)
        .padding(.vertical, 8)
        .accessibilityLabel(Text(voice.heard + voice.partial))
    }
}

/// ✕, the sound wave and the time while recording (web .rec-bar); holding says 松开放入 · 上滑取消.
struct VoiceBar: View {
    let voice: VoiceInput

    var body: some View {
        HStack(spacing: 4) {
            if voice.mode == .recording {
                Button(action: voice.cancel) {
                    Image(systemName: "xmark")
                        .font(.system(size: 15, weight: .semibold))
                        .foregroundStyle(Palette.ink)
                        .frame(width: 40, height: 40)
                        .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .accessibilityLabel(Text("不要这段录音"))
            } else {
                Spacer().frame(width: 8)
            }
            Canvas { context, size in
                let step: CGFloat = 5
                let bar: CGFloat = 3
                let shown = voice.levels.suffix(Int(size.width / step))
                let faint = voice.cancelArmed || voice.mode == .finishing ? 0.35 : 1
                var x = size.width - CGFloat(shown.count) * step
                for level in shown {
                    let height = max(3, CGFloat(level) * size.height)
                    let rect = CGRect(x: x, y: (size.height - height) / 2, width: bar, height: height)
                    context.fill(Path(roundedRect: rect, cornerRadius: 1.5), with: .color(Palette.ink.opacity((0.35 + 0.65 * min(1, Double(level) * 1.6)) * faint)))
                    x += step
                }
                var dot = size.width - CGFloat(shown.count) * step - step
                while dot >= 0 {
                    context.fill(Path(CGRect(x: dot, y: size.height / 2 - 1, width: bar, height: 2)), with: .color(Palette.ink.opacity(0.25 * faint)))
                    dot -= step
                }
            }
            .frame(height: 28)
            .accessibilityHidden(true)
            Text(String(format: "%d:%02d", voice.seconds / 60, voice.seconds % 60))
                .scaledFont(13, relativeTo: .footnote)
                .monospacedDigit()
                .foregroundStyle(Palette.muted)
                .padding(.horizontal, 6)
            if voice.mode == .hold {
                Text(voice.cancelArmed ? "松开取消" : "松开放入 · 上滑取消")
                    .captionFont()
                    .foregroundStyle(voice.cancelArmed ? Palette.danger : Palette.muted)
                    .lineLimit(1)
            }
        }
        .frame(minHeight: 44)
    }
}

/// The microphone (web voice-ui.js): tap to talk as long as you like and tap ✓; or hold, talk, let go to keep the
/// words, slide up and let go to drop them. Leaving the app ends the recording and keeps what was said; leaving the
/// conversation drops it.
struct MicButton: View {
    let model: AppModel
    let voice: VoiceInput
    /// Where the cursor or selection is now, in characters.
    let cursor: () -> (Int, Int)
    @State private var touching = false
    /// This touch started the recording (a later tap on ✓ ends it instead).
    @State private var startedByTouch = false
    @State private var holding: Task<Void, Never>?
    @Environment(\.scenePhase) private var scenePhase

    var body: some View {
        let enabled = model.conversation.ready && voice.computer != nil
        ZStack {
            Circle().fill(fill)
            switch voice.mode {
            case .finishing:
                ProgressView().tint(Palette.muted)
            case .recording:
                Image(systemName: "checkmark")
                    .font(.system(size: 17, weight: .semibold))
                    .foregroundStyle(Palette.page)
            default:
                Image(systemName: "mic")
                    .font(.system(size: 19, weight: .medium))
                    .foregroundStyle(voice.mode == .idle ? Palette.muted.opacity(enabled ? 1 : 0.35) : .white)
            }
        }
        .frame(width: 40, height: 40)
        .frame(width: 44, height: 44)
        .contentShape(Circle())
        .gesture(press)
        .allowsHitTesting(enabled)
        .sensoryFeedback(.impact(weight: .medium), trigger: voice.mode == .press)
        .accessibilityElement()
        .accessibilityLabel(Text(label))
        .accessibilityAddTraits(.isButton)
        .accessibilityAction {
            switch voice.mode {
            case .idle: if enabled { start(tap: true) }
            case .recording: voice.finish()
            default: break
            }
        }
        .task(id: model.device?.id) { await voice.check(model) }
        .onChange(of: scenePhase) { if scenePhase == .background && voice.active { voice.finish() } }
        .onChange(of: model.conversation.key) { if voice.active { voice.cancel() } }
        .onDisappear { if voice.active { voice.cancel() } }
    }

    private var label: String {
        switch voice.mode {
        case .idle: return "语音输入"
        case .recording: return "完成，把文字放进输入框"
        case .finishing: return "正在出字"
        default: return "松开放进输入框"
        }
    }

    private var fill: Color {
        switch voice.mode {
        case .recording: return Palette.ink
        case .press, .hold: return Palette.danger
        default: return .clear
        }
    }

    /// Down starts listening; up within 0.35 s keeps listening until ✓, later up keeps the words (or drops them
    /// when slid up 70 pt). A touch on ✓ ends a recording a tap started.
    private var press: some Gesture {
        DragGesture(minimumDistance: 0)
            .onChanged { value in
                if !touching {
                    touching = true
                    startedByTouch = voice.mode == .idle
                    if startedByTouch {
                        start(tap: false)
                        holding = Task {
                            try? await Task.sleep(for: .milliseconds(350))
                            if !Task.isCancelled { voice.toHold() }
                        }
                    }
                }
                if voice.mode == .hold { voice.cancelArmed = value.translation.height < -70 }
            }
            .onEnded { _ in
                touching = false
                holding?.cancel()
                holding = nil
                if startedByTouch {
                    switch voice.mode {
                    case .press: voice.toTap()
                    case .hold: if voice.cancelArmed { voice.cancel() } else { voice.finish() }
                    default: break
                    }
                } else if voice.mode == .recording {
                    voice.finish()
                }
                startedByTouch = false
            }
    }

    /// Listening needs the microphone, and the phone's recogniser its own permission; asked the first time, after
    /// which it listens until ✓.
    private func start(tap: Bool) {
        let phone = voice.computer == false
        switch AVAudioApplication.shared.recordPermission {
        case .granted:
            if phone && SFSpeechRecognizer.authorizationStatus() == .notDetermined {
                Task {
                    if await requestSpeech() == .authorized { begin(tap: true) }
                }
                return
            }
            if phone && SFSpeechRecognizer.authorizationStatus() != .authorized {
                model.workspace.error = "没有语音识别权限：到 设置 → 遥应 里打开语音识别；可以继续打字。"
                return
            }
            begin(tap: tap)
        case .undetermined:
            Task {
                guard await AVAudioApplication.requestRecordPermission() else {
                    model.workspace.error = "没有麦克风权限：到 设置 → 遥应 里打开麦克风；可以继续打字。"
                    return
                }
                if phone && SFSpeechRecognizer.authorizationStatus() == .notDetermined, await requestSpeech() != .authorized { return }
                begin(tap: true)
            }
        default:
            model.workspace.error = "没有麦克风权限：到 设置 → 遥应 里打开麦克风；可以继续打字。"
        }
    }

    private func begin(tap: Bool) {
        let (start, end) = cursor()
        voice.begin(model, start: start, end: end)
        if tap { voice.toTap() }
    }

    private func requestSpeech() async -> SFSpeechRecognizerAuthorizationStatus {
        await withCheckedContinuation { (done: CheckedContinuation<SFSpeechRecognizerAuthorizationStatus, Never>) in
            SFSpeechRecognizer.requestAuthorization { @Sendable status in done.resume(returning: status) }
        }
    }
}
