import Foundation

/// 0.6.6 (user 10-31): typing / at the start of the box lists the source's commands (/compact…), $ at the start of a
/// word lists its skills, for every source the computer reports commands for. What the words ask for at the cursor.
public struct ComposerTrigger: Equatable, Sendable {
    public enum Kind: String, Sendable { case command, skill }
    public var kind: Kind
    /// What follows the / or $ up to the cursor.
    public var query: String
    /// The / or $ and the end of its word, in characters.
    public var start: Int
    public var end: Int

    public init(kind: Kind, query: String, start: Int, end: Int) {
        self.kind = kind
        self.query = query
        self.start = start
        self.end = end
    }
}

/// The list the words ask for at [cursor] (characters), or nil: a command only when the / opens the message, a skill
/// at any word's start.
public func composerTrigger(_ text: String, cursor: Int) -> ComposerTrigger? {
    let chars = Array(text)
    guard cursor >= 0, cursor <= chars.count else { return nil }
    var start = cursor
    while start > 0, !chars[start - 1].isWhitespace { start -= 1 }
    guard start < cursor else { return nil }
    let query = String(chars[(start + 1)..<cursor])
    guard !query.contains("/"), !query.contains("$"), query.count <= 64 else { return nil }
    var end = cursor
    while end < chars.count, !chars[end].isWhitespace { end += 1 }
    switch chars[start] {
    case "/" where chars[..<start].allSatisfy(\.isWhitespace):
        return ComposerTrigger(kind: .command, query: query, start: start, end: end)
    case "$":
        return ComposerTrigger(kind: .skill, query: query, start: start, end: end)
    default:
        return nil
    }
}

/// The rows that fit what was typed: names that start with it first, then any whose name, title or words hold it.
public func composerMatches(_ rows: [JSONValue], query: String, limit: Int = 30) -> [JSONValue] {
    let wanted = query.lowercased()
    guard !wanted.isEmpty else { return Array(rows.prefix(limit)) }
    let named = rows.filter { $0["name"].string().lowercased().hasPrefix(wanted) }
    let rest = rows.filter { row in
        !row["name"].string().lowercased().hasPrefix(wanted)
            && ["name", "title", "detail", "description"].contains { row[$0].string().lowercased().contains(wanted) }
    }
    return Array((named + rest).prefix(limit))
}

/// The box after a command was picked: the typed /word becomes the command, with a space after it when the command
/// takes words. The cursor goes after it.
public func pickCommand(_ text: String, _ trigger: ComposerTrigger, command: JSONValue) -> (text: String, cursor: Int) {
    let chars = Array(text)
    let start = min(trigger.start, chars.count), end = min(max(trigger.end, start), chars.count)
    let words = command["text"].string().isEmpty ? "/" + command["name"].string() : command["text"].string()
    let after = String(chars[end...])
    let insert = words + (!command["input"].string().isEmpty && !after.hasPrefix(" ") ? " " : "")
    let cursor = start + insert.count + (!command["input"].string().isEmpty && after.hasPrefix(" ") ? 1 : 0)
    return (String(chars[..<start]) + insert + after, cursor)
}

/// The box after a skill was picked: the typed $word goes (with one space after it); the skill goes with the message
/// as a reference, as 引用技能 adds it.
public func dropTrigger(_ text: String, _ trigger: ComposerTrigger) -> (text: String, cursor: Int) {
    let chars = Array(text)
    let start = min(trigger.start, chars.count)
    var end = min(max(trigger.end, start), chars.count)
    if end < chars.count, chars[end] == " " { end += 1 }
    return (String(chars[..<start]) + String(chars[end...]), start)
}
