import Foundation
import Testing
@testable import TeleplyDemo
import TeleplyModel
@testable import TeleplyState

/// Opens once; everything waiting on it goes on then (Android CompletableDeferred).
actor Gate {
    private var opened = false
    private var waiting: [CheckedContinuation<Void, Never>] = []

    func wait() async {
        if opened { return }
        await withCheckedContinuation { waiting.append($0) }
    }

    func open() {
        opened = true
        for continuation in waiting { continuation.resume() }
        waiting = []
    }
}

actor Counts {
    private(set) var sends = 0
    private(set) var receipts = 0
    private(set) var reads: [Bool] = []

    func send() { sends += 1 }
    func receipt() { receipts += 1 }
    func read(fresh: Bool) { reads.append(fresh) }
}

/// A computer whose source is running, whose sends wait for [gate] and then are accepted (or time out), whose
/// receipts know nothing, and whose live stream stays open (Android ChatControllerTest CommandApi).
final class CommandComputer: RelayStreamingTransport, @unchecked Sendable {
    struct Timeout: Error {}

    let gate = Gate()
    let counts = Counts()
    let unknown: Bool
    let running: Bool
    private let streams = Mutexed<[AsyncThrowingStream<[UInt8], any Error>.Continuation]>([])

    init(unknown: Bool = false, running: Bool = true) {
        self.unknown = unknown
        self.running = running
    }

