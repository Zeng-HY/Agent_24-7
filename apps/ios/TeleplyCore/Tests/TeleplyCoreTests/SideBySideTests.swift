import Foundation
import Testing
@testable import TeleplyDemo
import TeleplyModel
@testable import TeleplyState

/// The list beside the conversation (iPad, a wide window): the list's 10 s read keeps running, and the list's own
/// actions no longer cancel the conversation's, while a phone (a narrow window) keeps one action at a time.

/// Lets time pass quickly, for the list's 10 s read: almost every wait returns after 50 ms.
struct FastPacer: Pacer {
    func wait(_ duration: Duration) async throws {
        try await Task.sleep(for: .milliseconds(50))
    }
}

/// Holds the conversation history's answer until the test lets it go.
actor HistoryGate {
    private var released = false
    private var waiters: [CheckedContinuation<Void, Never>] = []

    func wait() async {
        if released { return }
        await withCheckedContinuation { waiters.append($0) }
    }

    func release() {
        released = true
        for waiter in waiters { waiter.resume() }
        waiters.removeAll()
    }
}

/// The demo computer, with every conversation history call waiting on [gate] first.
struct GatedHistoryTransport: RelayTransport {
    let demo = DemoTransport()
    let gate = HistoryGate()

    func send(_ request: RelayRequest) async throws -> RelayResponse {
        if request.url.path.hasSuffix("/api/chat") { await gate.wait() }
        return try await demo.send(request)
    }
}

@MainActor
func makeSideBySideApp(transport: any RelayTransport, pacer: any Pacer = IdlePacer()) -> AppModel {
    AppModel(services: AppServices(store: LocalStore(folder: temporaryFolder()), vault: MemoryCookieVault(),
                                  transport: transport, demo: { DemoTransport() }, pacer: pacer, newScope: { "scope-1" }))
}

/// Signed in on 测试电脑 A, with its list read: where the two columns start.
@MainActor
func signInOnA(_ model: AppModel) async {
    model.start()
    await model.settle()
    model.login(name: "账号", password: "密码")
    await model.settle()
    if let computer = model.account?.devices.first(where: { $0.id == DemoData.computerA }) { model.select(computer) }
    await model.settle()
}

/// How many times the list has been read (`/api/chats`).
func listReads(_ transport: WatchedTransport) async -> Int {
    await transport.log.items.filter { $0.url.path.hasSuffix("/api/chats") }.count
}

/// The demo conversation with Markdown and code, which every read test opens.
@MainActor
func demoChat(_ model: AppModel) throws -> Chat {
    try #require(model.chats.first { $0.title == "原生阅读示例" } ?? model.chats.first)
}

@MainActor
struct SideBySideTests {
    @Test func theListKeepsBeingReadBesideAnOpenConversation() async throws {
        let transport = WatchedTransport()
        let model = makeSideBySideApp(transport: transport, pacer: FastPacer())
        await signInOnA(model)
        let chat = try demoChat(model)

        model.setSideBySide(true)
        model.open(chat)
        await model.settle()
        try await Task.sleep(for: .milliseconds(150))
        let quiet = await listReads(transport)
        try await Task.sleep(for: .milliseconds(300))
        let later = await listReads(transport)

        #expect(model.screen == .reading)
        #expect(model.listShown)
        #expect(later > quiet, "the list was not read beside the open conversation")
        model.setSideBySide(false)
    }

    @Test func aNarrowWindowDoesNotReadTheListBesideAConversation() async throws {
        let transport = WatchedTransport()
        let model = makeSideBySideApp(transport: transport, pacer: FastPacer())
        await signInOnA(model)
        let chat = try demoChat(model)

        model.open(chat)
        await model.settle()
        try await Task.sleep(for: .milliseconds(150))
        let quiet = await listReads(transport)
        try await Task.sleep(for: .milliseconds(300))
        let later = await listReads(transport)

        #expect(model.screen == .reading)
        #expect(!model.listShown)
        #expect(later == quiet, "a narrow window read the list while a conversation was open")
    }

    @Test func aSearchOnTheLeftDoesNotCancelTheConversationOnTheRight() async throws {
        let transport = GatedHistoryTransport()
        let model = makeSideBySideApp(transport: transport)
        await signInOnA(model)
        let chat = try demoChat(model)

        model.setSideBySide(true)
        model.open(chat)
        // The conversation's read is at the computer, waiting; the list is searched meanwhile, as on the left.
        try await Task.sleep(for: .milliseconds(300))
        model.searchChats("原生")
        try await Task.sleep(for: .milliseconds(300))
        await transport.gate.release()
        await model.settle()

        #expect(model.messages.isEmpty == false, "the list's search cancelled the conversation's read")
        #expect(model.query == "原生")
        #expect(model.error == nil)
        #expect(model.listError == nil)
        #expect(model.screen == .reading)
        model.setSideBySide(false)
    }

    @Test func aNarrowWindowsSearchStillCancelsTheConversationRead() async throws {
        let transport = GatedHistoryTransport()
        let model = makeSideBySideApp(transport: transport)
        await signInOnA(model)
        let chat = try demoChat(model)

        model.open(chat)
        try await Task.sleep(for: .milliseconds(300))
        model.searchChats("原生")
        try await Task.sleep(for: .milliseconds(300))
        await transport.gate.release()
        await model.settle()

        #expect(model.messages.isEmpty, "a narrow window no longer cancels the conversation's read")
        #expect(model.query == "原生")
    }

    @Test func twoColumnsAreOnlyTheWideWindowsChoice() async throws {
        let model = makeApp()
        await signInOnA(model)
        #expect(!model.sideBySide)
        model.setSideBySide(false)
        #expect(!model.sideBySide)
        model.setSideBySide(true)
        #expect(model.sideBySide)
        model.setSideBySide(false)
        #expect(!model.sideBySide)
    }
}
