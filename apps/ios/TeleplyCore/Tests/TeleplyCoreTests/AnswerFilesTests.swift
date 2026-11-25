import Foundation
import Testing
@testable import TeleplyDemo
@testable import TeleplyModel

/// The answer side of the file-preview design, first stage (iOS 0.9.1): an answer's `files` and `file_notes` (§5.1), a
/// link found by its path (§6.1), the reasons (§6.4), the file strip's cards, the pictures drawn in place and the thumb
/// cache (§7). Everything is made up; no computer is read.
struct AnswerFilesTests {
    private func ref(_ id: String, _ path: String = "D:\\work\\out\\file", view: String = "code",
                     via: [String] = ["link"], thumb: Bool = false, texts: [String] = [], state: String = "current",
                     version: String = "v1") -> FileRef {
        FileRef(id: id, name: id, path: path, kind: view == "image" || view == "svg" ? "image" : "text",
                view: view, state: state, version: version, thumb: thumb, texts: texts, via: via)
    }

    private func picturePieces(_ source: String, _ files: [FileRef]?) -> [MarkdownPiece] {
        for block in MarkdownReader.answerBlocks(source, files: files) {
            if case .pictureParagraph(let pieces) = block { return pieces }
        }
        return []
    }

    private func hasPicture(_ pieces: [MarkdownPiece]) -> Bool {
        pieces.contains { piece in
            if case .picture = piece { return true }
            return false
        }
    }

    private func plain(_ blocks: [MarkdownBlock]) -> String {
        var words = ""
        func walk(_ blocks: [MarkdownBlock]) {
            for block in blocks {
                switch block {
                case .heading(_, let runs), .paragraph(let runs):
                    words += runs.plain
                case .pictureParagraph(let pieces):
                    for piece in pieces {
                        if case .words(let runs) = piece { words += runs.plain }
                    }
                case .quote(let children):
                    walk(children)
                case .list(_, _, let items):
                    for item in items { walk(item) }
                default:
                    break
                }
            }
        }
        walk(blocks)
        return words
    }

    // MARK: §5.1: what the computer sent

