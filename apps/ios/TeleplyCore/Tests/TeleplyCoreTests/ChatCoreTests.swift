import Foundation
import Testing
@testable import TeleplyModel

/// Android ChatCoreTest, case for case.
struct ChatCoreTests {
    @Test func reconnectCannotRegressATerminalTurnButANewTurnCanRun() {
        let done = Control(available: true, turns: ["t": "completed"])
        #expect(!mergeControl(previous: done, incoming: Control(available: true, running: true, turn: "t", turns: ["t": "inProgress"])).running)
        #expect(mergeControl(previous: done, incoming: Control(available: true, running: true, turn: "new", turns: ["new": "inProgress"])).running)
    }

    private func frame(_ seq: Int, _ type: String = "update", chat: String = "c") throws -> JSONValue {
        try JSONValue.parse(Data("""
        {"protocol":1,"app":"codex","id":"\(chat)","type":"\(type)","seq":\(seq),"chat":{"id":"\(chat)","app":"codex","messages":[]},"messages":[]}
        """.utf8))
    }

    @Test func sequenceRestartsOnlyWithASnapshotAndDropsRepeats() throws {
        var reducer = StreamReducer(chat: "c")
        #expect(try reducer.accept(frame(1, "snapshot")) != nil)
        #expect(try reducer.accept(frame(1, "snapshot")) == nil)
        #expect(try reducer.accept(frame(2)) != nil)
        #expect(throws: ReadFailure("实时序号不连续")) { try reducer.accept(frame(4)) }
        var fresh = StreamReducer(chat: "c")
        #expect(try fresh.accept(frame(1, "snapshot")) != nil)
    }

    @Test func rejectsAnotherConversationAndAMissingSnapshot() throws {
        var other = StreamReducer(chat: "c")
        #expect(throws: ReadFailure.self) { try other.accept(frame(1, "snapshot", chat: "other")) }
        var noSnapshot = StreamReducer(chat: "c")
        #expect(throws: ReadFailure("实时序号不连续")) { try noSnapshot.accept(frame(1)) }
    }

    @Test func aCommittedAliasReplacesTheLiveMessageAndSourceOrderWins() {
        var first = Message(id: "first", role: "assistant", text: "same"); first.order = 1
        var live = Message(id: "live", role: "assistant", text: "same"); live.order = 3
        var committed = Message(id: "committed", role: "assistant", text: "same"); committed.order = 2; committed.aliases = ["live"]
        #expect(mergeLive([first, live], [committed]).map(\.id) == ["first", "committed"])
    }

    @Test func unknownAndQueuedAreNotDelivery() throws {
        #expect(receiptLabel(state: "unknown", result: [:], action: "send") == "送达状态待确认")
        #expect(receiptLabel(state: "queued", result: [:], action: "send") == "已排队")
        #expect(receiptLabel(state: "accepted", result: [:], action: "send") == "已接收")
        #expect(receiptLabel(state: "accepted", result: ["evidence": ["source": "conversation_record"]], action: "send") == "已送达")
        #expect(receiptLabel(state: "accepted", result: [:], action: "stop").contains("等待"))
    }

    @Test func mergeKeepsServerOrderAndNeverMergesByText() {
        let a = Message(id: "a", role: "user", text: "同样的字")
        let b = Message(id: "b", role: "user", text: "同样的字")
        var newer = a; newer.text = "改过"
        #expect(mergeMessages([a], [b, newer], prepend: false).map(\.id) == ["a", "b"])
        #expect(mergeMessages([a], [b, newer], prepend: false).first?.text == "改过")
        #expect(mergeMessages([a], [b], prepend: true).map(\.id) == ["b", "a"])
    }

    @Test func controlReadsTurnsQueueAndQuestions() throws {
        let state = try JSONValue.parse(Data("""
        {"available":true,"running":true,"turn_id":"t1","queue_available":true,"queued":[{"id":"q","text":"排队","status":"queued"}],
         "recent_turns":[{"id":"t0","status":"completed"}],"prompt":{}}
        """.utf8))
        let control = parseControl(state)
        #expect(control.turn == "t1")
        #expect(control.queued == [Queued(id: "q", text: "排队", status: "queued")])
        #expect(control.turns == ["t0": "completed"])
        #expect(control.questions)
    }
}
