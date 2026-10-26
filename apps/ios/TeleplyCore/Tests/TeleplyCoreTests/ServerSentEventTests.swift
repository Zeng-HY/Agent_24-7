import Testing
@testable import TeleplyModel

struct ServerSentEventTests {
    @Test func readsTheComputersFramesAndSkipsTheHeartbeat() throws {
        var parser = ServerSentEventParser()
        let events = try parser.feed(Array(": heartbeat\n\nid: 1\nevent: update\ndata: {\"seq\":1}\n\n".utf8))
        #expect(events == [ServerSentEvent(id: "1", event: "update", data: "{\"seq\":1}")])
    }

    @Test func aCRLFSplitAcrossChunksEndsOneLine() throws {
        var parser = ServerSentEventParser()
        #expect(try parser.feed(Array("data: a\r".utf8)).isEmpty)
        #expect(try parser.feed(Array("\n\r\n".utf8)) == [ServerSentEvent(data: "a")])
    }

    @Test func lineAndParagraphSeparatorsStayInsideTheData() throws {
        var parser = ServerSentEventParser()
        let text = "data: {\"text\":\"一\u{2028}二\u{2029}三\"}\n\n"
        let events = try parser.feed(Array(text.utf8))
        #expect(events.map(\.data) == ["{\"text\":\"一\u{2028}二\u{2029}三\"}"])
    }

    @Test func severalDataLinesJoinWithNewlines() throws {
        var parser = ServerSentEventParser()
        #expect(try parser.feed(Array("data: a\ndata:b\n\n".utf8)).map(\.data) == ["a\nb"])
    }
}
