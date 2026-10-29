import Foundation
import Testing
import TeleplyModel

/// 0.6.5: a send the computer took stays in the timeline until the record shows it; then the record's row replaces it
/// and there is never both.
struct OutboxTests {
    private let key = ChatKey(scope: "s", device: "d", app: "codex", chat: "c")
    private let now: Int64 = 1_800_000_000_000

    private func send(_ text: String = "新指令", label: String = "已接收", created: Int64? = nil,
                      request: String = "req-1") -> Submission {
        Submission(request: request, key: key, text: text, action: "send", turn: "t", body: "{}",
                   label: label, created: created ?? now - 30_000)
    }

    private func user(_ text: String, at: String, request: String = "") -> Message {
        var message = Message(id: "m1", role: "user", text: text)
        message.request = request
        message.details = ["time": .string(at)]
        return message
    }

    @Test func aTakenSendStaysUntilTheRecordHasIt() {
        let record = send()
        #expect(outboxSends([record], messages: [], now: now).map(\.request) == ["req-1"])
        #expect(outboxSends([record], messages: [user("别的", at: "2027-01-15T08:00:00Z")], now: now)
            .map(\.request) == ["req-1"])
    }

    @Test func theRecordsOwnRequestReplacesItAndNothingDuplicates() {
        let record = send()
        let shown = user("新指令", at: "2027-01-15T07:59:50Z", request: "req-1")
        #expect(outboxSends([record], messages: [shown], now: now).isEmpty)
    }

    @Test func claudeAndDeepSeekMatchByWordsAndTime() {
        let record = send("整理发布说明", created: 1_800_000_000_000)
        let shown = user("整理发布说明", at: "2027-01-15T08:00:00Z")
        #expect(outboxSends([record], messages: [shown], now: now).isEmpty)
        let tooOld = user("整理发布说明", at: "2027-01-15T07:50:00Z")
        #expect(outboxSends([record], messages: [tooOld], now: now).map(\.request) == ["req-1"])
    }

    @Test func aSendIsGivenUpOnlyWhenALaterMessageExists() {
        let old = send(created: now - 11 * 60_000)
        let later = user("下一件事", at: "2027-01-15T08:05:00Z")
        #expect(outboxSends([old], messages: [later], now: now).isEmpty)
        #expect(outboxSends([old], messages: [], now: now).map(\.request) == ["req-1"])
    }

    @Test func aSendWithAPictureMatchesTheWordsAfterTheMark() {
        let record = send("看一下这个", created: 1_800_000_000_000)
        let shown = user("[图片] 看一下这个", at: "2027-01-15T08:00:00Z")
        #expect(outboxSends([record], messages: [shown], now: now).isEmpty)
    }
}
