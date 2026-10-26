import SwiftUI
import TeleplyModel
import TeleplyState

/// The conversation list (spec 4.1; Android ChatListScreen): ☰, "对话" and the computer in the title bar, ✎ on
/// the right; under it the source chips with ⋯ 列表显示, the search capsule and the rows. Read again every 10 s
/// while shown (the model does that); rows merge in without moving what was read.
struct ChatListView: View {
    let model: AppModel
    @Environment(Chrome.self) private var chrome
    @State private var query = ""
    @State private var folds = ListFolds()

    var body: some View {
        List {
            SourceChips(model: model)
                .plainRow()
            SearchLine(query: $query) { model.searchChats(query) }
                .plainRow()
            rows
        }
        .listStyle(.plain)
        .scrollContentBackground(.hidden)
        .environment(\.defaultMinListRowHeight, 0)
        .background(Palette.page)
        .scrollDismissesKeyboard(.immediately)
        .safeAreaBar(edge: .top) { notes }
        .overlay(alignment: .bottom) {
            NoticeToast(text: model.notice) { model.notice = nil }
                .padding(.bottom, 16)
        }
        .toolbar { toolbar }
        .navigationBarTitleDisplayMode(.inline)
        .task(id: query) {
            guard query != model.query else { return }
            try? await Task.sleep(for: .milliseconds(450))
            if !Task.isCancelled, query != model.query { model.searchChats(query) }
        }
        .onChange(of: model.query) { if model.query.isEmpty { query = "" } }
        .onChange(of: model.device?.id) { query = model.query }
    }

    // MARK: Title bar

    @ToolbarContentBuilder
    private var toolbar: some ToolbarContent {
        ToolbarItem(placement: .topBarLeading) {
            Button {
                chrome.openDrawer()
            } label: {
                Image(systemName: "line.3.horizontal")
            }
            .accessibilityLabel(Text("打开导航"))
        }
        ToolbarItem(placement: .topBarLeading) {
            ListTitle(model: model)
        }
        .sharedBackgroundVisibility(.hidden)
        ToolbarItem(placement: .topBarTrailing) {
            // 新建对话 arrives in 0.4.0 (plan phase 3); until then the button shows where it will be.
            Button {} label: {
                Image(systemName: "square.and.pencil")
            }
            .disabled(true)
            .accessibilityLabel(Text("新建对话"))
            .accessibilityHint(Text("新建对话在 0.4.0 提供"))
        }
    }

    @ViewBuilder
    private var notes: some View {
        VStack(spacing: 0) {
            DelayedProgressLine(busy: model.busy)
            if model.fixture {
                NoteBar(text: "本地示例 · 固定数据 · 未连接真实服务", tone: .info)
            }
            if let error = model.error {
                NoteBar(text: error, tone: .error, action: "重试", actionEnabled: !model.busy, onAction: model.retry)
            }
        }
    }

    // MARK: Rows

    @ViewBuilder
    private var rows: some View {
        if model.chats.isEmpty {
            if !model.busy {
                EmptyList(model: model, searching: !query.trimmingCharacters(in: .whitespaces).isEmpty) {
                    query = ""
                    model.clearListFilters()
                }
                .plainRow()
            }
        } else {
            ForEach(items) { item in
                row(item)
                    .plainRow()
            }
            if model.listMore {
                Button("加载更多对话", action: model.moreChats)
                    .buttonStyle(PillStyle())
                    .disabled(model.busy)
                    .frame(maxWidth: .infinity)
                    .padding(.top, 12)
                    .padding(.bottom, 24)
                    .plainRow()
            }
        }
    }

    @ViewBuilder
    private func row(_ item: ListItem) -> some View {
        switch item.kind {
        case .heading(let name):
            Text(name)
                .noteFont()
                .foregroundStyle(Palette.muted)
                .padding(.leading, 8)
                .padding(.top, 16)
                .padding(.bottom, 4)
                .accessibilityAddTraits(.isHeader)
        case .chat(let chat, let first):
            let key = rowKey(chat)
            Button {
                if chat.group {
                    withAnimation(.easeOut(duration: 0.2)) { folds.toggle(key) }
                } else if !chat.kind.isEmpty {
                    model.openChild(chat, parent: nil)
                } else {
                    model.open(chat)
                }
            } label: {
                ChatRow(chat: chat, first: first, open: chat.group ? folds.keys.contains(key) : nil)
            }
            .buttonStyle(RowPressStyle())
            .disabled(model.busy)
        case .fold(let chat):
            let key = rowKey(chat)
            FoldRow(open: folds.keys.contains(key), count: chat.childCount, running: chat.childRunning) {
                withAnimation(.easeOut(duration: 0.2)) { folds.toggle(key) }
            }
        case .child(let parent, let child):
            Button {
                model.openChild(child, parent: parent)
            } label: {
                ChildRow(chat: child)
            }
            .buttonStyle(RowPressStyle())
            .disabled(model.busy)
        case .more(let parent, let left):
            Button {
                model.moreChildren(parent)
            } label: {
                Text("再显示 \(min(50, left)) 个（共 \(parent.childCount) 个）")
                    .noteFont()
                    .foregroundStyle(Palette.accent)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(.leading, 24)
                    .padding(.top, 6)
                    .padding(.bottom, 14)
            }
            .buttonStyle(RowPressStyle())
        }
    }

