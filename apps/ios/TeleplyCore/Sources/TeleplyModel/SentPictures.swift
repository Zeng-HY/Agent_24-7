import Foundation

/// A picture sent with a message through this service (web codex-ui.js renderImages): the computer keeps it and a
/// small copy, by its id (GET /api/codex/image).
public struct SentPicture: Sendable, Equatable, Identifiable {
    public let id: String
    public let name: String

    public init(id: String, name: String) {
        self.id = id
        self.name = name
    }

    /// One of the computer's records of a picture ({id, name, url, thumbnail, …}); nil without a usable id.
    init?(_ json: JSONValue) {
        let id = json["id"].string()
        guard !id.isEmpty, id.count <= 64, id.allSatisfy({ $0.isASCII && ($0.isLetter || $0.isNumber || $0 == "-") }) else { return nil }
        let name = json["name"].string()
        self.init(id: id, name: name.isEmpty ? "图片" : name)
    }
}

/// The pictures to show in each user message, by the message's id (user 10-27: a sent picture showed as "[图片]";
/// web message-projection.js decorate). The computer keeps a record of each send with pictures (state `images`, oldest
/// first) and Codex keeps that send's request id on its message, so those go by it. Claude keeps none: a send of its
/// goes to the newest message not yet taken whose words after its [图片] mark are the send's, written no earlier than
/// the send. Newest first, as the page holds the newest messages: an older send whose message is not loaded gets none.
public func sentPictures(messages: [Message], records: [JSONValue]) -> [String: [SentPicture]] {
    let users = messages.filter { $0.role == "user" }
    var taken: [String: [SentPicture]] = [:]
    for record in records.reversed() {
        let pictures = record["images"].array.compactMap(SentPicture.init)
        guard !pictures.isEmpty else { continue }
        let request = record["request_id"].string()
        var found = request.isEmpty ? nil : users.last { taken[$0.id] == nil && $0.request == request }
        if found == nil {
            // A picture sent without words goes to Claude as 请查看这些图片。 (remote.py _send_with_references).
            let sent = record["text"].string().trimmingCharacters(in: .whitespacesAndNewlines)
            let words = squeezed(sent.isEmpty ? "请查看这些图片。" : sent)
            let since = record["created"].double() - 5
            found = users.last { message in
                guard taken[message.id] == nil, message.request.isEmpty, let rest = picturedWords(message.text), squeezed(rest) == words else { return false }
                return (writtenAt(message) ?? .greatestFiniteMagnitude) >= since
            }
        }
        if let found { taken[found.id] = pictures }
    }
    return taken
}

/// A user message's words after the [图片] marks the computer writes for its pictures (chats.py), or nil without one.
public func picturedWords(_ text: String) -> String? {
    guard let marks = text.range(of: #"^(\[图片\]\s*)+"#, options: .regularExpression) else { return nil }
    return String(text[marks.upperBound...])
}

/// Text without any whitespace, as the web compares a send with its message (codex-ui.js normalize).
func squeezed(_ text: String) -> String {
    text.filter { !$0.isWhitespace }
}

/// When the record wrote a message (its `time`, ISO 8601), in seconds since 1970 as the computer counts a send's.
func writtenAt(_ message: Message) -> Double? {
    let text = message.details["time"].string()
    guard !text.isEmpty else { return nil }
    let reader = ISO8601DateFormatter()
    reader.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
    if let date = reader.date(from: text) { return date.timeIntervalSince1970 }
    reader.formatOptions = [.withInternetDateTime]
    return reader.date(from: text)?.timeIntervalSince1970
}
