import SwiftUI
import TeleplyModel
import TeleplyState

/// Projects a new conversation went to from this phone, newest first (web lbr_new_folder; Android new_folders_):
/// the next one starts there, and they come first in the menu. A convenience of this phone only.
enum RecentFolders {
    static func list(_ app: String) -> [String] {
        UserDefaults.standard.stringArray(forKey: "teleply.new.folders." + app) ?? []
    }

    static func remember(_ app: String, _ path: String) {
        guard !path.isEmpty else { return }
        UserDefaults.standard.set(Array(([path] + list(app).filter { $0 != path }).prefix(8)), forKey: "teleply.new.folders." + app)
    }

    /// The computer's folders, the recently used ones first.
    static func ordered(_ app: String, _ folders: [JSONValue]) -> [JSONValue] {
        let recent = list(app)
        return folders.enumerated().sorted { a, b in
            let x = recent.firstIndex(of: a.element["path"].string()) ?? Int.max
            let y = recent.firstIndex(of: b.element["path"].string()) ?? Int.max
            return x == y ? a.offset < b.offset : x < y
        }.map(\.element)
    }
}

/// 新建对话 (spec 4.4; web new-chat-ui.js; Android NewChatSheet): a sheet at middle height, glass on iOS 26, that
/// fits one screen. The source, the first message with ＋ and 创建并发送, then one row each for 项目 and 模型与推理强度
/// (DeepSeek also 权限); a row opens its menu where it is. Nothing here waits on the computer: the lists of last
/// time show and the computer's come in behind. The server takes no mode for a new conversation, so plan mode is
/// chosen in the conversation afterwards.
struct NewChatSheet: View {
    let model: AppModel
    @Environment(\.dismiss) private var dismiss
    @State private var confirming: JSONValue?
    @State private var searching = false