    /// The rows in order (Android chatRows): group headings when grouping, a fold row under a conversation with
    /// children, and its open children with 再显示.
    private var items: [ListItem] {
        let name: (Chat) -> String
        switch model.listGroup {
        case "project": name = { $0.folder.isEmpty ? "未分组" : $0.folder }
        case "app": name = { Labels.sourceName($0.app) }
        default: name = { _ in "" }
        }
        let ordered = model.listGroup == "none" ? model.chats
            : model.chats.enumerated().sorted { (name($0.element), $0.offset) < (name($1.element), $1.offset) }.map(\.element)
        var result: [ListItem] = []
        var previous: String?
        for (index, chat) in ordered.enumerated() {
            let heading = name(chat)
            if !heading.isEmpty, heading != previous { result.append(ListItem(id: "group:" + heading, kind: .heading(heading))) }
            previous = heading
            let key = rowKey(chat)
            result.append(ListItem(id: "chat:" + key, kind: .chat(chat, first: index == 0)))
            if chat.childCount > 0, !chat.group { result.append(ListItem(id: "fold:" + key, kind: .fold(chat))) }
            if folds.keys.contains(key), chat.childCount > 0 {
                var seen = Set<String>()
                let kids = (chat.children + (model.moreKids[key] ?? [])).filter { seen.insert($0.id).inserted }
                for child in kids { result.append(ListItem(id: "child:\(key):\(child.id)", kind: .child(chat, child))) }
                if chat.childCount > kids.count { result.append(ListItem(id: "more:" + key, kind: .more(chat, chat.childCount - kids.count))) }
            }
        }
        return result
    }
}

private struct ListItem: Identifiable {
    enum Kind {
        case heading(String)
        case chat(Chat, first: Bool)
        case fold(Chat)
        case child(Chat, Chat)
        case more(Chat, Int)
    }

    let id: String
    let kind: Kind
}

/// Open folds of children, kept on this phone (web lbr_conv_folds).
@Observable
final class ListFolds {
    private(set) var keys: Set<String>

    init() {
        keys = Set(UserDefaults.standard.stringArray(forKey: "teleply.list.folds") ?? [])
    }

    func toggle(_ key: String) {
        if keys.contains(key) { keys.remove(key) } else { keys.insert(key) }
        UserDefaults.standard.set(Array(keys).sorted(), forKey: "teleply.list.folds")
    }
}

extension View {
    /// A list row drawn by the page itself: no system separator, inset or background.
    func plainRow() -> some View {
        listRowSeparator(.hidden)
            .listRowInsets(EdgeInsets(top: 0, leading: 16, bottom: 0, trailing: 16))
            .listRowBackground(Color.clear)
    }
}

/// "对话" with the computer under it (web .app-heading): a menu of the account's computers when there is more
/// than one, ending with 账号与电脑.
private struct ListTitle: View {
    let model: AppModel

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            Text("对话")
                .titleFont()
                .foregroundStyle(Palette.ink)
                .accessibilityAddTraits(.isHeader)
            let devices = model.account?.devices ?? []
            let label = model.device?.label ?? "电脑上的工作，随时继续"
            if devices.count > 1 {
                Menu {
                    Picker("切换电脑", selection: selection) {
                        ForEach(devices) { device in
                            if device.connectable {
                                Text(device.label).tag(device.id)
                            } else {
                                Text(device.label + "（电脑离线）").tag(device.id)
                            }
                        }
                    }
                    .pickerStyle(.inline)
                    Section {
                        Button("账号与电脑", systemImage: "desktopcomputer") { model.showComputers() }
                    }
                } label: {
                    Text(label + " ⌄")
                        .captionFont(.medium)
                        .foregroundStyle(Palette.muted)
                        .lineLimit(1)
                }
                .menuStyle(.button)
                .buttonStyle(.plain)
                .accessibilityLabel(Text("切换电脑，当前是\(model.device?.label ?? "未选择")"))
            } else {
                Text(label)
                    .captionFont(.medium)
                    .foregroundStyle(Palette.muted)
                    .lineLimit(1)
            }
        }
        .fixedSize(horizontal: false, vertical: true)
    }

    /// Picking a computer connects to it; an offline one says so instead of switching.
    private var selection: Binding<String> {
        Binding(get: { model.device?.id ?? "" }, set: { id in
            guard id != model.device?.id, let device = model.account?.devices.first(where: { $0.id == id }) else { return }
            if device.connectable { model.select(device) } else { model.notice = "电脑已离线，请稍后刷新。" }
        })
    }
}

