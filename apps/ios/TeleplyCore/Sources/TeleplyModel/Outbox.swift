import Foundation

/// 0.6.6: the note a send's saved body gets when the source ran it as a command of its own (Codex's and DeepSeek's
/// /compact): no message of it ever comes into the record, so it does not wait in the timeline.
public let commandNote = "_command"

/// 11-01: the notes a send keeps in its body for finding its message in the record, written by ChatModel.dispatch and
/// never sent. `claudeOffsetNote` is where Claude's record stood when the computer pressed Enter; `acceptedAtNote` is
/// when the computer took the send on its own clock (milliseconds). Claude's and DeepSeek's record times come from the
/// computer, and its clock was 13 s behind the phone's: comparing them with the phone's clock kept the send waiting.
public let claudeOffsetNote = "_claude_offset"
public let acceptedAtNote = "_accepted_at"

/// Sends that are on this phone but not in the conversation's record yet (0.6.5). A send stays in the timeline, in the
/// light "not yet in the record" style, until the record has the same message; then the record's row replaces it.
///
/// Codex keeps the phone's request id on the message, so that is exact. Claude and DeepSeek keep none: their messages
/// are matched by words, and then by where the record stood (Claude, its position) or by the computer's own time of
/// accepting the send (both). Without either (an older computer) the words and 120 s are all there is. If ten minutes
/// have passed and the record already has a later user message, the send is given up and left to 核对发送记录.
public func outboxSends(_ submissions: [Submission], messages: [Message], now: Int64) -> [Submission] {
    let users = messages.filter { $0.role == "user" }
    var used = Set<String>()
    var kept: [Submission] = []
    for record in submissions.sorted(by: { $0.created < $1.created }) {
        guard record.action == "send", !record.request.isEmpty else { continue }
        guard !["未接收", "已取消排队"].contains(record.label) else { continue }
        if record.body.contains(commandNote), let notes = try? JSONValue.parse(Data(record.body.utf8)),
           !notes[commandNote].string().isEmpty { continue }
        if let found = users.first(where: { !used.contains($0.id) && $0.request == record.request }) {
            used.insert(found.id)
            continue
        }
        if let found = users.first(where: { !used.contains($0.id) && $0.request.isEmpty && matches($0, record) }) {
            used.insert(found.id)
            continue
        }
        let sentAt = Double(sendBase(record)) / 1000
        let later = users.contains { message in
            guard let written = writtenAt(message) else { return false }
            return written > sentAt + 1
        }
        if now - sendBase(record) >= 10 * 60_000 && later { continue }
        kept.append(record)
    }
    return kept
}

/// When the computer took this send, on the computer's own clock (milliseconds); the phone's own time of sending
/// when the computer did not say (an older computer).
private func sendBase(_ record: Submission) -> Int64 {
    let accepted = notesOf(record)[acceptedAtNote].int64()
    return accepted > 0 ? accepted : record.created
}

private func notesOf(_ record: Submission) -> JSONValue {
    (try? JSONValue.parse(Data(record.body.utf8))) ?? [:]
}

/// A Claude/DeepSeek user message that is this send: the same words (after any picture marks), and then:
/// - Claude, with the record's position when the send went out: the message came after it. No time comparison at
///   all — both clocks are this computer's, but the record's time can be a couple of seconds earlier than the phone
///   thinks it sent (11-01: a picture came into the record 2.6 s after Enter and still looked older).
/// - otherwise, when the computer said when it took the send: no earlier than five seconds before that.
/// - and with an older computer that says neither: no earlier than two minutes before the phone's own clock.
private func matches(_ message: Message, _ record: Submission) -> Bool {
    // DeepSeek appends "\n[1 张图片]" to the record; the phone's send has only the words. Without this, the send
    // never matches and stays under the record's own row as a second, faded copy (10-30).
    let words = squeezed(wordsIgnoringPictureMarks(message.text))
    guard !words.isEmpty, words == squeezed(record.text) else { return false }
    let notes = notesOf(record)
    if record.app == "claude", notes[claudeOffsetNote].double() > 0, let order = message.order {
        return order > notes[claudeOffsetNote].double()
    }
    guard let written = writtenAt(message) else { return false }
    let accepted = notes[acceptedAtNote].double()
    if accepted > 0 {
        return written >= accepted / 1000 - 5
    }
    return written >= Double(record.created) / 1000 - 120
}
