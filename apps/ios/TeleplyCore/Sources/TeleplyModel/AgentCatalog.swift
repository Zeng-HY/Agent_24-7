import Foundation
import Synchronization

/// What the computer says about each assistant (GET /api/agents; docs/adding-an-agent.md §三) and the catalog the
/// app draws from. The three old assistants are described once, here; every other one comes from the computer, so a
/// new assistant never needs a new build of this app. Android: AgentInfo.kt and AgentCatalog.kt.

/// A legal assistant id, as the computer and the relay check it (`^[a-z][a-z0-9_-]{0,31}$`).
public func isValidAgentId(_ value: String) -> Bool {
    let bytes = Array(value.utf8)
    guard (1...32).contains(bytes.count), (0x61...0x7A).contains(bytes[0]) else { return false }
    return bytes.dropFirst().allSatisfy { byte in
        (0x61...0x7A).contains(byte) || (0x30...0x39).contains(byte) || byte == 0x5F || byte == 0x2D
    }
}

/// `#RRGGBB` or `#AARRGGBB` as a number, nil when it is neither (the computer's words are never trusted here).
public func agentColorValue(_ text: String) -> UInt32? {
    var digits = Substring(text.trimmingCharacters(in: .whitespaces))
    if digits.hasPrefix("#") { digits = digits.dropFirst() }
    guard digits.count == 6 || digits.count == 8, digits.allSatisfy(\.isHexDigit) else { return nil }
    return UInt32(digits, radix: 16)
}

/// One assistant's display name, in the phone's language (docs §三: zh, else en, else the id).
public struct AgentName: Sendable, Equatable {
    public var zh: String
    public var en: String

    public init(zh: String, en: String) {
        self.zh = zh
        self.en = en
    }

    /// Chinese when the phone is Chinese, English otherwise; the other one when this one is empty.
    public func localized(_ language: String = Labels.language) -> String {
        let preferZh = language.hasPrefix("zh")
        let first = preferZh ? zh : en
        let second = preferZh ? en : zh
        return first.isEmpty ? second : first
    }
}

/// The icon the computer describes (`{"kind": "builtin", "key": "generic"}` or `{"kind": "url", path, etag}`).
/// Remote pictures are not downloaded yet (as on Android): every new assistant draws the generic mark.
public struct AgentIcon: Sendable, Equatable {
    public var kind: String
    public var key: String
    public var path: String
    public var etag: String

    public init(kind: String = "builtin", key: String = "generic", path: String = "", etag: String = "") {
        self.kind = kind
        self.key = key
        self.path = path
        self.etag = etag
    }
}

/// What one assistant can do (docs §三: 能力位). The manifest's own value is the default; what changes during a turn
/// comes from the control state's `capabilities_now` (Android AgentCapabilities).
public struct AgentCapabilities: Sendable, Equatable {
    public static let defaultStatuses = ["running", "waiting", "idle", "unknown"]

    public var list: Bool
    public var read: Bool
    public var search: Bool
    public var open: Bool
    public var stop: Bool
    public var queue: Bool
    public var steer: Bool
    public var approve: Bool
    public var answer: Bool
    public var new: Bool
    public var newProjectless: Bool
    public var newPermission: Bool
    public var archive: Bool
    public var restore: Bool
    public var delete: Bool
    public var usage: Bool
    public var waiting: Bool
    public var attachments: Bool
    public var slashCommands: Bool
    /// nil when the manifest does not say (an older computer): the caller keeps its own old rule.
    public var skills: Bool?
    public var settings: [String]
    public var sendModes: [String]
    public var statuses: [String]

    public init(list: Bool = false, read: Bool = false, search: Bool = false, open: Bool = false, stop: Bool = false,
                queue: Bool = false, steer: Bool = false, approve: Bool = false, answer: Bool = false, new: Bool = false,
                newProjectless: Bool = false, newPermission: Bool = false, archive: Bool = false, restore: Bool = false,
                delete: Bool = false, usage: Bool = false, waiting: Bool = false, attachments: Bool = false,
                slashCommands: Bool = false, skills: Bool? = nil, settings: [String] = [], sendModes: [String] = [],
                statuses: [String] = ["running", "waiting", "idle", "unknown"]) {
        self.list = list
        self.read = read
        self.search = search
        self.open = open
        self.stop = stop
        self.queue = queue
        self.steer = steer
        self.approve = approve
        self.answer = answer
        self.new = new
        self.newProjectless = newProjectless
        self.newPermission = newPermission
        self.archive = archive
        self.restore = restore
        self.delete = delete
        self.usage = usage
        self.waiting = waiting
        self.attachments = attachments
        self.slashCommands = slashCommands
        self.skills = skills
        self.settings = settings
        self.sendModes = sendModes
        self.statuses = statuses
    }