    @Test func aNewComputerSaysSoWithFilesEvenAnEmptyList() throws {
        let older = try parseMessage(JSONValue.parse(Data(#"{"id":"m1","role":"assistant","text":"hi"}"#.utf8)))
        #expect(older.files == nil)
        #expect(older.fileNotes.isEmpty)
        let empty = try parseMessage(JSONValue.parse(Data(#"{"id":"m2","role":"assistant","text":"hi","files":[]}"#.utf8)))
        #expect(empty.files?.isEmpty == true)
        let full = try parseMessage(JSONValue.parse(Data("""
            {"id":"m3","role":"assistant","text":"x",
             "files":[{"id":"3f0c","name":"chart.png","path":"D:\\\\work\\\\out\\\\chart.png","kind":"image","view":"image",
                       "size":183422,"modified":1764031000000,"state":"current","v":"9f2c41d0","w":2400,"h":1500,"thumb":true,"via":["image","link"]}],
             "file_notes":[{"href":"out/old.png","reason":"not_found","text":"电脑上没找到这个文件"}]}
            """.utf8)))
        #expect(full.files?.count == 1)
        let file = try #require(full.files?.first)
        #expect(file.name == "chart.png")
        #expect(file.path == "D:\\work\\out\\chart.png")
        #expect(file.width == 2400 && file.height == 1500)
        #expect(file.modified == 1_764_031_000_000)
        #expect(file.stableVersion == "9f2c41d0")
        #expect(file.picture)
        #expect(file.via == ["image", "link"])
        #expect(full.fileNotes == [FileNote("out/old.png", "not_found", "电脑上没找到这个文件")])
        // The entry carries over into the file page's JSON unchanged, with its `v`.
        #expect(file.pageJSON["v"].string() == "9f2c41d0")
        #expect(file.pageJSON["view"].string() == "image")
        #expect(file.pageJSON["texts"].isNull)
    }

    @Test func aLinkFindsItsFileByPathAndAPictureOnlyWhenItCanBeDrawn() {
        let files = [
            ref("a", "D:\\Work\\Out\\A.R"),
            ref("b", "D:\\work\\out\\b.png", view: "image", thumb: true),
            ref("c", "D:\\work\\out\\c.svg", view: "svg", thumb: false),
        ]
        // Slashes and case do not matter (§5.1); a line number after the path names the same file.
        #expect(fileForLink(files, "D:/work/out/a.R:12-20")?.id == "a")
        #expect(fileForLink(files, "D:\\work\\out\\b.png")?.id == "b")
        #expect(fileForLink(files, "D:\\work\\out\\missing.png") == nil)
        #expect(fileForLink(files, "https://example.invalid/a") == nil)
        // An SVG the computer cannot make a thumb of stays a card, not a picture in the text (§5.1, 6.1).
        #expect(pictureForImage(files, "D:\\work\\out\\c.svg") == nil)
        #expect(pictureForImage(files, "D:\\work\\out\\b.png")?.id == "b")
    }

    @Test func theReasonIsFoundByItsDecodedHrefAndSaysWhatTheDesignSays() {
        let notes = [FileNote("out/%E6%97%A7%E5%9B%BE.png", "not_found"), FileNote("//nas/share/r.pdf", "not_local")]
        #expect(noteForLink(notes, "out/旧图.png")?.reason == "not_found")
        #expect(noteForLink(notes, "//nas/share/r.pdf")?.reason == "not_local")
        #expect(noteForLink(notes, "out/other.png") == nil)
        #expect(fileNoteShort("not_found") == "找不到文件")
        #expect(fileNoteFull("not_found") == "电脑上没找到这个文件（回答写的是相对位置，在对话文件夹里没找到）")
        #expect(fileNoteFull("not_local") == "文件在网络位置或别的电脑上，遥应只读这台电脑自己的磁盘")
        #expect(fileNoteFull("missing") == "文件已移动或删除")
        #expect(fileNoteFull("local_web") == "这是电脑本机的网址，手机打不开")
    }

    // MARK: §6.1: pictures drawn where the answer put them

    @Test func aParagraphWithAPictureSplitsIntoWordsPictureWords() {
        let files = [ref("fig", "D:\\a\\fig.png", view: "image", thumb: true)]
        let three = picturePieces("前文 ![图](<D:/a/fig.png>) 后文", files)
        #expect(three.count == 3)
        guard case .picture(let picture) = three[1] else {
            Issue.record("expected a picture in the middle")
            return
        }
        #expect(picture.id == "fig")
        guard case .words(let before) = three[0], case .words(let after) = three[2] else {
            Issue.record("expected words either side")
            return
        }
        #expect(before.plain.contains("前文"))
        #expect(after.plain.contains("后文"))
        // A picture inside a link or emphasis is still found, not turned into a line of text.
        #expect(hasPicture(picturePieces("[![图](<D:/a/fig.png>)](https://example.invalid)", files)))
        #expect(hasPicture(picturePieces("**![图](<D:/a/fig.png>)**", files)))
        // Without a picture (or without the newer computer's files) the paragraph stays one piece of words.
        #expect(picturePieces("只有文字，没有图。", files).isEmpty)
        #expect(picturePieces("前文 ![图](<D:/a/fig.png>) 后文", nil).isEmpty)
        // A picture the computer cannot thumb stays words, as §5.1 says.
        let svg = [ref("svg", "D:\\a\\fig.svg", view: "svg", thumb: false)]
        #expect(!hasPicture(picturePieces("前文 ![图](<D:/a/fig.svg>) 后文", svg)))
        // A code sample's `![` is not a picture: the test is by Markdown node, not by its words.
        let code = "`![图](<D:/a/fig.png>)`"
        #expect(picturePieces(code, files).isEmpty)
        #expect(plain(MarkdownReader.answerBlocks(code, files: files)).contains("![图]"))
    }

    @Test func theThumbWidthFollowsTheBubbleInPixels() {
        #expect(pictureWidth(320) == 640)
        #expect(pictureWidth(640) == 640)
        #expect(pictureWidth(641) == 1280)
        #expect(pictureWidth(1290) == 1280)
        #expect(answerThumbWidth(320) == 320)
        #expect(answerThumbWidth(640) == 640)
        #expect(answerThumbWidth(1200) == 1280)
        #expect(answerThumbWidth(2048) == 2048)
        #expect(answerThumbWidth(4096) == 4096)
    }

    // MARK: §6.1: links, reasons and the older computer

    @Test func aNewComputerOpensTheFileEntryAndSaysWhyALinkCannotBeGiven() throws {
        var files = [ref("run", "D:\\work\\out\\run.R", texts: ["D:/work/out/run.R"])]
        files.append(ref("chart", "D:\\work\\out\\chart.png", view: "image", thumb: true))
        let source = """
        见 [脚本](D:/work/out/run.R)，还有 [旧图](out/old.png)；[#页内](#part) 和 [信箱](mailto:a@example.invalid)。
        """
        let notes = [FileNote("out/old.png", "not_found")]
        let blocks = MarkdownReader.answerBlocks(source, files: files, notes: notes)
        let runs = blocks.flatMap { block -> [InlineRun] in
            if case .paragraph(let runs) = block { return runs }
            return []
        }
        let script = try #require(runs.first { $0.text == "脚本" })
        let url = try #require(script.link.flatMap(URL.init(string:)))
        #expect(answerItem(url)?.id == "run")
        let old = try #require(runs.first { $0.text == "旧图" })
        let why = try #require(old.link.flatMap(URL.init(string:)).flatMap(answerNote))
        #expect(why.reason == "not_found")
        #expect(runs.contains { $0.text == "（找不到文件）" && $0.muted })
        #expect(!runs.plain.contains("链接未开放"))
    }

    @Test func anOlderComputerStillSaysWhenAFileLikeLinkCannotOpen() {
        #expect(fileLikeLink("out/old.png"))
        #expect(fileLikeLink("/D:/work/out/a.pdf"))
        #expect(fileLikeLink("file:///D:/a/b.png"))
        #expect(fileLikeLink("~/notes/a.md"))
        #expect(fileLikeLink("docs\\release.md"))
        #expect(!fileLikeLink("https://example.invalid/a"))
        #expect(!fileLikeLink("#part-2"))
        #expect(!fileLikeLink("mailto:a@example.invalid"))
        #expect(!fileLikeLink("javascript:alert(1)"))

        let old = MarkdownReader.answerBlocks("见 [旧图](out/old.png)，[#页内](#part)，[信箱](mailto:a@example.invalid)。", files: nil)
        let words = plain(old)
        #expect(words.contains("（链接未开放）"))
        // `#` and `mailto:` are words only.
        #expect(!words.contains("（链接未开放）（链接未开放）"))
        let anchorsOnly = plain(MarkdownReader.answerBlocks("[#页内](#part) [信箱](mailto:a@example.invalid)", files: nil))
        #expect(!anchorsOnly.contains("链接未开放"))
        // A web address on the computer itself says so, on a newer computer too.
        let local = plain(MarkdownReader.answerBlocks("[开发服务器](http://localhost:3000)", files: []))
        #expect(local.contains("（电脑本机网址，手机打不开）"))
    }

    @Test func notEverythingIsALinkAndALocalAddressSaysSo() {
        #expect(plainLink("#part-2"))
        #expect(plainLink("mailto:a@example.invalid"))
        #expect(plainLink("javascript:alert(1)"))
        #expect(!plainLink("https://example.invalid/a"))
        #expect(localWebLink("http://localhost:3000/a"))
        #expect(localWebLink("https://127.0.0.1:8443"))
        #expect(localWebLink("http://[::1]:3000"))
        #expect(!localWebLink("https://example.invalid"))
        #expect(!localWebLink("http://localhost.example.invalid"))
    }

    // MARK: §5.1 `texts`: code and path words open their file

    @Test func wordsOfACodeOrPathFileBecomeALinkUnlessTheyAlreadyAreOne() {
        var files = [ref("run", "D:\\a\\run.R", texts: ["D:/a/run.R"])]
        files.append(ref("report", "D:\\a\\report.txt", view: "text", texts: ["D:/a/report.txt"]))
        let linked = linkingFileTexts([InlineRun("见 D:/a/run.R，再读 D:/a/report.txt。")], files: files)
        #expect(linked.count == 5)
        #expect(linked[1].text == "D:/a/run.R")
        #expect(linked[1].link.flatMap(URL.init(string:)).flatMap(answerItem)?.id == "run")
        #expect(linked[3].link.flatMap(URL.init(string:)).flatMap(answerItem)?.id == "report")
        // Words already inside another link keep that one: one piece of text never carries two targets.
        let already = linkingFileTexts([InlineRun("D:/a/run.R", link: "https://example.invalid")], files: files)
        #expect(already.count == 1)
        #expect(already[0].link == "https://example.invalid")
    }

    // MARK: §6.1: the strip

    @Test func theStripLeavesOutWhatIsDrawnOrWrittenAsAPathAndKeepsEight() {
        let drawn = Set(["pic"])
        let many = (1...12).map { ref("f\($0)", view: "code", via: ["presented"]) }
        var message = Message(id: "m", role: "assistant", text: "t")
        message.files = many + [
            ref("pic", view: "image", via: ["image"], thumb: true),
            ref("code", via: ["code"]),
            ref("path", via: ["path"]),
            ref("dup", via: ["link"]),
            ref("dup", via: ["citation"]),
        ]
        let strip = fileStripFiles(message, drawn: drawn)
        #expect(strip.map(\.id) == (1...12).map { "f\($0)" } + ["dup"])
        #expect(fileStripExtra(strip) == 5)
        #expect(fileStripExtra(Array(strip.prefix(fileStripMax))) == 0)
        // An older computer has no strip, and an answer without one has none either.
        #expect(fileStripFiles(Message(id: "o", role: "assistant", text: "t")).isEmpty)
    }

    @Test func theEntryAndTheReasonTravelInTheLinksThemselves() throws {
        let file = ref("chart", "D:\\a\\chart.png", view: "image", thumb: true, texts: ["D:/a/chart.png"])
        let item = try #require(URL(string: answerItemLink(file)))
        #expect(answerItem(item) == file)
        #expect(answerItem(URL(string: "https://example.invalid")!) == nil)
        let note = FileNote("out/旧图.png", "not_found", "电脑上没找到这个文件")
        let why = try #require(URL(string: answerNoteLink(note)))
        #expect(answerNote(why) == note)
        #expect(answerNote(item) == nil)
    }

    // MARK: The demo's own example

    @Test func theFilePreviewDemoIsListedOnlyWithItsSwitchAndParsesLikeANewComputer() throws {
        #expect(!DemoWorld().firstPage().contains { $0["id"].string() == "file-preview" })
        #expect(DemoWorld(filesDemo: true).firstPage().contains { $0["id"].string() == "file-preview" })
        let rows = DemoData.messages(app: "codex", chat: "file-preview")
        #expect(rows.count == 3)
        let answer = try parseMessage(rows[1])
        #expect(answer.files?.count == DemoData.previewFiles.count)
        #expect(answer.files?.filter { $0.picture }.count == 6)
        #expect(drawnPictureIDs(answer) == Set(["fp-chart", "fp-logo", "fp-huge", "fp-gif"]))
        let strip = fileStripFiles(answer, drawn: drawnPictureIDs(answer))
        #expect(strip.map(\.id) == ["fp-contract", "fp-analysis", "fp-budget", "fp-pages", "fp-shot-1", "fp-shot-2",
                                   "fp-longlog", "fp-csv", "fp-audio", "fp-video", "fp-zip", "fp-markdown", "fp-html"])
        #expect(answer.fileNotes.map(\.reason) == ["not_found", "not_local"])
        // The older computer's answer has no files at all.
        let older = try parseMessage(rows[2])
        #expect(older.files == nil)
        // The viewer's pages: the pictures in the words first, then the picture cards below, each once.
        #expect(messagePictures(answer).map(\.id) == ["fp-chart", "fp-logo", "fp-huge", "fp-gif", "fp-shot-1", "fp-shot-2"])
        #expect(messagePictures(older).isEmpty)
    }

    // MARK: §7: the thumb cache

    @Test func aThumbIsKeptByComputerFileVersionAndWidth() {
        let dir = FileManager.default.temporaryDirectory.appendingPathComponent("teleply-thumbs-\(UUID().uuidString)")
        defer { try? FileManager.default.removeItem(at: dir) }
        let cache = ThumbCache(folder: dir, maxBytes: 150)
        let name = ThumbCache.name(file: "file-1", version: "v1", width: 640)
        #expect(name.hasSuffix(ThumbCache.suffix))
        #expect(name == ThumbCache.name(file: "file-1", version: "v1", width: 640))
        let others = [
            ThumbCache.name(file: "file-1", version: "v1", width: 1280),
            ThumbCache.name(file: "file-1", version: "v2", width: 640),
            ThumbCache.name(file: "file-2", version: "v1", width: 640),
        ]
        #expect(Set(others).count == others.count)
        #expect(!others.contains(name))
        // A name never writes the file id, `v` or width out as the phone's name.
        #expect(!name.contains("file-1") && !name.contains("v1"))
        // A subfolder per computer, so forgetting one clears only its own.
        #expect(cache.entry(computer: "pc-a", file: "f", version: "v", width: 320).deletingLastPathComponent().lastPathComponent == "pc-a")
        #expect(cache.entry(computer: "pc-b", file: "f", version: "v", width: 320).deletingLastPathComponent().lastPathComponent == "pc-b")
        #expect(!cache.entry(computer: "../pc", file: "f", version: "v", width: 320).path.contains(".."))

        #expect(cache.keep(Data(repeating: 1, count: 60), computer: "pc-a", file: "file-1", version: "v1", width: 640) != nil)
        #expect(cache.read(computer: "pc-a", file: "file-1", version: "v1", width: 640)?.count == 60)
        #expect(cache.read(computer: "pc-b", file: "file-1", version: "v1", width: 640) == nil)
        let walk = FileManager.default.enumerator(at: dir, includingPropertiesForKeys: nil)
        let names = (walk?.allObjects as? [URL] ?? []).map(\.lastPathComponent)
        #expect(!names.contains { $0.hasSuffix(".part") })
    }

    @Test func pastTheLimitTheLeastRecentlyUsedThumbsGo() {
        let dir = FileManager.default.temporaryDirectory.appendingPathComponent("teleply-thumbs-\(UUID().uuidString)")
        defer { try? FileManager.default.removeItem(at: dir) }
        let cache = ThumbCache(folder: dir, maxBytes: 100)
        #expect(cache.keep(Data(repeating: 1, count: 60), computer: "pc", file: "old", version: "v1", width: 320) != nil)
        let old = cache.entry(computer: "pc", file: "old", version: "v1", width: 320)
        try? FileManager.default.setAttributes([.modificationDate: Date(timeIntervalSince1970: 1_000)], ofItemAtPath: old.path)
        #expect(cache.keep(Data(repeating: 2, count: 60), computer: "pc", file: "new", version: "v1", width: 320) != nil)
        let fresh = cache.entry(computer: "pc", file: "new", version: "v1", width: 320)
        #expect(cache.totalBytes() <= 100)
        #expect(!FileManager.default.fileExists(atPath: old.path))
        #expect(FileManager.default.fileExists(atPath: fresh.path))
        // Reading touches a file; the least recently used still goes when room is needed.
        #expect(cache.read(computer: "pc", file: "new", version: "v1", width: 320) != nil)
        let touched = (try? FileManager.default.attributesOfItem(atPath: fresh.path))?[.modificationDate] as? Date
        #expect((touched ?? .distantPast) > Date(timeIntervalSince1970: 1_000))
    }
}
