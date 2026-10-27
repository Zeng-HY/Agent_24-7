import SwiftUI
import TeleplyModel
import TeleplyState

/// The conversation page (spec 4.3; Android ChatScreen): the title with project and source, 停止这一轮, the context
/// ring and ⋯ in the title bar; the messages scroll under it and under the glass input card. Following the bottom
/// only while the reader is there; reading above keeps its place and "有新消息 ↓" appears (B09).
struct ConversationView: View {
    let model: AppModel
    @State private var position = ScrollPosition(idType: String.self)
    @State private var atBottom = true
    @State private var unseen = false
    @State private var restored = false
    @State private var folds: [String: Bool] = [:]
    @State private var runtimeShown = false
    @State private var searchShown = false
    @State private var selecting: Message?
    /// The first message before 加载更早消息, kept in view when the older ones arrive above it.
    @State private var keepTop: String?
    @State private var saveTick = 0
    @State private var pendingShown = false
    @State private var promptsShown = false
    /// 从电脑选择文件 was tapped in an empty 对话文件: the picker opens when that sheet has gone.
    @State private var pickAfterFiles = false
    /// The question bar's tap moves VoiceOver to the first card too (spec 7).
    @AccessibilityFocusState private var cardFocused: Bool

    var body: some View {
        let control = model.conversation.control
        let roles = timelineRoles(model.messages, app: model.app, raw: control.raw, running: control.running, asking: control.questions)
        let actions = MessageActions(select: { selecting = $0 }, expand: { model.expand($0) }, diff: { model.workspace.diff($0) },
                                     files: { model.workspace.filesOf(message: $0) }, busy: model.busy)
        let submissions = model.conversation.submissions
        let receipts = Dictionary(submissions.filter { !$0.request.isEmpty }.map { ($0.request, $0.label) }, uniquingKeysWith: { first, _ in first })
        // Sends still on their way that the record does not show yet (Android outbox).
        let outbox = submissions.filter { record in
            record.action == "send" && record.label == "提交中" && !model.messages.contains { $0.request == record.request }
        }
        let cards = inlineCards(app: model.conversation.key?.app ?? model.app, raw: control.raw)
        ScrollView {
            // A plain stack, not a lazy one: with LazyVStack the area above the input card went blank after the
            // keyboard came up (0.3.0 screenshots on iOS 26.5, two runs of three). Pages hold 60 messages, the
            // long demo 200; how that scrolls on a phone is T04.
            VStack(alignment: .leading, spacing: 0) {
                historyTools
                newFirst
                ForEach(Array(zip(model.messages, roles)), id: \.0.id) { message, role in
                    TimelineItem(model: model, message: message, role: role, raw: control.raw,
                                 receipt: message.request.isEmpty ? nil : receipts[message.request], folds: $folds, actions: actions)
                }
                // Questions and approvals where the source asked: at the end of its turn (spec 4.3).
                if !cards.isEmpty {
                    VStack(alignment: .leading, spacing: 12) {
                        ForEach(cards) { card in
                            if card.id == cards.first?.id {
                                InlineCardView(model: model, card: card)
                                    .accessibilityFocused($cardFocused)
                            } else {
                                InlineCardView(model: model, card: card)
                            }
                        }
                    }
                    .padding(.top, 16)
                    .id("interactions")
                }
                if model.newerAvailable {
                    Button("回到最新") {
                        unseen = false
                        model.latest()
                    }
                    .buttonStyle(PillStyle())
                    .disabled(model.busy)
                    .frame(maxWidth: .infinity)
                    .padding(.top, 16)
                }
                ForEach(outbox.reversed()) { record in
                    UserBubble(message: Message(id: record.request, role: "user", text: record.text), actions: actions, receipt: record.label, sending: true)
                        .padding(.top, 16)
                }
            }
            .scrollTargetLayout()
            .frame(maxWidth: 820)
            .padding(.horizontal, 20)
            .padding(.bottom, 16)
            .frame(maxWidth: .infinity)
        }
        .scrollPosition($position, anchor: .top)
        .defaultScrollAnchor(atBottom ? .bottom : .top, for: .sizeChanges)
        .scrollDismissesKeyboard(.interactively)
        .onScrollGeometryChange(for: Bool.self) { geometry in
            geometry.contentOffset.y + geometry.containerSize.height - geometry.contentInsets.bottom >= geometry.contentSize.height - 24
        } action: { _, bottom in
            atBottom = bottom
            if bottom { unseen = false }
        }
        .onScrollPhaseChange { _, phase in
            if phase == .idle { saveTick += 1 }
        }
        .task(id: saveTick) {
            guard saveTick > 0 else { return }
            try? await Task.sleep(for: .milliseconds(400))
            if !Task.isCancelled { saveAnchor() }
        }
        .background(Palette.page)
        .safeAreaBar(edge: .top) { notes(control: control) }
        .safeAreaBar(edge: .bottom) {
            VStack(spacing: 0) {
                newMessagesPill
                InputArea(model: model) {
                    withAnimation(.easeOut(duration: 0.3)) { position.scrollTo(id: "interactions", anchor: .top) }
                    cardFocused = true
                }
            }
            .frame(maxWidth: .infinity)
        }
        .toolbar { toolbar(control: control) }
        .navigationBarTitleDisplayMode(.inline)
        .toolbarRole(.editor)
        .onChange(of: model.scrollRevision, initial: true) { restore() }
        .onChange(of: model.conversation.revision) { follow() }
        .onChange(of: model.messages.first?.id) { keepPlace() }
        .onChange(of: model.screen) { if model.screen != .reading { saveAnchor() } }
        .sheet(isPresented: $searchShown) { SearchSheet(model: model) }
        .sheet(item: $selecting) { message in SelectTextSheet(text: MarkdownReader.tidy(message.text)) }
        // A file an answer links to opens its page, to look at or save (web: the link downloads it).
        .environment(\.openURL, OpenURLAction { url in
            guard let path = MarkdownReader.fileLinkPath(url) else { return .systemAction }
            model.workspace.openLinkedFile(path)
            return .handled
        })
        .sheet(isPresented: $pendingShown) { PendingSheet(model: model) }
        .sheet(isPresented: $promptsShown) { PromptLibrarySheet(model: model) }
        .sheet(isPresented: Binding(get: { model.workspace.pane == "files" }, set: { if !$0 && model.workspace.pane == "files" { model.workspace.close() } }),
               onDismiss: {
                   // 从电脑选择文件 from an empty 对话文件: its sheet comes once this one has gone.
                   if pickAfterFiles {
                       pickAfterFiles = false
                       model.workspace.openPicker("remote")
                   }
               }) {
            FilesSheet(model: model) {
                pickAfterFiles = true
                model.workspace.close()
            }
        }
        .sheet(isPresented: Binding(get: { model.workspace.picker != nil && model.workspace.key?.chat != "@new" },
                                    set: { if !$0 { model.workspace.closePicker() } })) {
            PickerSheet(model: model)
        }
    }

