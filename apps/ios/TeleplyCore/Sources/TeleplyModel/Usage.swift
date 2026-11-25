import Foundation

/// 用量 (11-17): what the computer said about Codex's and Claude's limits (usage_limits.py) and the words the phone
/// shows for them (Android Usage.kt). Plain values and pure functions: the tests need no screen, no window and no
/// network, and every time is the caller's.
public struct UsageWindow: Sendable, Equatable {
    /// "5h", "weekly" or "other" (Codex reports the length in minutes; Claude only says which limit it shows).
    public var kind: String
    /// What the phone shows: 5 小时, 每周, or another length.
    public var name: String
    public var usedPercent: Int
    /// Seconds since 1970; nil when the computer only named a time (Claude).
    public var resetsAt: Int64?
    /// Claude's own words for when it resets, already as hours and minutes ("12:20") when its button said so.
    public var resetsText: String

    public init(kind: String = "", name: String = "", usedPercent: Int = 0, resetsAt: Int64? = nil, resetsText: String = "") {
        self.kind = kind
        self.name = name
        self.usedPercent = usedPercent
        self.resetsAt = resetsAt
        self.resetsText = resetsText
    }
}

/// One of Codex's reset credits; [expiresAt] nil: it does not expire.
public struct ResetCredit: Sendable, Equatable {
    public var id: String
    public var title: String
    public var expiresAt: Int64?

    public init(id: String = "", title: String = "", expiresAt: Int64? = nil) {
        self.id = id
        self.title = title
        self.expiresAt = expiresAt
    }
}

/// Codex's usage. [source] is "live" (its app-server, just now) or "records" (as of its last answer); [resets] false
/// means the computer did not know the reset credits, which the records never carry. [credits] nil: only the count.
public struct CodexUsage: Sendable, Equatable {
    public var available: Bool
    public var reason: String
    public var source: String
    public var asOf: Int64
    public var plan: String
    public var windows: [UsageWindow]
    public var reached: String?
    public var resets: Bool
    public var resetsAvailable: Int?
    public var credits: [ResetCredit]?
    public var liveError: String

    public init(available: Bool = false, reason: String = "", source: String = "", asOf: Int64 = 0, plan: String = "",
                windows: [UsageWindow] = [], reached: String? = nil, resets: Bool = false, resetsAvailable: Int? = nil,
                credits: [ResetCredit]? = nil, liveError: String = "") {
        self.available = available
        self.reason = reason
        self.source = source
        self.asOf = asOf
        self.plan = plan
        self.windows = windows
        self.reached = reached
        self.resets = resets
        self.resetsAvailable = resetsAvailable
        self.credits = credits
        self.liveError = liveError
    }
}

/// Claude's usage: one limit, the one its button shows; [text] is that button's words as Claude wrote them.
public struct ClaudeUsage: Sendable, Equatable {
    public var available: Bool
    public var reason: String
    public var text: String
    public var windows: [UsageWindow]
    public var minimized: Bool

    public init(available: Bool = false, reason: String = "", text: String = "", windows: [UsageWindow] = [], minimized: Bool = false) {
        self.available = available
        self.reason = reason
        self.text = text
        self.windows = windows
        self.minimized = minimized
    }
}

/// Usage of any assistant reported under protocol 2 `agents.<id>` (§3.3): [windows] are the limits it gave, [text] is
/// its own words when it has no windows to read.
public struct AgentUsage: Sendable, Equatable {
    public var id: String
    public var available: Bool
    public var reason: String
    public var source: String
    public var asOf: Int64
    public var text: String
    public var windows: [UsageWindow]

    public init(id: String, available: Bool = false, reason: String = "", source: String = "", asOf: Int64 = 0,
                text: String = "", windows: [UsageWindow] = []) {
        self.id = id
        self.available = available
        self.reason = reason
        self.source = source
        self.asOf = asOf
        self.text = text
        self.windows = windows
    }
}

/// GET /api/usage whole; [now] is the computer's clock, so "a minute ago" does not depend on the phone's.
public struct UsageReport: Sendable, Equatable {
    public var codex: CodexUsage
    public var claude: ClaudeUsage
    public var now: Int64
    /// Protocol 2 `agents.<id>`, by id, in whatever order the computer sent them; the page orders them by its catalog.
    public var agents: [String: AgentUsage]

    public init(codex: CodexUsage = CodexUsage(), claude: ClaudeUsage = ClaudeUsage(), now: Int64 = 0,
                agents: [String: AgentUsage] = [:]) {
        self.codex = codex
        self.claude = claude
        self.now = now
        self.agents = agents
    }
}

// MARK: - Reading what the computer sent

