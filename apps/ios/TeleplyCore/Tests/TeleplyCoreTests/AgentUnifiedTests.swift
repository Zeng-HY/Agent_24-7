import Foundation
import Testing
@testable import TeleplyDemo
import TeleplyModel

/// A new assistant's own addresses (handoff 3.4; docs/adding-an-agent.md §四.3): the state and its timeout, send,
/// stop, queue, answer, receipt, open, options, the three new-conversation steps and the upload — and that the three
/// old assistants keep their own addresses and bodies exactly as before.
struct AgentUnifiedTests {
    let device = String(repeating: "a", count: 32)

    /// The catalog a protocol 2 phone holds: the three and Antigravity (its manifest as the computer sends it).
    var catalog: AgentCatalogSnapshot {
        AgentCatalogSnapshot.fromServer(AgentCatalogTests.agents(AgentCatalogTests.antigravity))
    }

    func makeClient(_ transport: any RelayTransport) -> RelayClient {
        RelayClient(origin: .default, transport: transport, vault: MemoryCookieVault())
    }

    @Test func theStateIsReadAtItsOwnAddressWithinTheTimeoutItsManifestAsksFor() async throws {
        let transport = RecordingTransport { _ in .json(#"{"available":true,"running":false,"status":"idle","questions":[]}"#) }
        let client = makeClient(transport)
        let state = try await client.control(device: device, app: "antigravity", chat: "c1", catalog: catalog)
        #expect(state.available && !state.running)
        let sent = await transport.log.items
        #expect(sent.count == 1)
        #expect(sent[0].method == .get)
        #expect(sent[0].url.path == "/d/\(device)/api/agents/antigravity/state")
        #expect(queryValue(sent[0], "id") == "c1" && queryValue(sent[0], "fresh") == "1")
        #expect(sent[0].deadline == 40)  // params.state_timeout_s
        #expect(sent[0].headers["X-Teleply-Protocol"] == "2")
        // Not fresh (the poll): no fresh flag.
        _ = try await client.control(device: device, app: "antigravity", chat: "c1", fresh: false, catalog: catalog)
        let polled = await transport.log.items
        #expect(queryValue(polled[1], "fresh") == nil)
    }

    @Test func theThreeKeepTheirOwnStateAddressAndTimeouts() async throws {
        let transport = RecordingTransport { _ in .json(#"{"available":true,"running":true}"#) }
        let client = makeClient(transport)
        _ = try await client.control(device: device, app: "codex", chat: "c1")
        _ = try await client.control(device: device, app: "claude", chat: "c1")
        let sent = await transport.log.items
        #expect(sent[0].url.path == "/d/\(device)/api/codex/state")
        #expect(sent[1].url.path == "/d/\(device)/api/claude/state")
        #expect(sent[1].deadline == 20)  // Claude's window read, as before
    }

    @Test func actionsGoToItsOwnAddresses() async throws {
        let transport = RecordingTransport { request in
            request.url.path.hasSuffix("/send")
                ? .json(#"{"ok":true,"accepted":true,"delivery_state":"queued","request_id":"r1"}"#)
                : .json(#"{"ok":true,"text":"好"}"#)
        }
        let client = makeClient(transport)
        _ = try await client.command(device: device, app: "antigravity", route: "send",
                                     body: ["id": "c1", "request_id": "r1", "text": "你好", "intent": "send"], catalog: catalog)
        _ = try await client.command(device: device, app: "antigravity", route: "stop",
                                     body: ["id": "c1", "operation_id": "o1", "turn_id": "t1"], catalog: catalog)
        _ = try await client.command(device: device, app: "antigravity", route: "queue-action",
                                     body: ["request_id": "r1", "message_id": "m1", "action": "promote"], catalog: catalog)
        _ = try await client.command(device: device, app: "antigravity", route: "answer",
                                     body: ["id": "c1", "request_id": "r2", "question_id": "q1",
                                            "answers": ["decision": ["允许一次"]]], catalog: catalog)
        let sent = await transport.log.items
        #expect(sent.map(\.method) == [.post, .post, .post, .post])
        #expect(sent.map(\.url.path) == ["/d/\(device)/api/agents/antigravity/send",
                                         "/d/\(device)/api/agents/antigravity/stop",
                                         "/d/\(device)/api/agents/antigravity/queue",
                                         "/d/\(device)/api/agents/antigravity/answer"])
        #expect(sent[0].deadline == 60)  // params.send_timeout_s
        let send = try JSONValue.parse(try #require(sent[0].body))
        #expect(send["text"].string() == "你好" && send["intent"].string() == "send" && send["request_id"].string() == "r1")
        let queue = try JSONValue.parse(try #require(sent[2].body))
        #expect(queue["item_id"].string() == "m1" && queue["action"].string() == "promote")
        let answer = try JSONValue.parse(try #require(sent[3].body))
        #expect(answer["question_id"].string() == "q1" && answer["answers"]["decision"].array.map { $0.string() } == ["允许一次"])
    }

    @Test func theThreeKeepTheirOwnActionAddressesAndBodies() async throws {
        let transport = RecordingTransport { _ in .json(#"{"ok":true,"request_id":"r1"}"#) }
        let client = makeClient(transport)
        _ = try await client.command(device: device, app: "codex", route: "send", body: ["id": "c1", "intent": "auto"])
        _ = try await client.command(device: device, app: "deepseek", route: "send", body: ["id": "c1", "intent": "auto"])
        _ = try await client.command(device: device, app: "claude", route: "send", body: ["id": "c1", "text": "x"])
        let sent = await transport.log.items
        #expect(sent.map(\.url.path) == ["/d/\(device)/api/codex/send", "/d/\(device)/api/deepseek/send", "/d/\(device)/api/chat/send"])
        let deepseek = try JSONValue.parse(try #require(sent[1].body))
        // DeepSeek's own fields as its branch sends them: the same body, `intent` mapped (auto → steer), no `app`.
        #expect(deepseek["id"].string() == "c1")
        #expect(deepseek["intent"].string() == "steer")
        #expect(deepseek["app"].isNull)
    }

    @Test func aReceiptAtItsOwnAddressIsReadAsDelivered() async throws {
        let transport = RecordingTransport { _ in
            .json(#"{"state":"accepted","id":"c1","request_id":"r1","delivered":true,"queued":false,"stage":"conversation_record"}"#)
        }
        let receipt = try await makeClient(transport).receipt(device: device, app: "antigravity", chat: "c1", request: "r1", catalog: catalog)
        #expect(receipt["delivered"].bool())
        #expect(agentReceiptLabel(state: receipt["state"].string(), result: receipt, action: "send") == "已送达")
        let sent = await transport.log.items
        #expect(sent[0].url.path == "/d/\(device)/api/agents/antigravity/receipt")
        #expect(queryValue(sent[0], "id") == "c1" && queryValue(sent[0], "request_id") == "r1")
        // Still queued: 已排队; unknown and not queued: 待确认. The three's own receipts read as before.
        #expect(agentReceiptLabel(state: "unknown", result: ["queued": true, "delivered": false], action: "send") == "已排队")
        #expect(agentReceiptLabel(state: "unknown", result: ["queued": false], action: "send") == "送达状态待确认")
        #expect(receiptLabel(state: "unknown", result: ["queued": true], action: "send") == "送达状态待确认")
    }

    @Test func openAndTheThreeNewConversationStepsUseItsOwnAddresses() async throws {
        let transport = RecordingTransport { _ in
            .json(#"{"request_id":"r1","state":"accepted","app":"antigravity","id":"new-1","title":"T","folder":"D:/x"}"#)
        }
        let client = makeClient(transport)
        _ = try await client.agentOpen(device: device, agent: "antigravity", chat: "c1", catalog: catalog)
        _ = try await client.agentOptions(device: device, agent: "antigravity")
        _ = try await client.agentCreate(device: device, agent: "antigravity",
                                         body: ["request_id": "r1", "folder": "D:/x", "text": "T"], catalog: catalog)
        let created = try await client.agentCreateState(device: device, agent: "antigravity", request: "r1")
        #expect(created["state"].string() == "accepted")
        let sent = await transport.log.items
        #expect(sent.map(\.url.path) == ["/d/\(device)/api/agents/antigravity/open",
                                         "/d/\(device)/api/agents/antigravity/options",
                                         "/d/\(device)/api/agents/antigravity/create",
                                         "/d/\(device)/api/agents/antigravity/create/state"])
        #expect(sent[0].method == .post && sent[0].deadline == 45)     // params.open_timeout_s
        #expect(sent[2].method == .post && sent[2].deadline == 140)    // params.new_timeout_s
        #expect(queryValue(sent[3], "request_id") == "r1")
    }

    @Test func aPictureGoesUpToItsOwnAddressAndTheManifestsLimitsAreKept() async throws {
        let transport = RecordingTransport { _ in .json(#"{"id":"pic-1","kind":"image","app":"antigravity"}"#) }
        let client = makeClient(transport)
        let file = URL(fileURLWithPath: "/tmp/teleply-unified-test.png")
        _ = try await client.upload(device: device, app: "antigravity", chat: "c1", draft: false, name: "a.png",
                                    file: file, size: 3, image: true, catalog: catalog)
        let sent = await transport.log.items
        #expect(sent[0].method == .post)
        #expect(sent[0].url.path == "/d/\(device)/api/agents/antigravity/upload")
        #expect(queryValue(sent[0], "id") == "c1" && queryValue(sent[0], "name") == "a.png")
        #expect(sent[0].upload == file)
        // Over the manifest's `params.max_image_bytes` (20 MB): refused here, no request made.
        await #expect(throws: ReadFailure("图片超过 20MB，传不上去")) {
            _ = try await client.upload(device: device, app: "antigravity", chat: "c1", draft: false, name: "big.png",
                                        file: file, size: 20 * 1024 * 1024 + 1, image: true, catalog: catalog)
        }
        // A new assistant's upload is pictures only.
        await #expect(throws: ReadFailure("这个助手只能发图片")) {
            _ = try await client.upload(device: device, app: "antigravity", chat: "c1", draft: false, name: "a.txt",
                                        file: file, size: 3, image: false, catalog: catalog)
        }
        #expect(await transport.log.items.count == 1)
    }

    @Test func theThreeKeepTheirOwnUploadAddresses() async throws {
        let transport = RecordingTransport { _ in .json(#"{"id":"pic-1"}"#) }
        let client = makeClient(transport)
        let file = URL(fileURLWithPath: "/tmp/teleply-three-test.png")
        _ = try await client.upload(device: device, app: "codex", chat: "c1", draft: false, name: "a.png",
                                    file: file, size: 3, image: true)
        _ = try await client.upload(device: device, app: "codex", chat: "c1", draft: false, name: "a.txt",
                                    file: file, size: 3, image: false)
        let sent = await transport.log.items
        #expect(sent[0].url.path == "/d/\(device)/api/codex/upload")
        #expect(sent[1].url.path == "/d/\(device)/api/files/upload")
    }

    @Test func capabilitiesNowOnlyNarrowsTheManifest() {
        let base = AgentCapabilities(list: true, read: true, stop: true, approve: true,
                                     skills: false, settings: ["model"], sendModes: ["send", "steer"])
        #expect(base.narrowed(by: .null) == base)
        #expect(base.narrowed(by: .array([])) == base)
        let narrower = base.narrowed(by: ["stop": false])
        #expect(!narrower.stop && narrower.list && narrower.approve)
        #expect(narrower.sendModes == ["send", "steer"])
        // A manifest's false cannot become true, and a list only loses entries, in the manifest's order.
        let attempted = base.narrowed(by: ["approve": false, "open": true, "send_modes": ["send", "queue"],
                                          "settings": ["model", "effort"], "skills": true])
        #expect(!attempted.approve && !attempted.open && attempted.stop)
        #expect(attempted.sendModes == ["send"] && attempted.settings == ["model"])
        #expect(attempted.skills == false)
        // A key the state does not mention keeps the manifest's value.
        #expect(base.narrowed(by: ["answer": false]).skills == false)
        #expect(base.flag("stop") == true && base.flag("open") == false && base.flag("nope") == nil)
    }

    @Test func aStateCarriesItsCapabilitiesNowAndTheComputersReasons() {
        let state = parseControl(["available": true, "running": true,
                                  "capabilities_now": ["approve": false],
                                  "capability_notes": ["approve": "  电脑上的 Antigravity 没开  "]])
        #expect(state.capabilitiesNow.isObject)
        #expect(state.note("approve") == "电脑上的 Antigravity 没开")
        #expect(state.note("answer") == "")
        #expect(!state.narrowed(AgentCapabilities(approve: true)).approve)
        #expect(parseControl(["available": true]).narrowed(AgentCapabilities(approve: true)).approve)
    }

    @Test func theSkillsListFollowsTheManifestOrTheOldRule() {
        #expect(skillsAvailable(AgentCapabilities(slashCommands: true, sendModes: ["send"]), layout: "claude.v1"))
        #expect(!skillsAvailable(AgentCapabilities(slashCommands: true, skills: false), layout: "claude.v1"))
        #expect(!skillsAvailable(AgentCapabilities(slashCommands: false), layout: "codex.v1"))
    }

    @Test func aNewAssistantsCardsBecomeTheQuestionBarAndTheTimeline() throws {
        let state: JSONValue = ["questions": [DemoData.testingApprovalCard]]
        let pending = pendingCards(app: "testing", raw: state)
        #expect(pending.map(\.kind) == ["approval"])
        #expect(pending.first?.summary == "测试助手想运行命令" && pending.first?.count == 1)
        let cards = genericCards(state)
        #expect(cards.count == 1)
        #expect(cards.first?["id"].string() == "approval-7")
        // Its own title, else the first question's header, else the assistant's name and the kind.
        let header = JSONValue.object(["id": "c", "status": "pending", "kind": "question",
                                       "questions": .array([.object(["id": "q", "header": "选一个方案", "question": "用哪个？",
                                                                     "options": .array([])])])])
        #expect(genericCardTitle(header, app: "testing") == "选一个方案")
        let bare = JSONValue.object(["id": "c", "status": "pending", "kind": "question",
                                     "questions": .array([.object(["id": "q", "question": "用哪个？", "options": .array([])])])])
        #expect(genericCardTitle(bare, app: "testing", assistant: "测试助手") == "测试助手 有问题要问你")
        let approval = JSONValue.object(["id": "c", "status": "pending", "kind": "approval",
                                         "questions": .array([.object(["id": "q", "question": "允许吗？", "options": .array([])])])])
        #expect(genericCardTitle(approval, app: "testing", assistant: "测试助手") == "测试助手 等你批准")
        // Only pending cards with questions count.
        let nothing = JSONValue.object(["questions": .array([.object(["id": "c", "status": "answered", "kind": "question",
                                                                     "questions": .array([.object(["id": "q", "question": "x",
                                                                                                   "options": .array([])])])])])])
        #expect(genericCards(nothing).isEmpty && pendingCards(app: "testing", raw: nothing).isEmpty)
    }

    @Test func anAssistantsIdIsCheckedBeforeItsAddressIsBuilt() {
        #expect((try? RelayClient.agentPath("antigravity", "state")) == "/api/agents/antigravity/state")
        #expect((try? RelayClient.agentPath("Mail!", "state")) == nil)
    }
}
