import Foundation
import Testing
@testable import TeleplyModel

/// Android RelayApiTest, for the calls the read-only app makes.
struct RelayReadTests {
    let device = String(repeating: "a", count: 32)
    let key = ServiceOrigin.default.key

    @Test func loginKeepsTheCookieAndSendsOnlyItsNameAndValue() async throws {
        let vault = MemoryCookieVault()
        let transport = RecordingTransport { request in
            if request.url.path == "/account/login" {
                return RelayResponse(status: 200, headers: ["set-cookie": "__Host-ar_account=synthetic; Path=/; Secure; HttpOnly; Max-Age=3600"], body: Data("{\"ok\":true}".utf8))
            }
            return .json(#"{"items":[{"id":"chat","app":"codex","title":"测试"}],"has_more":true,"next_cursor":"p2"}"#)
        }
        let client = RelayClient(origin: .default, transport: transport, vault: vault)
        try await client.login(name: "fixture", password: "test-only")
        let page = try await client.chatList(device: device, app: "codex", query: "中文 & ?")
        let sent = await transport.log.items
        #expect(sent[0].method == .post)
        #expect(sent[0].headers["Origin"] == "https://8.166.15.235")
        #expect(sent[1].url.path == "/d/\(device)/api/chats")
        #expect(sent[1].url.absoluteString.contains("query=%E4%B8%AD%E6%96%87%20%26%20%3F"))
        #expect(sent[1].headers["Cookie"] == "__Host-ar_account=synthetic")
        #expect(sent[1].headers["Origin"] == nil)
        #expect(page.hasMore && page.cursor == "p2")
    }

    @Test func aLoginAnswerWithoutTheSignInFails() async {
        let client = RelayClient(origin: .default, transport: RecordingTransport { _ in .json("{\"ok\":true}") }, vault: MemoryCookieVault())
        await #expect(throws: ReadFailure("登录响应缺少有效的账号凭据")) { try await client.login(name: "a", password: "b") }
    }

    @Test func mixedListKeepsEachRowsSourceAndRefusesUnknownOnes() async throws {
        let mixed = RelayClient(origin: .default, transport: RecordingTransport { _ in
            .json(#"{"items":[{"id":"a","app":"codex","title":"A"},{"id":"b","app":"claude","title":"B"},{"id":"c","app":"deepseek","title":"C"}],"has_more":false}"#)
        })
        #expect(try await mixed.chatList(device: device, app: "all", sort: "created", status: "waiting").items.map(\.app) == ["codex", "claude", "deepseek"])
        let unknown = RelayClient(origin: .default, transport: RecordingTransport { _ in .json(#"{"items":[{"id":"x","app":"other","title":"X"}]}"#) })
        await #expect(throws: ReadFailure("来源应用不匹配")) { try await unknown.chatList(device: device, app: "all") }
        let claudeRow = RelayClient(origin: .default, transport: RecordingTransport { _ in .json(#"{"items":[{"id":"x","app":"claude","title":"X"}]}"#) })
        await #expect(throws: ReadFailure("来源应用不匹配")) { try await claudeRow.chatList(device: device, app: "codex") }
    }

    @Test func historyCarriesTheRuntimeAsPageMetaAndKeepsIdentity() async throws {
        let transport = RecordingTransport { _ in
            .json(#"{"app":"codex","id":"x/y","title":"标题","status":"idle","runtime":{"percent":46},"messages":[{"id":"m","role":"assistant","text":"原文\n","truncated":true,"phase":"commentary"},{"id":"u","role":"user","text":"q","client_request_id":"r1"}],"next_cursor":"m","has_more":true,"has_newer":true}"#)
        }
        let page = try await RelayClient(origin: .default, transport: transport).history(device: device, app: "codex", chat: "x/y", before: "opaque + / ?")
        #expect(page.meta["title"].string() == "标题")
        #expect(page.meta["runtime"]["percent"].int() == 46)
        #expect(page.items.first?.text == "原文\n" && page.items.first?.truncated == true && page.items.first?.phase == "commentary")
        #expect(page.items.last?.request == "r1")
        #expect(page.hasNewer && page.cursor == "m")
        let url = await transport.log.items.first?.url.absoluteString ?? ""
        #expect(url.contains("id=x%2Fy") && url.contains("before=opaque%20%2B%20%2F%20%3F"))
        let wrong = RelayClient(origin: .default, transport: RecordingTransport { _ in .json(#"{"app":"codex","id":"other","messages":[]}"#) })
        await #expect(throws: ReadFailure("对话身份不匹配")) { try await wrong.history(device: device, app: "codex", chat: "x/y") }
    }

    @Test func selectRefusesAnotherComputersPathAndNamesOffline() async {
        let other = RelayClient(origin: .default, transport: RecordingTransport { _ in .json(#"{"url":"/d/\#(String(repeating: "b", count: 32))/"}"#) })
        await #expect(throws: ReadFailure("服务返回的电脑路径不匹配")) { try await other.select(device: device) }
        let offline = RelayClient(origin: .default, transport: RecordingTransport { _ in .json(#"{"code":"device_offline"}"#, status: 409) })
        do { try await offline.select(device: device); Issue.record("select should fail") } catch let failure as ServiceFailure {
            #expect(failure.status == 409 && failure.code == "device_offline")
        } catch { Issue.record("unexpected \(error)") }
    }

    @Test func expiryForgetsOnlyThisServicesSignIn() async throws {
        let vault = MemoryCookieVault()
        try vault.write(key, SessionCookie(value: "synthetic", expires: nil))
        try vault.write("https://another.invalid/", SessionCookie(value: "other", expires: nil))
        let client = RelayClient(origin: .default, transport: RecordingTransport { _ in .json("{}", status: 401) }, vault: vault)
        await #expect(throws: ServiceFailure(status: 401)) { _ = try await client.account() }
        #expect(try vault.read(key) == nil)
        #expect(try vault.read("https://another.invalid/")?.value == "other")
    }

    @Test func aRedirectIsAFailureNotAFollow() async throws {
        let vault = MemoryCookieVault()
        try vault.write(key, SessionCookie(value: "synthetic", expires: nil))
        let transport = RecordingTransport { _ in RelayResponse(status: 302, headers: ["location": "https://leak.invalid/"]) }
        let client = RelayClient(origin: .default, transport: transport, vault: vault)
        await #expect(throws: ServiceFailure(status: 302)) { _ = try await client.account() }
        #expect(await transport.log.items.count == 1)
    }

    @Test func aFullMessageMustBeTheOneAskedFor() async {
        let client = RelayClient(origin: .default, transport: RecordingTransport { _ in .json(#"{"id":"wrong","role":"assistant","text":"no"}"#) })
        await #expect(throws: ReadFailure("消息身份不匹配")) { _ = try await client.message(device: device, app: "codex", chat: "chat", message: "expected") }
    }

    @Test func searchPagesWithinOneComputer() async throws {
        let transport = RecordingTransport { _ in .json(#"{"items":[{"id":"m","role":"user","snippet":"match"}],"has_more":true,"next_cursor":"next"}"#) }
        let page = try await RelayClient(origin: .default, transport: transport).search(device: device, app: "codex", chat: "chat", query: "match", cursor: "p2")
        #expect(page.cursor == "next" && page.items.first?.text == "match")
        let request = await transport.log.items.first
        #expect(request?.url.path == "/d/\(device)/api/chat/search")
        #expect(request?.url.absoluteString.contains("cursor=p2") == true)
    }

    @Test func malformedJSONFailsWithoutTheBody() async {
        let client = RelayClient(origin: .default, transport: RecordingTransport { _ in RelayResponse(status: 200, body: Data("<html>upstream error</html>".utf8)) })
        await #expect(throws: RelayError.unreadable) { _ = try await client.account() }
    }

    @Test func anInvalidComputerIdNeverMakesARequest() async {
        let transport = RecordingTransport { _ in .json("{}") }
        let client = RelayClient(origin: .default, transport: transport)
        await #expect(throws: ReadFailure("电脑标识无效")) { _ = try await client.chatList(device: "../account", app: "codex") }
        await #expect(throws: ReadFailure("电脑标识无效")) { try await client.select(device: String(repeating: "A", count: 32)) }
        #expect(await transport.log.items.isEmpty)
    }

    @Test func stateAsksFreshOnlyWhenToldAndDeepSeekCanQueue() async throws {
        let transport = RecordingTransport { _ in .json(#"{"available":true,"running":false}"#) }
        let client = RelayClient(origin: .default, transport: transport)
        _ = try await client.control(device: device, app: "claude", chat: "c")
        let polled = try await client.control(device: device, app: "deepseek", chat: "c", fresh: false)
        let sent = await transport.log.items
        #expect(sent[0].url.path == "/d/\(device)/api/claude/state" && sent[0].url.absoluteString.contains("fresh=1") && sent[0].deadline == 20)
        #expect(!sent[1].url.absoluteString.contains("fresh") && polled.queueAvailable)
    }

    @Test func theLiveStreamUsesTheComputersPathAndChecksFrames() async throws {
        let snapshot = "event: update\ndata: {\"protocol\":1,\"seq\":1,\"type\":\"snapshot\",\"app\":\"codex\",\"id\":\"chat\",\"chat\":{\"app\":\"codex\",\"id\":\"chat\",\"messages\":[{\"id\":\"m\",\"role\":\"assistant\",\"text\":\"stream\",\"order\":1}]}}\n\n"
        let bytes = Array(snapshot.utf8)
        let transport = StreamingTransport(status: 200, chunks: [Array(bytes[..<40]), Array(bytes[40...])])
        var frames: [LiveFrame] = []
        do {
            for try await frame in try RelayClient(origin: .default, transport: transport).events(device: device, app: "codex", chat: "chat") { frames.append(frame) }
            Issue.record("the stream should end with an error so the caller reconnects")
        } catch let failure as ReadFailure {
            #expect(failure == ReadFailure("实时连接已关闭"))
        }
        #expect(frames.first?.messages.first?.text == "stream")
        let request = await transport.log.items.first
        #expect(request?.url.path == "/d/\(device)/api/events" && request?.headers["Accept"] == "text/event-stream")
    }

    @Test func accountListsComputersAndTreeNamesItsApps() async throws {
        let client = RelayClient(origin: .default, transport: RecordingTransport { _ in
            .json(#"{"devices":[{"id":"\#(String(repeating: "a", count: 32))","label":"测试电脑 A","connectable":true}],"email":""}"#)
        })
        #expect(try await client.account().devices == [Computer(id: device, label: "测试电脑 A", connectable: true)])
        let tree = try JSONValue.parse(Data(#"{"apps":[{"app":"deepseek"},{"app":"codex"},{"app":"other"}]}"#.utf8))
        #expect(treeApps(tree) == ["codex", "deepseek"])
    }
}
