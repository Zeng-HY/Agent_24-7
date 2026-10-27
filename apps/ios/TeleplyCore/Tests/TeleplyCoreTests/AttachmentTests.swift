import Foundation
import Testing
@testable import TeleplyDemo
import TeleplyModel
@testable import TeleplyState

/// Attachments, references, conversation files and diffs on the local demo (Android ReaderUiScenarios T08, T10).
@MainActor
struct AttachmentTests {
    /// [title] opened in the local demo, on [demo] when given (to watch its requests or slow it).
    func demoConversation(_ title: String, on demo: (any RelayTransport)? = nil) async -> AppModel {
        let model = demo.map { transport in
            AppModel(services: AppServices(store: LocalStore(folder: temporaryFolder()), vault: MemoryCookieVault(), transport: DemoTransport(),
                                           demo: { transport }, pacer: IdlePacer(), newScope: { "scope-1" }))
        } ?? makeApp()
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
        workspace.computerFile(workspace.data["items"].array.first!)
        await workspace.settle()
        workspace.addComputerFile()
        #expect(workspace.picker == nil)
        #expect(workspace.saved["references"].array.map { $0["name"].string() } == ["固定引用", "遥应下载测试.txt"])
        workspace.removeReference("fixture-reference")
        #expect(try workspace.sendExtras()["references"].array.count == 1)
    }

