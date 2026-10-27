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
        #expect(workspace.preview == nil && workspace.fileNote.isEmpty && workspace.paneError == nil)
        // Without "preview": "pdf" no PDF is asked for: the page is as before.
        #expect(workspace.officePDF == nil && !workspace.converting && workspace.convertNote.isEmpty)
        #expect(await !watched.log.items.contains { $0.url.path.hasSuffix("/api/file/pdf") })
        let copy = try await workspace.fileCopy()
        #expect(copy.lastPathComponent == "翻译稿.docx")
        #expect(try Data(contentsOf: copy) == DemoData.docx)
        // The whole conversation's files still list it beside the others.
        workspace.panel("files")
        await workspace.settle()
        #expect(workspace.data["items"].array.count == 5)
    }

    /// A Word file the computer's Office can open shows as the PDF it makes (Windows dev.26); 保存到文件, 分享 and 快速查看
    /// still take the Word file itself, and the PDF goes with the page.
    @Test func anOfficeFileShowsAsTheComputersPDFAndSavesItself() async throws {
        let model = await demoConversation("原生阅读示例")
        let workspace = model.workspace
        workspace.panel("files")
        await workspace.settle()
        let report = try #require(workspace.data["items"].array.first { $0["preview"].string() == "pdf" })
        workspace.file(report)
        await workspace.settle()
        #expect(workspace.data["kind"].string() == "download" && workspace.preview == nil && workspace.paneError == nil)
        #expect(!workspace.converting && workspace.convertNote.isEmpty)
        let pdf = try #require(workspace.officePDF)
        #expect(try Data(contentsOf: pdf) == DemoData.pdf)
        let copy = try await workspace.fileCopy()
        #expect(copy.lastPathComponent == "发布说明.docx")
        #expect(try Data(contentsOf: copy) == DemoData.docx)
        workspace.close()
        #expect(workspace.officePDF == nil && !FileManager.default.fileExists(atPath: pdf.path))
    }

    /// The first time can take half a minute: the page offers the file meanwhile and says what it waits for.
    @Test func whileOfficeWorksThePageAlreadyOffersTheFile() async throws {
        let world = DemoWorld()
        let model = await demoConversation("原生阅读示例", on: DemoTransport(world: world))
        let workspace = model.workspace
        world.network = .normal
        workspace.file(DemoData.files[3])
        for _ in 0..<300 where workspace.paneBusy { try await Task.sleep(for: .milliseconds(10)) }
        #expect(!workspace.paneBusy && workspace.converting && workspace.officePDF == nil)
        #expect(workspace.data["meta"]["preview"].string() == "pdf")
        await workspace.settle()
        #expect(!workspace.converting && workspace.officePDF != nil)
    }

    /// The computer's Office could not make it: its words, and the file can still be saved. A row's own "preview": "pdf"
    /// is enough to ask (the computer's facts of 翻译稿.docx leave it out).
    @Test func anOfficeFileTheComputerCannotShowSaysWhyAndStillSaves() async throws {
        let watched = WatchedTransport()
        let model = await demoConversation("原生阅读示例", on: watched)
        let workspace = model.workspace
        workspace.file(["id": "fixture-office-broken", "name": "旧格式报告.doc"])
        await workspace.settle()
        #expect(workspace.paneError == nil && !workspace.converting && workspace.officePDF == nil)
        #expect(workspace.convertNote == "电脑上的 Word 打不开这个文件，没能转成 PDF")
        let copy = try await workspace.fileCopy()
        #expect(copy.lastPathComponent == "旧格式报告.doc")
        workspace.file(["id": "fixture-docx", "name": "翻译稿.docx", "preview": "pdf"])
        await workspace.settle()
        #expect(await watched.log.items.filter { $0.url.path.hasSuffix("/api/file/pdf") }.compactMap { queryValue($0, "file") }
            == ["fixture-office-broken", "fixture-docx"])
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
