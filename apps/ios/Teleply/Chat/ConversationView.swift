import SwiftUI
import TeleplyModel
import TeleplyState

/// The conversation page's reading part (spec 4.3; Android ChatScreen): the title with project and source, the
/// context ring and ⋯ in the title bar; the messages scroll under it. Following the bottom only while the reader is
/// there; reading above keeps its place and "有新消息 ↓" appears (B09). Sending arrives in 0.3.0.
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

    var body: some View {
        let control = model.conversation.control
        let roles = timelineRoles(model.messages, app: model.app, raw: control.raw, running: control.running, asking: control.questions)
        let actions = MessageActions(select: { selecting = $0 }, expand: { model.expand($0) }, busy: model.busy)
        ScrollView {
            LazyVStack(alignment: .leading, spacing: 0) {
                historyTools
                ForEach(Array(zip(model.messages, roles)), id: \.0.id) { message, role in
                    TimelineItem(message: message, role: role, raw: control.raw, folds: $folds, actions: actions)
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
        .overlay(alignment: .bottom) { newMessagesPill }
        .toolbar { toolbar(control: control) }
        .navigationBarTitleDisplayMode(.inline)
        .toolbarRole(.editor)
        .onChange(of: model.scrollRevision, initial: true) { restore() }
        .onChange(of: model.conversation.revision) { follow() }
        .onChange(of: model.messages.first?.id) { keepPlace() }
        .onChange(of: model.screen) { if model.screen != .reading { saveAnchor() } }
        .sheet(isPresented: $searchShown) { SearchSheet(model: model) }
        .sheet(item: $selecting) { message in SelectTextSheet(text: message.text) }
    }

    // MARK: Title bar

    @ToolbarContentBuilder
    private func toolbar(control: Control) -> some ToolbarContent {
        ToolbarItem(placement: .topBarLeading) {
            ConversationTitle(model: model)
        }
        .sharedBackgroundVisibility(.hidden)
        ToolbarItem(placement: .topBarTrailing) {
            let runtime = runtimeOf(app: model.app, control: control.raw, page: model.runtime)
            HStack(spacing: 0) {
                if let percent = contextPercent(runtime) {
                    ContextRing(percent: percent) { runtimeShown = true }
                }
                Menu {
                    Button("会话状态", systemImage: "info.circle") {
                        // The menu closes first; the panel then opens from the ring.
                        Task {
                            try? await Task.sleep(for: .milliseconds(350))
                            runtimeShown = true
                        }
                    }
                    Button("查找消息", systemImage: "magnifyingglass") { searchShown = true }
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
            if !model.busy && model.messages.isEmpty {
                Text("暂无消息")
                    .noteFont()
                    .foregroundStyle(Palette.muted)
                    .padding(24)
            }
        }
        .frame(maxWidth: .infinity)
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
        .frame(maxWidth: 260, alignment: .leading)
        .fixedSize(horizontal: false, vertical: true)
    }
}
