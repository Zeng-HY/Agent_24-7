import Foundation
import Testing
import TeleplyIsland

/// The island's words, times and address (handoff 5.2, 5.4), and the sample the relay's tests read too.
struct IslandTests {
    /// tests/fixtures/island-states.json, from this file's place in the repository.
    static func fixture() throws -> [String: IslandState] {
        var root = URL(fileURLWithPath: #filePath)
        for _ in 0..<6 { root.deleteLastPathComponent() }
        let data = try Data(contentsOf: root.appendingPathComponent("tests/fixtures/island-states.json"))
        return try JSONDecoder().decode([String: IslandState].self, from: data)
    }

    @Test func theSampleHasOneOfEachStateAndOnlyTheAllowedFields() throws {
        let states = try Self.fixture()
        #expect(Set(states.keys) == Set(IslandStatus.allCases.map(\.rawValue)))
        let allowed: Set<String> = ["state", "since", "turn", "ask", "askType", "choices", "askText", "askOptions", "step",
                                    "ended", "more", "resets", "peers", "working", "waiting"]
        for state in states.values {
            let encoded = try JSONEncoder().encode(state)
            let object = try #require(JSONSerialization.jsonObject(with: encoded) as? [String: Any])
            #expect(Set(object.keys).isSubset(of: allowed))
            #expect(object["state"] as? String == state.state)
            #expect(object["since"] as? Int == state.since)
        }
        #expect(states["waiting"]?.askType == "permission" && states["waiting"]?.choices == 2)
        #expect(states["limited"]?.resets == 1761636785)
        #expect(states["done"]?.turn == 1761629700)
    }

    @Test func aStateThisBuildDoesNotKnowStillDecodesAsWorking() throws {
        let data = Data(#"{"state":"brand-new","since":1,"turn":2,"future":true}"#.utf8)
        let state = try JSONDecoder().decode(IslandState.self, from: data)
        #expect(state.status == nil)
        #expect(IslandWords.state(state.status ?? .working) == "在干活")
        #expect(state.since == 1 && state.turn == 2)
    }

    @Test func eachStateSaysTheSameShortWordsAsTheNotifications() {
        #expect(IslandWords.state(.working) == "在干活")
        #expect(IslandWords.state(.waiting) == "在等你")
        #expect(IslandWords.state(.done) == "好了")
        #expect(IslandWords.state(.failed) == "出错停了")
        #expect(IslandWords.state(.offline) == "断开了")
        #expect(IslandWords.compactTrailing(IslandState(status: .waiting, since: 0, turn: 0), now: 0) == "等你")
        #expect(IslandWords.compactTrailing(IslandState(status: .offline, since: 0, turn: 0), now: 0) == "断开")
        #expect(IslandWords.symbol(.done) == "checkmark")
        #expect(IslandWords.symbol(.failed) == "exclamationmark")
        #expect(IslandWords.symbol(.working) == nil)
    }

    /// 0.6.2: the compact right side is pinned. Without a limit, `Text(timerInterval:)` asks for the widest reading it
    /// could show and stretches the island across the top of the screen (over the clock, signal and battery).
    @Test func theCompactSidesArePinnedSoTheTimerCannotStretchTheIsland() {
        #expect(IslandMetrics.compactTrailing >= 44)  // "59:59" at 13 points
        #expect(IslandMetrics.compactTrailing <= 80)  // still one compact block, not a bar
        #expect(IslandMetrics.compactTrailing >= 60)  // 0.6.3: five characters ("3个工作中")
        #expect(IslandMetrics.rowTimer >= IslandMetrics.compactTrailing - 12)
    }

    /// 0.6.3: one island for a whole computer counts its conversations; one conversation still shows its own timer.
    @Test func severalConversationsAreCountedAndOneIsStillItself() {
        let one = IslandState(status: .working, since: 1761629880, turn: 1761629880, working: 1, waiting: 0)
        #expect(IslandWords.compactCount(one) == nil)  // one conversation: the timer says it better
        #expect(IslandWords.aggregate(one) == "1 个对话工作中")
        #expect(IslandWords.only(one)?.chat == nil)  // no peers sent: nothing to name
        let busy = IslandState(status: .working, since: 1761630000, turn: 1761630000, working: 3, waiting: 0)
        #expect(IslandWords.compactCount(busy) == "3个工作中")
        #expect(IslandWords.aggregate(busy) == "3 个对话工作中")
        let mixed = IslandState(status: .waiting, since: 1761630000, turn: 1761630000, working: 2, waiting: 1)
        #expect(IslandWords.compactCount(mixed) == "1个等你定")  // waiting wins
        #expect(IslandWords.aggregate(mixed) == "2 个对话工作中 · 1 个对话等你定")
        #expect(IslandWords.compactCount(IslandState(status: .done, since: 1, turn: 1, working: 0, waiting: 0)) == nil)
        let peer = IslandPeer(app: "codex", chat: "c1", title: "改登录页", state: "working", since: 1, turn: 1)
        let single = IslandState(status: .working, since: 1, turn: 1, peers: [peer], working: 1, waiting: 0)
        #expect(IslandWords.only(single)?.chat == "c1")
        #expect(IslandWords.title(peer, computer: "我的电脑") == "改登录页")
        #expect(IslandWords.title(IslandPeer(app: "codex", chat: "c", title: "", state: "working", since: 1, turn: 1),
                                  computer: "我的电脑") == "Codex · 我的电脑")
        #expect(IslandWords.aggregate(IslandState(status: .working, since: 1, turn: 1)) == nil)  // a 0.6.2 island
    }

