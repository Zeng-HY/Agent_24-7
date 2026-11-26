import Foundation
import Testing
@testable import TeleplyDemo
@testable import TeleplyModel

/// 11-26 P3 and P4, the parts that are only rules (design 4.1, 4.3): the system converter's own error page, the
/// answer's PDF of the same name, and the file-type table. Everything is made up; no computer is read.
struct FilePreviewRulesTests {
    // MARK: P3: the converter's own error page (design 4.1.1)

    @Test func theSystemsOwnErrorPageIsAFailure() {
        // What the phone writes for a Word file its converter cannot read (the user's report, 11-26).
        #expect(systemPreviewFailed("未能完成操作。（OfficeImportErrorDomain 错误 912。）\n(null)"))
        #expect(systemPreviewFailed("OfficeImportErrorDomain 错误 912"))
        #expect(systemPreviewFailed("The operation couldn’t be completed. (OfficeImportErrorDomain error 912.)"))
        // The domain name alone, in a short page.
        #expect(systemPreviewFailed("OfficeImportErrorDomain"))
        // A number after 错误 / error, in either case, as long as it has two digits.
        #expect(systemPreviewFailed("错误 12"))
        #expect(systemPreviewFailed("ERROR 1024"))
        #expect(systemPreviewFailed("error\t7" + "1"))
    }

    @Test func aDocumentIsNotAnErrorPage() {
        // An empty page says nothing either way.
        #expect(!systemPreviewFailed(""))
        // A long page is a document, whatever it says: the read stops at 400 words.
        #expect(!systemPreviewFailed("OfficeImportErrorDomain 错误 912 " + String(repeating: "x", count: 400)))
        #expect(!systemPreviewFailed(String(repeating: "正常的一页文字。", count: 100)))
        // A short page without trouble in it is a document too.
        #expect(!systemPreviewFailed("这是一份很短的说明。"))
        // 错误 or error without a number is not the system's page.
        #expect(!systemPreviewFailed("错误"))
        #expect(!systemPreviewFailed("error"))
        #expect(!systemPreviewFailed("error 9"))
    }

    // MARK: P3: the answer's PDF of the same name (design 4.1.3)

    @Test func theSameDocumentsPDFIsFoundInAnyCaseAndWithAnyNumberOfDots() {
        let doc = FileRef(id: "doc", name: "季度报告.v2.docx", kind: "download", version: "v1")
        let pdf = FileRef(id: "pdf", name: "季度报告.V2.PDF", kind: "pdf", version: "v1")
        let other = FileRef(id: "other", name: "别的.pdf", kind: "pdf", version: "v1")
        let docx2 = FileRef(id: "docx2", name: "发布说明.docx", kind: "download")
        let pdf2 = FileRef(id: "pdf2", name: "发布说明.pdf", kind: "pdf")
        #expect(sameNamePDF(in: [other, pdf, doc], for: doc.name)?.id == "pdf")
        #expect(sameNamePDF(in: [other, doc], for: doc.name) == nil)
        #expect(sameNamePDF(in: [pdf, pdf2, docx2], for: docx2.name)?.id == "pdf2")
        // A name without a dot is its own base, so a PDF of that very name is offered.
        #expect(sameNamePDF(in: [pdf2], for: "发布说明")?.id == "pdf2")
        #expect(sameNamePDF(in: [], for: "季度报告.docx") == nil)
        // A PDF without an id cannot be opened, so it is not offered.
        #expect(sameNamePDF(in: [FileRef(id: "", name: "发布说明.pdf", kind: "pdf")], for: "发布说明.docx") == nil)
        // A name with dots keeps the last one only: 「带.点的.报告.docx」 → 「带.点的.报告.PDF」 is the same document.
        let dottedDoc = FileRef(id: "dotted", name: "带.点的.报告.docx", kind: "download")
        let dottedPDF = FileRef(id: "dotted-pdf", name: "带.点的.报告.PDF", kind: "pdf")
        #expect(sameNamePDF(in: [dottedPDF], for: dottedDoc.name)?.id == "dotted-pdf")
        // A PDF whose extension is not .pdf is not offered.
        #expect(sameNamePDF(in: [FileRef(id: "f", name: "发布说明.txt")], for: "发布说明.docx") == nil)
    }

    // MARK: P4: the file-type table (design 4.3)