    // MARK: Title bar

    @ToolbarContentBuilder
    private func toolbar(control: Control) -> some ToolbarContent {
        // The middle of the bar takes what the back button and the right side leave; the title sits left in it, so it
        // starts beside the back button (spec 4.3) without a fixed width.
        ToolbarItem(placement: .principal) {
            ConversationTitle(model: model)
        }
        .sharedBackgroundVisibility(.hidden)
        // A new conversation's page has nothing to stop and no menu yet (web .new-provisional).
        if !isNewPage(model.chat?.id) {
            conversationTools(control: control)
        }
    }

    @ToolbarContentBuilder
    private func conversationTools(control: Control) -> some ToolbarContent {
        if canStop(control) {
            ToolbarItem(placement: .topBarTrailing) {
                StopPill(enabled: control.available && !model.conversation.submitting && !model.workspace.busy) {
                    let token = control.raw["stop_token"].string()
                    if model.app == "claude" {
                        model.workspace.action("claude/choose", ["token": .string(token)])
                    } else {
                        model.conversation.stop()
                    }
                }
            }
            .sharedBackgroundVisibility(.hidden)
            ToolbarSpacer(.fixed, placement: .topBarTrailing)
        }
        ToolbarItem(placement: .topBarTrailing) {
            let runtime = runtimeOf(app: model.app, control: control.raw, page: model.runtime)
            HStack(spacing: 0) {
                if let percent = contextPercent(runtime) {
                    ContextRing(percent: percent) { runtimeShown = true }
                }
                Menu {
                    Button("电脑上打开", systemImage: "arrow.up.forward.app") { model.workspace.openOnComputer() }
                        .disabled(model.workspace.busy)
                    Button("会话状态", systemImage: "info.circle") {
                        // The menu closes first; the panel then opens from the ring.
                        Task {
                            try? await Task.sleep(for: .milliseconds(350))
                            runtimeShown = true
                        }
                    }
                    Button("查找消息", systemImage: "magnifyingglass") { searchShown = true }
                    Button("对话文件", systemImage: "doc.on.doc") { model.workspace.panel("files") }
                    Button("常用提示语", systemImage: "text.quote") { promptsShown = true }
                    let unconfirmed = model.conversation.submissions.filter { ["提交中", "送达状态待确认"].contains($0.label) }.count
                    if unconfirmed > 0 {
                        Button {
                            pendingShown = true
                        } label: {
                            Label("待核对发送记录（\(unconfirmed)）", systemImage: "clock")
                        }
                    }
                    let folder = folderLine
                    if !folder.isEmpty {
                        Section {
                            Text(folder)
                        }
                    }
                } label: {
                    Image(systemName: "ellipsis")
                        .frame(width: 32, height: 36)
                        .contentShape(Rectangle())
                }
                .accessibilityLabel(Text("对话菜单"))
            }
            .popover(isPresented: $runtimeShown) {
                RuntimePanel(app: model.app, control: control.raw, runtime: runtime)
                    .presentationCompactAdaptation(.popover)
            }
        }
    }

