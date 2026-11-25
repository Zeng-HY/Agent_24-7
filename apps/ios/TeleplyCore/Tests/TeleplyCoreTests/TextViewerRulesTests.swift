import Foundation
import Testing
@testable import TeleplyModel

/// Stage C's rules (file-preview design §6.2, §5.4, §5.6, §5.7): the code page's address and sources, the table's RFC
/// 4180 reading, a zip's listing, media addresses and cookies, and which page resources go the new way.
struct TextViewerRulesTests {
    @Test func csvQuotesCommasAndNewlinesFollowRFC4180() {
        let table = parseTable("name,note\n\"a,b\",\"line1\nline2\"\n\"q\"\"x\",z\n")
        #expect(table.header == ["name", "note"])
        #expect(table.rows == [["a,b", "line1\nline2"], ["q\"x", "z"]])
        #expect(!table.truncated)
        #expect(table.totalRows == 2)
        // A last line without a newline is a row too.
        #expect(parseTable("a,b\n1,2").rows == [["1", "2"]])
        #expect(parseTable("").header.isEmpty)
    }

    @Test func aTableStopsAtFiveThousandRows() {
        var text = "n,v\n"
        for i in 1...5_001 { text += "\(i),\(i * 2)\n" }
        let table = parseTable(text)
        #expect(table.header == ["n", "v"])
        #expect(table.rows.count == tableRowLimit)
        #expect(table.totalRows == 5_001)
        #expect(table.truncated)
    }

    @Test func theCodePageAddressCarriesDarkLanguageLineAndTheCut() {
        #expect(codePageURLString(dark: false, lang: "r", line: 0, truncated: false, shownBytes: 12, totalBytes: 0)
            == "teleply-viewer://viewer/code.html?dark=0&lang=r&line=0")
        #expect(codePageURLString(dark: true, lang: "c++", line: 7, truncated: true, shownBytes: 100, totalBytes: 200)
            == "teleply-viewer://viewer/code.html?dark=1&lang=c%2B%2B&line=7&truncated=1&size=100&total=200")
        #expect(codePageURLString(dark: false, lang: "text", line: 3, truncated: false, shownBytes: 1, totalBytes: 0)
            == "teleply-viewer://viewer/code.html?dark=0&lang=text&line=3")
    }

    @Test func theCodePageMayOnlyLoadItsOwnFilesAndTheText() {
        #expect(viewerResourceName("/code.html") == "code.html")
        #expect(viewerResourceName("highlight.min.js") == "highlight.min.js")
        #expect(viewerResourceName("/text") == "text")
        #expect(viewerResourceName("/../secret") == nil)
        #expect(viewerResourceName("/code.html/../x") == nil)
        #expect(viewerResourceName("/other.js") == nil)
        #expect(viewerResourceName("/") == nil)
        #expect(viewerResourceMime("code.html") == "text/html")
        #expect(viewerResourceMime("text") == "text/plain")
    }

    @Test func theCodeLanguageComesFromTheComputerOrTheEnding() {
        #expect(codeLanguage("r", name: "whatever.txt") == "r")
        #expect(codeLanguage("", name: "run.R") == "r")
        #expect(codeLanguage("", name: "Dockerfile") == "dockerfile")
        #expect(codeLanguage("", name: "a.unknownext") == "plaintext")
        #expect(shouldHighlight(highlightLimit))
        #expect(!shouldHighlight(highlightLimit + 1))
        #expect(shouldHighlight(highlightLimit - 1))
        #expect(jumpLine(5, lineCount: 3) == 3)
        #expect(jumpLine(0, lineCount: 3) == 0)
        #expect(truncationNotice(shownBytes: 1_048_576, totalBytes: 2_097_152) == "只显示了开头 1.0 MB，共 2.0 MB，可以保存后看全文")
        #expect(truncationNotice(shownBytes: 2, totalBytes: 2) == nil)
    }

    @Test func aZipListsFoldersFirstThenByPath() {
        let json: JSONValue = [
            "entries": .array([
                ["name": "B.txt", "size": 3, "modified": 1_000, "dir": false],
                ["name": "docs/", "size": 0, "modified": 900, "dir": true],
                ["name": "a.txt", "size": 5, "modified": 1_100, "dir": false],
                ["name": "C.txt", "size": 1, "modified": 800, "dir": false],
            ]),
            "total": 5,
            "truncated": true,
        ]
        let listing = parseZipListing(json)
        #expect(listing.entries.map(\.name) == ["docs/", "a.txt", "B.txt", "C.txt"])
        #expect(listing.entries.map(\.size) == [0, 5, 3, 1])
        #expect(listing.total == 5)
        #expect(listing.truncated)
        #expect(listing.more)
        #expect(listing.unpackedBytes == 9)
        #expect(zipFile("资料.ZIP") && !zipFile("资料.7z") && !zipFile("资料.rar"))
    }

    @Test func aMediaAddressCarriesTheProtocolAndTheCookieTheRelaySet() throws {
        let url = try mediaFileURL(origin: .default, device: String(repeating: "a", count: 32), app: "codex",
                                   chat: "c1", file: "f1", version: "v1")
        #expect(url.absoluteString == "https://app.pocketagentdesk.com/d/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/api/file?app=codex&id=c1&file=f1&v=v1&protocol=2")
        let cookie = mediaCookie(origin: .default, cookie: SessionCookie(value: "abc", expires: Date(timeIntervalSince1970: 2_000_000_000)),
                                 now: Date(timeIntervalSince1970: 1_000_000_000))
        #expect(cookie?.name == "__Host-ar_account")
        #expect(cookie?.value == "abc")
        #expect(cookie?.domain?.hasSuffix("app.pocketagentdesk.com") == true)
        #expect(cookie?.path == "/")
        #expect(cookie?.isSecure == true)
        #expect(mediaCookie(origin: .default, cookie: SessionCookie(value: "abc", expires: Date(timeIntervalSince1970: 1_000)),
                            now: Date(timeIntervalSince1970: 2_000)) == nil)
        #expect(mediaCookie(origin: .default, cookie: nil) == nil)
        #expect(mediaKind("clip.MP4") == "video")
        #expect(mediaKind("tone.mp3") == "audio")
        #expect(mediaKind("notes.txt") == nil)
    }

    @Test func aPageResourceGoesTheNewWayOnlyForANewerComputer() {
        #expect(usesFileResource(view: "html", id: "f1"))
        #expect(usesFileResource(view: "markdown", id: "f1"))
        #expect(!usesFileResource(view: "", id: "f1"))
        #expect(!usesFileResource(view: "html", id: ""))
        #expect(markdownRelativeResource("pic.png"))
        #expect(markdownRelativeResource("images/a.png"))
        #expect(!markdownRelativeResource("D:/a/pic.png"))
        #expect(!markdownRelativeResource("https://example.invalid/a.png"))
        #expect(resourcePath("pic.png", pagePath: "D:/fixture/file-preview/notes.md") == "pic.png")
        #expect(resourcePath("D:/fixture/file-preview/style.css", pagePath: "D:/fixture/file-preview/page.html") == "style.css")
    }
}
