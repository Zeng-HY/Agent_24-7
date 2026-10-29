import SwiftUI
import TeleplyModel
import TeleplyState

/// The input area (spec 4.3, 8.1; Android InputArea), top to bottom: the question bar, the queue tray, a send the
/// computer turned away or whose delivery is unknown, then the input card. It has no background of its own:
/// messages slide under the glass card (the page puts it in a bottom safe-area bar).
struct InputArea: View {
    let model: AppModel
    /// The question bar's tap: to the first card in the timeline.
    var onAsk: () -> Void = {}

    var body: some View {
        let chat = model.conversation
        let last = chat.submissions.first { $0.label != removedLabel }
        VStack(spacing: 8) {
            AskBar(model: model, onAsk: onAsk)
            QueueTray(model: model)
            if let last, last.action == "send", last.label == "未接收" {
                RejectedBar(model: model, record: last)
            }
            if let last, last.label == "送达状态待确认" {
                HStack(spacing: 4) {
                    Text("上一条送达状态待确认")
                        .noteFont()
                        .foregroundStyle(Palette.noteInk)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .padding(.vertical, 8)
                    Button("核对待发送消息") { chat.check(last) }
                        .buttonStyle(PillStyle(kind: .text, minHeight: 36))
                        .disabled(chat.submitting)
                }
                .padding(.leading, 14)
                .padding(.trailing, 4)
                .background(Palette.noteFill, in: RoundedRectangle(cornerRadius: 18, style: .continuous))
            }
            ComposerCard(model: model)
        }
        .padding(.horizontal, 12)
        .padding(.bottom, 8)
        .frame(maxWidth: 820)
        .animation(.easeOut(duration: 0.2), value: chat.submissions.first?.label)
    }
}

/// Queued messages right above the card (spec 4.3 队列条): each can be handed to the running turn now (立即补充) or
/// withdrawn (⋯). Claude's come from its desktop with tokens; 撤回 is not offered there.
private struct QueueTray: View {
    let model: AppModel

    private struct Row: Identifiable {
        let id: String
        let text: String
        let token: String
    }

    var body: some View {
        let chat = model.conversation
        let app = chat.key?.app ?? model.app
        let rows = app == "claude"
            ? chat.control.raw["queued"].array.map { Row(id: $0["id"].string(), text: $0["text"].string(), token: $0["token"].string()) }
            : chat.control.queued.map { Row(id: $0.id, text: $0.text, token: "") }
        if !rows.isEmpty {
            VStack(spacing: 0) {
                ForEach(rows) { row in
                    HStack(spacing: 8) {
                        Image(systemName: "clock")
                            .font(.system(size: 13, weight: .medium))
                            .foregroundStyle(Palette.muted)
                            .accessibilityHidden(true)
                        Text(row.text)
                            .smallBodyFont()
                            .foregroundStyle(Palette.ink)
                            .lineLimit(2)
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .padding(.vertical, 8)
                        Button("立即补充") {
                            if app == "claude" {
                                model.workspace.action("claude/choose", ["token": .string(row.token)])
                            } else {
                                chat.promote(row.id)
                            }
                        }
                        .buttonStyle(PillStyle(kind: .text, minHeight: 36))
                        .disabled(!chat.control.running || chat.submitting || model.workspace.busy || app == "claude" && row.token.isEmpty)
                        .accessibilityLabel(Text("立即补充：\(row.text)"))
                        if app != "claude" {
                            Menu {
                                Button("撤回这条", systemImage: "arrow.uturn.backward", role: .destructive) { chat.cancel(row.id) }
                                    .disabled(!chat.control.queueAvailable || chat.submitting)
                            } label: {
                                Image(systemName: "ellipsis")
                                    .foregroundStyle(Palette.muted)
                                    .frame(width: 36, height: 36)
                                    .contentShape(Rectangle())
                            }
                            .accessibilityLabel(Text("这条排队消息的更多操作"))
                        }
                    }
                    .padding(.leading, 14)
                    .padding(.trailing, 4)
                }
            }
            .padding(.vertical, 4)
            .background(Palette.panel, in: RoundedRectangle(cornerRadius: 18, style: .continuous))
        }
    }
}

/// A send the computer turned away (web: 没发出去 ›): why, and what can be done. Claude's box on the computer
/// holding other text offers to send again replacing exactly that text; 恢复草稿 puts the message back in the box;
/// 移除 takes the record away. Nothing is sent again by itself.
private struct RejectedBar: View {
    let model: AppModel
    let record: Submission