    @Test func whatIsBeingAskedIsSaidWithoutTheCommand() {
        let permission = IslandState(status: .waiting, since: 10, turn: 0, ask: "a1", askType: "permission", choices: 2)
        #expect(IslandWords.detail(permission, now: 20) == "想运行一条命令")
        let question = IslandState(status: .waiting, since: 10, turn: 0, ask: "a1", askType: "question", choices: 3)
        #expect(IslandWords.detail(question, now: 20) == "有 3 个选项等你选")
        let filled = IslandState(status: .waiting, since: 10, turn: 0, askText: "要在哪里建文件？", askOptions: ["这里", "那里"])
        #expect(IslandWords.detail(filled, now: 20) == "要在哪里建文件？")
    }

    @Test func howLongItTookIsSaidInMinutesAndSeconds() {
        let done = IslandState(status: .done, since: 1761630000, turn: 1761630000 - 372)
        #expect(IslandWords.detail(done, now: 1761630000) == "好了 · 用了 6 分 12 秒")
        #expect(IslandWords.duration(0) == "0 秒")
        #expect(IslandWords.duration(59) == "59 秒")
        #expect(IslandWords.duration(60) == "1 分")
        #expect(IslandWords.duration(3780) == "1 小时 3 分")
        #expect(IslandWords.duration(3600) == "1 小时")
    }

    /// 0.6.4: a finished turn stops at the record's end; the clock moving on must not make 用时 grow on the lock screen.
    @Test func howLongItTookEndsAtTheRecordsEnd() {
        let done = IslandState(status: .done, since: 1761630000, turn: 1761629700, ended: 1761630000)
        #expect(IslandWords.detail(done, now: 1761639999) == "好了 · 用了 5 分")
        let last = IslandPeer(app: "codex", chat: "c1", title: "这是一个 word 的双语文件…", state: "done",
                              since: 1761630000, turn: 1761629700, ended: 1761630000)
        let state = IslandState(status: .done, since: 1761630000, turn: 1761629700,
                                peers: [last], working: 0, waiting: 0, ended: 1761630000)
        #expect(IslandWords.finished(state)?.title == "这是一个 word 的双语文件…")
        #expect(IslandWords.cardPeer(state)?.chat == "c1")
        #expect(IslandWords.title(last, computer: "我的电脑") == "这是一个 word 的双语文件…")
    }

    /// 0.6.4 方案六: the four actions, and the live/finished words on the conversation page and list.
    @Test func theStepNamesAndTheLiveLines() {
        #expect(IslandWords.stepName("edit") == "改文件")
        #expect(IslandWords.stepName("run") == "跑命令")
        #expect(IslandWords.stepName("search") == "查资料")
        #expect(IslandWords.stepName("read") == "读文件")
        #expect(IslandWords.stepName(nil) == nil)
        #expect(IslandWords.stepSymbol("edit") == "pencil")
        #expect(IslandWords.stepSymbol("run") == "terminal")
        #expect(IslandWords.stepSymbol("search") == "magnifyingglass")
        #expect(IslandWords.stepSymbol("read") == "doc.text")
        let working = IslandState(status: .working, since: 1761629700, turn: 1761629700, step: "run")
        #expect(IslandWords.detail(working, now: 1761629700) == "跑命令")
        #expect(IslandWords.thinkingLine(step: nil, started: 1761629700, now: 1761629892) == "正在思考 · 3 分 12 秒")
        #expect(IslandWords.thinkingLine(step: "run", started: 1761629700, now: 1761629892) == "正在跑命令 · 3 分 12 秒")
        #expect(IslandWords.thoughtLine(started: 1761629700, ended: 1761629892) == "思考了 3 分 12 秒")
        #expect(IslandWords.runningLine(started: 1761629700, now: 1761629892) == "运行中 · 3 分 12 秒")
    }

