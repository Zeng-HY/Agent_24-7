import Foundation

/// A first message sent (spec 4.4; Android NewJob, web new-chat-ui.js jobs). The sheet is free again at once; the
/// job is followed on its own page while that is open, as a row above the list otherwise. [pending] is the
/// computer's latest word on it (chat/new and chat/new/state); [note] why it could not be asked just now.
/// [created] is milliseconds.
public struct NewJob: Codable, Sendable, Equatable, Identifiable {
    public var request: String
    public var app: String
    public var folder: String
    public var projectless: Bool
    public var label: String
    public var text: String
    public var references: JSONValue
    public var images: JSONValue
    public var body: JSONValue
    public var pending: JSONValue
    public var created: Int64
    public var note: String

    public init(request: String, app: String, folder: String, projectless: Bool, label: String, text: String,
                references: JSONValue = [], images: JSONValue = [], body: JSONValue, pending: JSONValue, created: Int64, note: String = "") {
        self.request = request
        self.app = app
        self.folder = folder
        self.projectless = projectless
        self.label = label
        self.text = text
        self.references = references
        self.images = images
        self.body = body
        self.pending = pending
        self.created = created
        self.note = note
    }

    public var id: String { request }
    /// The page shown for it until the conversation exists (web preview_id).
    public var preview: String { "new:" + request }
    public var state: String { pending["state"].string() }
    public var problem: Bool { state == "failed" || state == "unconfirmed" }
    public var createdID: String { pending["id"].string() }
    public var accepted: Bool { state == "accepted" && !createdID.isEmpty }
    /// 继续发送 may go: the computer has no submission (can_submit), or one that failed before it was sent.
    public var retryable: Bool {
        pending["can_submit"].bool() || state == "failed" && pending["not_submitted"].bool() && pending["can_retry"].bool(or: true)
    }
}

/// A conversation's page before it exists (web preview id new:…).
public func isNewPage(_ chat: String?) -> Bool {
    chat?.hasPrefix("new:") == true
}

/// The first message's words in one line, at most [limit] characters.
public func oneLine(_ text: String, limit: Int) -> String {
    String(text.split(whereSeparator: \.isWhitespace).joined(separator: " ").prefix(limit))
}

/// A conversation's unsent words as the list shows them after a red [草稿] (WeChat): one line, at most 100
/// characters; empty when there is nothing but spaces.
public func draftPreview(_ text: String) -> String {
    oneLine(text, limit: 100)
}

/// Where a job stands, in the web's words (stateText).
public func newJobState(_ job: NewJob) -> String {
    switch job.state {
    case "accepted": return "新对话已就绪"
    case "failed": return "没发出去"
    case "unconfirmed": return "尚未确认发送"
    case "dispatching": return "发送中…"
    default: return "对话创建中…"
    }
}

/// The line under the first message on its page (web inlineText): a problem says it can be tapped.
public func newJobInline(_ job: NewJob) -> String {
    if !job.note.isEmpty { return job.note }
    switch job.state {
    case "failed": return "没发出去 · 点击处理"
    case "unconfirmed": return "尚未确认发送 · 点击核对"
    case "accepted": return ""
    default: return newJobState(job)
    }
}

/// The job sheet's line (web progressText): the step the computer is at, or what went wrong.
public func newJobProgress(_ job: NewJob) -> String {
    if !job.note.isEmpty { return job.note }
    if job.problem {
        let message = job.pending["message"].string()
        return message.isEmpty ? newJobState(job) : message
    }
    if job.state == "accepted" { return "首条消息已送达" }
    let stage = job.pending["timing"]["active"]["name"].string()
    if ["claude_record", "receipt", "send_ack", "late_receipt"].contains(stage) { return "正在确认首条消息" }
    if stage.hasPrefix("send_") || ["claude_fill", "claude_images", "claude_verify", "claude_invoke"].contains(stage) { return "正在发送首条消息" }
    if stage.hasPrefix("desktop_") { return "正在连接电脑端" }
    return "正在创建对话"
}

/// A row above the list for a job not on screen (web dockText).
public func newJobDock(_ job: NewJob) -> String {
    let words = oneLine(job.text, limit: 60)
    return Labels.sourceName(job.app) + " · " + newJobState(job) + " · " + (words.isEmpty ? "新对话" : words)
}