    var body: some View {
        let chat = model.conversation
        let notes = (try? JSONValue.parse(Data(record.body.utf8))) ?? [:]
        let box = notes[SendNote.desktopDraft].string()
        let reason = notes[SendNote.sendError].string()
        VStack(alignment: .leading, spacing: 2) {
            Text("上一条没发出去" + (reason.isEmpty ? "" : "：" + reason))
                .noteFont()
                .foregroundStyle(Palette.stopInk)
                .lineLimit(3)
            ViewThatFits(in: .horizontal) {
                HStack(spacing: 2) { actions(chat: chat, box: box) }
                VStack(alignment: .leading, spacing: 0) { actions(chat: chat, box: box) }
            }
        }
        .padding(.leading, 14)
        .padding(.trailing, 6)
        .padding(.top, 8)
        .padding(.bottom, 4)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Palette.stopFill, in: RoundedRectangle(cornerRadius: 18, style: .continuous))
    }

    @ViewBuilder
    private func actions(chat: ChatModel, box: String) -> some View {
        if !box.isEmpty {
            let shown = box.count > 8 ? String(box.prefix(8)) + "…" : box
            Button("换掉电脑上的「\(shown)」再发") { chat.resendReplacing(record) }
                .buttonStyle(PillStyle(kind: .text, minHeight: 36))
                .disabled(chat.submitting || !chat.control.available)
                .accessibilityLabel(Text("换掉电脑上 Claude 输入框里的「\(box)」，再发这条消息"))
        }
        if chat.draft.isEmpty {
            Button("恢复草稿") { chat.restore(record) }
                .buttonStyle(PillStyle(kind: .text, minHeight: 36))
                .disabled(chat.submitting)
        }
        Button("移除") { chat.dismiss(record) }
            .buttonStyle(PillStyle(kind: .text, minHeight: 36))
            .accessibilityLabel(Text("移除这条没发出去的记录"))
    }
}

/// The input card (spec 4.3): glass with 26 pt corners and no coloured edge. The status line on top, the text,
/// then the model and mode chips and send. ⌘↩ sends from a hardware keyboard; Return makes a new line. While
/// the source runs, send queues (发送并排队, B05).
struct ComposerCard: View {
    let model: AppModel
    @State private var text = ""
    /// Where the cursor is, so voice's words go there.
    @State private var selection: TextSelection?
    @State private var voice = VoiceInput()
    @State private var confirming: JSONValue?
    @FocusState private var focused: Bool
    /// The card's width: under 370 pt the chips use 11 pt (web .composer-chip).
    @State private var width: CGFloat = 400
    @Environment(\.dynamicTypeSize) private var typeSize

