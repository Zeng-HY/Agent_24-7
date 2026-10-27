import Foundation
import Synchronization
import Testing
@testable import TeleplyDemo
import TeleplyModel
@testable import TeleplyState

/// A clock the test moves by hand (milliseconds).
final class TestClock: Sendable {
    private let value = Mutex<Int64>(1_792_843_200_000)

    var now: Int64 { value.withLock { $0 } }

    func advance(_ milliseconds: Int64) {
        value.withLock { $0 += milliseconds }
    }
}

/// The demo computer with Claude's desktop clicks whose replies never come back, as a dropped connection does: the
/// click either landed on the computer first ([lands]) or never got there.
struct LostChoiceTransport: RelayFileTransport {
    struct Dropped: Error {}

    let demo: DemoTransport
    let lands: Bool

    func send(_ request: RelayRequest) async throws -> RelayResponse {
        guard request.url.path.hasSuffix("/api/claude/choose") else { return try await demo.send(request) }
        if lands { _ = try await demo.send(request) }
        throw Dropped()
    }

    func download(_ request: RelayRequest, limit: Int64, progress: (@Sendable (Int64, Int64) -> Void)?) async throws -> RelayDownload {
        try await demo.download(request, limit: limit, progress: progress)
    }
}

/// 「上次操作的结果还没确认」 for Claude (user 10-27: it never went away). A desktop option goes as a token the computer takes
/// for two minutes only, and Claude keeps no receipt: 核对上次操作 settles it from what Claude shows now, and a state
/// read after two minutes settles it with no tap. Nothing is ever sent again.
@MainActor
struct PendingChoiceTests {
    let clock = TestClock()

    func conversation(_ title: String, world: DemoWorld = DemoWorld(), lands: Bool = false) async -> AppModel {
        let clock = clock
        let model = AppModel(services: AppServices(store: LocalStore(folder: temporaryFolder()), vault: MemoryCookieVault(), transport: DemoTransport(),
                                                   demo: { LostChoiceTransport(demo: DemoTransport(world: world), lands: lands) }, pacer: IdlePacer(),
                                                   newScope: { "scope-1" }, now: { clock.now }))
        model.openDemo()
        model.login(name: "x", password: "y")
        await model.settle()
        model.select(model.account!.devices[0])
        await model.settle()
        model.open(model.chats.first { $0.title == title }!)
        await model.settle()
        await until(model)
        return model
    }

    func until(_ model: AppModel) async {
        await model.workspace.settle()
        await model.conversation.settle()
        await model.workspace.settle()
    }

    /// 上次操作的结果还没确认 shows.
    func unknown(_ model: AppModel) -> Bool {
        model.workspace.saved["pending_action"]["status"].string() == "unknown"
    }

    @Test func aLostChoiceKeepsItsTimeAndTheCheckSaysClaudeStillWaits() async {
        let model = await conversation("Claude 选项示例")
        model.workspace.action("claude/choose", ["token": "t-choice-1"])
        await until(model)
        #expect(unknown(model))
        #expect(model.workspace.saved["pending_action"]["at"].int64() == clock.now)
        #expect(model.workspace.error != nil)
        model.workspace.checkAction()
        await until(model)
        #expect(model.workspace.saved["pending_action"]["status"].string() == "done")
        #expect(model.workspace.result == "电脑上的 Claude 还在等你选；上次那一下可能没送到，请再选一次。")
        #expect(model.workspace.error == nil)
        // The question is still on the page, to be chosen again with the computer's fresh tokens.
        #expect(pendingCards(app: "claude", raw: model.conversation.control.raw).first?.kind == "choice")
    }

    @Test func theCheckSaysSoWhenClaudeNoLongerWaits() async {
        let world = DemoWorld()
        let model = await conversation("Claude 选项示例", world: world, lands: true)
        model.workspace.action("claude/choose", ["token": "t-choice-1"])
        await until(model)
        #expect(unknown(model))
        // Meanwhile the question was answered on the computer.
        world.state.withLock { $0.claudeStep = 2 }
        model.workspace.checkAction()
        await until(model)
        #expect(model.workspace.saved["pending_action"]["status"].string() == "done")
        #expect(model.workspace.result == "电脑上已经没有在等的选项，上次的选择已处理。")
        #expect(pendingCards(app: "claude", raw: model.conversation.control.raw).isEmpty)
    }

    @Test func aStateReadAfterTwoMinutesSettlesItWithNoTap() async {
        let model = await conversation("Claude 选项示例")
        model.workspace.action("claude/choose", ["token": "t-choice-1"])
        await until(model)
        // Within two minutes the press may still be on its way: it stays, to be checked.
        clock.advance(119_000)
        model.conversation.refreshControl()
        await until(model)
        #expect(unknown(model))
        clock.advance(2_000)
        model.conversation.refreshControl()
        await until(model)
        #expect(model.workspace.saved["pending_action"]["status"].string() == "done")
        #expect(model.workspace.result.isEmpty)
        // The next press starts afresh and keeps the settled one in the history.
        model.workspace.action("claude/choose", ["token": "t-choice-2"])
        await until(model)
        #expect(model.workspace.saved["action_history"].array.last?["status"].string() == "done")
    }

    /// One kept by a build before 10-27 has no time: the next state read settles it.
    @Test func anOldUnconfirmedChoiceWithoutATimeGoesAtTheNextStateRead() async {
        let model = await conversation("Claude 选项示例")
        model.workspace.edit("pending_action", ["route": "claude/choose", "body": ["token": "t-old", "id": "claude-demo"], "status": "unknown"])
        #expect(unknown(model))
        model.conversation.refreshControl()
        await until(model)
        #expect(model.workspace.saved["pending_action"]["status"].string() == "done")
        #expect(model.workspace.saved["pending_action"]["body"]["token"].string() == "t-old")
    }

    /// Codex's answers keep waiting for 核对上次操作, which reads their receipt.
    @Test func otherSourcesWaitForTheCheckAsBefore() async {
        let model = await conversation("只读问题记录")
        model.workspace.edit("pending_action", ["route": "codex/answer", "body": ["question_id": "q", "request_id": "r-lost"], "status": "unknown"])
        clock.advance(600_000)
        model.conversation.refreshControl()
        await until(model)
        #expect(unknown(model))
    }
}
