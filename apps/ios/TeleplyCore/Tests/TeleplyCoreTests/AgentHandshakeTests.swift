import Foundation
import Testing
@testable import TeleplyDemo
import TeleplyModel
@testable import TeleplyState

/// The demo computer as an older one: no `/api/agents` at all (404), everything else as the demo answers.
struct LegacyAgentsTransport: RelayTransport {
    let demo = DemoTransport()

    func send(_ request: RelayRequest) async throws -> RelayResponse {
        if request.url.path.hasSuffix("/api/agents") { return .json(#"{"error":"没有这个地址"}"#, status: 404) }
        return try await demo.send(request)
    }
}

/// The demo computer with its manifest list out of reach: the call fails, so nothing new is kept.
struct NoAgentsTransport: RelayTransport {
    struct Unreachable: Error {}
    let demo = DemoTransport()

    func send(_ request: RelayRequest) async throws -> RelayResponse {
        if request.url.path.hasSuffix("/api/agents") { throw Unreachable() }
        return try await demo.send(request)
    }
}

/// The protocol 2 handshake (handoff 3.1) and the catalog reaching the model (3.2, 3.3).
@MainActor
struct AgentHandshakeTests {
    let a = String(repeating: "a", count: 32)
    let device = String(repeating: "a", count: 32)

    func makeModel(_ transport: any RelayTransport) -> AppModel {
        AppModel(services: AppServices(store: LocalStore(folder: temporaryFolder()), vault: MemoryCookieVault(),
                                       transport: transport, demo: { DemoTransport() }, pacer: IdlePacer(),
                                       newScope: { "scope-1" }))
    }

    func enterA(_ model: AppModel) async {
        model.start()
        await model.settle()
        model.login(name: "账号", password: "密码")
        await model.settle()
        if let computer = model.account?.devices.first(where: { $0.id == a }) { model.select(computer) }
        await model.settle()
    }

    @Test func everyRequestCarriesProtocolTwoAndTheAppTag() async throws {
        TeleplyClient.version = "0.9.0"
        defer { TeleplyClient.version = "" }
        let watched = WatchedTransport(world: DemoWorld())
        let client = RelayClient(origin: .default, transport: watched, vault: MemoryCookieVault())
        try await client.login(name: "x", password: "y")
        _ = try await client.chatList(device: device, app: "all")
        _ = try await client.agents(device: device)
        try await client.pushRegister(token: String(repeating: "f", count: 64), environment: "production",
                                      label: "iPhone", version: "0.9.0")
        _ = try await client.upload(device: device, app: "codex", chat: "demo", draft: false, name: "a.png",
                                    file: URL(fileURLWithPath: "/tmp/teleply-test.png"), size: 3, image: true)
        _ = try await client.download(device: device, app: "codex", chat: "demo", file: "fixture-png")

        let sent = await watched.log.items
        #expect(sent.count >= 6)
        for request in sent {
            #expect(request.headers["X-Teleply-Protocol"] == "2")
            #expect(request.headers["X-Teleply-Client"] == "ios/0.9.0")
        }
        // The push registration tells the relay which assistants this phone can show (docs §九).
        let register = try #require(sent.last { $0.url.path == "/account/push/register" })
        let body = try JSONValue.parse(register.body ?? Data())
        #expect(body["protocol"].string() == "2")
        #expect(body["platform"].string() == "ios")
    }

    @Test func theLiveStreamAlsoSaysProtocolTwo() async throws {
        let snapshot = "event: update\ndata: {\"protocol\":1,\"seq\":1,\"type\":\"snapshot\",\"app\":\"codex\",\"id\":\"chat\",\"chat\":{\"app\":\"codex\",\"id\":\"chat\",\"messages\":[]}}\n\n"
        let transport = StreamingTransport(status: 200, chunks: [Array(snapshot.utf8)])
        do {
            for try await _ in try RelayClient(origin: .default, transport: transport).events(device: device, app: "codex", chat: "chat") {}
        } catch {}
        let request = await transport.log.items.first
        #expect(request?.headers["X-Teleply-Protocol"] == "2")
        #expect(request?.url.absoluteString.contains("protocol=2") == true)
    }

    @Test func anUnknownAssistantsRowDoesNotFailTheWholePage() async throws {
        let client = RelayClient(origin: .default, transport: RecordingTransport { _ in
            .json(#"{"items":[{"id":"x","app":"other","title":"X"}],"has_more":false}"#)
        })
        let page = try await client.chatList(device: device, app: "all")
        #expect(page.items.map(\.app) == ["other"])
        // An id that is not one at all is still refused: the row cannot name a source.
        let broken = RelayClient(origin: .default, transport: RecordingTransport { _ in
            .json(#"{"items":[{"id":"x","app":"Mail!","title":"X"}]}"#)
        })
        await #expect(throws: ReadFailure("来源应用不匹配")) { try await broken.chatList(device: device, app: "all") }
    }

    @Test func theCatalogComesFromTheComputerWithTheFakeTestingHelper() async {
        let model = makeModel(DemoTransport(world: DemoWorld()))
        await enterA(model)
        #expect(model.catalog.order == ["codex", "claude", "deepseek", "testing"])
        #expect(model.catalog.fromServer)
        #expect(model.catalog.name("testing") == "测试助手")
        #expect(!model.catalog.isLegacy("testing") && model.catalog.isLegacy("codex"))
        #expect(model.knownApps?.contains("testing") == true)
        #expect(Labels.sourceName("testing", catalog: model.catalog) == "测试助手")
    }

    @Test func anOlderComputerKeepsTheThreeBuiltinsAndTheListStillLoads() async {
        let model = makeModel(LegacyAgentsTransport())
        await enterA(model)
        #expect(model.catalog.order == ["codex", "claude", "deepseek"])
        #expect(!model.catalog.fromServer)
        // The chips come from the computer's tree, which still names the fake testing helper; only its manifest is gone.
        #expect(model.knownApps?.contains("testing") == true)
        #expect(model.chats.first?.title == "原生阅读示例")
        #expect(model.error == nil && model.treeError == nil)
    }

    @Test func aManifestListOutOfReachKeepsTheThreeAndDoesNotFailThePage() async {
        let model = makeModel(NoAgentsTransport())
        await enterA(model)
        #expect(model.catalog.order == ["codex", "claude", "deepseek"])
        #expect(model.error == nil && model.treeError == nil)
        #expect(!model.chats.isEmpty)
    }

    @Test func aNewAssistantsConversationOpensAndReads() async throws {
        let model = makeModel(DemoTransport(world: DemoWorld()))
        await enterA(model)
        let row = try #require(model.chats.first { $0.app == "testing" && $0.id == "test-waiting" })
        model.open(row)
        await model.settle()
        #expect(model.screen == .reading && model.app == "testing")
        #expect(model.messages.map(\.text) == ["选一个方案", "请选择 A 或 B"])
        // 第一段 only reads: the state address of a new assistant comes in the second step, so nothing of it is
        // available and the composer cannot send (handoff 3.3, 3.4).
        #expect(!model.conversation.control.available)
    }
}
