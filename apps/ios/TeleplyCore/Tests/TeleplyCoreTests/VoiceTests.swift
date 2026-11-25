import Foundation
import Testing
@testable import TeleplyDemo
import TeleplyModel
@testable import TeleplyState

/// Where voice's words go and how audio is packed (Android Voice.kt placeDictation, pcmBytes, wavBytes).
struct VoiceTextTests {
    @Test func wordsGoWhereTheCursorWasWithTheRightGap() {
        #expect(placeDictation("", "你好", start: 0).draft == "你好")
        #expect(placeDictation("先说", "后说", start: 2).draft == "先说后说")
        #expect(placeDictation("hello", "world", start: 5).draft == "hello world")
        #expect(placeDictation("ab", "第一行\n第二行", start: 2).draft == "ab\n第一行\n第二行")
        let replaced = placeDictation("一二三四", "X", start: 1, end: 3)
        #expect(replaced.draft == "一X四")
        #expect(replaced.at == 1)
        #expect(placeDictation("abc", "d", start: 99).draft == "abc d")
    }

    @Test func tidyingSwapsOnlyWordsStillThereAsTheyWere() throws {
        let placed = placeDictation("开头", "好的帮我", start: 2)
        let tidied = try #require(swapDictation(placed.draft, placed, with: "好的，帮我。"))
        #expect(tidied.draft == "开头好的，帮我。")
        #expect(swapDictation("开头改了别的", placed, with: "x") == nil)
        let undone = try #require(swapDictation(tidied.draft, tidied, with: placed.raw))
        #expect(undone.draft == placed.draft)
    }

    @Test func audioIsLittleEndianPCMInAWaveFile() {
        #expect(pcmBytes([1, -2]) == Data([0x01, 0x00, 0xFE, 0xFF]))
        let wave = wavBytes([0, 0, 0])
        #expect(wave.count == 44 + 6)
        #expect(String(decoding: wave.prefix(4), as: UTF8.self) == "RIFF")
        #expect(wave[24] == 0x80 && wave[25] == 0x3E)
        #expect(voiceLevel([Int16](repeating: 0, count: 64)) == 0)
        #expect(voiceLevel([Int16](repeating: 20_000, count: 64)) > 0.9)
    }
}

/// iOS's own recogniser starts afresh after a pause, and its answers then hold only the new words (Apple developer
/// forums 731761, 762952): what was said before the pause stays (11-24, on an iPad).
struct HeardStretchesTests {
    func hear(_ answers: String...) -> HeardStretches {
        var heard = HeardStretches()
        for answer in answers { heard.take(answer) }
        return heard
    }

    @Test func wordsBeforeAPauseStayWhenTheRecogniserStartsAfresh() {
        var heard = HeardStretches()
        for answer in ["今", "今天", "今天天气", "今天天气很好"] { heard.take(answer) }
        heard.take("今天天气很好", closes: true)  // the stretch's last answer carries metadata
        for answer in ["我", "我们去", "我们去公园"] { heard.take(answer) }
        #expect(heard.text == "今天天气很好我们去公园")
        // shown as the settled words, then the open stretch in grey
        #expect(heard.settled == "今天天气很好")
        #expect(String(heard.text.dropFirst(heard.settled.count)) == "我们去公园")
        // after ✓ the final answer holds the last stretch only, or no words at all
        heard.take("我们去公园。", closes: true)
        heard.take("")
        #expect(heard.text == "今天天气很好我们去公园。")
    }

    @Test func aFreshStartIsSeenWithoutTheClosingMarkToo() {
        // the words fall back to the first of the new ones (a log on the forum: 105 segments, then 1)
        #expect(hear("今天天气很好", "我", "我们去公园").text == "今天天气很好我们去公园")
        // an answer with no words in between
        #expect(hear("好的", "", "那我们走吧").text == "好的那我们走吧")
        // the new words start after the open stretch ended
        var heard = HeardStretches()
        heard.take("好的", start: 0.4, end: 0.9)
        heard.take("那我们走吧", start: 3.1, end: 4.2)
        #expect(heard.text == "好的那我们走吧")
    }

    @Test func aNewStretchMayStartWithTheSameWords() {
        var heard = HeardStretches()
        heard.take("我们走吧")
        heard.take("我们走吧", closes: true)
        heard.take("我们")
        heard.take("我们明天再说")
        #expect(heard.text == "我们走吧我们明天再说")
        #expect(heard.earlier == ["我们走吧"])
    }

