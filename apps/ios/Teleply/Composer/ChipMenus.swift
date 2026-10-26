import SwiftUI
import TeleplyModel
import TeleplyState

/// Effort names as the web writes them (Android EffortNames).
func effortName(_ value: String) -> String {
    ["none": "无", "minimal": "最低", "low": "低", "medium": "中", "high": "高", "xhigh": "极高", "max": "最高", "ultra": "Ultra"][value] ?? value
}

/// What the chips say, per source (spec 4.3; Android chipLabels): Codex model · effort and 普通执行 / 计划;
/// Claude its desktop labels; DeepSeek model · effort and its permission. [plan] gives the mode chip the
/// selected look.
func chipLabels(app: String, raw: JSONValue, saved: JSONValue) -> (model: String, mode: String, plan: Bool) {
    let settings = raw["settings"]
    switch app {
    case "claude":
        let label = raw["model_label"].string()
        let model = label.isEmpty ? (settings["model"].string().isEmpty ? "模型" : settings["model"].string()) : label
        let effort = raw["effort_label"].string()
        let mode = raw["mode_label"].string()
        return (effort.isEmpty ? model : "\(model) · \(effort)", mode.isEmpty ? "默认" : mode, settings["mode"].string() == "plan")
    case "deepseek":
        let model = settings["model"].string().isEmpty ? "模型" : settings["model"].string()
        let effort = effortName(settings["reasoningEffort"].string())
        let permission = raw["permission_name"].string()
        return (effort.isEmpty ? model : "\(model) · \(effort)", permission.isEmpty ? "权限" : permission, false)
    default:
        let chosen = saved["settings"].isObject ? saved["settings"] : settings
        let id = chosen["model"].string()
        let named = raw["catalog"]["models"].array.first { $0["id"].string() == id }?["name"].string() ?? ""
        let name = named.isEmpty ? (id.isEmpty ? "模型" : id) : named
        let effort = effortName(chosen["effort"].string())
        let plan = chosen["mode"].string() == "plan"
        return (effort.isEmpty ? name : "\(name) · \(effort)", plan ? "计划" : "普通执行", plan)
    }
}

/// A model or mode chip (web .composer-chip): a clear capsule, 12 pt / 500 (11 pt on screens under 370 pt), a
/// small arrow, at most 150 pt wide; plan mode takes the selected colours. The label of a system menu.
struct ChipLabel: View {
    let text: String
    var selected = false
    var narrow = false

    var body: some View {
        HStack(spacing: 2) {
            Text(text)
                .scaledFont(narrow ? 11 : 12, .medium, relativeTo: .caption)
                .lineLimit(1)
            Image(systemName: "chevron.down")
                .font(.system(size: 9, weight: .semibold))
        }
        .foregroundStyle(selected ? Palette.selectedInk : Palette.muted)
        .padding(.horizontal, 10)
        .frame(minHeight: 32)
        .frame(maxWidth: 150)
        .background(selected ? Palette.selectedFill : .clear, in: Capsule())
        .contentShape(Capsule())
    }
}

/// A menu row with a tick when chosen and an optional second line (系统菜单 puts the second Text under the first).
struct CheckRow: View {
    let title: String
    var detail: String?
    let on: Bool
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            if on {
                Label {
                    Text(title)
                    if let detail { Text(detail) }
                } icon: {
                    Image(systemName: "checkmark")
                }
            } else {
                Text(title)
                if let detail { Text(detail) }
            }
        }
    }
}

/// The model chip's menu (spec 4.3, B17): the models with a tick on the current one, then the current model's
/// effort steps in one row. Codex binds the choice to the next message; Claude and DeepSeek switch on the computer
/// and the status line says how it went. Claude's and DeepSeek's lists show at once as last read and are checked
/// behind; only 刷新电脑上的列表 has the computer open Claude's menus again.
struct ModelMenu: View {
    let model: AppModel

    var body: some View {
        let app = model.workspace.key?.app ?? model.app
        let raw = model.conversation.control.raw
        let current = raw["settings"]
        Group {
            switch app {
            case "codex": codex(raw: raw, current: current)
            case "claude": claude(current: current)
            default: deepseek(current: current)
            }
        }
        .onAppear { model.workspace.loadChoices(model: current["model"].string()) }
        .onDisappear { if app == "claude" { model.workspace.closeClaudeMenu() } }
        .disabled(model.workspace.busy)
    }