    var body: some View {
        let workspace = model.workspace
        let target = model.pendingNew
        let key = workspace.key
        let app = target?.app ?? key?.app ?? model.app
        // Only the apps this computer has, as read when it was entered: nothing is read while the sheet moves.
        let known = model.knownApps
        let apps = known ?? [app]
        let ready = key?.chat == "@new" && key?.app == app && workspace.ready && workspace.pane == "new"
        // While another source binds, the sheet keeps its shape with the carried words and nothing to press.
        let saved: JSONValue = ready ? workspace.saved : ["first_message": .string(target?.text ?? "")]
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 12) {
                    if apps.count > 1 {
                        Picker("来源", selection: Binding(get: { app }, set: { next in switchSource(to: next, from: app, ready: ready) })) {
                            ForEach(apps, id: \.self) { Text(Labels.sourceName($0)).tag($0) }
                        }
                        .pickerStyle(.segmented)
                    }
                    if known == nil { sourceNote(app) }
                    if ready, let error = workspace.error {
                        Text(error)
                            .noteFont()
                            .foregroundStyle(Palette.danger)
                    }
                    NewComposer(model: model, app: app, saved: saved, ready: ready)
                    if let note = workspace.newNote {
                        Text(note)
                            .noteFont()
                            .foregroundStyle(Palette.muted)
                    }
                    VStack(spacing: 0) {
                        folderRow(app: app, saved: saved, ready: ready)
                        modelRow(app: app, saved: saved, ready: ready)
                        if app == "deepseek" { permissionRow(saved: saved, ready: ready) }
                    }
                }
                .padding(.horizontal, 20)
                .padding(.top, 4)
                .padding(.bottom, 16)
            }
            .scrollBounceBehavior(.basedOnSize)
            .scrollDismissesKeyboard(.interactively)
            .navigationTitle("新建对话")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button(role: .close) { dismiss() }
                }
            }
            .navigationDestination(isPresented: $searching) { FolderSearch(model: model, app: app) }
        }
        .presentationDetents([.medium, .large])
        // A source the computer turns out not to have: its first app instead, with the words typed so far.
        .task(id: "\(known ?? [])|\(app)|\(ready)") {
            guard let first = known?.first, ready, known?.contains(app) == false else { return }
            switchSource(to: first, from: app, ready: ready)
        }
        .alert(confirmTitle, isPresented: confirmShown, presenting: confirming) { option in
            Button("取消", role: .cancel) {}
            Button("确认选择此权限") { workspace.setNewPermission(option) }
        } message: { option in
            Text(option["description"].string())
        }
    }

    /// Another source, the words written so far carried over.
    private func switchSource(to next: String, from app: String, ready: Bool) {
        guard next != app, ready else { return }
        let text = model.workspace.saved["first_message"].string()
        if !text.isEmpty { model.workspace.edit("first_message", "") }
        model.startNew(app: next, text: text, switching: true)
    }

    @ViewBuilder
    private func sourceNote(_ app: String) -> some View {
        let name = Labels.sourceName(app)
        if model.sources.failed != nil && !model.sources.loading {
            Button("读不到这台电脑上有哪些应用，先用 \(name)。点这里重试") { model.retrySources() }
                .noteFont()
                .foregroundStyle(Palette.accent)
                .buttonStyle(.plain)
        } else {
            Text("正在读取这台电脑上的应用，先用 \(name)")
                .noteFont()
                .foregroundStyle(Palette.muted)
        }
    }

    // MARK: 项目

    @ViewBuilder
    private func folderRow(app: String, saved: JSONValue, ready: Bool) -> some View {
        let workspace = model.workspace
        let data = ready ? workspace.newData : [:]
        let folders = RecentFolders.ordered(app, data["folders"]["items"].array)
        let folder = saved["folder"].string()
        let projectless = saved["projectless"].bool()
        let current = folders.first { $0["path"].string() == folder }
        let none = folder.isEmpty && app != "deepseek"
        let title = none ? "无项目" : current.map { $0["name"].string().isEmpty ? folder : $0["name"].string() } ?? (folder.isEmpty ? "选择工作区" : lastPart(folder))
        let detail = none ? "不放进任何项目" : !folder.isEmpty ? folder : data.has("folders") ? "DeepSeek 的工作区" : "读取电脑上的项目…"
        Menu {
            Group {
                if app != "deepseek" {
                    CheckRow(title: "无项目", detail: app == "claude" ? "Claude 不选文件夹，电脑上显示 No folder" : "在「文档\\Codex」下新建一个文件夹",
                             on: folder.isEmpty) {
                        workspace.chooseFolder("", projectless: true)
                    }
                }
                ForEach(Array(folders.prefix(8).enumerated()), id: \.offset) { _, row in
                    let path = row["path"].string()
                    CheckRow(title: row["name"].string().isEmpty ? path : row["name"].string(), detail: path, on: !folder.isEmpty && folder == path) {
                        workspace.chooseFolder(path, projectless: false)
                    }
                }
                if folders.count > 8 {
                    Button("搜索全部项目…", systemImage: "magnifyingglass") { searching = true }
                }
                if !data.has("folders") {
                    Text("首次读取电脑上的项目…")
                } else if folders.isEmpty {
                    Text(app == "deepseek" ? "电脑上的 DeepSeek 还没有工作区" : "电脑上还没有项目文件夹")
                }
            }
            .onAppear { workspace.loadNewFolders() }
        } label: {
            ChoiceRowLabel(symbol: none ? "tray" : "folder", title: title, detail: detail, enabled: ready)
        }
        .menuOrder(.fixed)
        .disabled(!ready)
        .accessibilityLabel(Text("项目：\(title)，\(detail)"))
        // Like the web: a project not chosen yet starts as the one used last here, or the first the computer lists.
        .task(id: "\(ready)|\(folders.first?["path"].string() ?? "")") {
            if ready, folder.isEmpty, !projectless, let first = folders.first {
                workspace.chooseFolder(first["path"].string(), projectless: false)
            }
        }
    }

    // MARK: 模型与推理强度

    @ViewBuilder
    private func modelRow(app: String, saved: JSONValue, ready: Bool) -> some View {
        let workspace = model.workspace
        let options = (ready ? workspace.newData : [:])["models"]
        let models = options["models"].array
        let modelID = saved["new_model"].string()
        let effortID = saved["new_effort"].string()
        let chosen = models.first { $0["id"].string() == modelID }
        let efforts = chosen?["efforts"].array ?? []
        let effortLabel = efforts.first { $0["id"].string() == effortID }.map { app == "codex" ? effortName($0["id"].string()) : $0["label"].string() }
        let named = chosen?["label"].string() ?? ""
        let title = modelID.isEmpty ? "默认模型" : (named.isEmpty ? (saved["new_model_label"].string().isEmpty ? modelID : saved["new_model_label"].string()) : named)
            + (effortLabel.map { " · " + $0 } ?? "")
        let detail = modelID.isEmpty ? "跟电脑当前设置走" : "新对话用这个模型"
        Menu {
            Group {
                CheckRow(title: "默认（电脑当前设置）", on: modelID.isEmpty) {
                    workspace.edit("new_model", "")
                    workspace.edit("new_model_label", "")
                    workspace.edit("new_effort", "")
                }
                ForEach(Array(models.enumerated()), id: \.offset) { _, row in
                    let id = row["id"].string()
                    let label = row["label"].string().isEmpty ? id : row["label"].string()
                    CheckRow(title: label, on: id == modelID) {
                        guard id != modelID else { return }
                        workspace.edit("new_model", .string(id))
                        workspace.edit("new_model_label", .string(label))
                        workspace.edit("new_effort", "")
                    }
                }
                if !efforts.isEmpty {
                    Section("推理强度") {
                        Picker("推理强度", selection: Binding(get: { effortID }, set: { workspace.edit("new_effort", .string($0)) })) {
                            Text("默认").tag("")
                            ForEach(Array(efforts.enumerated()), id: \.offset) { _, effort in
                                let id = effort["id"].string()
                                let label = effort["label"].string()
                                Text(app == "codex" ? effortName(id) : label.isEmpty ? id : label).tag(id)
                            }
                        }
                        .pickerStyle(.palette)
                    }
                }
                if !options.isObject {
                    Text("首次读取电脑上的模型…")
                } else if !options["note"].string().isEmpty {
                    Text(options["note"].string())
                } else if chosen == nil && !modelID.isEmpty && !models.isEmpty {
                    Text("之前选的模型不在电脑现在的列表里，请重新选。")
                }
            }
            .onAppear { workspace.loadNewModels() }
        } label: {
            ChoiceRowLabel(symbol: "sparkles", title: title, detail: detail, enabled: ready)
        }
        .menuOrder(.fixed)
        .disabled(!ready)
        .accessibilityLabel(Text("模型与推理强度：\(title)，\(detail)"))
    }

    // MARK: 权限 (DeepSeek)

    @ViewBuilder
    private func permissionRow(saved: JSONValue, ready: Bool) -> some View {
        let workspace = model.workspace
        let data = ready ? workspace.newData : [:]
        let current = saved["new_permission"].string()
        let options = data["permissions"]["options"].array
        let chosen = options.first { !current.isEmpty && $0["value"].string() == current }
        let title = chosen?["name"].string() ?? (saved["new_permission_name"].string().isEmpty ? "默认权限" : saved["new_permission_name"].string())
        Menu {
            Group {
                CheckRow(title: "默认权限", detail: "用 DeepSeek 当前的设置", on: current.isEmpty) { workspace.setNewPermission([:]) }
                ForEach(Array(options.enumerated()), id: \.offset) { _, option in
                    let on = current == option["value"].string()
                    let description = option["description"].string()
                    CheckRow(title: option["name"].string(), detail: description.isEmpty ? nil : description, on: on) {
                        guard !on else { return }
                        if option["confirm"].bool() { confirming = option } else { workspace.setNewPermission(option) }
                    }
                }
                if !data.has("permissions") { Text("首次读取电脑上的权限…") }
            }
            .onAppear { workspace.loadNewPermissions() }
        } label: {
            ChoiceRowLabel(symbol: "lock.shield", title: title, detail: "首条消息发送前设置并核对", enabled: ready)
        }
        .menuOrder(.fixed)
        .disabled(!ready)
        .accessibilityLabel(Text("权限：\(title)"))
    }

    private var confirmTitle: String {
        "确认改成「\(confirming?["name"].string() ?? "")」？"
    }

    private var confirmShown: Binding<Bool> {
        Binding(get: { confirming != nil }, set: { if !$0 { confirming = nil } })
    }

    private func lastPart(_ path: String) -> String {
        path.split(whereSeparator: { $0 == "/" || $0 == "\\" }).last.map(String.init) ?? path
    }
}

