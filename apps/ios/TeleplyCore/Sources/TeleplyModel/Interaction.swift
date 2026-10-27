import Foundation

/// One question or approval waiting in a conversation, for the question bar above the input card (Android
/// PendingCard): [kind] is question, choice, actions or approval; [progress] Claude's "1/3"; [count] how many
/// DeepSeek items wait.
public struct PendingCard: Equatable, Sendable {
    public var kind: String
    public var summary: String
    public var progress: String
    public var count: Int

    public init(kind: String, summary: String, progress: String = "", count: Int = 1) {
        self.kind = kind
        self.summary = summary
        self.progress = progress
        self.count = count
    }
}

/// What waits for an answer in a source's state (Android pendingCards): Codex's pending question cards; Claude's
/// desktop prompt, or else its plan options; DeepSeek's approvals first, then its questions.
public func pendingCards(app: String, raw: JSONValue) -> [PendingCard] {
    switch app {
    case "claude":
        let prompt = raw["prompt"]
        if claudeAsks(raw) { return [PendingCard(kind: "choice", summary: prompt["title"].string(), progress: prompt["progress"].string())] }
        return raw["actions"].array.isEmpty ? [] : [PendingCard(kind: "actions", summary: "计划与执行选项")]
    case "deepseek":
        let approvals = deepseekApprovals(raw)
        let questions = deepseekQuestionCards(raw)
        let total = approvals.count + questions.count
        if total == 0 { return [] }
        if let first = approvals.first {
            let tool = first["request"]["toolName"].string()
            return [PendingCard(kind: "approval", summary: "批准这一步吗？" + (tool.isEmpty ? "" : " · " + tool), count: total)]
        }
        let question = questions.first?["questions"].array.first?["question"].string() ?? ""
        return [PendingCard(kind: "question", summary: question.isEmpty ? "有问题要回答" : question, count: total)]
    default:
        return raw["questions"].array.filter { $0["status"].string() == "pending" }.map { card in
            let question = card["questions"].array.first?["question"].string() ?? ""
            return PendingCard(kind: "question", summary: question.isEmpty ? "Codex 有问题要问你" : question)
        }
    }
}

/// Whether Claude's desktop shows a question laid out for the phone (web askParts): a prompt with choices or
/// navigation. Its buttons are also the plan options, so those show only without one (the PC repeated them as
/// raw names under the question until dev.23).
public func claudeAsks(_ raw: JSONValue) -> Bool {
    let prompt = raw["prompt"]
    return prompt.isObject && (!prompt["choices"].array.isEmpty || !prompt["nav"].array.isEmpty)
}

/// DeepSeek's approval requests, each its own card.
public func deepseekApprovals(_ raw: JSONValue) -> [JSONValue] {
    raw["interactions"].array.filter { $0["event"].string() == "approval/request" }
}

/// DeepSeek's question cards: those in its state and those that came as events, once per call id.
public func deepseekQuestionCards(_ raw: JSONValue) -> [JSONValue] {
    // Filtered rather than `c ? request : nil`, whose nil is JSONValue.null and would be kept.
    let events = raw["interactions"].array.filter { $0["event"].string() == "user-questions/request" && $0["request"].isObject }.map { $0["request"] }
    var seen = Set<String>()
    return (raw["questions"].array + events).filter { seen.insert($0["callId"].string()).inserted }
}

/// Folds . and .. and the slashes, in lower case, as the web compares an HTML page's resource with the listed files
/// (artifact-preview.js).
public func normalizePath(_ path: String) -> String {
    var parts: [Substring] = []
    for bit in path.replacingOccurrences(of: "\\", with: "/").split(separator: "/", omittingEmptySubsequences: false) {
        switch bit {
        case "", ".": continue
        case "..": if !parts.isEmpty { parts.removeLast() }
        default: parts.append(bit)
        }
    }
    return parts.joined(separator: "/").lowercased()
}

/// A path written in a page that may name a file beside it (web artifact-preview relative()).
public func relativeResource(_ path: String) -> Bool {
    !path.isEmpty && !path.hasPrefix("/") && !path.hasPrefix("\\") && !path.contains(":")
        && !path.unicodeScalars.contains { $0 == "?" || $0 == "#" || $0.value < 0x20 }
}

/// The event that brought a DeepSeek question card, which its answer names.
public func deepseekQuestionEvent(_ raw: JSONValue, callId: String) -> String {
    raw["interactions"].array.first { $0["event"].string() == "user-questions/request" && $0["request"]["callId"].string() == callId }?["eventId"].string() ?? ""
}