    @ViewBuilder
    private func codex(raw: JSONValue, current: JSONValue) -> some View {
        let saved = model.workspace.saved
        let chosen = saved["settings"].isObject ? saved["settings"] : current
        let models = raw["catalog"]["models"].array
        if models.isEmpty {
            Text("电脑没有给出可选的模型")
        }
        ForEach(Array(models.enumerated()), id: \.offset) { _, row in
            let id = row["id"].string()
            CheckRow(title: row["name"].string().isEmpty ? id : row["name"].string(), on: id == chosen["model"].string()) {
                guard id != chosen["model"].string() else { return }
                var next = chosen.object
                next["model"] = .string(id)
                next["effort"] = .string(row["default_effort"].string())
                model.workspace.selectSettings(.object(next), expected: current)
            }
        }
        let efforts = models.first { $0["id"].string() == chosen["model"].string() }?["efforts"].array.map { $0.string() } ?? []
        if !efforts.isEmpty {
            Section("推理强度") {
                Picker("推理强度", selection: Binding(get: { chosen["effort"].string() }, set: { effort in
                    var next = chosen.object
                    next["effort"] = .string(effort)
                    model.workspace.selectSettings(.object(next), expected: current)
                })) {
                    ForEach(efforts, id: \.self) { effort in
                        Text(effortName(effort)).tag(effort)
                    }
                }
                .pickerStyle(.palette)
            }
        }
    }

    @ViewBuilder
    private func claude(current: JSONValue) -> some View {
        let workspace = model.workspace
        let catalog = workspace.choices["source_catalog"]
        if !catalog.isObject {
            // Only a conversation never read before waits here: the computer opens Claude's menus once.
            Text(workspace.choicesError ?? "首次读取电脑上的模型列表…")
        } else {
            let expected = catalog["model_id"].string()
            ForEach(Array(catalog["model"].array.enumerated()), id: \.offset) { _, row in
                let on = row["selected"].bool()
                CheckRow(title: row["name"].string(), on: on) {
                    if !on { workspace.claudeSetting(kind: "model", name: row["name"].string(), value: true, expected: expected) }
                }
            }
            ForEach(Array(catalog["fast"].array.enumerated()), id: \.offset) { _, row in
                let on = row["selected"].bool()
                CheckRow(title: row["name"].string(), on: on) {
                    workspace.claudeSetting(kind: "fast", name: row["name"].string(), value: .bool(!on), expected: expected)
                }
            }
            let efforts = catalog["effort"].array
            // JSONValue takes nil as .null, so the optional is spelled out.
            let range: JSONValue? = efforts.count == 1 && efforts[0]["range"]["step"].double() > 0 ? efforts[0]["range"] : nil
            if let range {
                // The desktop shows effort as one slider with steps.
                let steps = stride(from: range["min"].double(), through: range["max"].double(), by: range["step"].double()).prefix(20).map { $0 }
                Section("推理强度") {
                    Picker("推理强度", selection: Binding(get: { efforts[0]["value"].double() }, set: { value in
                        workspace.claudeSetting(kind: "effort", name: efforts[0]["name"].string(), value: .number(value), expected: expected)
                    })) {
                        ForEach(steps, id: \.self) { value in
                            let label = range["labels"][String(Int(value))].string()
                            Text(label.isEmpty ? (value.rounded() == value ? String(Int(value)) : String(value)) : label).tag(value)
                        }
                    }
                    .pickerStyle(.palette)
                }
            } else if !efforts.isEmpty {
                Section("推理强度") {
                    Picker("推理强度", selection: Binding(get: { efforts.first { $0["selected"].bool() }?["name"].string() ?? "" }, set: { name in
                        workspace.claudeSetting(kind: "effort", name: name, value: true, expected: expected)
                    })) {
                        ForEach(efforts.map { $0["name"].string() }, id: \.self) { name in
                            Text(name).tag(name)
                        }
                    }
                    .pickerStyle(.palette)
                }
            }
            Section {
                if workspace.choices["refreshing"].bool() && workspace.choicesBusy {
                    Text("正在电脑上重新读取…")
                } else if let error = workspace.choicesError {
                    Text(error)
                } else if catalog["borrowed"].bool() {
                    Text("先用同一模型的列表；这个对话现在的选项点「刷新」核对。")
                } else if catalog["updated_at"].int64() > 0 {
                    Text("列表读于 \(Self.time(catalog["updated_at"].int64()))；选了以后应用到这个对话。")
                }
                Button {
                    workspace.loadChoices(fresh: true, model: current["model"].string())
                } label: {
                    Text("刷新电脑上的列表")
                    Text("会在电脑上打开 Claude 的模型菜单读一遍")
                }
                .disabled(workspace.choices["refreshing"].bool() && workspace.choicesBusy)
            }
        }
    }