    /// The capabilities that apply now: the manifest's, narrowed by a control state's `capabilities_now` (handoff
    /// 3.4; Android AgentCaps.capsNow). A flag can only go from true to false; a list keeps the manifest's order and
    /// drops what the computer no longer offers; a key `capabilities_now` does not mention keeps the manifest's value.
    public func narrowed(by now: JSONValue?) -> AgentCapabilities {
        guard let now, now.isObject else { return self }
        func flag(_ key: String, _ current: Bool) -> Bool { now.has(key) ? current && now[key].bool() : current }
        func words(_ key: String, _ current: [String]) -> [String] {
            guard now.has(key) else { return current }
            let offered = now[key].array.map { $0.string() }
            return current.filter { offered.contains($0) }
        }
        var next = self
        next.list = flag("list", list)
        next.read = flag("read", read)
        next.search = flag("search", search)
        next.open = flag("open", open)
        next.stop = flag("stop", stop)
        next.queue = flag("queue", queue)
        next.steer = flag("steer", steer)
        next.approve = flag("approve", approve)
        next.answer = flag("answer", answer)
        next.new = flag("new", new)
        next.newProjectless = flag("new_projectless", newProjectless)
        next.newPermission = flag("new_permission", newPermission)
        next.archive = flag("archive", archive)
        next.restore = flag("restore", restore)
        next.delete = flag("delete", delete)
        next.usage = flag("usage", usage)
        next.waiting = flag("waiting", waiting)
        next.attachments = flag("attachments", attachments)
        next.slashCommands = flag("slash_commands", slashCommands)
        if now.has("skills") {
            next.skills = skills == false ? false : now["skills"].bool()
        }
        next.settings = words("settings", settings)
        next.sendModes = words("send_modes", sendModes)
        next.statuses = words("statuses", statuses)
        return next
    }

    /// One capability by its name as the manifest and `capability_notes` write it (docs §三); nil for a name this
    /// app does not know.
    public func flag(_ name: String) -> Bool? {
        switch name {
        case "list": return list
        case "read": return read
        case "search": return search
        case "open": return open
        case "stop": return stop
        case "queue": return queue
        case "steer": return steer
        case "approve": return approve
        case "answer": return answer
        case "new": return new
        case "new_projectless": return newProjectless
        case "new_permission": return newPermission
        case "archive": return archive
        case "restore": return restore
        case "delete": return delete
        case "usage": return usage
        case "waiting": return waiting
        case "attachments": return attachments
        case "slash_commands": return slashCommands
        case "skills": return skills
        default: return nil
        }
    }
}

/// Whether the composer's `$` list (引用技能) can show: a manifest that says `skills` decides; one that does not (an
/// older computer) keeps the old rule — commands and not DeepSeek (Android AgentCaps.skillsAvailable).
public func skillsAvailable(_ caps: AgentCapabilities, layout: String) -> Bool {
    caps.skills ?? (caps.slashCommands && layout != "deepseek.v1")
}

/// How long the computer may take and how much it takes at once (docs §三: 运行参数).
public struct AgentParams: Sendable, Equatable {
    public var stateTimeoutS: Int
    public var sendTimeoutS: Int
    public var openTimeoutS: Int
    public var newTimeoutS: Int
    public var refreshMs: Int
    public var maxImages: Int
    public var maxImageBytes: Int
    public var maxText: Int

    public init(stateTimeoutS: Int = 40, sendTimeoutS: Int = 60, openTimeoutS: Int = 45, newTimeoutS: Int = 60,
                refreshMs: Int = 2_500, maxImages: Int = 5, maxImageBytes: Int = 50 * 1024 * 1024, maxText: Int = 20_000) {
        self.stateTimeoutS = stateTimeoutS
        self.sendTimeoutS = sendTimeoutS
        self.openTimeoutS = openTimeoutS
        self.newTimeoutS = newTimeoutS
        self.refreshMs = refreshMs
        self.maxImages = maxImages
        self.maxImageBytes = maxImageBytes
        self.maxText = maxText
    }
}

