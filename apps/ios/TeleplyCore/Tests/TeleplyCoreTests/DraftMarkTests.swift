import Foundation
import Testing
@testable import TeleplyDemo
import TeleplyModel
@testable import TeleplyState

/// The list's red [草稿] (WeChat; user 10-26): a conversation left with words in its box shows them on its row, after
/// another start of the app too, until they are sent or cleared.
@MainActor
struct DraftMarkTests {
    /// The list of the first demo computer, as if it were the real service, on [store].
    func listOn(_ store: LocalStore) async -> AppModel {
        let model = makeApp(store: store)
        model.login(name: "x", password: "y")
        await model.settle()
        model.select(model.account!.devices[0])
        await model.settle()
        return model
    }

    /// Opens [chat] and waits until its box can be written and sent (the live round stays open, so not for that).
    func enter(_ model: AppModel, _ chat: Chat) async {
        model.open(chat)
        await model.settle()
        for _ in 0..<5_000 where !(model.conversation.ready && model.conversation.control.available) { await Task.yield() }
    }

    @Test func wordsLeftInTheBoxShowOnTheRowUntilSent() async throws {
        let store = LocalStore(folder: temporaryFolder())
        let model = await listOn(store)
        let chat = try #require(model.chats.first { $0.title == "原生阅读示例" })
        #expect(model.drafts.isEmpty)
        await enter(model, chat)
        model.conversation.edit("先写一半\n  第二行")
        #expect(model.drafts.isEmpty)
        model.back()
        #expect(model.drafts[rowKey(chat)] == "先写一半 第二行")
        await model.conversation.flushDraft()

        // Another start of the app reads it from this phone.
        let again = await listOn(store)
        #expect(again.drafts[rowKey(chat)] == "先写一半 第二行")
        await enter(again, chat)
        #expect(again.conversation.draft == "先写一半\n  第二行")
        again.conversation.send()
        await again.conversation.settleSends()
        #expect(again.conversation.draft.isEmpty)
        again.back()
        #expect(again.drafts[rowKey(chat)] == nil)
    }

    @Test func aBoxClearedByHandLosesItsMark() async throws {
        let model = await listOn(LocalStore(folder: temporaryFolder()))
        let chat = try #require(model.chats.first { $0.title == "原生阅读示例" })
        await enter(model, chat)
        model.conversation.edit("要删掉的话")
        model.back()
        #expect(model.drafts[rowKey(chat)] == "要删掉的话")
        await enter(model, chat)
        model.conversation.edit("   ")
        model.back()
        #expect(model.drafts.isEmpty)
    }

    @Test func theStoreFindsOnlyThisComputersDrafts() async {
        let store = LocalStore(folder: temporaryFolder())
        await store.setDraft(ChatKey(scope: "s", device: "d1", app: "codex", chat: "a"), "这一台")
        await store.setDraft(ChatKey(scope: "s", device: "d2", app: "codex", chat: "b"), "另一台")
        await store.setDraft(ChatKey(scope: "t", device: "d1", app: "codex", chat: "c"), "另一次登录")
        await store.setDraft(ChatKey(scope: "s", device: "d1", app: "claude", chat: "d"), "   ")
        await store.setDraft(ChatKey(scope: "s", device: "d1", app: "deepseek", chat: "new:x/y"), "新对话页")
        let found = await store.drafts(scope: "s", device: "d1")
        #expect(found == [ChatKey(scope: "s", device: "d1", app: "codex", chat: "a"): "这一台",
                          ChatKey(scope: "s", device: "d1", app: "deepseek", chat: "new:x/y"): "新对话页"])
    }

    @Test func aDraftShowsAsOneShortLine() {
        #expect(draftPreview("  第一行\n\n第二行\t尾  ") == "第一行 第二行 尾")
        #expect(draftPreview(" \n ").isEmpty)
        #expect(draftPreview(String(repeating: "字", count: 150)).count == 100)
    }
}
