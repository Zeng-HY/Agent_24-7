import Foundation

/// Effort names as the web writes them (remote.html EFFORT; Android EffortNames).
public func effortName(_ value: String) -> String {
    ["none": "无", "minimal": "最低", "low": "低", "medium": "中", "high": "高", "xhigh": "极高", "max": "最高", "ultra": "Ultra"][value] ?? value
}

/// What the chips say, per source (spec 4.3; Android chipLabels): Codex model · effort and 普通执行 / 计划;
/// Claude as the web paints it (claude-ui.js): the desktop's label, else the name kept for the recorded model, then
/// the recorded effort, else the desktop's; its mode the desktop's label, else the recorded one. DeepSeek model ·
/// effort and its permission. [plan] gives the mode chip the selected look.
public func chipLabels(app: String, raw: JSONValue, saved: JSONValue) -> (model: String, mode: String, plan: Bool) {
    let settings = raw["settings"]
    switch app {
    case "claude":
        let name = [raw["model_label"].string(), raw["recorded_label"].string(), settings["model"].string()].first { !$0.isEmpty } ?? ""
        let recorded = settings["effort"].string()
        let effort = recorded.isEmpty ? raw["effort_label"].string() : effortName(recorded)
        let shown = raw["mode_label"].string()
        let plan = shown.isEmpty ? settings["mode"].string() == "plan" : shown.lowercased().hasPrefix("plan")
        let mode = plan ? "计划模式" : !shown.isEmpty ? shown
            : ["auto": "Auto", "default": "Manual", "acceptEdits": "Accept edits"][settings["mode"].string()] ?? "普通执行"
        return (name.isEmpty ? "模型" : "\(name) · \(effort.isEmpty ? "默认" : effort)", mode, plan)
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

/// The computer read the conversation and it is not the one open there (state `available` false).
func notOnComputer(_ raw: JSONValue) -> Bool {
    raw.has("available") && !raw["available"].bool()
}

/// The model chip says 电脑上打开 and opens the conversation there instead of its menu (web codex-ui.js and
/// claude-ui.js "away"): Codex not open on the computer; Claude not open there with nothing recorded to show, since
/// a pick from a recorded Claude conversation switches the computer to it by itself.
public func chipAway(app: String, raw: JSONValue) -> Bool {
    guard notOnComputer(raw) else { return false }
    switch app {
    case "codex": return true
    case "claude": return raw["settings"]["model"].string().isEmpty
    default: return false
    }
}

/// Why the next message cannot go now, in the computer's own words, for the composer's status line: otherwise the
/// send button is grey with no word on why (user 10-27). Claude's messages go all the same (the computer opens the
/// conversation itself, as on the web), so only an away chip says why there.
public func awayReason(app: String, raw: JSONValue) -> String? {
    guard notOnComputer(raw) else { return nil }
    if app == "claude" && !chipAway(app: app, raw: raw) { return nil }
    let reason = raw["reason"].string()
    if !reason.isEmpty { return reason }
    return app == "deepseek" ? nil : "电脑上没有打开这个对话；点「电脑上打开」后再发"
}

/// Whether a message can go while the computer shows another conversation: Claude's can (web sendConv; the computer
/// opens it, Windows 0.27.0-dev.19 and later), the others' cannot.
public func sendsWhileAway(_ app: String) -> Bool {
    app == "claude"
}
