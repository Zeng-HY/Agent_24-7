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

    /// A place.json from before the domain reads as not moved yet; the move keeps the place and changes the address only.
    @Test func theMoveToTheDomainKeepsThePlace() async throws {
        let at = folder()
        try FileManager.default.createDirectory(at: at, withIntermediateDirectories: true)
        let old = #"{"app":"claude","chat":"c","device":"d","origin":"https://8.166.15.235","scope":"s","theme":"dark","title":"标题"}"#
        try Data(old.utf8).write(to: at.appendingPathComponent("place.json"))
        let store = LocalStore(folder: at)
        let before = await store.place()
        #expect(before.origin == "https://8.166.15.235" && !before.movedToDomain && before.scope == "s")
        await store.setMovedToDomain(origin: "")
        let after = await LocalStore(folder: at).place()
        #expect(after.origin.isEmpty && after.movedToDomain)
        #expect(after.scope == "s" && after.device == "d" && after.chat == "c" && after.title == "标题" && after.app == "claude" && after.theme == "dark")
        await store.setOrigin("https://example.com")
        #expect(await LocalStore(folder: at).place().movedToDomain)
    }

    /// 删除账号: one sign-in's records all go, those moved aside too, and a late write for it is dropped; another
    /// sign-in's stay and still change.
    @Test func forgettingASignInTakesAllItsRecordsAndNoneOfAnothers() async throws {
        let at = folder()
        let store = LocalStore(folder: at)
        let gone = ChatKey(scope: "gone", device: "d", app: "codex", chat: "c1")
        let kept = ChatKey(scope: "kept", device: "d", app: "codex", chat: "c1")
        // A send takes the draft with it (begin), so the draft typed after it comes second.
        await store.begin(Submission(request: "r1", key: gone, text: "发过的", action: "send", turn: "t1", body: "{}", created: 1))
        await store.setDraft(gone, "草稿")
        await store.setDetail(scope: "gone", device: "d", app: "codex", chat: "@sources", kind: "sources", value: "codex")
        let draftBefore = await store.draft(gone), sendsBefore = await store.submissions(gone)
        #expect(draftBefore == "草稿" && sendsBefore.count == 1)
        await store.setDraft(kept, "留着")
        let chats = at.appendingPathComponent("chats")
        let aside = LocalStore.recordName(scope: "gone", device: "d", app: "claude", chat: "c2") + ".unreadable-1.json"
        try Data("not json".utf8).write(to: chats.appendingPathComponent(aside))
        await store.forget(scope: "gone")
        #expect(try FileManager.default.contentsOfDirectory(atPath: chats.path) == [LocalStore.recordName(scope: "kept", device: "d", app: "codex", chat: "c1") + ".json"])
        let draft = await store.draft(gone), sends = await store.submissions(gone), drafts = await store.drafts(scope: "gone", device: "d")
        #expect(draft.isEmpty && sends.isEmpty && drafts.isEmpty)
        #expect(await store.detail(scope: "gone", device: "d", app: "codex", chat: "@sources", kind: "sources") == nil)
        await store.setDraft(gone, "迟到的")
        await store.setDraft(kept, "改过")
        let reopened = LocalStore(folder: at)
        #expect(await reopened.draft(gone).isEmpty)
        #expect(await reopened.draft(kept) == "改过")
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