/// 全部 and a chip for each app this computer has, then ⋯ 列表显示 (spec 4.1). Only the computer's own apps: while
/// they are not known yet, only 全部 (and a filter already chosen) with a short note. The chips keep their full
/// width and scroll sideways; the edge they pass under fades while there is more that way. ⋯ stays put.
private struct SourceChips: View {
    let model: AppModel
    @State private var room = EdgeRoom()

    var body: some View {
        let known = model.knownApps
        let apps = known ?? (model.listSource == "all" ? [] : [model.listSource])
        let options = [("all", "全部")] + apps.map { ($0, Labels.sourceName($0)) }
        HStack(spacing: 8) {
            ScrollViewReader { proxy in
                ScrollView(.horizontal) {
                    HStack(spacing: 8) {
                        ForEach(options, id: \.0) { value, label in
                            SourceChip(label: label, selected: model.listSource == value) {
                                model.listDisplay(source: value)
                                withAnimation(.easeOut(duration: 0.25)) { proxy.scrollTo(value) }
                            }
                            .disabled(model.busy)
                            .id(value)
                        }
                        if known == nil, model.device != nil {
                            if model.sources.failed != nil, !model.sources.loading {
                                Button("读不到这台电脑的应用 · 重试", action: model.retrySources)
                                    .noteFont()
                                    .foregroundStyle(Palette.accent)
                                    .padding(.horizontal, 8)
                                    .frame(minHeight: 40)
                            } else {
                                Text("正在读取这台电脑的应用…")
                                    .noteFont()
                                    .foregroundStyle(Palette.muted)
                                    .padding(.horizontal, 8)
                                    .frame(minHeight: 40)
                            }
                        }
                    }
                }
                .scrollIndicators(.hidden)
                .onScrollGeometryChange(for: EdgeRoom.self) { geometry in
                    EdgeRoom(back: geometry.contentOffset.x > 1,
                             forward: geometry.contentOffset.x + geometry.containerSize.width < geometry.contentSize.width - 1)
                } action: { _, now in
                    withAnimation(.easeOut(duration: 0.15)) { room = now }
                }
                .mask(fade)
                .onAppear { proxy.scrollTo(model.listSource) }
                .onChange(of: model.listSource) { withAnimation(.easeOut(duration: 0.25)) { proxy.scrollTo(model.listSource) } }
            }
            ListDisplayMenu(model: model)
        }
        .padding(.top, 8)
        .padding(.bottom, 12)
    }

    private var fade: some View {
        HStack(spacing: 0) {
            LinearGradient(colors: [.black.opacity(room.back ? 0 : 1), .black], startPoint: .leading, endPoint: .trailing)
                .frame(width: 24)
            Rectangle().fill(.black)
            LinearGradient(colors: [.black, .black.opacity(room.forward ? 0 : 1)], startPoint: .leading, endPoint: .trailing)
                .frame(width: 24)
        }
    }
}

private struct EdgeRoom: Equatable {
    var back = false
    var forward = false
}

/// A source chip at its full width (web .seg button): accent with its text colour when chosen, otherwise the
/// button colour with an edge on dark.
private struct SourceChip: View {
    let label: String
    let selected: Bool
    let action: () -> Void
    @Environment(\.colorScheme) private var scheme

    var body: some View {
        Button(action: action) {
            Text(label)
                .buttonFont()
                .lineLimit(1)
                .fixedSize()
                .foregroundStyle(selected ? Palette.onAccent : Palette.ink)
                .padding(.horizontal, 14)
                .frame(minHeight: 40)
                .background(selected ? Palette.accent : Palette.controlFill, in: Capsule())
                .overlay {
                    if scheme == .dark && !selected { Capsule().stroke(Palette.controlBorder, lineWidth: 1) }
                }
                .padding(.vertical, 2)
                .contentShape(Capsule())
        }
        .buttonStyle(PressScaleStyle())
        .accessibilityAddTraits(selected ? [.isSelected, .isButton] : .isButton)
    }
}

/// ⋯ 列表显示 (spec 4.1): 分组, 排序, 状态 and 来源, each a picker whose options open as a submenu with the
/// current one ticked.
private struct ListDisplayMenu: View {
    let model: AppModel