/// The panel and words for conversations of one assistant (docs §三: `ui`).
public struct AgentUi: Sendable, Equatable {
    public var cardLayout: String
    public var waitingText: String

    public init(cardLayout: String = "generic.v1", waitingText: String = "等待你处理") {
        self.cardLayout = cardLayout
        self.waitingText = waitingText
    }
}

/// One assistant as the computer describes it. Only [id] is required: every field falls back to a safe default, so a
/// manifest missing one thing is still usable (a bad one is dropped as a whole by `parseAgentInfo`).
public struct AgentInfo: Sendable, Equatable, Identifiable {
    /// The neutral grey of an assistant without a colour, light and dark (Android `#6B7280` / `#9CA3AF`).
    public static let genericColor = "#6B7280"
    public static let genericDarkColor = "#9CA3AF"

    public var id: String
    public var name: AgentName
    public var order: Int
    public var color: String
    public var colorDark: String
    public var badgeColor: String
    public var icon: AgentIcon
    public var legacy: Bool
    public var minProtocol: Int
    public var caps: AgentCapabilities
    public var params: AgentParams
    public var ui: AgentUi

    public init(id: String, name: AgentName? = nil, order: Int = 1_000, color: String = "#6B7280",
                colorDark: String = "#9CA3AF", badgeColor: String = "", icon: AgentIcon = AgentIcon(),
                legacy: Bool = false, minProtocol: Int = 2, caps: AgentCapabilities = AgentCapabilities(),
                params: AgentParams = AgentParams(), ui: AgentUi = AgentUi()) {
        self.id = id
        self.name = name ?? AgentName(zh: id, en: id)
        self.order = order
        self.color = color
        self.colorDark = colorDark
        self.badgeColor = badgeColor.isEmpty ? color : badgeColor
        self.icon = icon
        self.legacy = legacy
        self.minProtocol = minProtocol
        self.caps = caps
        self.params = params
        self.ui = ui
    }

    /// The name in the phone's language; the id when the computer gave no name at all.
    public func displayName(_ language: String = Labels.language) -> String {
        let text = name.localized(language)
        return text.isEmpty ? id : text
    }

    /// A safe read-only assistant for an id the catalog does not know: never crash, never pretend to be one of the
    /// three (docs §八: 未知助手用通用样式、只能读).
    public static func generic(_ id: String) -> AgentInfo {
        AgentInfo(id: id, order: Int.max, caps: AgentCapabilities(list: true, read: true))
    }
}