    /// 停止这一轮 shows while the source runs; Claude stops with the token its desktop gives.
    private func canStop(_ control: Control) -> Bool {
        control.running && (model.app != "claude" || !control.raw["stop_token"].string().isEmpty)
    }

    /// The folder the conversation runs in, grey at the menu's bottom (the web has it after the first two rows).
    private var folderLine: String {
        let meta = model.pageMeta
        let cwd = meta["cwd"].string()
        if !cwd.isEmpty { return cwd }
        let folder = meta["folder"].string()
        return folder.isEmpty ? model.chat?.folder ?? "" : folder
    }

    @ViewBuilder
    private func notes(control: Control) -> some View {
        VStack(spacing: 0) {
            DelayedProgressLine(busy: model.busy)
            if model.fixture {
                NoteBar(text: "本地示例 · 固定数据 · 未连接真实服务", tone: .info)
            }
            if let error = model.error {
                NoteBar(text: error, tone: .error, action: "重试", actionEnabled: !model.busy, onAction: model.retry)
            }
            let connection = model.conversation.connection
            if connection.contains("中断") || connection.contains("失效") {
                NoteBar(text: connection, tone: .connection)
            }
        }
    }

    // MARK: Messages

    @ViewBuilder
    private var historyTools: some View {
        VStack(spacing: 0) {
            if model.olderAvailable {
                Button("加载更早消息") {
                    keepTop = model.messages.first?.id
                    model.older()
                }
                .buttonStyle(PillStyle(kind: .text))
                .disabled(model.busy)
            }
            if model.newerAvailable {
                Text("这里是历史位置，后面还有更新的消息。")
                    .noteFont()
                    .foregroundStyle(Palette.muted)
                    .padding(.vertical, 8)
            }
            if !model.busy && model.messages.isEmpty && !isNewPage(model.chat?.id) && handoff == nil {
                Text("暂无消息")
                    .noteFont()
                    .foregroundStyle(Palette.muted)
                    .padding(24)
            }
        }
        .frame(maxWidth: .infinity)
    }

