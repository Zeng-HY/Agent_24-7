import Foundation
import Testing
@testable import TeleplyDemo
import TeleplyModel
@testable import TeleplyState

/// Attachments, references, conversation files and diffs on the local demo (Android ReaderUiScenarios T08, T10).
@MainActor
struct AttachmentTests {
    func demoConversation(_ title: String) async -> AppModel {
        let model = makeApp()
        model.openDemo()
        model.login(name: "x", password: "y")
        await model.settle()
        model.select(model.account!.devices[0])
        await model.settle()
        model.open(model.chats.first { $0.title == title }!)
        await model.settle()
        await model.conversation.settle()
        await model.workspace.settle()
        return model
    }

    /// A file of [size] bytes the model takes over.
    func staged(_ name: String, size: Int) throws -> URL {
        let folder = temporaryFolder()
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        let file = folder.appendingPathComponent(name)
        try Data(repeating: 0x41, count: size).write(to: file)
        return file
    }

    @Test func aPictureAndAFileGoUpThenWithTheSendAndLeaveTheCard() async throws {
        let model = await demoConversation("原生阅读示例")
        let workspace = model.workspace
        let picture = try staged("photo.heic", size: 1_000)
        workspace.importFile(picture, name: "photo.heic", image: true)
        #expect(workspace.saved["uploads"].array.first?["status"].string() == "uploading")
        #expect(throws: (any Error).self) { try workspace.sendExtras() }
        workspace.importFile(try staged("notes.txt", size: 10), name: "notes.txt", image: false)
        await workspace.settle()
        #expect(!FileManager.default.fileExists(atPath: picture.path))
        let rows = workspace.saved["uploads"].array
        #expect(rows.map { $0["status"].string() } == ["ready", "ready"])
        #expect(rows[0]["meta"]["original_size"].int64() == 1_000)
        let extras = try workspace.sendExtras()
        #expect(extras["attachments"].array.count == 1)
        #expect(extras["references"].array.first?["name"].string() == "notes.txt")
        model.conversation.edit("看看这两个")
        model.conversation.send()
        await model.conversation.settle()
        await workspace.settle()
        let body = jsonValue(model.conversation.submissions.first!.body)
        #expect(body["attachments"].array.count == 1)
        #expect(body["references"].array.count == 1)
        #expect(workspace.saved["uploads"].array.isEmpty)
    }

    @Test func aFileOverTheRelaysLimitIsRefusedWithWhyAndCanBeRemoved() async throws {
        let model = await demoConversation("原生阅读示例")
        let workspace = model.workspace
        let big = try staged("big.zip", size: Int(RelayClient.fileLimit) + 1)
        workspace.importFile(big, name: "big.zip", image: false)
        await workspace.settle()
        let row = workspace.saved["uploads"].array.first
        #expect(row?["status"].string() == "failed")
        #expect(row?["error"].string() == "文件超过 64MB，中转一次最多传 64MB")
        #expect(throws: (any Error).self) { try workspace.sendExtras() }
        workspace.removeUpload(row!["local"].string())
        await workspace.settle()
        #expect(workspace.saved["uploads"].array.isEmpty)
        #expect(!FileManager.default.fileExists(atPath: big.path))
    }

    @Test func atMostFivePictures() async throws {
        let model = await demoConversation("原生阅读示例")
        for index in 0..<6 { model.workspace.importFile(try staged("p\(index).jpg", size: 10), name: "p\(index).jpg", image: true) }
        await model.workspace.settle()
        #expect(model.workspace.saved["uploads"].array.count == 5)
        #expect(model.workspace.error == "最多5张图片")
    }

    @Test func referencesArePickedOverTheConversationAndGoWithTheSend() async throws {
        let model = await demoConversation("原生阅读示例")
        let workspace = model.workspace
        workspace.openPicker("chat")
        await workspace.settle()
        #expect(workspace.picker == "chat")
        let found = workspace.data["items"].array.first!
        workspace.addReference(found)
        workspace.addReference(found)
        workspace.closePicker()
        workspace.openPicker("remote")
        await workspace.settle()
        #expect(workspace.data["items"].array.first?["path"].string() == "D:/fixture")
        workspace.refresh("remote", query: "D:/fixture")
        await workspace.settle()
        workspace.addReference(workspace.data["items"].array.first!)
        workspace.closePicker()
        #expect(workspace.saved["references"].array.map { $0["name"].string() } == ["固定引用", "测试.txt"])
        workspace.removeReference("fixture-reference")
        #expect(try workspace.sendExtras()["references"].array.count == 1)
    }

    @Test func aFilePageHasItsTextOrACopyAndTheDiffIsTheRecords() async throws {
        let model = await demoConversation("原生阅读示例")
        let workspace = model.workspace
        workspace.panel("files")
        await workspace.settle()
        let files = workspace.data["items"].array
        #expect(files.count == 3)
        workspace.file(files.first { $0["id"].string() == "fixture-md" }!)
        await workspace.settle()
        #expect(workspace.pane == "file")
        #expect(workspace.fileText.hasPrefix("# 说明"))
        #expect(workspace.preview == nil)
        workspace.file(files.first { $0["id"].string() == "fixture-png" }!)
        await workspace.settle()
        let preview = try #require(workspace.preview)
        #expect(FileManager.default.fileExists(atPath: preview.path))
        let copy = try await workspace.fileCopy()
        #expect(copy.lastPathComponent == "logo.png")
        workspace.close()
        #expect(!FileManager.default.fileExists(atPath: preview.path))
        workspace.diff("fixture-diff")
        await workspace.settle()
        #expect(workspace.pane == "diff")
        #expect(workspace.data["hunks"].array.first?.string().contains("+新内容") == true)
    }

    @Test func anHTMLPageGetsOnlyTheListedFileBesideIt() async {
        let model = await demoConversation("原生阅读示例")
        let page = DemoData.files[0]
        let found = await model.workspace.previewResource(for: page, path: "D:/fixture/images/logo.png")
        #expect(found?.count == 462)
        let missing = await model.workspace.previewResource(for: page, path: "D:/fixture/secret.txt")
        #expect(missing == nil)
    }

    @Test func pathsCompareAsTheWebDoes() {
        #expect(normalizePath("D:\\Fixture\\images\\..\\logo.PNG") == "d:/fixture/logo.png")
        #expect(normalizePath("./a//b/./c") == "a/b/c")
        #expect(relativeResource("images/logo.png"))
        #expect(!relativeResource("https://example.com/x.png"))
        #expect(!relativeResource("/etc/passwd"))
        #expect(!relativeResource("a.png?x=1"))
    }
}