/// A choice row of the new conversation (web .new-folder): the icon, the value with one small line under it, ⌄.
private struct ChoiceRowLabel: View {
    let symbol: String
    let title: String
    let detail: String
    let enabled: Bool

    var body: some View {
        HStack(spacing: 12) {
            Image(systemName: symbol)
                .font(.system(size: 18, weight: .regular))
                .foregroundStyle(Palette.muted)
                .frame(width: 24)
            VStack(alignment: .leading, spacing: 2) {
                Text(title)
                    .scaledFont(15, .medium, relativeTo: .callout)
                    .foregroundStyle(Palette.ink.opacity(enabled ? 1 : 0.6))
                    .lineLimit(1)
                Text(detail)
                    .captionFont()
                    .foregroundStyle(Palette.muted)
                    .lineLimit(1)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            Image(systemName: "chevron.down")
                .font(.system(size: 13, weight: .semibold))
                .foregroundStyle(Palette.muted)
        }
        .padding(.horizontal, 4)
        .padding(.vertical, 10)
        .frame(minHeight: 60)
        .contentShape(Rectangle())
    }
}

/// The first message (web .new-composer): the text, then the round 创建并发送 button.
private struct NewComposer: View {
    let model: AppModel
    let app: String
    let saved: JSONValue
    let ready: Bool
    @FocusState private var focused: Bool