/// One assistant out of the computer's `{"schema":1,"protocol":2,"agents":[...]}`. nil for an entry without a legal
/// id: the caller drops that entry only, never the whole answer (docs §三, 3.2).
public func parseAgentInfo(_ json: JSONValue) -> AgentInfo? {
    let id = json["id"].string().trimmingCharacters(in: .whitespaces)
    guard isValidAgentId(id) else { return nil }
    let nameObject = json["name"]
    let plainName = json["name"].string()
    // A name missing in one language stays empty there, so the other one shows instead (docs: zh, else en, else id).
    let zh = nameObject["zh"].string().isEmpty ? plainName : nameObject["zh"].string()
    let en = nameObject["en"].string().isEmpty ? zh : nameObject["en"].string()
    let color = json["color"].string().isEmpty ? AgentInfo.genericColor : json["color"].string()
    let colorDark = json["color_dark"].string().isEmpty ? color : json["color_dark"].string()
    let iconObject = json["icon"]
    let icon = iconObject.isObject
        ? AgentIcon(kind: iconObject["kind"].string().isEmpty ? "builtin" : iconObject["kind"].string(),
                    key: iconObject["key"].string().isEmpty ? "generic" : iconObject["key"].string(),
                    path: iconObject["path"].string(), etag: iconObject["etag"].string())
        : AgentIcon()

    let caps = json["capabilities"].isObject ? json["capabilities"] : [:]
    func flag(_ key: String, _ fallback: Bool) -> Bool {
        caps.has(key) ? caps[key].bool() : fallback
    }
    func words(_ key: String) -> [String] { caps[key].array.map { $0.string() }.filter { !$0.isEmpty } }
    let statuses = words("statuses")

    let params = json["params"].isObject ? json["params"] : [:]
    func seconds(_ key: String, _ fallback: Int) -> Int {
        max(1, params.has(key) ? params[key].int(or: fallback) : fallback)
    }
    func amount(_ key: String, _ fallback: Int) -> Int {
        max(0, params.has(key) ? params[key].int(or: fallback) : fallback)
    }

    let ui = json["ui"].isObject ? json["ui"] : [:]
    return AgentInfo(
        id: id,
        name: AgentName(zh: zh, en: en),
        order: json.has("order") ? json["order"].int(or: 1_000) : 1_000,
        color: color,
        colorDark: colorDark,
        badgeColor: color,
        icon: icon,
        legacy: json.has("legacy") && json["legacy"].bool(),
        minProtocol: json.has("min_protocol") ? json["min_protocol"].int(or: 2) : 2,
        caps: AgentCapabilities(
            list: flag("list", true),
            read: flag("read", true),
            search: flag("search", false),
            open: flag("open", false),
            stop: flag("stop", false),
            queue: flag("queue", false),
            steer: flag("steer", false),
            approve: flag("approve", false),
            answer: flag("answer", false),
            new: flag("new", false),
            newProjectless: flag("new_projectless", false),
            newPermission: flag("new_permission", false),
            archive: flag("archive", false),
            restore: flag("restore", false),
            delete: flag("delete", false),
            usage: flag("usage", false),
            waiting: flag("waiting", false),
            attachments: flag("attachments", false),
            slashCommands: flag("slash_commands", false),
            skills: caps.has("skills") ? caps["skills"].bool() : nil,
            settings: words("settings"),
            sendModes: words("send_modes"),
            statuses: statuses.isEmpty ? AgentCapabilities.defaultStatuses : statuses),
        params: AgentParams(
            stateTimeoutS: seconds("state_timeout_s", 40),
            sendTimeoutS: seconds("send_timeout_s", 60),
            openTimeoutS: seconds("open_timeout_s", 45),
            newTimeoutS: seconds("new_timeout_s", 60),
            refreshMs: max(250, params.has("refresh_ms") ? params["refresh_ms"].int(or: 2_500) : 2_500),
            maxImages: amount("max_images", 5),
            maxImageBytes: amount("max_image_bytes", 50 * 1024 * 1024),
            maxText: seconds("max_text", 20_000)),
        ui: AgentUi(cardLayout: ui["card_layout"].string().isEmpty ? "generic.v1" : ui["card_layout"].string(),
                    waitingText: ui["waiting_text"].string().isEmpty ? "等待你处理" : ui["waiting_text"].string()))
}

/// Every valid entry of an `agents` answer, sorted by `order` then id. A broken entry is dropped alone.
public func parseAgentsResponse(_ json: JSONValue) -> [AgentInfo] {
    var seen = Set<String>()
    var agents: [AgentInfo] = []
    for item in json["agents"].array {
        guard let info = parseAgentInfo(item), seen.insert(info.id).inserted else { continue }
        agents.append(info)
    }
    return agents.sorted { ($0.order, $0.id) < ($1.order, $1.id) }
}

/// The assistants one computer offers, in the order the web and the sidebar show them. The three built-in ones are
/// always here (they look exactly as before), so nothing has to special-case them.
public struct AgentCatalogSnapshot: Sendable, Equatable {
    /// The catalog in use, for the parts that draw an assistant without the model at hand (Labels, Palette, Marks).
    /// The app sets it whenever its computer's catalog changes; it stays the three built-ins until then.
    nonisolated(unsafe) public static var current = AgentCatalogSnapshot.builtin

    public private(set) var agents: [AgentInfo]
    /// Whether this came from the computer's `/api/agents` (false: the built-in three).
    public private(set) var fromServer: Bool
    /// The computer's version when this was fetched, for noticing an upgrade (AgentCatalog.updateVersion).
    public var version: String
    private let byId: [String: AgentInfo]

    public init(agents: [AgentInfo], fromServer: Bool = false, version: String = "") {
        self.agents = agents
        self.fromServer = fromServer
        self.version = version
        self.byId = Dictionary(agents.map { ($0.id, $0) }, uniquingKeysWith: { first, _ in first })
    }