    /// One example of every row of the table, with the table's own bytes.
    @Test func everyRowOfTheTableHasItsMark() {
        let rows: [(name: String, text: String, red: UInt8, green: UInt8, blue: UInt8)] = [
            ("合同.pdf", "PDF", 0xE5, 0x48, 0x3B),
            ("发布说明.docx", "W", 0x2F, 0x6F, 0xDE),
            ("预算表.xlsx", "X", 0x1E, 0x8E, 0x4F),
            ("数据.csv", "CSV", 0x2E, 0x9E, 0x6B),
            ("季度汇报.pptx", "P", 0xE4, 0x6A, 0x2C),
            ("资料.zip", "ZIP", 0xB7, 0x86, 0x2C),
            ("日志.txt", "TXT", 0x7A, 0x85, 0x94),
            ("说明.md", "MD", 0x5F, 0x6B, 0x7A),
            ("分析.R", "</>", 0x7A, 0x55, 0xD6),
            ("截图.png", "IMG", 0x12, 0xA3, 0xA3),
            ("标志.svg", "SVG", 0x0E, 0x8F, 0x8F),
            ("提示音.mp3", "♪", 0xD2, 0x4C, 0x8E),
            ("演示视频.mp4", "▶", 0x5B, 0x5B, 0xD6),
            ("安装包.apk", "APK", 0x3D, 0xA3, 0x5D),
            ("安装程序.exe", "EXE", 0x4B, 0x55, 0x63),
            ("报告.abcde", "ABCD", 0x8B, 0x95, 0xA1),
        ]
        for row in rows {
            let mark = fileTypeMark(for: row.name)
            #expect(mark.text == row.text, "\(row.name)")
            #expect(mark.red == row.red, "\(row.name)")
            #expect(mark.green == row.green, "\(row.name)")
            #expect(mark.blue == row.blue, "\(row.name)")
        }
    }

    @Test func theOtherExtensionsOfARowKeepItsMark() {
        #expect(fileTypeMark(for: "a.doc").text == "W")
        #expect(fileTypeMark(for: "a.pages").text == "W")
        #expect(fileTypeMark(for: "a.ods").text == "X")
        #expect(fileTypeMark(for: "a.tsv").text == "CSV")
        #expect(fileTypeMark(for: "a.key").text == "P")
        #expect(fileTypeMark(for: "a.tar.gz").text == "ZIP")
        #expect(fileTypeMark(for: "a.log").text == "TXT")
        #expect(fileTypeMark(for: "a.markdown").text == "MD")
        #expect(fileTypeMark(for: "a.kts").text == "</>")
        #expect(fileTypeMark(for: "a.tiff").text == "IMG")
        #expect(fileTypeMark(for: "a.m4a").text == "♪")
        #expect(fileTypeMark(for: "a.mov").text == "▶")
        #expect(fileTypeMark(for: "a.msi").text == "EXE")
        // Capitals are the same type as small letters.
        #expect(fileTypeMark(for: "照片.JPG").text == "IMG")
        #expect(fileTypeMark(for: "报告.PDF").text == "PDF")
        // At most four letters of an unknown extension, in capitals.
        #expect(fileTypeMark(for: "a.longextension").text == "LONG")
        #expect(fileTypeMark(for: "a.longextension").red == 0x8B)
        // No extension at all: nothing on the page, still the table's grey.
        #expect(fileTypeMark(for: "Makefile").text == "")
        #expect(fileTypeMark(for: ".gitignore").text == "")
        #expect(fileTypeMark(for: "a.").text == "")
        #expect(fileTypeMark(for: "文件夹.资料").text == "资料")
    }

    @Test func theDemoHasAFileThePhoneCannotShow() throws {
        let answer = try parseMessage(DemoData.messages(app: "codex", chat: "file-preview")[1])
        let files = try #require(answer.files)
        let doc = try #require(files.first { $0.id == "fp-heavy-docx" })
        #expect(doc.name == "季度报告.docx")
        #expect(sameNamePDF(in: files, for: doc.name)?.id == "fp-heavy-pdf")
        #expect(sameNamePDF(in: files, for: doc.name)?.kind == "pdf")
        // The example is only listed with -TeleplyDemoFiles.
        #expect(!DemoWorld().firstPage().contains { $0["id"].string() == "file-preview" })
        #expect(DemoWorld(filesDemo: true).firstPage().contains { $0["id"].string() == "file-preview" })
    }
}