    @Test func revisionsReplaceOnlyTheirOwnStretch() {
        #expect(hear("是的", "实际上", "实际上我们").text == "实际上我们")
        #expect(hear("今天天气很好", "今天天气真好我们").text == "今天天气真好我们")
        #expect(hear("一二三", "123").text == "123")
        // a recogniser that keeps everything, closing marks and all, is not written twice
        var heard = HeardStretches()
        heard.take("今天天气很好")
        heard.take("今天天气很好。", closes: true)
        heard.take("今天天气很好。我们")
        heard.take("今天天气很好。我们去公园。", closes: true)
        #expect(heard.text == "今天天气很好。我们去公园。")
        #expect(heard.earlier.isEmpty)
    }

    @Test func wordsHeardAgainAreTakenBackNotDoubled() {
        // all of it once more in the final answer
        var heard = HeardStretches()
        heard.take("今天天气很好")
        heard.take("今天天气很好", closes: true)
        heard.take("我们去公园")
        heard.take("今天天气很好。我们去公园。", closes: true)
        #expect(heard.text == "今天天气很好。我们去公园。")
        // a revision first taken for new words
        #expect(hear("我们走吧", "我们", "我们走吧好").text == "我们走吧好")
        // answers without words change nothing
        #expect(hear("今天天气很好", "。", " ").text == "今天天气很好")
    }

    @Test func stretchesJoinLikeTheComputersRecogniser() {
        var heard = HeardStretches()
        heard.take("hello there")
        heard.take("Hello there.", closes: true)
        heard.take("How")
        heard.take("How are you")
        #expect(heard.text == "Hello there. How are you")
        #expect(joinStretches(["v1.2", "ok", "好的", "OK", " ", "了"]) == "v1.2 ok好的OK了")
    }
}

/// Voice and notifications through the demo computer (Android ReaderUiScenarios voice and ntfy cases, Bark here).
@MainActor
struct VoiceAndNotifyTests {
    func demoConversation() async -> AppModel {
        let model = makeApp()
        model.openDemo()
        model.login(name: "x", password: "y")
        await model.settle()
        model.select(model.account!.devices[0])
        await model.settle()
        model.open(model.chats.first { $0.title == "原生阅读示例" }!)
        await model.settle()
        await model.conversation.settle()
        return model
    }

    @Test func theComputersRecogniserHearsPiecesThenTheSentenceAndTidies() async throws {
        let model = await demoConversation()
        #expect(await model.voiceAvailable())
        let start = try await model.voiceCall("voice/stream/start", query: [("tidy", "1")])
        let sid = start["sid"].string()
        #expect(!sid.isEmpty)
        let piece = try await model.voiceCall("voice/stream/chunk", query: [("sid", sid)], audio: pcmBytes([Int16](repeating: 0, count: 4_000)))
        #expect(piece["final"].string() == "好的")
        let text = try await model.voiceCall("voice/stream/end", query: [("sid", sid)])["text"].string()
        let key = try #require(model.conversation.key)
        model.conversation.edit("请")
        let placed = try #require(model.conversation.insertVoice(key, text, start: 1))
        #expect(model.conversation.draft == "请好的帮我把发布说明里的升级步骤补上")
        let tidy = try await model.deviceCall("voice/tidy", body: ["text": .string(placed.raw)])["text"].string()
        _ = model.conversation.swapVoice(key, placed, with: tidy)
        #expect(model.conversation.draft == "请好的，帮我把发布说明里的升级步骤补上。")
        var other = key
        other.chat = "another"
        #expect(model.conversation.insertVoice(other, "x", start: 0) == nil)
    }

    @Test func barkIsSavedTriedAndTurnedOff() async throws {
        let model = await demoConversation()
        #expect(try await model.deviceCall("notify")["configured"].bool() == false)
        let saved = try await model.deviceCall("notify", body: ["address": "https://api.day.app/fixture/"])
        #expect(saved["text"].string() == "本地示例：已保存，刚推了一条")
        let state = try await model.deviceCall("notify")
        #expect(state["configured"].bool() && state["server"].string() == "api.day.app")
        #expect(try await model.deviceCall("notify/test", body: ["channel": "bark"])["text"].string() == "本地示例：刚推了一条，看看手机")
        #expect(try await model.deviceCall("notify")["recent"].array.count == 2)
        _ = try await model.deviceCall("notify", body: ["address": ""])
        #expect(try await model.deviceCall("notify")["configured"].bool() == false)
    }

    @Test func theVoiceDictionaryIsKeptOnTheComputer() async throws {
        let model = await demoConversation()
        #expect(try await model.deviceCall("voice/terms")["count"].int64() == 3)
        let saved = try await model.deviceCall("voice/terms", body: ["text": "遥应\n中转"])
        #expect(saved["count"].int64() == 2)
        #expect(try await model.deviceCall("voice/terms")["text"].string() == "遥应\n中转")
    }
}