    /// A first message whose conversation the computer has not made yet ends up here (web new-chat-ui.js): the page
    /// shows it with where it stands; once made, the conversation shows it until its record has it.
    @ViewBuilder
    private var newFirst: some View {
        if isNewPage(model.chat?.id) {
            if let job = model.jobs.jobs.first(where: { $0.preview == model.chat?.id }) {
                NewFirstMessage(text: job.text, status: newJobInline(job), problem: job.problem) { model.openJob(job) }
            } else {
                Text("这个创建请求已经处理过了，请从对话列表打开。")
                    .noteFont()
                    .foregroundStyle(Palette.muted)
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 16)
            }
        } else if let handoff {
            NewFirstMessage(text: handoff.text, status: "", problem: false)
        }
    }

    /// The first message of a conversation just made, until its record shows a message of the user's.
    private var handoff: NewHandoff? {
        guard let handoff = model.handoff, handoff.id == model.chat?.id, handoff.app == model.app,
              !model.messages.contains(where: { $0.role == "user" }) else { return nil }
        return handoff
    }

    @ViewBuilder
    private var newMessagesPill: some View {
        if unseen && !atBottom {
            Button {
                unseen = false
                if model.newerAvailable {
                    model.latest()
                } else {
                    withAnimation(.easeOut(duration: 0.3)) { position.scrollTo(edge: .bottom) }
                }
            } label: {
                Label("有新消息", systemImage: "arrow.down")
                    .buttonFont()
                    .foregroundStyle(Palette.ink)
                    .padding(.horizontal, 16)
                    .frame(minHeight: 40)
            }
            .buttonStyle(.plain)
            .glassEffect(.regular.interactive(), in: .capsule)
            .padding(.bottom, 12)
            .accessibilityLabel(Text("有新消息，回到底部"))
            .transition(.opacity.combined(with: .scale(scale: 0.96)))
        }
    }

    // MARK: Reading position (B09)

    /// Opening (or 回到最新, a found message): to the saved place when there is one, otherwise the bottom.
    private func restore() {
        guard !model.messages.isEmpty else { return }
        if let anchor = model.anchor, model.messages.contains(where: { $0.id == anchor.message }) {
            position.scrollTo(id: anchor.message, anchor: .top)
            atBottom = false
        } else {
            position.scrollTo(edge: .bottom)
            atBottom = !model.newerAvailable
        }
        unseen = false
        restored = true
    }

    /// New output: follow it at the bottom; otherwise say there is more below.
    private func follow() {
        guard restored, model.conversation.revision > 0, !model.messages.isEmpty else { return }
        if atBottom && !model.newerAvailable {
            position.scrollTo(edge: .bottom)
        } else {
            withAnimation(.easeOut(duration: 0.2)) { unseen = true }
        }
    }

    /// Older messages came in above: the message that was first stays where the reader saw it.
    private func keepPlace() {
        guard let keep = keepTop, model.messages.first?.id != keep else { return }
        keepTop = nil
        position.scrollTo(id: keep, anchor: .top)
    }

    private func saveAnchor() {
        guard restored, let id = position.viewID(type: String.self) else { return }
        model.saveAnchor(message: id, offset: 0)
    }
}

/// 停止这一轮 (web .stop-turn): a light red capsule with red text in the title bar, kept apart from the ring and ⋯.
private struct StopPill: View {
    let enabled: Bool
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            Text("停止这一轮")
                .captionFont(.medium)
                .foregroundStyle(Palette.stopInk.opacity(enabled ? 1 : 0.45))
                .lineLimit(1)
                .padding(.horizontal, 12)
                .frame(minHeight: 36)
                .background(Palette.stopFill, in: Capsule())
                .contentShape(Capsule())
        }
        .buttonStyle(PressScaleStyle())
        .disabled(!enabled)
        .accessibilityHint(Text(enabled ? "" : "暂时不能控制这个来源"))
    }
}

/// The title and, under it, the project and source (web #cvTitle, #cvMeta), left beside the back button.
private struct ConversationTitle: View {
    let model: AppModel

    var body: some View {
        let folder = model.chat?.folder.isEmpty == false ? model.chat?.folder ?? "" : model.pageMeta["folder"].string()
        let meta = [folder, Labels.sourceName(model.app)].filter { !$0.isEmpty }.joined(separator: " · ")
        VStack(alignment: .leading, spacing: 2) {
            Text(model.chat?.title ?? "对话")
                .chatTitleFont()
                .foregroundStyle(Palette.ink)
                .lineLimit(1)
                .accessibilityAddTraits(.isHeader)
            if !meta.isEmpty {
                Text(meta)
                    .captionFont()
                    .foregroundStyle(Palette.muted)
                    .lineLimit(1)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .fixedSize(horizontal: false, vertical: true)
    }
}