    @ViewBuilder
    private func deepseek(current: JSONValue) -> some View {
        let workspace = model.workspace
        let catalog = workspace.choices["source_catalog"]
        if !catalog.isObject {
            Text(workspace.choicesError ?? "正在读取电脑上的模型…")
        } else {
            let groups = catalog["groups"].array
            let picks = groups.flatMap { group in group["models"].array.map { (provider: group["id"].string(), group: group["name"].string(), model: $0) } }
            let selected = picks.first { $0.model["id"].string() == current["model"].string() }
            ForEach(Array(groups.enumerated()), id: \.offset) { _, group in
                Section(groups.count > 1 ? group["name"].string() : "") {
                    ForEach(Array(group["models"].array.enumerated()), id: \.offset) { _, row in
                        let on = row["id"].string() == current["model"].string()
                        CheckRow(title: row["name"].string().isEmpty ? row["id"].string() : row["name"].string(), on: on) {
                            guard !on else { return }
                            // Keeps the current effort when the new model has it; otherwise the computer picks its default.
                            let effort = current["reasoningEffort"].string()
                            let has = row["reasoning"]["efforts"].array.contains { $0["id"].string() == effort }
                            choose(provider: group["id"].string(), model: row["id"].string(), effort: has ? effort : nil)
                        }
                    }
                }
            }
            if let selected {
                let efforts = selected.model["reasoning"]["efforts"].array
                if !efforts.isEmpty {
                    Section("推理强度") {
                        Picker("推理强度", selection: Binding(get: { current["reasoningEffort"].string() }, set: { effort in
                            choose(provider: selected.provider, model: selected.model["id"].string(), effort: effort)
                        })) {
                            ForEach(Array(efforts.enumerated()), id: \.offset) { _, step in
                                Text(step["name"].string().isEmpty ? step["id"].string() : step["name"].string()).tag(step["id"].string())
                            }
                        }
                        .pickerStyle(.palette)
                    }
                }
            }
        }
    }

    private func choose(provider: String, model id: String, effort: String?) {
        var settings: [String: JSONValue] = ["provider": .string(provider), "model": .string(id)]
        if let effort, !effort.isEmpty { settings["reasoningEffort"] = .string(effort) }
        model.workspace.action("deepseek/model", ["settings": .object(settings)])
    }

    /// "10月24日 11:59" (Android M月d日 HH:mm).
    static func time(_ milliseconds: Int64) -> String {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "zh_CN")
        formatter.dateFormat = "M月d日 HH:mm"
        return formatter.string(from: Date(timeIntervalSince1970: Double(milliseconds) / 1000))
    }
}

/// The mode chip's menu: Codex 普通执行 / 计划, Claude the desktop's modes, DeepSeek the permissions (some are
/// confirmed first, [confirm]).
struct ModeMenu: View {
    let model: AppModel
    let confirm: (JSONValue) -> Void

    var body: some View {
        let app = model.workspace.key?.app ?? model.app
        let raw = model.conversation.control.raw
        let current = raw["settings"]
        Group {
            switch app {
            case "codex":
                let saved = model.workspace.saved
                let chosen = saved["settings"].isObject ? saved["settings"] : current
                let mode = chosen["mode"].string().isEmpty ? "default" : chosen["mode"].string()
                ForEach([("default", "普通执行", nil), ("plan", "计划", "先出计划，你确认后再执行")] as [(String, String, String?)], id: \.0) { value, label, detail in
                    CheckRow(title: label, detail: detail, on: mode == value) {
                        guard mode != value else { return }
                        var next = chosen.object
                        next["mode"] = .string(value)
                        model.workspace.selectSettings(.object(next), expected: current)
                    }
                }
            case "claude":
                let options = raw["mode_options"].array
                if options.isEmpty { Text("电脑没有给出可选的模式") }
                ForEach(Array(options.enumerated()), id: \.offset) { _, option in
                    let name = option["name"].string()
                    let on = current["mode"].string() == name
                    CheckRow(title: option["label"].string().isEmpty ? name : option["label"].string(), on: on) {
                        if !on { model.workspace.claudeSetting(kind: "mode", name: name) }
                    }
                }
            default:
                let permissions = model.workspace.choices["permissions"]
                if !permissions.isObject {
                    Text(model.workspace.choicesError ?? "正在读取电脑上的权限…")
                } else {
                    ForEach(Array(permissions["options"].array.enumerated()), id: \.offset) { _, option in
                        let on = raw["permission"].string() == option["value"].string()
                        let detail = option["description"].string()
                        CheckRow(title: option["name"].string(), detail: detail.isEmpty ? nil : detail, on: on) {
                            guard !on else { return }
                            if option["confirm"].bool() {
                                confirm(option)
                            } else {
                                model.workspace.action("deepseek/permission", ["preset": .string(option["value"].string()), "confirmed": false])
                            }
                        }
                    }
                }
            }
        }
        .onAppear { if app == "deepseek" { model.workspace.loadChoices() } }
        .disabled(model.workspace.busy)
    }
}