    var body: some View {
        let workspace = model.workspace
        let text = saved["first_message"].string()
        let uploads = saved["uploads"].array
        let extras = uploads.count + saved["references"].array.count
        let uploading = uploads.contains { $0["status"].string() != "ready" }
        let folder = saved["folder"].string()
        let canCreate = ready && !workspace.busy && (!text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || extras > 0) && !uploading
            && (app != "deepseek" || !folder.isEmpty)
        VStack(alignment: .leading, spacing: 0) {
            TextField("", text: Binding(get: { text }, set: { workspace.edit("first_message", .string($0)) }),
                      prompt: Text("想做什么？").foregroundStyle(Palette.muted), axis: .vertical)
                .bodyFont()
                .foregroundStyle(Palette.ink)
                .tint(Palette.accent)
                .lineLimit(2...6)
                .focused($focused)
                .disabled(!ready)
                .padding(.horizontal, 10)
                .padding(.vertical, 8)
                .accessibilityLabel(Text("首条消息"))
            HStack(spacing: 4) {
                Spacer(minLength: 0)
                Button {
                    guard canCreate else { return }
                    if !model.fixture { RecentFolders.remember(app, folder) }
                    workspace.create()
                } label: {
                    Image(systemName: "arrow.up")
                        .font(.system(size: 17, weight: .semibold))
                        .foregroundStyle(canCreate ? Palette.onAccent : Palette.muted)
                        .opacity(workspace.busy ? 0.5 : 1)
                        .frame(width: 40, height: 40)
                        .background(canCreate ? Palette.accent : Palette.controlFill, in: Circle())
                        .frame(width: 44, height: 44)
                        .contentShape(Circle())
                }
                .buttonStyle(PressScaleStyle(scale: 0.88))
                .disabled(!canCreate)
                .keyboardShortcut(.return, modifiers: .command)
                .accessibilityLabel(Text("创建并发送"))
                .accessibilityValue(Text(workspace.busy ? "提交中" : ""))
            }
        }
        .padding(.horizontal, 6)
        .padding(.top, 6)
        .padding(.bottom, 4)
        .background(Palette.sheet, in: RoundedRectangle(cornerRadius: 20, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: 20, style: .continuous).stroke(Palette.line, lineWidth: 1))
    }
}

/// 搜索全部项目…: every project the computer lists, with a search box (a system menu has no room for one).
private struct FolderSearch: View {
    let model: AppModel
    let app: String
    @State private var query = ""
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        let workspace = model.workspace
        let folders = RecentFolders.ordered(app, workspace.newData["folders"]["items"].array)
        let words = query.trimmingCharacters(in: .whitespaces)
        let hits = folders.filter { row in
            words.isEmpty || (row["name"].string() + " " + row["path"].string() + " " + row["sources"].array.map { $0.string() }.joined(separator: " "))
                .localizedCaseInsensitiveContains(words)
        }
        let folder = workspace.saved["folder"].string()
        List {
            if app != "deepseek" && (words.isEmpty || "无项目".contains(words)) {
                pick(title: "无项目", detail: "不放进任何项目", on: folder.isEmpty) { workspace.chooseFolder("", projectless: true) }
            }
            ForEach(Array(hits.enumerated()), id: \.offset) { _, row in
                let path = row["path"].string()
                pick(title: row["name"].string().isEmpty ? path : row["name"].string(), detail: path, on: folder == path) {
                    workspace.chooseFolder(path, projectless: false)
                }
            }
            if hits.isEmpty && !words.isEmpty {
                Text("没有匹配的项目文件夹")
                    .noteFont()
                    .foregroundStyle(Palette.muted)
            }
        }
        .listStyle(.plain)
        .searchable(text: $query, placement: .navigationBarDrawer(displayMode: .always), prompt: Text("搜索项目名称或路径"))
        .navigationTitle("项目")
        .navigationBarTitleDisplayMode(.inline)
    }

    private func pick(title: String, detail: String, on: Bool, action: @escaping () -> Void) -> some View {
        Button {
            action()
            dismiss()
        } label: {
            HStack(spacing: 10) {
                VStack(alignment: .leading, spacing: 2) {
                    Text(title)
                        .bodyFont()
                        .foregroundStyle(Palette.ink)
                    Text(detail)
                        .captionFont()
                        .foregroundStyle(Palette.muted)
                        .lineLimit(1)
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                if on {
                    Image(systemName: "checkmark")
                        .foregroundStyle(Palette.accent)
                }
            }
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .accessibilityAddTraits(on ? .isSelected : [])
    }
}
