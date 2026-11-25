import SwiftUI
import TeleplyModel
import TeleplyState

/// The conversation page (spec 4.3; Android ChatScreen): the title with project and source, 停止这一轮, the context
/// ring and ⋯ in the title bar; the messages scroll under it and under the glass input card. It always opens at the
/// latest messages (user 10-27). Following the bottom only while the reader is there; reading above keeps its place
/// and "有新消息 ↓" appears (B09). A redraw leaves unchanged messages alone (TimelineItem, TimelineMemo), and the ⋯
/// menu keeps what it opens to itself (ConversationMenu): a long conversation stays quick (10-27).
struct ConversationView: View {
    let model: AppModel
    @State private var position = ScrollPosition(idType: String.self)
    /// 11-16: following new output, and whether it is unseen while reading above (Android ReadingFollow).
    @State private var reading = ReadingFollow()
    @State private var nearBottom = true
    @State private var phase: ScrollPhase = .idle
    @State private var restored = false
    @State private var folds: [String: Bool] = [:]
    @State private var selecting: Message?
    /// A long message's whole words, read from the computer for 分享.
    @State private var sharing: String?
    /// The first message before 加载更早消息, kept in view when the older ones arrive above it.
    @State private var keepTop: String?
    /// 从电脑选择文件 was tapped in an empty 对话文件: the picker opens when that sheet has gone.
    @State private var pickAfterFiles = false
    /// The messages' roles, the pictures sent with them and the waiting cards, kept between redraws.
    @State private var memo = TimelineMemo()
    /// DemoLive (11-17 scroll probe): what last moved or flagged the page, newest last.
    @State private var trail: [String] = []
    /// 开发者选项 → 显示滚动诊断: the probe line on a real phone too (11-17).
    @AppStorage("TeleplyScrollProbe") private var probeSetting = false
    /// When this page instance was made: a new time after a jump means the page itself was made anew.
    @State private var born = Date()
    /// Probe only: the scroll view's latest numbers (ProbeGeometry).
    @State private var geo = ProbeGeometry()
    /// The question bar's tap moves VoiceOver to the first card too (spec 7).
    @AccessibilityFocusState private var cardFocused: Bool