public extension UsageReport {
    /// The answer of GET /api/usage (Android parseUsage): a missing part reads as an empty one. An `agents` key whose id
    /// is not a legal assistant id is dropped, as Android does.
    static func parse(_ json: JSONValue) -> UsageReport {
        var agents: [String: AgentUsage] = [:]
        for (id, value) in json["agents"].object where isValidAgentId(id) && value.isObject {
            agents[id] = AgentUsage(id: id, json: value)
        }
        return UsageReport(codex: CodexUsage(json["codex"]), claude: ClaudeUsage(json["claude"]),
                           now: json["now"].int64(), agents: agents)
    }
}

public extension AgentUsage {
    init(id: String, json: JSONValue) {
        self.init(id: id, available: json["available"].bool(), reason: json["reason"].string(),
                  source: json["source"].string(), asOf: json["as_of"].int64(), text: json["text"].string(),
                  windows: usageWindows(json["windows"]))
    }
}

public extension CodexUsage {
    init(_ json: JSONValue) {
        let resets = json["resets"]
        let credits: [ResetCredit]? = resets.isNull ? nil : (resets["items"].isNull ? nil : usageCredits(resets["items"]))
        self.init(
            available: json["available"].bool(),
            reason: json["reason"].string(),
            source: json["source"].string(),
            asOf: json["as_of"].int64(),
            plan: json["plan"].string(),
            windows: usageWindows(json["windows"]),
            reached: json["reached"].isNull ? nil : json["reached"].string(),
            resets: !resets.isNull,
            resetsAvailable: resets.has("available") ? resets["available"].int() : nil,
            credits: credits,
            liveError: json["live_error"].string()
        )
    }
}

public extension ClaudeUsage {
    init(_ json: JSONValue) {
        self.init(
            available: json["available"].bool(),
            reason: json["reason"].string(),
            text: json["text"].string(),
            windows: usageWindows(json["windows"]),
            minimized: json["minimized"].bool()
        )
    }
}

private func usageWindows(_ value: JSONValue) -> [UsageWindow] {
    value.array.compactMap { item in
        guard item.isObject else { return nil }
        let name = item["name"].string()
        return UsageWindow(
            kind: item["kind"].string(),
            name: name.isEmpty ? item["label"].string() : name,
            usedPercent: min(100, max(0, item["used_percent"].int())),
            resetsAt: item.has("resets_at") ? item["resets_at"].int64() : nil,
            resetsText: item["resets_text"].string()
        )
    }
}

private func usageCredits(_ value: JSONValue) -> [ResetCredit] {
    value.array.compactMap { item in
        guard item.isObject else { return nil }
        return ResetCredit(
            id: item["id"].string(),
            title: item["title"].string(),
            expiresAt: item.has("expires_at") ? item["expires_at"].int64() : nil
        )
    }
}

// MARK: - A new assistant's section

/// The new assistants to show, in the catalog's order: the ones that are not the old three and whose manifest offers
/// `usage` (§3.3). The three keep their own sections above.
public func agentUsageOrder(_ report: UsageReport, catalog: AgentCatalogSnapshot) -> [String] {
    catalog.order.filter { id in
        !catalog.isLegacy(id) && catalog.can(id) { caps in caps.usage }
    }
}

/// What a new assistant's section says when it cannot be read: the computer's own reason, else a sentence with its name.
public func agentUsageLine(_ agent: AgentUsage, name: String) -> String {
    if agent.available { return "" }
    return agent.reason.isEmpty ? "读不到 \(name) 的用量" : agent.reason
}

/// One window of a new assistant: the reset line from `resets_at` when it has one, else the computer's `resets_text`.
public func agentWindowLine(_ window: UsageWindow, source: String, nowMs: Int64, zone: TimeZone) -> String {
    if window.resetsAt != nil { return resetLine(window, source: source, nowMs: nowMs, zone: zone) }
    return window.resetsText.isEmpty ? "" : window.resetsText + " 重置"
}

// MARK: - When it resets

/// 今天 20:54 重置（还有 1 天 10 小时）; a reset already passed says so instead, and the records add when they catch up.
public func resetLine(_ window: UsageWindow, source: String, nowMs: Int64, zone: TimeZone) -> String {
    guard let resetsAt = window.resetsAt else { return "" }
    let left = resetsAt * 1000 - nowMs
    if left <= 0 { return "已过重置时间" + (source == "records" ? "，等电脑上 Codex 下一次回话就会更新" : "") }
    return dayLabel(resetsAt * 1000, nowMs, zone) + " " + clockText(resetsAt * 1000, zone) + " 重置" + remainingText(left)
}

