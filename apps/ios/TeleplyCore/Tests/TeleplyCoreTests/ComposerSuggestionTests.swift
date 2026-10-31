import Foundation
import Testing
@testable import TeleplyDemo
import TeleplyModel
@testable import TeleplyState

/// 0.6.6 (user 10-31): / at the start of the box lists the source's commands, $ at a word's start its skills; a
/// command the source runs itself (Codex's and DeepSeek's /compact) never waits in the timeline; the ring and
/// 正在压缩上下文 follow the computer.
@MainActor
struct ComposerSuggestionTests {
    @Test func slashOnlyOpensTheMessageAndDollarAnyWord() {
        #expect(composerTrigger("/", cursor: 1) == ComposerTrigger(kind: .command, query: "", start: 0, end: 1))
        #expect(composerTrigger("  /com", cursor: 6) == ComposerTrigger(kind: .command, query: "com", start: 2, end: 6))
        #expect(composerTrigger("/compact", cursor: 4) == ComposerTrigger(kind: .command, query: "com", start: 0, end: 8))
        #expect(composerTrigger("看一下 /compact", cursor: 12) == nil)  // not the start of the message
        #expect(composerTrigger("/compact ", cursor: 9) == nil)          // the command is written; its words follow
        #expect(composerTrigger("路径 a/b", cursor: 6) == nil)
        #expect(composerTrigger("用 $rev", cursor: 6) == ComposerTrigger(kind: .skill, query: "rev", start: 2, end: 6))
        #expect(composerTrigger("$", cursor: 1)?.kind == .skill)
        #expect(composerTrigger("价格 5$", cursor: 5) == nil)
        #expect(composerTrigger("", cursor: 0) == nil)
        #expect(composerTrigger("/x", cursor: 9) == nil)
    }

    @Test func namesThatStartWithTheWordsComeFirst() {
        let rows: [JSONValue] = [["name": "security-review", "title": "安全审查"], ["name": "review", "title": "审查改动"],
                                 ["name": "init", "detail": "写一份 review 说明"]]
        #expect(composerMatches(rows, query: "rev").map { $0["name"].string() } == ["review", "security-review", "init"])
        #expect(composerMatches(rows, query: "REV").count == 3)
        #expect(composerMatches(rows, query: "").count == 3)
        #expect(composerMatches(rows, query: "压缩").isEmpty)
    }

    @Test func aPickedCommandFillsTheBoxAndOneThatTakesWordsLeavesASpace() {
        let typed = composerTrigger("/co", cursor: 3)!
        let compact: JSONValue = ["name": "compact", "text": "/compact", "input": ""]
        #expect(pickCommand("/co", typed, command: compact) == ("/compact", 8))
        let goal: JSONValue = ["name": "goal", "text": "/goal", "input": "[<objective>|clear]"]
        #expect(pickCommand("/go", composerTrigger("/go", cursor: 3)!, command: goal) == ("/goal ", 6))
        #expect(pickCommand("/go 写完", composerTrigger("/go 写完", cursor: 3)!, command: goal) == ("/goal 写完", 6))
    }

    @Test func aPickedSkillLeavesTheBox() {
        let typed = composerTrigger("请 $rev 看看", cursor: 6)!
        #expect(dropTrigger("请 $rev 看看", typed) == ("请 看看", 2))
        #expect(dropTrigger("$re", composerTrigger("$re", cursor: 3)!) == ("", 0))
    }

    @Test func aCommandTheSourceRanDoesNotWaitInTheTimeline() {
        let key = ChatKey(scope: "s", device: "d", app: "codex", chat: "c")
        let run = Submission(request: "r1", key: key, text: "/compact", action: "send", turn: "",
                             body: #"{"text":"/compact","_command":"/compact"}"#, label: "已送达", created: 1_800_000_000_000)
        let plain = Submission(request: "r2", key: key, text: "/compact", action: "send", turn: "", body: #"{"text":"/compact"}"#,
                               label: "已接收", created: 1_800_000_000_000)
        #expect(outboxSends([run, plain], messages: [], now: 1_800_000_030_000).map(\.request) == ["r2"])
        #expect(receiptLabel(state: "accepted", result: ["command": "/compact"], action: "send") == "已送达")
        #expect(receiptLabel(state: "accepted", result: [:], action: "send") == "已接收")
    }

    @Test func aCompactionIsReadFromTheState() throws {
        let codex = try JSONValue.parse(Data(#"{"running":true,"step":"compact","compacting":true,"compact_started":1761900000}"#.utf8))
        let control = parseControl(codex)
        #expect(control.compacting && control.compactStarted == 1761900000)
        let claude = parseControl(try JSONValue.parse(Data(#"{"running":true,"step":"compact","turn_started":1761900010}"#.utf8)))
        #expect(claude.compacting && claude.compactStarted == 0)  // the page's row takes the turn's start
        #expect(!parseControl(try JSONValue.parse(Data(#"{"running":true,"step":"run"}"#.utf8))).compacting)
    }

    @Test func anUpdateCarriesThePagesRuntime() throws {
        var reducer = StreamReducer(chat: "c1")
        _ = try reducer.accept(JSONValue.parse(Data(#"{"protocol":1,"type":"snapshot","seq":1,"app":"codex","id":"c1","chat":{"id":"c1","app":"codex","messages":[]}}"#.utf8)))
        let update = try reducer.accept(JSONValue.parse(Data("""
        {"protocol":1,"type":"update","seq":2,"app":"codex","id":"c1","messages":[],
         "meta":{"status":"idle","runtime":{"context_state":"available","percent":6.2,"used_tokens":51715,"context_window":828400}}}
        """.utf8)))
        #expect(update?.meta?["runtime"]["percent"].double() == 6.2)
        let bare = try reducer.accept(JSONValue.parse(Data(#"{"protocol":1,"type":"update","seq":3,"app":"codex","id":"c1","messages":[]}"#.utf8)))
        #expect(bare?.meta == nil)
    }

    @Test func theListsAreReadForTheConversationInUse() async throws {
        let world = DemoWorld()
        let model = AppModel(services: AppServices(store: LocalStore(folder: temporaryFolder()), vault: MemoryCookieVault(),
                                                   transport: WatchedTransport(world: world), demo: { DemoTransport(world: world) },
                                                   pacer: IdlePacer(), newScope: { "scope-1" }))
        model.start()
        await model.settle()
        model.login(name: "账号", password: "密码")
        await model.settle()
        model.openNotification(PushTarget(device: DemoData.computerA, app: "codex", chat: "demo")!)
        await model.settle()
        for _ in 0..<100 where !model.workspace.ready { try? await Task.sleep(for: .milliseconds(20)) }
        model.workspace.suggest(composerTrigger("/", cursor: 1))
        for _ in 0..<100 where model.workspace.suggestions.commands == nil { try? await Task.sleep(for: .milliseconds(20)) }
        #expect(model.workspace.suggestions.commands?.map { $0["text"].string() } == ["/compact"])
        model.workspace.suggest(composerTrigger("$固定", cursor: 3))
        for _ in 0..<100 where model.workspace.suggestions.skills == nil { try? await Task.sleep(for: .milliseconds(20)) }
        #expect(model.workspace.suggestions.skills?.first?["name"].string() == "固定引用")
        #expect(model.workspace.suggestions.skillQuery == "固定")
    }
}