    var body: some View {
        let chat = model.conversation
        let saved = model.workspace.saved
        let queue = chat.control.running && chat.control.queueAvailable
        let words = chat.draft.trimmingCharacters(in: .whitespacesAndNewlines)
        let extras = !saved["uploads"].array.isEmpty || !saved["references"].array.isEmpty
        // Claude's message goes while the computer shows another conversation: the computer opens it (web sendConv).
        let reachable = chat.control.available || sendsWhileAway(chat.key?.app ?? model.app)
        let canSend = chat.ready && reachable && !chat.submitting && (!words.isEmpty || extras) && words.count <= 20_000
        // A new conversation's page: words only, sent once the conversation exists; no files or chips yet.
        let newPage = isNewPage(chat.key?.chat)
        let prompt = newPage ? L("可以先写下一条，创建完成后发送") : chat.hint.isEmpty ? L("输入消息…") : chat.hint
        VStack(alignment: .leading, spacing: 0) {
            StatusLine(model: model, voice: voice)
            // While recording, the card shows what is heard in place of the box (web: the box becomes the recorder).
            if voice.active {
                VoiceLive(voice: voice)
            } else {
                if !newPage { AttachmentTiles(workspace: model.workspace, saved: saved) }
                TextField("", text: $text, selection: $selection, prompt: Text(prompt).foregroundStyle(Palette.muted), axis: .vertical)
                    .bodyFont()
                    .foregroundStyle(Palette.ink)
                    .tint(Palette.accent)
                    .lineLimit(1...8)
                    .focused($focused)
                    .disabled(!chat.ready)
                    .padding(.horizontal, 10)
                    .padding(.vertical, 8)
                    .accessibilityLabel(Text("输入消息"))
            }
            // The microphone keeps its place in this row whatever the rest shows: a hold starts on it, and a view that
            // left would take the gesture with it (the recording would never end).
            HStack(alignment: .bottom, spacing: 4) {
                Group {
                    if voice.active {
                        VoiceBar(voice: voice)
                    } else if newPage {
                        // A new conversation's page: words only, sent once the conversation exists.
                        Spacer(minLength: 0)
                    } else {
                        controls
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                MicButton(model: model, voice: voice, cursor: cursor)
                if !voice.active {
                    sendButton(queue: queue && !newPage, enabled: canSend && !newPage)
                }
            }
        }
        .padding(.horizontal, 6)
        .padding(.top, 6)
        .padding(.bottom, 4)
        .glassEffect(.regular, in: .rect(cornerRadius: 26, style: .continuous))
        .onGeometryChange(for: CGFloat.self) { $0.size.width } action: { width = $0 }
        .sensoryFeedback(.impact(weight: .light), trigger: chat.acknowledged)
        .onChange(of: text) { if text != chat.draft { chat.edit(text) } }
        .onChange(of: chat.draftReset, initial: true) { if text != chat.draft { text = chat.draft } }
        .onChange(of: chat.key) { text = chat.draft }
        .onChange(of: chat.focus) { focused = true }
        // A file or 本轮差异 goes over the page: the keyboard goes first, or it comes back over the card on return
        // (0.4.0 screenshots: the card stayed under the keyboard).
        .onChange(of: model.workspace.pane) { if ["file", "diff"].contains(model.workspace.pane ?? "") { focused = false } }
        .alert(confirmTitle, isPresented: confirmShown, presenting: confirming) { option in
            Button("取消", role: .cancel) {}
            Button("确认选择此权限") {
                model.workspace.action("deepseek/permission", ["preset": .string(option["value"].string()), "confirmed": true])
            }
        } message: { option in
            Text(option["description"].string())
        }
    }

    /// ＋ and the chips, left of the microphone and send. Chips that do not fit slide sideways in their row
    /// (Android); at the largest text sizes they take their own line above ＋. Send keeps its size.
    private var controls: some View {
        let app = model.conversation.key?.app ?? model.app
        let row = ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 4) { chips }
        }
        .scrollBounceBehavior(.basedOnSize, axes: .horizontal)
        return Group {
            if typeSize.isAccessibilitySize {
                VStack(alignment: .leading, spacing: 4) {
                    row
                    AttachButton(model: model, app: app, enabled: model.workspace.ready)
                }
            } else {
                HStack(spacing: 4) {
                    AttachButton(model: model, app: app, enabled: model.workspace.ready)
                    row
                }
            }
        }
    }

    /// The cursor or selection in the box, in characters; the end of the draft when it cannot be told.
    private func cursor() -> (Int, Int) {
        let draft = text
        guard let selection, case .selection(let range) = selection.indices,
              let lower = String.Index(range.lowerBound, within: draft), let upper = String.Index(range.upperBound, within: draft),
              lower <= upper, upper <= draft.endIndex else { return (draft.count, draft.count) }
        return (draft.distance(from: draft.startIndex, to: lower), draft.distance(from: draft.startIndex, to: upper))
    }

    private var chips: some View {
        let app = model.conversation.key?.app ?? model.app
        let raw = model.conversation.control.raw
        let labels = chipLabels(app: app, raw: raw, saved: model.workspace.saved)
        let narrow = width + 24 < 370
        let modeName = app == "deepseek" ? "权限" : "模式"
        return Group {
            if chipAway(app: app, raw: raw) {
                // Not open on the computer: the chip opens it there; its menus would act on another conversation
                // (web codex-ui.js, claude-ui.js "away").
                Button { model.workspace.openOnComputer() } label: {
                    ChipLabel(text: "电脑上打开", narrow: narrow)
                }
                .buttonStyle(.plain)
                .disabled(model.workspace.busy)
                .accessibilityLabel(Text("电脑上打开这个对话"))
            } else {
                modelChip(labels: labels, narrow: narrow)
                modeChip(labels: labels, narrow: narrow, modeName: modeName)
            }
        }
    }

    private func modelChip(labels: (model: String, mode: String, plan: Bool), narrow: Bool) -> some View {
        Menu {
            ModelMenu(model: model)
        } label: {
            ChipLabel(text: labels.model, narrow: narrow)
        }
        .menuStyle(.button)
        .buttonStyle(.plain)
        .menuIndicator(.hidden)
        // The system turns a menu that opens upward around; the models stay first (spec 4.3).
        .menuOrder(.fixed)
        .accessibilityLabel(Text("模型：\(labels.model)"))
    }