    /// Assistant ids in catalog order.
    public var order: [String] { agents.map(\.id) }

    public func info(_ id: String) -> AgentInfo { byId[id] ?? .generic(id) }

    public func contains(_ id: String) -> Bool { byId[id] != nil }

    /// The name to show; the id for an assistant the catalog does not know (docs §八).
    public func name(_ id: String, language: String = Labels.language) -> String {
        guard let entry = byId[id] else { return id }
        let text = entry.displayName(language)
        return text.isEmpty ? id : text
    }

    /// The three old assistants keep their old routes and cards (`legacy`); everything else takes the unified ones.
    public func isLegacy(_ id: String) -> Bool { byId[id]?.legacy ?? false }

    public func caps(_ id: String) -> AgentCapabilities { info(id).caps }

    public func can(_ id: String, _ check: (AgentCapabilities) -> Bool) -> Bool { check(caps(id)) }

    /// #RRGGBB for the assistant's mark in light or dark mode; the neutral grey when the computer's value is not one.
    public func color(_ id: String, dark: Bool = false) -> String {
        let entry = info(id)
        let raw = dark ? entry.colorDark : entry.color
        guard agentColorValue(raw) != nil else { return dark ? Self.neutralDark : Self.neutralLight }
        return raw
    }

    /// #RRGGBB of the list badge; the same neutral grey when there is none.
    public func badgeColor(_ id: String) -> String {
        let entry = info(id)
        let raw = entry.badgeColor.isEmpty ? entry.color : entry.badgeColor
        guard agentColorValue(raw) != nil else { return Self.neutralLight }
        return raw
    }

    public static let neutralLight = AgentInfo.genericColor
    public static let neutralDark = AgentInfo.genericDarkColor

    // MARK: The built-in three

    static let builtinAgents: [AgentInfo] = [builtinCodex, builtinClaude, builtinDeepSeek]
    private static let builtinById = Dictionary(builtinAgents.map { ($0.id, $0) }, uniquingKeysWith: { first, _ in first })

    /// The three old assistants, as the app has always drawn them. Only their order and capabilities are taken from
    /// the computer's manifest; name, colours, mark, `legacy` and `min_protocol` stay the app's own (docs 3.2), so
    /// their routes and cards never change whatever the computer says.
    static let builtinCodex = AgentInfo(
        id: "codex", name: AgentName(zh: "Codex", en: "Codex"), order: 10, color: "#1E222A", colorDark: "#EEEEEE",
        badgeColor: "#111111", icon: AgentIcon(kind: "builtin", key: "codex"), legacy: true, minProtocol: 1,
        caps: AgentCapabilities(list: true, read: true, search: true, open: true, stop: true, queue: true, steer: true,
                                approve: true, answer: true, new: true, newProjectless: true, archive: true, restore: true,
                                delete: true, usage: true, waiting: true, attachments: true, slashCommands: true,
                                settings: ["model", "effort"], sendModes: ["send", "steer", "queue"]),
        ui: AgentUi(cardLayout: "codex.v1", waitingText: "等你处理"))

    static let builtinClaude = AgentInfo(
        id: "claude", name: AgentName(zh: "Claude", en: "Claude"), order: 20, color: "#D97757", colorDark: "#D97757",
        icon: AgentIcon(kind: "builtin", key: "claude"), legacy: true, minProtocol: 1,
        caps: AgentCapabilities(list: true, read: true, search: true, open: true, stop: true, steer: true, approve: true,
                                answer: true, new: true, newProjectless: true, archive: true, restore: true, usage: true,
                                waiting: true, attachments: true, slashCommands: true,
                                settings: ["model", "effort", "permission", "mode"], sendModes: ["send", "steer"]),
        params: AgentParams(stateTimeoutS: 20, newTimeoutS: 70, refreshMs: 5_000),
        ui: AgentUi(cardLayout: "claude.v1", waitingText: "等待你处理"))

