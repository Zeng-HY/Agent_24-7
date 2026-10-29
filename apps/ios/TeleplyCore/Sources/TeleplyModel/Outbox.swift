import Foundation

/// Sends that are on this phone but not in the conversation's record yet (0.6.5). A send stays in the timeline, in the
/// light "not yet in the record" style, until the record has the same message; then the record's row replaces it.
///
/// Codex keeps the phone's request id on the message, so that is exact. Claude and DeepSeek keep none: their messages
/// are matched by words and write time, the same way sent pictures are matched (SentPictures.swift). If ten minutes
/// have passed and the record already has a later user message, the send is given up and left to 核对发送记录.
public func outboxSends(_ submissions: [Submission], messages: [Message], now: Int64) -> [Submission] {
    let users = messages.filter { $0.role == "user" }
    var used = Set<String>()
    var kept: [Submission] = []
    for record in submissions.sorted(by: { $0.created < $1.created }) {
        guard record.action == "send", !record.request.isEmpty else { continue }
        guard !["未接收", "已取消排队"].contains(record.label) else { continue }
        if let found = users.first(where: { !used.contains($0.id) && $0.request == record.request }) {
            used.insert(found.id)
            continue
        }
        if let found = users.first(where: { !used.contains($0.id) && $0.request.isEmpty && matches($0, record) }) {
            used.insert(found.id)
            continue
        }
        let sentAt = Double(record.created) / 1000
        let later = users.contains { message in
            guard let written = writtenAt(message) else { return false }
            return written > sentAt + 1
        }
        if now - record.created >= 10 * 60_000 && later { continue }
        kept.append(record)
    }
    return kept
}

/// A Claude/DeepSeek user message that is this send: the same words (after any picture marks) and written no earlier
/// than five seconds before the phone sent it.
private func matches(_ message: Message, _ record: Submission) -> Bool {
    let words = squeezed(picturedWords(message.text) ?? message.text)
    guard !words.isEmpty, words == squeezed(record.text) else { return false }
    guard let written = writtenAt(message) else { return false }
    return written >= Double(record.created) / 1000 - 5
}
