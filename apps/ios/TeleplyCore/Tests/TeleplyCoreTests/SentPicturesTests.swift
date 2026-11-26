import Foundation
import Testing
@testable import TeleplyModel

/// Pictures sent with messages, matched to them as the computer kept the sends (user 10-27: a sent picture showed only
/// as "[图片]"; web message-projection.js decorate).
struct SentPicturesTests {
    func user(_ id: String, _ text: String, request: String = "", time: String? = nil) -> Message {
        var message = Message(id: id, role: "user", text: text)
        message.request = request
        if let time { message.details = ["time": .string(time)] }
        return message
    }

    func record(_ request: String, _ pictures: [String], text: String = "", created: Double = 0) -> JSONValue {
        ["request_id": .string(request), "text": .string(text), "created": .number(created), "status": "accepted",
         "images": .array(pictures.map { ["id": .string($0), "name": .string($0 + ".png")] })]
    }

    @Test func codexSendsGoByTheRequestIdOnTheirMessage() {
        let found = sentPictures(messages: [user("m1", "看这张", request: "r1"), user("m2", "别的", request: "r2")],
                                 records: [record("r1", ["a"], text: "看这张")])
        #expect(found == ["m1": [SentPicture(id: "a", name: "a.png")]])
    }

    /// Claude keeps no request id: by the words after the [图片] mark and the time, newest first.
    @Test func claudeSendsGoByTheirWordsAndTimeNewestFirst() {
        // 2026-10-20T08:00:00Z is 1792483200 s; a picture sent without words reached Claude as 请查看这些图片。
        let messages = [user("m1", "[图片] 请查看这些图片。", time: "2026-10-20T08:00:00.000Z"),
                        user("m2", "你好"),
                        user("m3", "[图片] 请查看这些图片。", time: "2026-10-20T09:00:00Z")]
        let records = [record("c1", ["a"], created: 1_792_483_198), record("c2", ["b", "c"], created: 1_792_486_798)]
        let found = sentPictures(messages: messages, records: records)
        #expect(found["m1"]?.map(\.id) == ["a"])
        #expect(found["m3"]?.map(\.id) == ["b", "c"])
        #expect(found["m2"] == nil)
        // The older send's message not loaded: it takes none, not the newer one's.
        #expect(sentPictures(messages: [messages[2]], records: records).mapValues { $0.map(\.id) } == ["m3": ["b", "c"]])
        // A message written before the send is not that send's.
        #expect(sentPictures(messages: [messages[0]], records: [record("c3", ["d"], created: 1_792_483_300)]).isEmpty)
    }

    @Test func deepSeeksPictureCountSuffixStillTakesItsPictures() {
        let record = record("d1", ["a"], text: "看这张图", created: 1_792_483_198)
        let message = user("m1", "看这张图\n[1 张图片]", time: "2026-10-20T08:00:00Z")
        #expect(sentPictures(messages: [message], records: [record])["m1"]?.map(\.id) == ["a"])
    }

    /// 11-26 (handoff §3.2): a user message may carry its own pictures (`images`), e.g. an interjection sent while the
    /// source worked, which no send record mentions. They go after the record's pictures, by id still unseen, and items
    /// the computer cannot serve (only a path, or a url outside /api/codex/image) are left out.
    @Test func aMessageCarriesItsOwnPicturesAfterTheRecordsAndOnlyOnce() throws {
        let own: [JSONValue] = [
            ["id": "a", "name": "a.png", "url": "/api/codex/image?id=a"],
            ["id": "b", "name": "b.png", "url": "/api/codex/image?id=b"],
            ["id": "path-only", "name": "c.png", "path": "D:/fixture/c.png"],
            ["id": "elsewhere", "name": "d.png", "url": "/api/file?id=d"],
            ["id": "a/b", "name": "e.png", "url": "/api/codex/image?id=a/b"],
            ["id": .string(String(repeating: "x", count: 65)), "name": "f.png", "url": "/api/codex/image?id=long"],
        ]
        let message = try parseMessage(["id": "m1", "role": "user", "text": "[图片] 看这张", "images": .array(own)])
        // The record's "a" comes first; the message's own "a" is not drawn twice.
        let found = sentPictures(messages: [message], records: [record("r1", ["a"], text: "看这张")])
        #expect(found["m1"]?.map(\.id) == ["a", "b"])
        // With no send record at all, the message's own pictures still show.
        #expect(sentPictures(messages: [message], records: [])["m1"]?.map(\.id) == ["a", "b"])
        // Without `images`, the result is what it always was.
        #expect(sentPictures(messages: [user("m1", "看这张", request: "r1")], records: [record("r1", ["a"], text: "看这张")])
            .mapValues { $0.map(\.id) } == ["m1": ["a"]])
        // The [图片] prefix and DeepSeek's [N 张图片] suffix both leave the bubble's words.
        #expect(wordsWithoutPictureMarks("[图片] 看这张") == "看这张")
        #expect(wordsWithoutPictureMarks("看这张\n[2 张图片]") == "看这张")
        #expect(wordsWithoutPictureMarks("没有图") == "没有图")
    }

    /// A message with nothing but pictures: the grid is all the bubble shows.
    @Test func aMessageOfPicturesAloneHasNoWordsLeft() throws {
        let message = try parseMessage(["id": "m1", "role": "user", "text": "[图片] [图片]",
                                        "images": .array([
                                            ["id": "a", "name": "a.png", "url": "/api/codex/image?id=a"],
                                            ["id": "b", "name": "b.png", "url": "/api/codex/image?id=b"],
                                        ])])
        let found = sentPictures(messages: [message], records: [])
        #expect(found["m1"]?.map(\.id) == ["a", "b"])
        #expect(wordsWithoutPictureMarks(message.text).trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
    }

    @Test func onlyAMessageWithTheMarkAndTheSameWordsTakesPictures() {
        let records = [record("c1", ["a"], text: "看 这张图")]
        #expect(sentPictures(messages: [user("m1", "看这张图")], records: records).isEmpty)
        #expect(sentPictures(messages: [user("m1", "[图片] 看这张 图")], records: records)["m1"]?.count == 1)
        #expect(sentPictures(messages: [user("m1", "[图片] 别的话")], records: records).isEmpty)
        #expect(sentPictures(messages: [user("m1", "[图片] 看这张图")], records: [record("c1", [], text: "看这张图")]).isEmpty)
        #expect(sentPictures(messages: [user("m1", "[图片] 看这张图")], records: [record("c1", ["../x"], text: "看这张图")]).isEmpty)
        #expect(picturedWords("[图片] [图片] 两张") == "两张")
        #expect(picturedWords("没有图") == nil)
        #expect(wordsAfterPictureMarks("看这张图\n[1 张图片]") == "看这张图")
    }
}