/// {M月d日} 到期, or 不会过期.
public func resetExpiryLine(_ credit: ResetCredit, zone: TimeZone) -> String {
    guard let expiresAt = credit.expiresAt else { return "不会过期" }
    let parts = dateParts(expiresAt * 1000, zone)
    return "\(parts.month ?? 0)月\(parts.day ?? 0)日 到期"
}

/// 刚从 Codex 读到 / {n} 分钟前从 Codex 读到, or where the records stood and what they cannot know.
public func sourceLine(source: String, asOf: Int64, nowMs: Int64, zone: TimeZone) -> String {
    switch source {
    case "live":
        let age = nowMs - asOf
        return age < 60_000 ? "刚从 Codex 读到" : "\(age / 60_000) 分钟前从 Codex 读到"
    case "records":
        return "来自电脑上 Codex 最近一次回话（\(clockText(asOf, zone))）。之后在别处用掉的，这里还没算上。"
    default:
        return ""
    }
}

/// 确认框's words, one sentence a line: what it does, which credit (when one was tapped), and a warning while the
/// limits are nowhere near spent.
public func confirmText(_ credit: ResetCredit?, windows: [UsageWindow], zone: TimeZone) -> String {
    var lines = ["会马上恢复 Codex 的用量限额。用掉就没了，不能撤回。"]
    if let credit {
        lines.append("这次用：" + (credit.title.isEmpty ? "用量重置" : credit.title) + "，" + resetExpiryLine(credit, zone: zone))
    }
    if let tightest = windows.max(by: { $0.usedPercent < $1.usedPercent }), windows.allSatisfy({ $0.usedPercent < 90 }) {
        lines.append("现在\(tightest.name)还剩 \(100 - tightest.usedPercent)%，还没用完，现在用可能浪费。")
    }
    return lines.joined(separator: "\n")
}

private func calendar(_ zone: TimeZone) -> Calendar {
    var calendar = Calendar(identifier: .gregorian)
    calendar.timeZone = zone
    return calendar
}

private func dateParts(_ millis: Int64, _ zone: TimeZone) -> DateComponents {
    calendar(zone).dateComponents([.year, .month, .day, .hour, .minute], from: Date(timeIntervalSince1970: Double(millis) / 1000))
}

private func clockText(_ millis: Int64, _ zone: TimeZone) -> String {
    let parts = dateParts(millis, zone)
    return String(format: "%02d:%02d", parts.hour ?? 0, parts.minute ?? 0)
}

private func dayLabel(_ millis: Int64, _ nowMs: Int64, _ zone: TimeZone) -> String {
    let day = calendar(zone).startOfDay(for: Date(timeIntervalSince1970: Double(millis) / 1000))
    let today = calendar(zone).startOfDay(for: Date(timeIntervalSince1970: Double(nowMs) / 1000))
    switch calendar(zone).dateComponents([.day], from: today, to: day).day ?? 0 {
    case 0: return "今天"
    case 1: return "明天"
    default:
        let parts = dateParts(millis, zone)
        return "\(parts.month ?? 0)月\(parts.day ?? 0)日"
    }
}

private func remainingText(_ left: Int64) -> String {
    let minutes = left / 60_000
    if minutes < 1 { return "（马上）" }
    let days = minutes / 1440, hours = (minutes % 1440) / 60, rest = minutes % 60
    if days > 0 { return "（还有 \(days) 天" + (hours > 0 ? " \(hours) 小时" : "") + "）" }
    if hours > 0 { return "（还有 \(hours) 小时" + (rest > 0 ? " \(rest) 分" : "") + "）" }
    return "（还有 \(rest) 分钟）"
}

// MARK: - The request id that keeps a retry from using a second credit

/// One reset attempt's request id: the same one until the computer gives a final answer, so a retry after an answer
/// that never arrived reuses the idempotency key instead of using a second credit (Android ResetAttempt).
public final class ResetAttempt {
    private var number: String?

    public init() {}

    public func id() -> String {
        if let number { return number }
        let made = UUID().uuidString
        number = made
        return made
    }

    public func done() { number = nil }

    /// Whether the same request id must be kept. Only the codes that say for certain nothing was used lose it; every
    /// other failure (another code, no code, not a ServiceFailure at all: a 500, a 502/504 from the relay, a broken
    /// connection) keeps it, because the first try may have gone through and a new id could use a second credit.
    public func keepsId(_ error: any Error) -> Bool {
        guard let failure = error as? ServiceFailure else { return true }
        return !Self.explainedNotUsed.contains(failure.code)
    }

    /// The computer's own answers that mean it did not use the credit (Android ResetAttempt).
    private static let explainedNotUsed: Set<String> = ["not_confirmed", "bad_request", "codex_unreachable", "codex_refused", "no_codex"]
}
