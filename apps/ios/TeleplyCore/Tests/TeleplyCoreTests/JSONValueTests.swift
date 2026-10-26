import Foundation
import Testing
@testable import TeleplyModel

struct JSONValueTests {
    @Test func readsMissingAndNullAsDefaults() throws {
        let json = try JSONValue.parse(Data(#"{"a":true,"n":1,"f":1.5,"s":"x","z":null,"list":[1,"2"],"t":"TRUE"}"#.utf8))
        #expect(json["a"].bool())
        #expect(json["n"].bool() == false)
        #expect(json["n"].int() == 1)
        #expect(json["n"].string() == "1")
        #expect(json["f"].string() == "1.5")
        #expect(json["f"].int() == 1)
        #expect(json["s"].string() == "x")
        #expect(json["z"].string(or: "默认") == "默认")
        #expect(json["missing"].string() == "")
        #expect(json["missing"]["deeper"].int(or: 7) == 7)
        #expect(json["list"].array.count == 2)
        #expect(json["list"][1].int() == 2)
        #expect(json["list"][5].isNull)
        #expect(json["t"].bool())
        #expect(json.has("a"))
        #expect(!json.has("z"))
    }

    @Test func writesWholeNumbersAsIntegers() throws {
        let body: JSONValue = ["answer_revision": 3, "ratio": 0.5, "ok": true, "text": "中文"]
        #expect(try JSONValue.parse(body.encoded()) == body)
        #expect(String(decoding: try JSONValue.number(3).encoded(), as: UTF8.self) == "3")
    }

    @Test func keepsMillisecondTimes() throws {
        let json = try JSONValue.parse(Data(#"{"updated":1792843200000}"#.utf8))
        #expect(json["updated"].int64() == 1_792_843_200_000)
        #expect(json["updated"].string() == "1792843200000")
    }
}
