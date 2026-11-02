import Foundation
import Testing
import TeleplyModel

/// 0.6.5: a send the computer took stays in the timeline until the record shows it; then the record's row replaces it
/// and there is never both.
struct OutboxTests {
    private let key = ChatKey(scope: "s", device: "d", app: "codex", chat: "c")
    private let now: Int64 = 1_800_000_000_000

    private func send(_ text: String = "新指令", label: String = "已接收", created: Int64? = nil,
                      request: String = "req-1", app: String = "codex",
                      notes: [String: JSONValue] = [:]) -> Submission {
        let body = String(decoding: (try? JSONValue.object(notes).encoded()) ?? Data("{}".utf8), as: UTF8.self)
        return Submission(request: request, key: ChatKey(scope: "s", device: "d", app: app, chat: "c"),
                          text: text, action: "send", turn: "t", body: body,
                          label: label, created: created ?? now - 30_000)
    }

    private func user(_ text: String, at: String, request: String = "", id: String = "m1",
                      order: Double? = nil) -> Message {
        var message = Message(id: id, role: "user", text: text)
        message.request = request
        message.order = order
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

    @Test func deepSeeksSixFractionalDigitsDoNotLeaveASecondCopy() {
        let record = send("Hello", created: 1_793_325_106_000)
        let shown = user("Hello", at: "2026-10-30T01:51:46.667000+00:00")
        #expect(outboxSends([record], messages: [shown], now: now).isEmpty)
    }

    @Test func deepSeeksPictureCountDoesNotLeaveASecondCopy() {
        let record = send("看一下这个", created: 1_800_000_000_000)
        let shown = user("看一下这个\n[1 张图片]", at: "2027-01-15T08:00:00Z")
        #expect(outboxSends([record], messages: [shown], now: now).isEmpty)
        #expect(outboxSends([record], messages: [user("看一下这个\n[2 张图片]", at: "2027-01-15T08:00:00Z")],
                            now: now).isEmpty)
    }

    // -- 11-01: the phone's clock was 13 s fast; a picture came into the record 3 s after Enter and never matched

    @Test func aPictureMessageThreeSecondsAfterEnterMatchesThoughThePhoneClockIsFast() {
        let computerTook: Int64 = 1_800_000_000_000  // the computer's clock when Enter was pressed (08:00:00)
        let record = send("看一下这个", created: computerTook + 13_000, app: "claude",
                          notes: [acceptedAtNote: .number(Double(computerTook))])
        let shown = user("[图片] 看一下这个", at: "2027-01-15T08:00:03Z")
        #expect(outboxSends([record], messages: [shown], now: now).isEmpty)
    }

    @Test func claudeMatchesByTheRecordsPositionNotTheClock() {
        let record = send("整理", created: 1_800_000_000_000, app: "claude",
                          notes: [claudeOffsetNote: .number(1000)])
        // hours "earlier" by the record's clock, but written after Enter: it is this send
        let shown = user("整理", at: "2027-01-15T07:00:00Z", order: 2000)
        #expect(outboxSends([record], messages: [shown], now: now).isEmpty)
        // written before Enter: someone else's message with the same words
        let earlier = user("整理", at: "2027-01-15T08:00:00Z", order: 500)
        #expect(outboxSends([record], messages: [earlier], now: now).map(\.request) == ["req-1"])
    }

    @Test func theSameWordsSentTwiceEachTakeTheirOwnRecord() {
        let first = send("好", created: now - 60_000, request: "req-1", app: "claude",
                         notes: [claudeOffsetNote: .number(1000)])
        let second = send("好", created: now - 30_000, request: "req-2", app: "claude",
                          notes: [claudeOffsetNote: .number(2000)])
        let one = user("好", at: "2027-01-15T07:59:30Z", id: "m1", order: 1500)
        let two = user("好", at: "2027-01-15T07:59:50Z", id: "m2", order: 2500)
        #expect(outboxSends([first, second], messages: [one, two], now: now).isEmpty)
        #expect(outboxSends([second], messages: [one], now: now).map(\.request) == ["req-2"])
    }

    @Test func anOlderComputerThatSaysNeitherGetsTwoMinutes() {
        let record = send("旧电脑", created: 1_800_000_000_000)  // no notes at all
        let shown = user("旧电脑", at: "2027-01-15T07:58:30Z")  // 90 s before the phone's time of sending
        #expect(outboxSends([record], messages: [shown], now: now).isEmpty)
        let tooEarly = user("旧电脑", at: "2027-01-15T07:57:00Z")  // 3 min before
        #expect(outboxSends([record], messages: [tooEarly], now: now).map(\.request) == ["req-1"])
    }

    @Test func givingUpUsesTheComputersTimeToo() {
        let computerTook: Int64 = 1_799_999_340_000  // 07:49:00 by the computer's clock, 11 minutes ago
        let record = send("旧的", created: computerTook + 13_000, app: "claude",
                          notes: [acceptedAtNote: .number(Double(computerTook))])
        let later = user("下一件事", at: "2027-01-15T07:49:02Z")
        #expect(outboxSends([record], messages: [later], now: now).isEmpty)
    }

    // -- 11-02: a long turn moved the page of the newest 60 rows past the sends of the day before

    private func answer(at: String, order: Double? = nil) -> Message {
        var message = Message(id: "a1", role: "assistant", text: "还在做")
        message.order = order
        message.details = ["time": .string(at)]
        return message
    }

    @Test func aSendThePageHasMovedPastLeavesTheBottom() {
        let record = send("跑完了吗", label: "已送达", created: now - 86_400_000, app: "claude",
                          notes: [claudeOffsetNote: .number(1000)])
        let newest = answer(at: "2027-01-15T08:00:00Z", order: 5000)
        #expect(outboxSends([record], messages: [newest], now: now, olderUnread: true).isEmpty)
        // No older rows left: the page is the whole record, and the record does not have it.
        #expect(outboxSends([record], messages: [newest], now: now).map(\.request) == ["req-1"])
    }

    @Test func aSendJustAfterThePagesFirstRowWaitsForItsOwnRow() {
        let record = send("跑完了吗", label: "已送达", app: "claude", notes: [claudeOffsetNote: .number(1000)])
        // Written before Enter: the send's row is still to come in this page.
        let earlier = answer(at: "2027-01-15T07:59:00Z", order: 500)
        #expect(outboxSends([record], messages: [earlier], now: now, olderUnread: true).map(\.request) == ["req-1"])
    }

    @Test func aSendOfAnotherSourceGoesByTheComputersTime() {
        let computerTook: Int64 = 1_799_996_400_000  // 07:00:00
        let record = send("整理", created: computerTook + 13_000, notes: [acceptedAtNote: .number(Double(computerTook))])
        let after = answer(at: "2027-01-15T07:00:30Z")
        #expect(outboxSends([record], messages: [after], now: now, olderUnread: true).isEmpty)
        let before = answer(at: "2027-01-15T06:59:30Z")
        #expect(outboxSends([record], messages: [before], now: now, olderUnread: true).map(\.request) == ["req-1"])
    }

    @Test func anOlderComputerLeavesTwoMinutesForThePhonesClock() {
        let record = send("旧电脑", created: 1_799_996_400_000)  // 07:00:00 by the phone, no notes at all
        let soon = answer(at: "2027-01-15T07:01:30Z")
        #expect(outboxSends([record], messages: [soon], now: now, olderUnread: true).map(\.request) == ["req-1"])
        let long = answer(at: "2027-01-15T07:03:00Z")
        #expect(outboxSends([record], messages: [long], now: now, olderUnread: true).isEmpty)
    }

    @Test func aQueuedSendStaysHoweverFarThePageHasMoved() {
        let record = send("排着队", label: "已排队", app: "claude", notes: [claudeOffsetNote: .number(1000)])
        let newest = answer(at: "2027-01-15T08:00:00Z", order: 5000)
        #expect(outboxSends([record], messages: [newest], now: now, olderUnread: true).map(\.request) == ["req-1"])
    }

    @Test func aRowStillInThePageIsMatchedAsBefore() {
        let record = send("跑完了吗", label: "已送达", app: "claude", notes: [claudeOffsetNote: .number(1000)])
        let own = user("跑完了吗", at: "2027-01-15T07:59:00Z", order: 1200)
        #expect(outboxSends([record], messages: [own], now: now, olderUnread: true).isEmpty)
    }
}