    @Test func aFilePageHasItsTextOrACopyAndTheDiffIsTheRecords() async throws {
        let model = await demoConversation("原生阅读示例")
        let workspace = model.workspace
        workspace.panel("files")
        await workspace.settle()
        let files = workspace.data["items"].array
        #expect(files.count == 4)
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

    @Test func aComputerFileOpensItsPageToSaveThenGoesBackToItsFolder() async throws {
        let model = await demoConversation("原生阅读示例")
        let workspace = model.workspace
        workspace.openPicker("remote")
        workspace.refresh("remote", query: "D:/fixture")
        await workspace.settle()
        let row = try #require(workspace.data["items"].array.first)
        workspace.computerFile(row)
        await workspace.settle()
        #expect(workspace.picker == "file" && workspace.pane == nil)
        #expect(workspace.data["id"].string() == "fixture-download")
        #expect(workspace.data["kind"].string() == "download")
        #expect(workspace.data["meta"]["size"].int64() == 18)
        let copy = try await workspace.fileCopy()
        #expect(copy.lastPathComponent == "遥应下载测试.txt")
        #expect(try String(contentsOf: copy, encoding: .utf8) == "固定测试内容")
        #expect(!workspace.transferring && workspace.transfer.isEmpty)
        // Saving does not attach it.
        #expect(workspace.saved["references"].array.isEmpty)
        workspace.leaveComputerFile()
        #expect(workspace.picker == "remote")
        #expect(workspace.data["path"].string() == "D:/fixture")
        // A computer too old to hand out tickets says so instead of opening a page that cannot download.
        var old = row.object
        old.removeValue(forKey: "download_id")
        workspace.computerFile(.object(old))
        #expect(workspace.picker == "remote")
        #expect(workspace.paneError == "请更新电脑端后下载文件")
    }

    @Test func aDeepSeekResultIsListedForItsMessageAndDownloadsWhole() async throws {
        let watched = WatchedTransport()
        let model = await demoConversation("DeepSeek 批准示例", on: watched)
        #expect(model.messages.first { $0.id == "d0b" }?.kind == "deliverables")
        let workspace = model.workspace
        workspace.filesOf(message: "d0b")
        await workspace.settle()
        #expect(workspace.pane == "files")
        let files = workspace.data["items"].array
        #expect(files.map { $0["name"].string() } == ["翻译稿.docx"])
        workspace.file(files[0])
        await workspace.settle()
        #expect(workspace.data["kind"].string() == "download")
        #expect(workspace.fileNote.isEmpty && workspace.paneError == nil)
        // The page shows the Word file itself.
        let shown = try #require(workspace.preview)
        #expect(shown.lastPathComponent == "翻译稿.docx")
        #expect(try Data(contentsOf: shown) == DemoData.docx)
        let copy = try await workspace.fileCopy()
        #expect(copy.lastPathComponent == "翻译稿.docx")
        #expect(try Data(contentsOf: copy) == DemoData.docx)
        // Saving took the page's copy: the file was fetched once.
        #expect(await watched.log.items.filter { $0.url.path.hasSuffix("/api/file") }.count == 1)
        // The whole conversation's files still list it beside the others.
        workspace.panel("files")
        await workspace.settle()
        #expect(workspace.data["items"].array.count == 5)
    }

    /// A Word file shows as itself even where the computer offers its PDF ("preview": "pdf", Windows dev.26): the page
    /// has a copy of the .docx and nothing is asked of the computer's Office (user 10-28: "不要这样转换了"). The copy
    /// goes with the page.
    @Test func anOfficeFileShowsAsItselfAndNeverAsksForAPDF() async throws {
        let watched = WatchedTransport()
        let model = await demoConversation("原生阅读示例", on: watched)
        let workspace = model.workspace
        workspace.panel("files")
        await workspace.settle()
        let report = try #require(workspace.data["items"].array.first { $0["preview"].string() == "pdf" })
        workspace.file(report)
        await workspace.settle()
        #expect(workspace.data["kind"].string() == "download" && workspace.paneError == nil && workspace.fileNote.isEmpty)
        let shown = try #require(workspace.preview)
        #expect(shown.lastPathComponent == "发布说明.docx")
        #expect(try Data(contentsOf: shown) == DemoData.docx)
        #expect(await !watched.log.items.contains { $0.url.path.hasSuffix("/api/file/pdf") })
        workspace.close()
        #expect(workspace.preview == nil && !FileManager.default.fileExists(atPath: shown.path))
    }

    /// Over 20 MB a file is not fetched by opening its page; saving it still downloads it whole.
    @Test func anOfficeFileOver20MBWaitsToBeAskedFor() async throws {
        let watched = WatchedTransport()
        let model = await demoConversation("原生阅读示例", on: watched)
        let workspace = model.workspace
        workspace.file(["id": "fixture-office-big", "name": "季度汇报.pptx"])
        await workspace.settle()
        #expect(workspace.paneError == nil && workspace.fileNote.isEmpty && workspace.preview == nil)
        #expect(workspace.data["meta"]["size"].int64() > RelayClient.previewLimit)
        #expect(await !watched.log.items.contains { $0.url.path.hasSuffix("/api/file") || $0.url.path.hasSuffix("/api/file/pdf") })
        let copy = try await workspace.fileCopy()
        #expect(copy.lastPathComponent == "季度汇报.pptx")
        #expect(await watched.log.items.filter { $0.url.path.hasSuffix("/api/file") }.compactMap { queryValue($0, "file") } == ["fixture-office-big"])
    }

    /// Office files, the pictures the computer lists as plain files, sound and video show in the page, whatever the
    /// letters' case; text, iWork, archives and names without an extension do not.
    @Test func whatAPageShowsByItself() {
        for name in ["报告.DOCX", "表.xlsx", "旧.doc", "汇报.pptx", "动图.gif", "照片.HEIC", "录音.m4a", "视频.mp4", "DJI_0194_D.MP4"] {
            #expect(WorkspaceModel.showsInPage(name), "\(name)")
        }
        for name in ["说明.txt", "说明.pages", "包.zip", "图.svg", "没有扩展名", "末尾是点.", ".docx.zip"] {
            #expect(!WorkspaceModel.showsInPage(name), "\(name)")
        }
    }

    @Test func aPreviewThatDoesNotLoadLeavesTheFileToSave() async throws {
        let model = await demoConversation("原生阅读示例")
        let workspace = model.workspace
        workspace.file(["id": "fixture-broken", "name": "报告.txt"])
        await workspace.settle()
        #expect(workspace.paneError == nil && !workspace.paneBusy)
        #expect(workspace.fileNote == "预览未能加载，仍可尝试保存原文件。")
        #expect(workspace.fileText.isEmpty)
        let copy = try await workspace.fileCopy()
        #expect(copy.lastPathComponent == "报告.txt")
        workspace.close()
        #expect(workspace.fileNote.isEmpty)
    }

    @Test func aDownloadCanBeCancelled() async throws {
        let world = DemoWorld()
        let model = makeApp(world: world)
        model.login(name: "x", password: "y")
        await model.settle()
        model.select(model.account!.devices[0])
        await model.settle()
        model.open(model.chats.first { $0.title == "原生阅读示例" }!)
        await model.settle()
        let workspace = model.workspace
        await workspace.settle()
        workspace.file(["id": "fixture-md", "name": "说明.md"])
        await workspace.settle()
        world.network = .slow
        let copying = Task { try await workspace.fileCopy() }
        for _ in 0..<1_000 where !workspace.transferring { await Task.yield() }
        #expect(workspace.transfer == "正在下载…")
        workspace.cancelCopy()
        await #expect(throws: CancellationError.self) { try await copying.value }
        #expect(!workspace.transferring && workspace.transfer.isEmpty)
    }

    @Test func aFileLinkInAnAnswerOpensThePageOfTheListedFileOnly() async {
        let model = await demoConversation("原生阅读示例")
        let workspace = model.workspace
        workspace.openLinkedFile("d:/FIXTURE/说明.md")
        await workspace.settle()
        #expect(workspace.pane == "file")
        #expect(workspace.data["id"].string() == "fixture-md")
        workspace.close()
        workspace.openLinkedFile(#"D:\fixture\secret.txt"#)
        await workspace.settle()
        #expect(workspace.pane == nil)
        #expect(workspace.error?.contains("不在电脑列出的对话文件里") == true)
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
