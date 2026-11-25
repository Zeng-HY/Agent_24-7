import Foundation
import Testing
@testable import TeleplyDemo
import TeleplyModel
@testable import TeleplyState

/// A new assistant through the whole app on the local demo: the fake `testing` helper only exists when the demo was
/// opened with it (handoff 3.7), and its own addresses then answer state, send, receipt, stop, answer, the three
/// new-conversation steps and the upload.
@MainActor
struct AgentUnifiedFlowTests {
    let a = String(repeating: "a", count: 32)

    func makeModel(_ world: DemoWorld) -> (AppModel, WatchedTransport) {
        let watched = WatchedTransport(world: world)
        let model = AppModel(services: AppServices(store: LocalStore(folder: temporaryFolder()), vault: MemoryCookieVault(),
                                                   transport: watched, demo: { DemoTransport() }, pacer: IdlePacer(),
                                                   newScope: { "scope-1" }))
        return (model, watched)
    }

    func enterA(_ model: AppModel) async {
        model.start()
        await model.settle()
        model.login(name: "账号", password: "密码")
        await model.settle()
        if let computer = model.account?.devices.first(where: { $0.id == a }) { model.select(computer) }
        await model.settle()
    }

    func until(_ ready: @escaping @MainActor () -> Bool) async {
        for _ in 0..<300 where !ready() { try? await Task.sleep(for: .milliseconds(10)) }
    }

    func open(_ model: AppModel, _ id: String) async throws {
        let row = try #require(model.chats.first { $0.app == "testing" && $0.id == id })
        model.open(row)
        await model.settle()
        await until { model.conversation.control.available && model.conversation.ready && model.workspace.ready }
        #expect(model.conversation.control.available && model.conversation.ready && model.workspace.ready)
    }

