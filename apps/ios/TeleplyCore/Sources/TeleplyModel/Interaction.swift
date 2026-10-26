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
/// desktop prompt and its plan options; DeepSeek's approvals first, then its questions.
public func pendingCards(app: String, raw: JSONValue) -> [PendingCard] {
    switch app {
    case "claude":
        var cards: [PendingCard] = []
        let prompt = raw["prompt"]
        if prompt.isObject { cards.append(PendingCard(kind: "choice", summary: prompt["title"].string(), progress: prompt["progress"].string())) }
        if !raw["actions"].array.isEmpty { cards.append(PendingCard(kind: "actions", summary: "计划与执行选项")) }
        return cards
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

/// DeepSeek's approval requests, each its own card.
public func deepseekApprovals(_ raw: JSONValue) -> [JSONValue] {
    raw["interactions"].array.filter { $0["event"].string() == "approval/request" }
}

/// DeepSeek's question cards: those in its state and those that came as events, once per call id.
public func deepseekQuestionCards(_ raw: JSONValue) -> [JSONValue] {
    let events = raw["interactions"].array.filter { $0["event"].string() == "user-questions/request" }.compactMap { event -> JSONValue? in
        event["request"].isObject ? event["request"] : nil
    }
    var seen = Set<String>()
    return (raw["questions"].array + events).filter { seen.insert($0["callId"].string()).inserted }
}

/// The event that brought a DeepSeek question card, which its answer names.
public func deepseekQuestionEvent(_ raw: JSONValue, callId: String) -> String {
    raw["interactions"].array.first { $0["event"].string() == "user-questions/request" && $0["request"]["callId"].string() == callId }?["eventId"].string() ?? ""
}
