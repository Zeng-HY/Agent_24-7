import Foundation
import Testing
@testable import TeleplyModel

struct LocalStoreTests {
    func folder() -> URL {
        FileManager.default.temporaryDirectory.appendingPathComponent("teleply-store-\(UUID().uuidString)")
    }

    @Test func remembersThePlaceAndAnotherServiceStartsFresh() async {
        let at = folder()
        let store = LocalStore(folder: at)
        await store.setSelection(scope: "s", device: "d", chat: "c", title: "标题")
        await store.setSource("claude")
        #expect(await LocalStore(folder: at).place().app == "claude")
        #expect(await LocalStore(folder: at).place().chat == "")
        await store.setOrigin("https://example.com")
        let fresh = await LocalStore(folder: at).place()
        #expect(fresh.origin == "https://example.com" && fresh.scope.isEmpty && fresh.device.isEmpty)
    }

    @Test func recordsAreKeptApartBySignInComputerSourceAndConversation() async {
        let at = folder()
        let store = LocalStore(folder: at)
        await store.update(scope: "s1", device: "d", app: "codex", chat: "new:1/x") { $0.position = .init(message: "m5", offset: 12) }
        await store.setDetail(scope: "s1", device: "d", app: "codex", chat: "@sources", kind: "sources", value: "codex,deepseek")
        let reopened = LocalStore(folder: at)
        #expect(await reopened.record(scope: "s1", device: "d", app: "codex", chat: "new:1/x").position == .init(message: "m5", offset: 12))
        #expect(await reopened.record(scope: "s2", device: "d", app: "codex", chat: "new:1/x").position == nil)
        #expect(await reopened.detail(scope: "s1", device: "d", app: "codex", chat: "@sources", kind: "sources") == "codex,deepseek")
    }

    @Test func anUnreadableFileIsMovedAsideNotOverwritten() async throws {
        let at = folder()
        try FileManager.default.createDirectory(at: at, withIntermediateDirectories: true)
        try Data("not json".utf8).write(to: at.appendingPathComponent("place.json"))
        #expect(await LocalStore(folder: at).place() == Place())
        let names = try FileManager.default.contentsOfDirectory(atPath: at.path)
        #expect(names.contains { $0.hasPrefix("place.unreadable-") })
    }
}
