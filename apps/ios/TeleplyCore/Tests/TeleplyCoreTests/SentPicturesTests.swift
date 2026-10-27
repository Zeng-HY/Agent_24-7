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

    @Test func onlyAMessageWithTheMarkAndTheSameWordsTakesPictures() {
        let records = [record("c1", ["a"], text: "看 这张图")]
        #expect(sentPictures(messages: [user("m1", "看这张图")], records: records).isEmpty)
        #expect(sentPictures(messages: [user("m1", "[图片] 看这张 图")], records: records)["m1"]?.count == 1)
        #expect(sentPictures(messages: [user("m1", "[图片] 别的话")], records: records).isEmpty)
        #expect(sentPictures(messages: [user("m1", "[图片] 看这张图")], records: [record("c1", [], text: "看这张图")]).isEmpty)
        #expect(sentPictures(messages: [user("m1", "[图片] 看这张图")], records: [record("c1", ["../x"], text: "看这张图")]).isEmpty)
        #expect(picturedWords("[图片] [图片] 两张") == "两张")
        #expect(picturedWords("没有图") == nil)
    }
}