    private func modeChip(labels: (model: String, mode: String, plan: Bool), narrow: Bool, modeName: String) -> some View {
        Menu {
            ModeMenu(model: model) { confirming = $0 }
        } label: {
            ChipLabel(text: labels.mode, selected: labels.plan, narrow: narrow)
        }
        .menuStyle(.button)
        .buttonStyle(.plain)
        .menuIndicator(.hidden)
        // The system turns a menu that opens upward around; the models stay first (spec 4.3).
        .menuOrder(.fixed)
        .accessibilityLabel(Text("\(modeName)：\(labels.mode)"))
        .accessibilityValue(Text(labels.plan ? "计划模式" : ""))
    }

    private func sendButton(queue: Bool, enabled: Bool) -> some View {
        Button {
            if enabled { model.conversation.send(queue: queue) }
        } label: {
            Image(systemName: "arrow.up")
                .font(.system(size: 17, weight: .semibold))
                .foregroundStyle(enabled ? Palette.onAccent : Palette.muted)
                .opacity(model.conversation.submitting ? 0.5 : 1)
                .frame(width: 40, height: 40)
                .background(enabled ? Palette.accent : Palette.controlFill, in: Circle())
                .frame(width: 44, height: 44)
                .contentShape(Circle())
        }
        .buttonStyle(PressScaleStyle(scale: 0.88))
        .disabled(!enabled)
        .keyboardShortcut(.return, modifiers: .command)
        .accessibilityLabel(Text(queue ? "发送并排队" : "发送"))
        .accessibilityValue(Text(model.conversation.submitting ? "提交中" : ""))
    }

    private var confirmTitle: String {
        "确认改成「\(confirming?["name"].string() ?? "")」？"
    }

    private var confirmShown: Binding<Bool> {
        Binding(get: { confirming != nil }, set: { if !$0 { confirming = nil } })
    }
}

/// The status line at the top of the card (spec 4.3): an error, a setting's result, or the last receipt (B03).
/// Takes no room when there is nothing to say. An action whose result is unknown offers 核对上次操作.
private struct StatusLine: View {
    let model: AppModel
    var voice: VoiceInput?

    var body: some View {
        if let voice, let pill = voice.pill {
            // Voice says what it is doing, with the one thing that can be done about it (web .voice-pill).
            HStack(spacing: 4) {
                Text(pill.text)
                    .noteFont()
                    .foregroundStyle(pill.error ? Palette.danger : Palette.muted)
                    .lineLimit(2)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(.vertical, 4)
                if let action = pill.action {
                    Button(action) { voice.runPill() }
                        .buttonStyle(PillStyle(kind: .text, minHeight: 32))
                }
            }
            .padding(.leading, 10)
            .padding(.trailing, 2)
            .padding(.top, 2)
            .task(id: pill.serial) {
                AccessibilityNotification.Announcement(pill.text).post()
                guard pill.hideAfter > .zero else { return }
                try? await Task.sleep(for: pill.hideAfter)
                if !Task.isCancelled, voice.pill?.serial == pill.serial { voice.pill = nil }
            }
        } else {
            lines
        }
    }

    @ViewBuilder
    private var lines: some View {
        let chat = model.conversation
        let workspace = model.workspace
        let receipt = chat.submissions.first { $0.label != removedLabel }?.label
        let unknown = workspace.saved["pending_action"]["status"].string() == "unknown"
        // The computer's words on why the next message cannot go, in place of an old receipt (user 10-27).
        let away = awayReason(app: chat.key?.app ?? model.app, raw: chat.control.raw)
        let line: (text: String, error: Bool)? = {
            if let error = chat.error { return (error, true) }
            if let error = workspace.error { return (error, true) }
            if !workspace.result.isEmpty { return (workspace.result, false) }
            if unknown { return ("上次操作的结果还没确认", false) }
            if let away { return (away, false) }
            if let receipt, receipt != "未接收", receipt != "送达状态待确认" { return (receipt, false) }
            return nil
        }()
        if let line {
            HStack(spacing: 4) {
                Text(line.text)
                    .noteFont()
                    .foregroundStyle(line.error ? Palette.danger : Palette.muted)
                    .lineLimit(2)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(.vertical, 4)
                if unknown {
                    Button("核对上次操作") { workspace.checkAction() }
                        .buttonStyle(PillStyle(kind: .text, minHeight: 32))
                        .disabled(workspace.busy)
                } else if let away, line.text == away {
                    Button("电脑上打开") { workspace.openOnComputer() }
                        .buttonStyle(PillStyle(kind: .text, minHeight: 32))
                        .disabled(workspace.busy)
                }
            }
            .padding(.leading, 10)
            .padding(.trailing, 2)
            .padding(.top, 2)
            .accessibilityElement(children: .combine)
            .task(id: line.text) { AccessibilityNotification.Announcement(line.text).post() }
        }
    }
}