    var body: some View {
        let control = model.conversation.control
        // The roles, the pictures sent with messages as the computer kept them (state `images`; web
        // message-projection.js) and the waiting cards, worked out again only when they change.
        let timeline = memo.update(messages: model.messages, app: model.app, cardsApp: model.conversation.key?.app ?? model.app,
                                   raw: control.raw, running: control.running, asking: control.questions,
                                   catalog: model.catalog)
        let busy = model.busy
        let actions = MessageActions(select: { message in model.whole(message) { selecting = $0 } }, expand: { model.expand($0) },
                                     diff: { model.workspace.diff($0) }, files: { model.workspace.filesOf(message: $0) },
                                     thread: { model.openCreated($0) }, picture: { await model.workspace.sentPicture($0, whole: $1) },
                                     whole: { model.whole($0, $1) }, share: { sharing = $0 }, busy: busy)
        let submissions = model.conversation.submissions
        let receipts = Dictionary(submissions.filter { !$0.request.isEmpty }.map { ($0.request, $0.label) }, uniquingKeysWith: { first, _ in first })
        // Sends still on their way that the record does not show yet (Android outbox). 0.6.5: a send taken by the
        // computer (已接收 etc.) stays here until the record has it, so it no longer disappears for 88 seconds while
        // Codex compacts a long conversation.
        let outbox = outboxSends(submissions, messages: model.messages,
                                 now: Int64(Date().timeIntervalSince1970 * 1000), olderUnread: model.olderAvailable)
        let cards = timeline.cards
        ScrollView {
            // A plain stack, not a lazy one: with LazyVStack the area above the input card went blank after the
            // keyboard came up (0.3.0 screenshots on iOS 26.5, two runs of three). Pages hold 60 messages, the
            // long demo 200; how that scrolls on a phone is T04.
            VStack(alignment: .leading, spacing: 0) {
                historyTools
                newFirst
                ForEach(Array(zip(model.messages, timeline.roles)), id: \.0.id) { message, role in
                    TimelineItem(model: model, message: message, role: role, raw: role.readsState ? control.raw : [:],
                                 receipt: message.request.isEmpty ? nil : receipts[message.request], pictures: timeline.pictures[message.id] ?? [],
                                 open: role.isOpen(folds), busy: role.waitsWhileBusy(message) && busy,
                                 fold: { key, open in folds[key] = open }, actions: actions)
                        .equatable()
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
                        reading = reading.opened(following: true)
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
                // 0.6.4: where the answer will appear, like the GPT app's 正在思考, with the turn's own timer.
                // 0.6.6: 正在压缩上下文 while the source compacts, with the compaction's own start when it says.
                if control.compacting {
                    ThinkingRow(step: "compact", started: control.compactStarted > 0 ? control.compactStarted : model.turnStarted)
                        .id("thinking")
                } else if control.running && !control.questions {
                    ThinkingRow(step: model.turnStep, started: model.turnStarted)
                        .id("thinking")
                }
            }
            .scrollTargetLayout()
            .frame(maxWidth: 820)
            .padding(.horizontal, 20)
            .padding(.bottom, 16)
            .frame(maxWidth: .infinity)
        }
        .scrollPosition($position, anchor: .top)
        .defaultScrollAnchor(reading.following ? .bottom : .top, for: .sizeChanges)
        .scrollDismissesKeyboard(.interactively)
        // Near the bottom: the end of what shows above the input card is within 48 points of the content's end. 11-17,
        // measured on iOS 26.5: containerSize is only the height between the bars (606 of 956) while contentOffset is
        // the top of the whole bounds, so the old sum (offset + container − bottom inset) stopped 350 points short of
        // the end and the page never read as near the bottom. The visible rect is the whole bounds: less the bottom
        // bar, its end is the content's end when the page is at the bottom.
        .onScrollGeometryChange(for: Bool.self) { geometry in
            geometry.visibleRect.maxY - geometry.contentInsets.bottom >= geometry.contentSize.height - 48
        } action: { _, bottom in
            nearBottom = bottom
            probe(bottom ? "near" : "far")
        }
        // Probe only: the scroll view's own numbers, to see how it measures its bottom (11-17).
        .onScrollGeometryChange(for: ProbeGeometry.self) { geometry in
            ProbeGeometry(offset: Int(geometry.contentOffset.y), size: Int(geometry.contentSize.height),
                          box: Int(geometry.containerSize.height), top: Int(geometry.contentInsets.top),
                          bottom: Int(geometry.contentInsets.bottom), seenTop: Int(geometry.visibleRect.minY),
                          seenBottom: Int(geometry.visibleRect.maxY))
        } action: { _, value in
            if probing { geo = value }
        }
        // The fingers themselves decide: starting to drag stops following at once (a programmatic scroll into
        // .animating does not). At rest near the bottom it follows again and finishes the scroll there.
        .onScrollPhaseChange { _, next in
            phase = next
            probe(String(describing: next))
            if next == .tracking || next == .interacting {
                reading = reading.dragged()
            } else if next == .idle, nearBottom {
                reading = reading.opened(following: true)
                position.scrollTo(edge: .bottom)
                probe("idle↓")
            }
        }
        .background(Palette.page)
        .overlay(alignment: .top) { if probing { probeLine } }
        .onAppear { probe("appear") }
        .onDisappear { probe("gone") }
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
        .onChange(of: control.running) { if $0 { follow() } }
        .onChange(of: timeline.cards.first?.id) { _ in follow() }
        // 11-16: a send follows the bottom again; its bubble then arrives under the same following.
        .onChange(of: model.conversation.sent) {
            guard $0 > 0 else { return }
            reading = reading.sent()
            withAnimation(.easeOut(duration: 0.3)) { position.scrollTo(edge: .bottom) }
            probe("sent↓")
        }
        .onChange(of: model.messages.first?.id) { keepPlace() }
        .sheet(item: $selecting) { message in SelectTextSheet(text: MarkdownReader.tidy(message.text)) }
        .sheet(isPresented: Binding(get: { sharing != nil }, set: { if !$0 { sharing = nil } })) {
            if let sharing {
                ShareSheet(items: [sharing]) { _ in }
                    .presentationDetents([.medium, .large])
            }
        }
        // A file an answer links to opens its page, to look at or save (web: the link downloads it).
        .environment(\.openURL, OpenURLAction { url in
            guard let path = MarkdownReader.fileLinkPath(url) else { return .systemAction }
            model.workspace.openLinkedFile(path)
            return .handled
        })
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
            ConversationMenu(model: model)
        }
    }