    var body: some View {
        let known = model.knownApps
        let apps = known ?? (model.listSource == "all" ? [] : [model.listSource])
        Menu {
            Picker("分组", selection: Binding(get: { model.listGroup }, set: { model.listDisplay(group: $0) })) {
                Text("不分组").tag("none")
                Text("按项目").tag("project")
                Text("按来源应用").tag("app")
            }
            .pickerStyle(.menu)
            Picker("排序", selection: Binding(get: { model.listSort }, set: { model.listDisplay(sort: $0) })) {
                Text("最近活动").tag("updated")
                Text("创建时间").tag("created")
            }
            .pickerStyle(.menu)
            Picker("状态", selection: Binding(get: { model.listStatus }, set: { model.listDisplay(status: $0) })) {
                Text("全部").tag("all")
                Text("运行中").tag("running")
                Text("等待处理").tag("waiting")
                Text("已结束").tag("done")
            }
            .pickerStyle(.menu)
            Picker("来源", selection: Binding(get: { model.listSource }, set: { model.listDisplay(source: $0) })) {
                Text("全部应用").tag("all")
                ForEach(apps, id: \.self) { app in
                    Text(Labels.sourceName(app)).tag(app)
                }
            }
            .pickerStyle(.menu)
            if known == nil {
                Text(model.sources.failed != nil && !model.sources.loading ? "读不到这台电脑上有哪些应用，可在列表上方重试" : "正在读取这台电脑上的应用…")
            }
        } label: {
            Image(systemName: "ellipsis")
                .font(.system(size: 17, weight: .medium))
                .frame(width: 30, height: 30)
        }
        .menuStyle(.button)
        .buttonStyle(.glass)
        .buttonBorderShape(.circle)
        .accessibilityLabel(Text("列表显示选项"))
    }
}

/// The search capsule under the chips (web placeholder). Searches as typing stops, or on the keyboard's search key.
private struct SearchLine: View {
    @Binding var query: String
    let search: () -> Void
    @Environment(\.colorScheme) private var scheme

    var body: some View {
        HStack(spacing: 10) {
            Image(systemName: "magnifyingglass")
                .font(.system(size: 16, weight: .medium))
                .foregroundStyle(Palette.muted)
                .accessibilityHidden(true)
            TextField("", text: $query, prompt: Text("搜索对话标题或文件夹").foregroundStyle(Palette.muted))
                .bodyFont()
                .foregroundStyle(Palette.ink)
                .tint(Palette.accent)
                .submitLabel(.search)
                .autocorrectionDisabled()
                .onSubmit(search)
                .accessibilityLabel(Text("搜索对话标题或文件夹"))
            if !query.isEmpty {
                Button {
                    query = ""
                    search()
                } label: {
                    Image(systemName: "xmark.circle.fill")
                        .foregroundStyle(Palette.muted)
                        .frame(width: 32, height: 32)
                }
                .accessibilityLabel(Text("清除搜索"))
            }
        }
        .padding(.leading, 14)
        .padding(.trailing, 6)
        .frame(minHeight: 44)
        .background(Palette.controlFill, in: Capsule())
        .overlay {
            if scheme == .dark { Capsule().stroke(Palette.controlBorder, lineWidth: 1) }
        }
        .padding(.bottom, 8)
    }
}

/// No rows (spec 8.2; Android EmptyList): which filters apply, with 清除筛选; a computer without any of the apps
/// says so with 重试 instead.
private struct EmptyList: View {
    let model: AppModel
    let searching: Bool
    let clear: () -> Void

    var body: some View {
        VStack(spacing: 10) {
            if model.knownApps?.isEmpty == true {
                Text("这台电脑上没有找到桌面应用")
                    .headingFont()
                    .foregroundStyle(Palette.ink)
                Text("没找到 Codex、Claude 或 DeepSeek 桌面版。装好后点重试；也可以在电脑的 remote_config.json 里用 \"apps\" 指定。")
                    .noteFont()
                    .foregroundStyle(Palette.muted)
                    .multilineTextAlignment(.center)
                Button("重试", action: model.retrySources)
                    .buttonStyle(PillStyle())
            } else {
                Text(model.error == nil ? "没有找到对话" : "暂时无法读取对话")
                    .headingFont()
                    .foregroundStyle(Palette.ink)
                if !conditions.isEmpty {
                    Text("当前条件：" + conditions.joined(separator: "，"))
                        .noteFont()
                        .foregroundStyle(Palette.muted)
                        .multilineTextAlignment(.center)
                }
                if searching || model.listSource != "all" || model.listStatus != "all" {
                    Button("清除筛选", action: clear)
                        .buttonStyle(PillStyle())
                }
            }
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, 32)
    }

    private var conditions: [String] {
        var parts: [String] = []
        if model.listSource != "all" { parts.append("来源：" + Labels.sourceName(model.listSource)) }
        let states = ["running": "运行中", "waiting": "等待处理", "done": "已结束"]
        if model.listStatus != "all" { parts.append("状态：" + (states[model.listStatus] ?? "")) }
        if searching { parts.append("搜索：" + model.query) }
        return parts
    }
}