    func send(_ request: RelayRequest) async throws -> RelayResponse {
        let path = request.url.path
        if path.hasSuffix("/state") {
            let fresh = URLComponents(url: request.url, resolvingAgainstBaseURL: false)?.queryItems?.contains { $0.name == "fresh" } ?? false
            await counts.read(fresh: fresh)
            return .json(#"{"available":true,"running":\#(running),"active_turn_id":"turn","queue_available":true}"#)
        }
        if path.hasSuffix("/send") {
            await counts.send()
            await gate.wait()
            if unknown { throw Timeout() }
            let body = (try? JSONValue.parse(request.body ?? Data())) ?? [:]
            return .json(#"{"request_id":"\#(body["request_id"].string())","delivery_state":"accepted"}"#)
        }
        if path.hasSuffix("/receipt") {
            await counts.receipt()
            return .json(#"{"state":"unknown"}"#)
        }
        return RelayResponse(status: 404)
    }

    func stream(_ request: RelayRequest) async throws -> RelayStream {
        let (chunks, continuation) = AsyncThrowingStream<[UInt8], any Error>.makeStream()
        streams.withLock { $0.append(continuation) }
        return RelayStream(status: 200, chunks: chunks)
    }
}

/// A lock around a value, for the test transport (Synchronization's Mutex needs a newer macOS than tests run on).
final class Mutexed<Value>: @unchecked Sendable {
    private let lock = NSLock()
    private var value: Value

    init(_ value: Value) {
        self.value = value
    }

    func withLock<T>(_ body: (inout Value) -> T) -> T {
        lock.lock()
        defer { lock.unlock() }
        return body(&value)
    }
}

/// Lets the first [free] waits pass at once and keeps the rest waiting; remembers how long each was asked for.
final class CountingPacer: Pacer, @unchecked Sendable {
    let free: Int
    private let asked = Mutexed<[Duration]>([])

    init(free: Int) {
        self.free = free
    }

    var waits: [Duration] { asked.withLock { $0 } }

    func wait(_ duration: Duration) async throws {
        let count = asked.withLock { asked -> Int in
            asked.append(duration)
            return asked.count
        }
        if count > free { try await Task.sleep(for: .seconds(3_600)) }
    }
}

@MainActor
struct ChatModelTests {
    let key = ChatKey(scope: "account", device: String(repeating: "a", count: 32), app: "codex", chat: "chat")

    func chat(_ computer: CommandComputer, store: LocalStore, pacer: any Pacer = IdlePacer()) -> ChatModel {
        let ids = Mutexed(0)
        return ChatModel(pacer: pacer, store: store, newID: { ids.withLock { $0 += 1; return "request-\($0)" } }, now: { 1_000 })
    }

    func bind(_ model: ChatModel, _ computer: CommandComputer, _ key: ChatKey, active: Bool = true) {
        model.bind(key, client: RelayClient(origin: .default, transport: computer), clientGeneration: 0, active: active, synthetic: false) { _, _ in }
    }

    /// Lets the model's tasks run until [done] holds (or gives up after a while).
    func until(_ done: () async -> Bool) async {
        for _ in 0..<2_000 {
            if await done() { return }
            await Task.yield()
        }
    }

    @Test func aDoubleTapSendsOnceAndALateReceiptKeepsTheNewDraft() async {
        let store = LocalStore(folder: temporaryFolder())
        let computer = CommandComputer()
        let model = chat(computer, store: store)
        bind(model, computer, key)
        await until { model.ready && model.control.available }
        model.edit("first")
        model.send()
        model.send()
        await until { await computer.counts.sends == 1 }
        #expect(await store.submissions(key).map(\.text) == ["first"])
        model.edit("new draft")
        await computer.gate.open()
        await model.settleSends()
        await model.flushDraft()
        #expect(await computer.counts.sends == 1)
        #expect(model.draft == "new draft")
        #expect(await store.draft(key) == "new draft")
        #expect(model.submissions.map(\.label) == ["已接收"])
    }

    @Test func aTimedOutSendIsOnlyCheckedAfterARestartAndKeepsItsCopy() async {
        let store = LocalStore(folder: temporaryFolder())
        let computer = CommandComputer(unknown: true)
        await computer.gate.open()
        let model = chat(computer, store: store)
        bind(model, computer, key)
        await until { model.ready && model.control.available }
        model.edit("snapshot")
        model.send()
        await model.settleSends()
        #expect(model.submissions.map(\.label) == ["送达状态待确认"])
        let recovered = chat(computer, store: store)
        bind(recovered, computer, key)
        await until { await computer.counts.receipts > 0 }
        #expect(await computer.counts.sends == 1)
        #expect(recovered.submissions.map(\.text) == ["snapshot"])
        #expect(recovered.draft == "")
    }

    @Test func switchingIdentityKeepsALateReceiptAndTheDraftApart() async {
        let store = LocalStore(folder: temporaryFolder())
        let computer = CommandComputer()
        let model = chat(computer, store: store)
        bind(model, computer, key)
        await until { model.ready && model.control.available }
        model.edit("private")
        model.send()
        await until { await computer.counts.sends == 1 }
        var other = key
        other.scope = "another"
        bind(model, computer, other)
        await until { model.ready }
        await computer.gate.open()
        await model.settleSends()
        #expect(model.draft == "")
        #expect(model.submissions.isEmpty)
        #expect(await store.submissions(key).map(\.label) == ["已接收"])
        #expect(await store.submissions(other).isEmpty)
    }

    @Test func inTheBackgroundNothingIsSentAndTheDraftIsKept() async {
        let store = LocalStore(folder: temporaryFolder())
        let computer = CommandComputer()
        let model = chat(computer, store: store)
        bind(model, computer, key)
        await until { model.ready && model.control.available }
        model.edit("中文草稿")
        bind(model, computer, key, active: false)
        await model.flushDraft()
        model.send()
        await model.settleSends()
        #expect(await computer.counts.sends == 0)
        let recovered = chat(computer, store: store)
        bind(recovered, computer, key)
        await until { recovered.ready }
        #expect(recovered.draft == "中文草稿")
    }

    @Test func claudePollsEveryFiveSecondsWithoutFreshReads() async {
        var claude = key
        claude.app = "claude"
        let computer = CommandComputer(running: false)
        let pacer = CountingPacer(free: 2)
        let model = chat(computer, store: LocalStore(folder: temporaryFolder()), pacer: pacer)
        bind(model, computer, claude)
        await until { await computer.counts.reads.count == 3 }
        #expect(await computer.counts.reads == [true, false, false])
        #expect(pacer.waits.prefix(2) == [.seconds(5), .seconds(5)])
    }

    @Test func noPollWhileATapWaitsOnTheComputer() async {
        var claude = key
        claude.app = "claude"
        let computer = CommandComputer(running: false)
        let pacer = CountingPacer(free: 2)
        let model = chat(computer, store: LocalStore(folder: temporaryFolder()), pacer: pacer)
        model.pollPaused = { true }
        bind(model, computer, claude)
        await until { pacer.waits.count == 3 }
        #expect(await computer.counts.reads == [true])
    }

    @Test func deepseekPollsEveryTwoAndAHalfSeconds() async {
        var deepseek = key
        deepseek.app = "deepseek"
        let computer = CommandComputer(running: false)
        let pacer = CountingPacer(free: 2)
        let model = chat(computer, store: LocalStore(folder: temporaryFolder()), pacer: pacer)
        bind(model, computer, deepseek)
        await until { await computer.counts.reads.count == 3 }
        #expect(await computer.counts.reads == [true, false, false])
        #expect(pacer.waits.prefix(2) == [.milliseconds(2_500), .milliseconds(2_500)])
    }
}

/// Sending on the local demo, through the whole app (Android ReaderUiScenarios sending cases).
@MainActor
struct SendingTests {
    func demoConversation(_ title: String) async -> AppModel {
        let model = makeApp()
        model.openDemo()
        model.login(name: "x", password: "y")
        await model.settle()
        model.select(model.account!.devices[0])
        await model.settle()
        model.open(model.chats.first { $0.title == title }!)
        await model.settle()
        await model.conversation.settle()
        await model.workspace.settle()
        return model
    }

    @Test func codexSendsQueuesWhileRunningAndHandsTheQueuedOneOver() async {
        let model = await demoConversation("原生阅读示例")
        let chat = model.conversation
        #expect(chat.ready && chat.control.available && !chat.control.running)
        chat.edit("第一条")
        chat.send()
        await chat.settle()
        #expect(chat.submissions.first?.label == "已接收" && chat.draft == "")
        #expect(chat.control.running && chat.acknowledged == 1)
        chat.edit("排队的一条")
        chat.send(queue: true)
        await chat.settle()
        #expect(chat.submissions.first?.label == "已排队")
        let queued = chat.control.queued.first
        #expect(queued?.text == "排队的一条")
        chat.promote(queued!.id)
        await chat.settle()
        #expect(chat.control.queued.isEmpty)
        chat.stop()
        await chat.settle()
        #expect(chat.submissions.first?.label == "停止请求已接收，等待轮次确认")
        #expect(!chat.control.running)
    }

    @Test func claudeIsCheckedInItsRecordAfterEnter() async {
        let model = await demoConversation("Claude 选项示例")
        let chat = model.conversation
        chat.edit("你好")
        chat.send()
        await chat.settle()
        for _ in 0..<500 where chat.submissions.first?.label != "已送达" { await Task.yield() }
        #expect(chat.submissions.first?.label == "已送达")
        #expect(chat.submissions.first?.text == "你好")
    }

    @Test func aClaudeBoxHoldingOtherTextTurnsTheSendAwayUntilReplaced() async {
        let model = await demoConversation("Claude 选项示例")
        let chat = model.conversation
        chat.edit("draft")
        chat.send()
        await chat.settle()
        let refused = chat.submissions.first!
        #expect(refused.label == "未接收")
        #expect(jsonValue(refused.body)[SendNote.desktopDraft].string() == "e")
        chat.resendReplacing(refused)
        await chat.settle()
        // Claude's record is looked at right after Enter, so it may already say 已送达.
        #expect(["已接收", "已送达"].contains(chat.submissions.first?.label ?? ""))
        #expect(jsonValue(chat.submissions.first!.body)["replace_draft"].string() == "e")
        #expect(chat.submissions.contains { $0.request == refused.request && $0.label == removedLabel })
    }

    @Test func codexSettingsBindToTheNextMessageOnly() async {
        let model = await demoConversation("原生阅读示例")
        let current = model.conversation.control.raw["settings"]
        var chosen = current.object
        chosen["effort"] = "low"
        model.workspace.selectSettings(.object(chosen), expected: current)
        await model.workspace.settle()
        #expect(model.workspace.result == "设置已绑定下一条消息，尚未发送")
        model.conversation.edit("用低强度")
        model.conversation.send()
        await model.conversation.settle()
        await model.workspace.settle()
        let body = jsonValue(model.conversation.submissions.first!.body)
        #expect(body["settings"]["effort"].string() == "low")
        #expect(body["expected_settings"]["effort"].string() == "medium")
        #expect(model.workspace.boundSettings().object.isEmpty)
    }

    @Test func claudeListsShowAsKeptAndOnlyRefreshReadsTheDesktop() async {
        let model = await demoConversation("Claude 选项示例")
        let workspace = model.workspace
        workspace.loadChoices(model: "opus")
        await workspace.settle()
        #expect(workspace.choices["source_catalog"]["model"].array.count == 2)
        workspace.loadChoices(model: "opus")
        await workspace.settle()
        #expect(workspace.choices["source_catalog"]["cached"].bool())
        workspace.claudeSetting(kind: "model", name: "Sonnet 4.6", value: true, expected: "opus")
        await workspace.settle()
        #expect(model.conversation.control.raw["model_label"].string() == "Sonnet 4.6")
        #expect(workspace.result == "本地示例：已在电脑上换好")
        #expect(workspace.choices["source_catalog"]["model"].array.first { $0["selected"].bool() }?["name"].string() == "Sonnet 4.6")
        workspace.loadChoices(fresh: true, model: "sonnet")
        await workspace.settle()
        #expect(!workspace.choicesBusy && workspace.choicesError == nil)
    }

    @Test func aDeepSeekPermissionIsPostedAndRecordedAsDone() async {
        let model = await demoConversation("DeepSeek 批准示例")
        model.workspace.action("deepseek/permission", ["preset": "read", "confirmed": false])
        await model.workspace.settle()
        for _ in 0..<500 where model.conversation.control.raw["permission"].string() != "read" { await Task.yield() }
        #expect(model.workspace.result == "本地示例：设置已记录")
        #expect(model.workspace.saved["pending_action"]["status"].string() == "done")
        #expect(model.conversation.control.raw["permission"].string() == "read")
    }
}