    @Test func itsStateAndItsCardComeFromItsOwnAddress() async throws {
        let (model, watched) = makeModel(DemoWorld(testingAgent: true))
        await enterA(model)
        try await open(model, "test-waiting")
        #expect(model.conversation.control.questions)
        // Since 0.9.1 a new assistant's 用量 follows its manifest's `usage` flag (dev.54's Antigravity opens it), and
        // the page gets its `agents.<id>` section.
        #expect(model.showsUsage("testing"))
        #expect(pendingCards(app: "testing", raw: model.conversation.control.raw, catalog: model.catalog).first?.summary == "测试助手想运行命令")
        #expect(genericCards(model.conversation.control.raw).count == 1)
        let paths = await watched.log.items.map(\.url.path)
        #expect(paths.contains("/d/\(a)/api/agents/testing/state"))
        // 批准 goes to the card's own address with this request's id and the chosen option.
        model.workspace.action("generic/answer", ["question_id": .string(DemoData.testingApprovalID),
                                                  "answers": ["decision": .array(["允许一次"])]])
        await model.workspace.settle()
        #expect(model.workspace.error == nil)
        await until { !model.conversation.control.questions }
        #expect(!model.conversation.control.questions)
        let answers = await watched.log.items.filter { $0.url.path.hasSuffix("/api/agents/testing/answer") }
        #expect(answers.count == 1)
        let body = try JSONValue.parse(try #require(answers.first?.body))
        #expect(body["id"].string() == "test-waiting")
        #expect(body["question_id"].string() == DemoData.testingApprovalID)
        #expect(body["answers"]["decision"].array.map { $0.string() } == ["允许一次"])
        #expect(!body["request_id"].string().isEmpty)
    }

    @Test func aSendGoesToItsOwnAddressAndItsReceiptIsRead() async throws {
        let (model, watched) = makeModel(DemoWorld(testingAgent: true))
        await enterA(model)
        try await open(model, "test-waiting")
        // The conversation's own state says a send is possible now — that is what the send path reads (not the
        // process-wide catalog).
        #expect(model.conversation.control.capabilitiesNow["send_modes"].array.contains { $0.string() == "send" })
        #expect(model.offersSend("testing"))
        model.conversation.edit("跑一下测试")
        model.conversation.send()
        await model.conversation.settleSends()
        let sends = await watched.log.items.filter { $0.url.path.hasSuffix("/api/agents/testing/send") }
        #expect(sends.count == 1)
        let body = try JSONValue.parse(try #require(sends.first?.body))
        #expect(body["id"].string() == "test-waiting")
        #expect(body["text"].string() == "跑一下测试")
        #expect(body["intent"].string() == "send")  // Antigravity's only send mode
        #expect(!body["request_id"].string().isEmpty)
        let record = try #require(model.conversation.submissions.first)
        #expect(record.label == "已接收")
        // The receipt at its own address says the computer found it: 已送达.
        model.conversation.check(record)
        await until { model.conversation.submissions.first?.label == "已送达" }
        #expect(model.conversation.submissions.first?.label == "已送达")
        let receipts = await watched.log.items.filter { $0.url.path.hasSuffix("/api/agents/testing/receipt") }
        #expect(receipts.count >= 1)
    }

    @Test func stopGoesToItsOwnAddress() async throws {
        let (model, watched) = makeModel(DemoWorld(testingAgent: true))
        await enterA(model)
        try await open(model, "test-running")
        #expect(model.conversation.control.running)
        #expect(model.can("stop", app: "testing"))
        model.conversation.stop()
        await model.conversation.settleSends()
        let stops = await watched.log.items.filter { $0.url.path.hasSuffix("/api/agents/testing/stop") }
        #expect(stops.count == 1)
        let body = try JSONValue.parse(try #require(stops.first?.body))
        #expect(body["id"].string() == "test-running")
        // The state after it says the turn is over; the stop button goes with it.
        await until { !model.conversation.control.running }
        #expect(!model.conversation.control.running)
    }

    @Test func itsNewConversationUsesItsOwnThreeSteps() async throws {
        let (model, watched) = makeModel(DemoWorld(testingAgent: true))
        await enterA(model)
        model.startNew(app: "testing")
        await model.applying?.value
        await model.workspace.settle()
        await until { !model.workspace.newData["folders"]["items"].array.isEmpty }
        let items = model.workspace.newData["folders"]["items"].array
        #expect(items.map { $0["path"].string() } == ["D:/fixture/测试项目"])
        #expect(items.first?["name"].string() == "测试项目")
        #expect(model.workspace.newData["models"]["models"].array.isEmpty)
        #expect(model.workspace.newData["models"]["note"].string().isEmpty == false)
        model.workspace.chooseFolder("D:/fixture/测试项目", projectless: false)
        model.workspace.edit("first_message", "写一个测试")
        model.workspace.create()
        await model.workspace.settle()
        await model.settle()
        let job = try #require(model.jobs.jobs.first)
        #expect(job.app == "testing" && job.folder == "D:/fixture/测试项目")
        // The fields follow the manifest: no projectless, no settings, no permission, no references.
        #expect(job.body["projectless"].isNull && job.body["settings"].isNull && job.body["permission"].isNull)
        #expect(job.body["references"].array.isEmpty)
        for _ in 0..<6 {
            if let next = model.jobs.jobs.first {
                if next.accepted { model.openJob(next) } else { model.jobs.check(next) }
            }
            await model.jobs.settle()
            await model.settle()
        }
        let creates = await watched.log.items.filter { $0.url.path.hasSuffix("/api/agents/testing/create") }
        #expect(creates.count >= 1)
        let body = try JSONValue.parse(try #require(creates.first?.body))
        #expect(body["folder"].string() == "D:/fixture/测试项目" && body["text"].string() == "写一个测试")
        let checked = await watched.log.items
        #expect(checked.contains { $0.url.path.hasSuffix("/api/agents/testing/create/state") })
        #expect(model.chat?.id == "test-new-1")
        model.back()
        await model.settle()
        #expect(model.chats.first?.id == "test-new-1")
    }

    @Test func aPictureGoesToItsOwnUploadAddress() async throws {
        let (model, watched) = makeModel(DemoWorld(testingAgent: true))
        await enterA(model)
        try await open(model, "test-waiting")
        let folder = temporaryFolder()
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        let file = folder.appendingPathComponent("picture.png")
        try Data([0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A]).write(to: file)
        model.workspace.importFile(file, name: "picture.png", image: true)
        await until {
            let rows = model.workspace.saved["uploads"].array
            return !rows.isEmpty && rows.allSatisfy { $0["status"].string() == "ready" }
        }
        let uploads = model.workspace.saved["uploads"].array
        #expect(uploads.count == 1 && uploads.first?["status"].string() == "ready")
        let items = await watched.log.items
        let request = try #require(items.first { $0.url.path.hasSuffix("/api/agents/testing/upload") })
        #expect(request.method == .post)
        #expect(queryValue(request, "id") == "test-waiting" && queryValue(request, "name") == "picture.png")
    }

    @Test func twoModelsKeepTheirOwnCatalogsAndFlows() async throws {
        // Two AppModels at once, each on its own demo world: the first has the fake helper, the second does not.
        // Each model keeps its own catalog now (handoff 第三段), so whatever the other syncs, its own send, new
        // conversation and upload keep going to its own assistant's addresses.
        let (one, watchedOne) = makeModel(DemoWorld(testingAgent: true))
        let (two, watchedTwo) = makeModel(DemoWorld())
        await enterA(one)
        await enterA(two)
        #expect(one.catalog.contains("testing"))
        #expect(!two.catalog.contains("testing"))
        #expect(!two.offersSend("testing"))
        // The first model: a send, a picture and a new conversation for the fake helper.
        try await open(one, "test-waiting")
        #expect(one.conversation.catalog.contains("testing"))
        one.conversation.edit("跑一下测试")
        one.conversation.send()
        await one.conversation.settleSends()
        let oneSends = await watchedOne.log.items.filter { $0.url.path.hasSuffix("/api/agents/testing/send") }
        #expect(oneSends.count == 1)
        let folder = temporaryFolder()
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        let file = folder.appendingPathComponent("picture.png")
        try Data([0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A]).write(to: file)
        one.workspace.importFile(file, name: "picture.png", image: true)
        await until {
            let rows = one.workspace.saved["uploads"].array
            return !rows.isEmpty && rows.allSatisfy { $0["status"].string() == "ready" }
        }
        let oneUploads = await watchedOne.log.items.filter { $0.url.path.hasSuffix("/api/agents/testing/upload") }
        #expect(oneUploads.count == 1)
        one.startNew(app: "testing")
        await one.applying?.value
        await one.workspace.settle()
        await until { !one.workspace.newData["folders"]["items"].array.isEmpty }
        one.workspace.chooseFolder("D:/fixture/测试项目", projectless: false)
        one.workspace.edit("first_message", "写一个测试")
        one.workspace.create()
        await one.workspace.settle()
        await one.jobs.settle()
        await one.settle()
        let oneItems = await watchedOne.log.items
        #expect(oneItems.contains { $0.url.path.hasSuffix("/api/agents/testing/create") })
        // The second model is untouched: its own Codex conversation sends through the old address, and its list has
        // no fake helper at all.
        let row = try #require(two.chats.first { $0.app == "codex" && $0.id == "demo" })
        two.open(row)
        await two.settle()
        await until { two.conversation.control.available && two.conversation.ready && two.workspace.ready }
        two.conversation.edit("你好")
        two.conversation.send()
        await two.conversation.settleSends()
        let twoSends = await watchedTwo.log.items.filter { $0.url.path.hasSuffix("/api/codex/send") }
        #expect(twoSends.count == 1)
        #expect(!two.chats.contains { $0.app == "testing" })
    }

    @Test func withoutTheHelperItsAddressesAreNotThere() async throws {
        let plain = RelayClient(origin: .default, transport: DemoTransport(world: DemoWorld()), vault: MemoryCookieVault())
        let catalog = AgentCatalogSnapshot.fromServer(AgentCatalogTests.agents(#"{"id":"testing","name":{"zh":"测试助手"}}"#))
        var status = 0
        do {
            _ = try await plain.control(device: a, app: "testing", chat: "test-waiting", catalog: catalog)
        } catch let failure as ServiceFailure {
            status = failure.status
        }
        #expect(status == 404)
    }

    // MARK: The three's buttons do not follow capabilities_now (handoff 3.4, second review)

    @Test func aSendModeComesFromTheConversationState() {
        let state = parseControl(["available": true, "capabilities_now": ["send_modes": ["send", "steer"]]])
        #expect(ChatModel.sendModes(of: state, app: "some-new-assistant", catalog: .builtin) == ["send", "steer"])
        // The state wins even when it offers nothing: that is the computer's word now.
        let closed = parseControl(["available": true, "capabilities_now": ["send_modes": []]])
        #expect(ChatModel.sendModes(of: closed, app: "some-new-assistant", catalog: .builtin).isEmpty)
    }

    @Test func theThreeKeepEveryButtonWhateverTheStateSays() async throws {
        let model = makeAgentModel(AllOffTransport(world: DemoWorld(), paths: ["/api/codex/state"]))
        await enterA(model)
        let row = try #require(model.chats.first { $0.app == "codex" && $0.id == "demo" })
        model.open(row)
        await model.settle()
        await until { model.conversation.control.available }
        #expect(model.conversation.control.available)
        // The state really did turn everything off (the display narrows for anyone), yet the three's buttons are the
        // ones they always had.
        #expect(!model.capabilities("codex").stop)
        #expect(model.capabilities("codex").sendModes.isEmpty)
        #expect(model.offersStop("codex"))
        #expect(model.offersQueue("codex"))
        #expect(model.offersSend("codex"))
        #expect(model.offersAttachments("codex"))
        #expect(model.offersOpenOnComputer("codex"))
        #expect(model.showsUsage("codex"))
        #expect(model.allowsCommands("codex"))
        #expect(model.allowsSkills("codex"))
        // DeepSeek's own rules are the ones they had: no 用量, no $.
        #expect(!model.showsUsage("deepseek"))
        #expect(!model.allowsSkills("deepseek"))
        #expect(model.sendBlockedNote("codex") == nil)
    }

    @Test func aNewAssistantsButtonsFollowItsState() async throws {
        let model = makeAgentModel(AllOffTransport(world: DemoWorld(testingAgent: true), paths: ["/api/agents/testing/state"]))
        await enterA(model)
        let row = try #require(model.chats.first { $0.app == "testing" && $0.id == "test-waiting" })
        model.open(row)
        await model.settle()
        await until { model.conversation.control.available }
        #expect(model.conversation.control.available)
        #expect(!model.offersStop("testing"))
        #expect(!model.offersQueue("testing"))
        #expect(!model.offersSend("testing"))
        #expect(!model.offersAttachments("testing"))
        #expect(!model.offersOpenOnComputer("testing"))
        // 用量 follows the assistant's own `usage` capability since 0.9.1; this state narrows it away with the rest.
        #expect(!model.showsUsage("testing"))
        #expect(!model.allowsCommands("testing"))
        #expect(!model.allowsSkills("testing"))
        #expect(model.sendBlockedNote("testing") != nil)
        #expect(model.sendBlockedNote("codex") == nil)
    }
}

/// The demo computer with one conversation's state narrowed to nothing: `capabilities_now` turns every flag off and
/// empties every list, as a computer whose assistant is not open would. The three must not notice; a new assistant
/// must lose the buttons.
struct AllOffTransport: RelayStreamingTransport {
    let demo: DemoTransport
    let paths: [String]

    init(world: DemoWorld, paths: [String]) {
        demo = DemoTransport(world: world)
        self.paths = paths
    }

    func stream(_ request: RelayRequest) async throws -> RelayStream {
        try await demo.stream(request)
    }

    func send(_ request: RelayRequest) async throws -> RelayResponse {
        let response = try await demo.send(request)
        guard response.status == 200, paths.contains(where: { request.url.path.hasSuffix($0) }),
              var fields = (try? JSONValue.parse(response.body))?.object else { return response }
        fields["capabilities_now"] = [
            "list": true, "read": true, "search": true, "open": false, "stop": false, "queue": false, "steer": false,
            "approve": false, "answer": false, "new": true, "new_projectless": true, "new_permission": false,
            "archive": false, "restore": false, "delete": false, "usage": false, "waiting": false,
            "attachments": false, "slash_commands": false, "skills": false, "send_modes": [], "settings": [],
        ]
        fields["capability_notes"] = ["send": "电脑上的助手没开", "stop": "电脑上的助手没开"]
        return RelayResponse(status: 200, headers: ["content-type": "application/json"],
                             body: (try? JSONValue.object(fields).encoded()) ?? response.body)
    }
}

@MainActor
func makeAgentModel(_ transport: any RelayTransport) -> AppModel {
    AppModel(services: AppServices(store: LocalStore(folder: temporaryFolder()), vault: MemoryCookieVault(),
                                   transport: transport, demo: { DemoTransport() }, pacer: IdlePacer(),
                                   newScope: { "scope-1" }))
}
