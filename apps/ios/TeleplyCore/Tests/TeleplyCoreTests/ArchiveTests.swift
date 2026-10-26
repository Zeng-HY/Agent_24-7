import Foundation
import Testing
@testable import TeleplyDemo
import TeleplyModel
@testable import TeleplyState

/// 左滑归档, 撤销 and 已归档对话 on the local demo (Android ReaderUiScenarios archive cases).
@MainActor
struct ArchiveTests {
    func demoList() async -> AppModel {
        let model = makeApp()
        model.openDemo()
        model.login(name: "x", password: "y")
        await model.settle()
        model.select(model.account!.devices[0])
        await model.settle()
        return model
    }

    @Test func aRowLeavesAtOnceAndUndoBringsItBack() async throws {
        let model = await demoList()
        let row = model.chats.first { $0.title == "只读问题记录" }!
        model.archive(row)
        #expect(!model.chats.contains { $0.id == row.id })
        #expect(model.undo?.chat.id == row.id && model.undo?.waiting == false)
        await model.settleArchives()
        let archived = try await model.deviceCall("chat/archived")
        #expect(archived["items"].array.map { $0["id"].string() } == ["question"])
        model.undoArchive()
        #expect(model.chats.contains { $0.id == row.id })
        await model.settleArchives()
        #expect(model.notice == "已恢复")
        #expect(try await model.deviceCall("chat/archived")["items"].array.isEmpty)
    }

    @Test func aRunningConversationIsNotArchived() async {
        let model = await demoList()
        var row = model.chats.first { $0.title == "只读问题记录" }!
        row.status = "running"
        model.archive(row)
        #expect(model.notice == "这个对话正在运行，先停止这一轮再归档")
        #expect(model.chats.contains { $0.id == row.id })
    }

    @Test func claudeWaitsForItsDesktopBeforeUndoIsOffered() async {
        let model = await demoList()
        let row = model.chats.first { $0.app == "claude" && $0.status != "running" }!
        model.archive(row)
        #expect(model.undo?.waiting == true)
        model.undoArchive()
        #expect(model.undo != nil)
        await model.settleArchives()
        #expect(model.undo?.waiting == false)
    }

    @Test func codexArchivesCanBeDeletedAfterConfirmingOthersOnlyRestored() async throws {
        let model = await demoList()
        model.archive(model.chats.first { $0.title == "只读问题记录" }!)
        model.archive(model.chats.first { $0.app == "deepseek" && !$0.group }!)
        await model.settleArchives()
        let list = try await model.deviceCall("chat/archived")
        #expect(list["items"].array.map { $0["app"].string() } == ["codex", "deepseek"])
        #expect(list["items"].array.map { $0["can_delete"].bool() } == [true, false])
        let refused = try? await model.deviceCall("chat/delete", body: ["items": [["app": "codex", "id": "question"]]])
        #expect(refused == nil)
        let gone = try await model.deviceCall("chat/delete", body: ["items": [["app": "codex", "id": "question"], ["app": "deepseek", "id": "deepseek-demo"]], "confirmed": true])
        #expect(gone["deleted"].int64() == 1)
        #expect(gone["results"].array.last?["error"].string() == "这种对话还不能删除")
        _ = try await model.deviceCall("chat/unarchive", body: ["app": "deepseek", "id": "deepseek-demo"])
        model.restored(app: "deepseek", id: "deepseek-demo")
        await model.settle()
        #expect(model.chats.contains { $0.id == "deepseek-demo" })
        #expect(!model.chats.contains { $0.id == "question" })
    }
}
