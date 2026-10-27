import Foundation
import Testing
@testable import TeleplyDemo
@testable import TeleplyModel

/// The local demo answers the app's own relay client the way the Android demo answers its screens.
struct DemoServiceTests {
    let a = String(repeating: "a", count: 32)
    let b = String(repeating: "b", count: 32)

    func client(_ world: DemoWorld = DemoWorld()) -> RelayClient {
        RelayClient(origin: .default, transport: DemoTransport(world: world), vault: MemoryCookieVault())
    }

    @Test func signsInWithAnythingAndListsThreeComputers() async throws {
        let demo = client()
        await #expect(throws: ServiceFailure(status: 401)) { _ = try await demo.account() }
        try await demo.login(name: "任何账号", password: "任何密码")
        #expect(try await demo.account().devices.map(\.label) == ["测试电脑 A", "测试电脑 B", "离线电脑"])
        try await demo.select(device: a)
        do { try await demo.select(device: String(repeating: "c", count: 32)); Issue.record("offline should fail") } catch let failure as ServiceFailure {
            #expect(failure.code == "device_offline")
        }
    }

    @Test func computerBHasNoClaudeAnywhere() async throws {
        let demo = client()
        let rows = try await demo.chatList(device: b, app: "all")
        #expect(!rows.items.contains { $0.app == "claude" })
        #expect(treeApps(try await demo.projects(device: b)) == ["codex", "deepseek"])
        #expect(treeApps(try await demo.projects(device: a)) == ["codex", "claude", "deepseek"])
    }

    @Test func listPagesAndSpecialInputs() async throws {
        let demo = client()
        let first = try await demo.chatList(device: a, app: "all")
        #expect(first.items.first?.title == "原生阅读示例" && first.cursor == "page2" && first.hasMore)
        #expect(first.items.first { $0.id == "deepseek-demo" }?.childCount == 3)
        #expect(try await demo.chatList(device: a, app: "all", cursor: "page2").items.map(\.id) == ["older"])
        #expect(try await demo.chatList(device: a, app: "all", query: "performance").items.map(\.id) == ["performance"])
        await #expect(throws: ServiceFailure(status: 503, detail: "本地示例：服务暂时不可用")) { _ = try await demo.chatList(device: a, app: "all", query: "error") }
        #expect(try await demo.chatList(device: a, app: "all", status: "waiting").items.allSatisfy { $0.status == "waiting" })
    }

    @Test func historyCarriesMetaAndTheLongConversation() async throws {
        let demo = client()
        let page = try await demo.history(device: a, app: "codex", chat: "demo")
        #expect(page.meta["title"].string() == "原生阅读示例" && page.meta["runtime"]["percent"].int() == 46)
        #expect(page.items.map(\.id) == ["m1", "m1b", "m1c", "m2", "m3"])
        #expect(page.items[2].status == "completed" && page.items[2].details["title"].string() == "修改 测试.txt")
        #expect(page.cursor == "m1" && page.hasMore)
        #expect(try await demo.history(device: a, app: "codex", chat: "performance").items.count == 200)
        #expect(try await demo.history(device: a, app: "codex", chat: "demo", before: "m1").items.map(\.id) == ["m0"])
        let next = try await demo.history(device: a, app: "claude", chat: "claude-next")
        #expect(next.items.first { $0.role == "next" }?.details["ask"].string() == "接下来做什么？")
    }

    @Test func stateReadsAreRecordedWithFreshness() async throws {
        let world = DemoWorld()
        let demo = client(world)
        let codex = try await demo.control(device: a, app: "codex", chat: "demo")
        _ = try await demo.control(device: a, app: "claude", chat: "claude-demo", fresh: false)
        #expect(codex.questions)
        #expect(world.stateReads.map(\.fresh) == [true, false])
    }

    /// The PDF the demo computer's Office makes is a real one: every object, and the page's text, where the
    /// cross-reference table and the lengths say.
    @Test func theDemoPDFIsWellFormed() throws {
        let bytes = Array(DemoData.pdf)
        let text = String(decoding: bytes, as: UTF8.self)
        #expect(text.hasPrefix("%PDF-1.4\n") && text.hasSuffix("%%EOF\n"))
        let written = try #require(text.components(separatedBy: "startxref\n").last?.split(separator: "\n").first)
        let start = try #require(Int(written))
        let table = String(decoding: bytes[start...], as: UTF8.self).split(separator: "\n", omittingEmptySubsequences: false)
        #expect(table[0] == "xref" && table[1] == "0 7" && table[2] == "0000000000 65535 f ")
        for index in 1...6 {
            let entry = table[2 + index]
            #expect(entry.utf8.count == 19 && entry.hasSuffix(" 00000 n "))
            let offset = try #require(Int(entry.prefix(10)))
            let head = Array("\(index) 0 obj\n".utf8)
            #expect(Array(bytes[offset..<offset + head.count]) == head)
        }
        let stream = try #require(text.range(of: "stream\n"))
        let end = try #require(text.range(of: "\nendstream"))
        let length = text[stream.upperBound..<end.lowerBound].utf8.count
        #expect(text.contains("<< /Length \(length) >>"))
        #expect(text.contains("(Release notes) Tj"))
    }

    @Test func aBrokenDemoNetworkFailsComputerCallsOnly() async throws {
        let world = DemoWorld()
        world.network = .offline
        let demo = client(world)
        try await demo.login(name: "x", password: "y")
        #expect(try await demo.account().devices.count == 3)
        await #expect(throws: DemoTransport.Offline.self) { _ = try await demo.chatList(device: a, app: "all") }
    }
}