    /// 停止这一轮 shows while the source runs; Claude stops with the token its desktop gives. The three always had
    /// it; a new assistant also needs `stop` now (handoff 3.4).
    private func canStop(_ control: Control) -> Bool {
        let app = model.conversation.key?.app ?? model.app
        return control.running && model.offersStop(app)
            && (app != "claude" || !control.raw["stop_token"].string().isEmpty)
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
        if reading.unseen && !reading.following {
            Button {
                reading = reading.opened(following: true)
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

    /// Opening (or 回到最新): the bottom. A found message (查找消息): that message at the top.
    private func restore() {
        guard !model.messages.isEmpty else { return }
        if let anchor = model.anchor, model.messages.contains(where: { $0.id == anchor.message }) {
            position.scrollTo(id: anchor.message, anchor: .top)
            reading = reading.opened(following: false)
            probe("restore@")
        } else {
            position.scrollTo(edge: .bottom)
            reading = reading.opened(following: !model.newerAvailable)
            probe("restore↓")
        }
        // nearBottom is the scroll view's own measure only. Set here by hand (until 11-17) it stayed true while the
        // measure never changed, and every drag up went back to the bottom when the finger stopped (the user's iPhone).
        restored = true
    }

    /// New output: follow it at the bottom; reading above only says there is more below.
    private func follow() {
        guard restored, !model.messages.isEmpty else { return }
        if reading.following && !model.newerAvailable && phase == .idle {
            position.scrollTo(edge: .bottom)
            probe("follow↓")
        } else {
            reading = reading.arrived(newer: model.newerAvailable, scrolling: phase != .idle)
        }
    }

    /// Older messages came in above: the message that was first stays where the reader saw it, and the page reads
    /// above from then on (11-16).
    private func keepPlace() {
        guard let keep = keepTop, model.messages.first?.id != keep else { return }
        keepTop = nil
        reading = reading.dragged()
        position.scrollTo(id: keep, anchor: .top)
        probe("keep")
    }

    /// The probe line is on: the simulator check (DemoLive) or 开发者选项 → 显示滚动诊断.
    private var probing: Bool { DemoLive.on || probeSetting }

    /// Probe only: notes what moved or flagged the page, the last ten (11-17 scroll probe).
    private func probe(_ event: String) {
        guard probing else { return }
        trail = Array((trail + [event]).suffix(10))
    }

    /// Probe only: following, near the bottom, the unseen mark, the scroll phase, the frame count, the open count
    /// (scrollRevision) and when this page was made, then what last moved the page (11-17).
    private var probeLine: some View {
        let flags = "follow \(reading.following ? "Y" : "N") near \(nearBottom ? "Y" : "N") unseen \(reading.unseen ? "Y" : "N")"
        let where_ = "phase \(String(describing: phase)) rev \(model.conversation.revision) sr \(model.scrollRevision)"
        let made = "page " + born.formatted(date: .omitted, time: .standard)
        let numbers = "off \(geo.offset) size \(geo.size) box \(geo.box) in \(geo.top)/\(geo.bottom) seen \(geo.seenTop)-\(geo.seenBottom)"
        let line: String = flags + " " + where_ + " " + made + "\n" + numbers + "\n" + trail.joined(separator: " ")
        return Text(verbatim: line)
            .font(.system(size: 11, design: .monospaced))
            .foregroundStyle(Color.black)
            .padding(6)
            .background(Color.yellow.opacity(0.9), in: RoundedRectangle(cornerRadius: 6))
            .padding(.top, 140)
            .padding(.horizontal, 12)
            .allowsHitTesting(false)
            .accessibilityIdentifier("scroll-probe")
    }
}

/// 11-17 scroll probe: the scroll view's offset, content height, container height, insets and visible rect, in points.
private struct ProbeGeometry: Equatable {
    var offset = 0, size = 0, box = 0, top = 0, bottom = 0, seenTop = 0, seenBottom = 0
}

/// The context ring and ⋯ in the title bar, with what they open: 会话状态 (from the ring), 查找消息, 常用提示语 and
/// 待核对发送记录. A view of its own with its own state, so that opening one redraws this, not the page with its
/// messages (the ⋯ of a long DeepSeek conversation answered slowly, 10-27).
private struct ConversationMenu: View {
    let model: AppModel
    @State private var runtimeShown = false
    @State private var searchShown = false
    @State private var pendingShown = false
    @State private var promptsShown = false
    @State private var usageShown = false

    var body: some View {
        let control = model.conversation.control
        let runtime = runtimeOf(app: model.app, control: control.raw, page: model.runtime)
        HStack(spacing: 0) {
            if let percent = contextPercent(runtime) {
                ContextRing(percent: percent) { runtimeShown = true }
            }
            Menu {
                // The three keep their menu exactly; a new one usually opens no desktop window and has no 用量
                // (handoff 3.4).
                if model.offersOpenOnComputer() {
                    Button("电脑上打开", systemImage: "arrow.up.forward.app") { model.workspace.openOnComputer() }
                        .disabled(model.workspace.busy)
                }
                Button("会话状态", systemImage: "info.circle") {
                    // The menu closes first; the panel then opens from the ring.
                    Task {
                        try? await Task.sleep(for: .milliseconds(350))
                        runtimeShown = true
                    }
                }
                Button("查找消息", systemImage: "magnifyingglass") { searchShown = true }
                // 11-17: DeepSeek has no plan limits, so no 用量 for its conversations.
                if model.showsUsage() {
                    Button("用量", systemImage: "clock") { usageShown = true }
                }
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
        .sheet(isPresented: $searchShown) { SearchSheet(model: model) }
        .sheet(isPresented: $pendingShown) { PendingSheet(model: model) }
        .sheet(isPresented: $promptsShown) { PromptLibrarySheet(model: model) }
        .sheet(isPresented: $usageShown) { NavigationStack { UsageView(model: model) } }
    }

    /// The folder the conversation runs in, grey at the menu's bottom (the web has it after the first two rows).
    private var folderLine: String {
        let meta = model.pageMeta
        let cwd = meta["cwd"].string()
        if !cwd.isEmpty { return cwd }
        let folder = meta["folder"].string()
        return folder.isEmpty ? model.chat?.folder ?? "" : folder
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
                .fixedSize()
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
        let meta = [folder, Labels.sourceName(model.app, catalog: model.catalog)].filter { !$0.isEmpty }.joined(separator: " · ")
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