    @Test func theQuotaComesBackInACountdown() {
        let limited = IslandState(status: .limited, since: 1761630000, turn: 1761629700, resets: 1761630000 + 7985)
        #expect(IslandWords.detail(limited, now: 1761630000) == "额度用完 · 2:13:05 后恢复")
        #expect(IslandWords.countdown(7985) == "2:13:05")
        #expect(IslandWords.countdown(785) == "13:05")
        #expect(IslandWords.countdown(-5) == "0:00")
        #expect(IslandWords.compactCountdown(7985) == "2:13")
    }

    @Test func theSystemIsToldWhatMattersMost() {
        let now = 1761630000
        func score(_ status: IslandStatus, turn: Int = 1761629700) -> Double {
            IslandWords.relevance(IslandState(status: status, since: now, turn: turn), now: now)
        }
        #expect(score(.waiting) == 100)
        #expect(score(.limited) == 90)
        #expect(score(.failed) == 80)
        #expect(score(.offline) == 60)
        #expect(score(.done) == 10)
        #expect(score(.working, turn: now - 100) == 58)
        #expect(score(.working, turn: now - 500) == 51)
        #expect(score(.working, turn: now - 5000) == 50)
        #expect(score(.working, turn: now - 100) > score(.working, turn: now - 500))
        #expect(score(.offline) > score(.working, turn: now - 100))
    }

    @Test func aWorkingIslandThatHeardNothingForAQuarterHourIsSaidToBeOld() {
        let now = 1761630000
        #expect(IslandWords.isStale(IslandState(status: .working, since: now - 901, turn: now - 901), now: now))
        #expect(!IslandWords.isStale(IslandState(status: .working, since: now - 900, turn: now - 900), now: now))
        #expect(!IslandWords.isStale(IslandState(status: .done, since: now - 9999, turn: now - 9999), now: now))
    }

    @Test func oneSentenceForVoiceOver() {
        let working = IslandState(status: .working, since: 1761630000 - 271, turn: 1761630000 - 271)
        #expect(IslandWords.accessibility(app: "claude", state: working, now: 1761630000) == "Claude在干活，已经 4 分 31 秒")
        let waiting = IslandState(status: .waiting, since: 1761630000, turn: 1761629700, askType: "permission")
        #expect(IslandWords.accessibility(app: "codex", state: waiting, now: 1761630000) == "Codex在等你，想运行一条命令")
    }

    @Test func tappingTheIslandOpensThatConversationAndNothingElse() throws {
        let device = String(repeating: "a", count: 32)
        let url = try #require(IslandURL.open(device: device, app: "claude", chat: "x 1"))
        #expect(url.scheme == "teleply" && url.host == "open")
        let parts = try #require(URLComponents(url: url, resolvingAgainstBaseURL: false))
        #expect(parts.queryItems == [URLQueryItem(name: "d", value: device), URLQueryItem(name: "a", value: "claude"),
                                     URLQueryItem(name: "c", value: "x 1")])
        #expect(IslandURL.list(device: device)?.absoluteString == "teleply://list?d=" + device)
    }

    @Test func theLongPressListDecodesWithModelTitleAndTime() throws {
        let data = Data(#"{"state":"working","since":1,"turn":1,"peers":[{"app":"deepseek","chat":"c1","title":"改登录页","state":"waiting","since":2,"turn":1}]}"#.utf8)
        let state = try JSONDecoder().decode(IslandState.self, from: data)
        let peer = try #require(state.peers?.first)
        #expect(peer.app == "deepseek" && peer.title == "改登录页" && peer.status == .waiting)
        #expect(peer.since == 2 && peer.turn == 1)
    }

    @Test func theRegistrationCarriesTheIdsAndTheStateOnly() throws {
        let device = String(repeating: "a", count: 32), token = String(repeating: "ab", count: 32)
        let registration = IslandRegistration(token: token, device: device, app: "claude", chat: "chat-1",
                                              environment: "production", state: "working", since: 1761629940, turn: 1761629940)
        let object = try #require(JSONSerialization.jsonObject(with: JSONEncoder().encode(registration)) as? [String: Any])
        #expect(Set(object.keys) == ["op", "token", "device", "app", "chat", "environment", "state", "since", "turn", "title", "language"])
        #expect(object["op"] as? String == "register" && object["state"] as? String == "working")
        #expect(object["title"] as? String == "" && object["language"] as? String == "zh-Hans")  // the title is optional; the app fills it when it knows it
        #expect(!object.keys.contains("message"))
    }
}