    static let builtinDeepSeek = AgentInfo(
        id: "deepseek", name: AgentName(zh: "DeepSeek", en: "DeepSeek"), order: 30, color: "#4D6BFE", colorDark: "#4D6BFE",
        icon: AgentIcon(kind: "builtin", key: "deepseek"), legacy: true, minProtocol: 1,
        caps: AgentCapabilities(list: true, read: true, search: true, open: true, stop: true, queue: true, steer: true,
                                approve: true, answer: true, new: true, newPermission: true, archive: true, restore: true,
                                waiting: true, attachments: true, slashCommands: true,
                                settings: ["model", "permission"], sendModes: ["send", "steer", "queue"]),
        ui: AgentUi(cardLayout: "deepseek.v1", waitingText: "等待你处理"))

    /// The three built-ins alone: an older computer (404 on /api/agents), or the app before a computer is entered.
    public static let builtin = AgentCatalogSnapshot(agents: builtinAgents)

    /// The computer's list, with the three built-ins' name, colours, mark and old-route flags taken from the app
    /// itself. An entry the computer did not mention is added back for the three, so they are always there.
    public static func fromServer(_ agents: [AgentInfo]) -> AgentCatalogSnapshot {
        var seen = Set<String>()
        var normalized: [AgentInfo] = []
        for agent in agents where seen.insert(agent.id).inserted {
            var info = agent
            if let builtin = builtinById[agent.id] {
                info.name = builtin.name
                info.color = builtin.color
                info.colorDark = builtin.colorDark
                info.badgeColor = builtin.badgeColor
                info.icon = builtin.icon
                info.legacy = builtin.legacy
                info.minProtocol = builtin.minProtocol
            }
            normalized.append(info)
        }
        for builtin in builtinAgents where !seen.contains(builtin.id) { normalized.append(builtin) }
        normalized.sort { ($0.order, $0.id) < ($1.order, $1.id) }
        return AgentCatalogSnapshot(agents: normalized, fromServer: true)
    }
}

/// One catalog per computer, kept in memory (Android AgentCatalog): asked again when the app starts, when another
/// computer is entered, on 重试, and when the computer's version changed. A 404 (an older computer) keeps the three
/// built-ins; any other failure leaves whatever this phone already had.
public final class AgentCatalog: Sendable {
    private struct Entry: Sendable {
        var snapshot: AgentCatalogSnapshot
        var version: String
    }

    private let entries = Mutex<[String: Entry]>([:])

    public init() {}

    /// The catalog known for [device]; the built-ins when nothing was fetched yet.
    public func snapshot(for device: String) -> AgentCatalogSnapshot {
        entries.withLock { $0[device]?.snapshot ?? AgentCatalogSnapshot.builtin }
    }

    /// What this phone already has for [device], nil when it has never asked.
    public func snapshotIfAny(for device: String) -> AgentCatalogSnapshot? {
        entries.withLock { $0[device]?.snapshot }
    }

    public func version(for device: String) -> String {
        entries.withLock { $0[device]?.version ?? "" }
    }

    /// True until this phone has asked [device] once (whatever the answer was).
    public func needsFetch(_ device: String) -> Bool {
        entries.withLock { $0[device] == nil }
    }

    /// Keeps the answer: [agents] nil is a computer without `/api/agents` (404), which keeps the three built-ins.
    @discardableResult
    public func store(_ agents: [AgentInfo]?, for device: String, version: String = "") -> AgentCatalogSnapshot {
        entries.withLock { entries in
            let known = version.isEmpty ? (entries[device]?.version ?? "") : version
            var snapshot = agents.map { AgentCatalogSnapshot.fromServer($0) } ?? AgentCatalogSnapshot.builtin
            snapshot.version = known
            entries[device] = Entry(snapshot: snapshot, version: known)
            return snapshot
        }
    }

    /// Records the computer's version; true when it changed, so its manifest list must be fetched again. A computer
    /// that never says one changes nothing.
    @discardableResult
    public func updateVersion(_ version: String, for device: String) -> Bool {
        guard !version.isEmpty else { return false }
        return entries.withLock { entries in
            guard var entry = entries[device], entry.version != version else { return false }
            entry.version = version
            entry.snapshot.version = version
            entries[device] = entry
            return true
        }
    }

    /// Forgets one computer's catalog (a sign-out, another account), or every computer's.
    public func forget(_ device: String? = nil) {
        entries.withLock { entries in
            if let device { entries[device] = nil } else { entries.removeAll() }
        }
    }
}
