import Foundation

// MARK: P3: when the phone's own converter cannot show a document (design 4.1)

/// Whether a web view that finished its page is really showing the system's own "could not convert" page (11-26 P3).
///
/// The phone hands a Word, Excel or PowerPoint file to the system's Quick Look converter. When the converter cannot
/// read it, it writes a page of its own — 未能完成操作。（OfficeImportErrorDomain 错误 912。） and (null) under it —
/// and finishes as if all were well, so the failure has to be read from the page's words.
///
/// [body] is those words, up to the first 400 characters. A page that is not short is a document rather than an error
/// page; an empty page says nothing either way. Both are not failures.
///
/// A short page is the system's own only when it says what no short document does: it names the system's error domain
/// (`OfficeImportErrorDomain`, …ErrorDomain in either language), or it has a line that is just `(null)`, which is how
/// the system writes a reason it has none of. Words like「错误 12」or「Error 404」are a document's own words as often as
/// the system's, so a number after 错误 / error proves nothing on its own (11-27).
public func systemPreviewFailed(_ body: String) -> Bool {
    guard !body.isEmpty, body.count < 400 else { return false }
    // The system's domain name, in English on every phone.
    if body.contains("ErrorDomain") { return true }
    // A whole line of nothing but `(null)`, as the system writes an empty reason; the words inside a sentence are a
    // document's own.
    return body.split(whereSeparator: { $0.isNewline }).contains {
        String($0).trimmingCharacters(in: .whitespaces) == "(null)"
    }
}

// MARK: P3: the same document as a PDF (design 4.1.3)

/// The answer's PDF of the same name as [name] (design 4.1.3), for 看 PDF 版 when the system cannot convert the file:
/// the first `.pdf` in [files] whose name without its extension is [name]'s without its extension, in any case and
/// however many dots either name has (「季度报告.v2.docx」 → 「季度报告.v2.PDF」). Nil when there is none.
public func sameNamePDF(in files: [FileRef], for name: String) -> FileRef? {
    let wanted = fileBaseName(name)
    guard !wanted.isEmpty else { return nil }
    return files.first { file in
        !file.id.isEmpty && fileExtension(file.name) == "pdf"
            && fileBaseName(file.name).caseInsensitiveCompare(wanted) == .orderedSame
    }
}

/// A file name's extension, lowercased: 「报告.PDF」 → "pdf", 「照片.tar.gz」 → "gz". Nothing for a name with no dot, or
/// with a dot only at its start (「.gitignore」 names no type).
public func fileExtension(_ name: String) -> String {
    guard let dot = name.lastIndex(of: "."), dot != name.startIndex else { return "" }
    return name[name.index(after: dot)...].lowercased()
}

/// A file name without its last extension: 「季度报告.v2.docx」 → 「季度报告.v2」; the whole name when it has none.
public func fileBaseName(_ name: String) -> String {
    guard let dot = name.lastIndex(of: "."), dot != name.startIndex else { return name }
    return String(name[name.startIndex..<dot])
}

// MARK: P4: the file-type table (design 4.3)

/// One row of the file-type table (design 4.3), drawn the same way on iPhone and Android: the short words on the page
/// and the page's colour, as the table's own red, green and blue (0–255, not a `#…` string: a raw string would end at
/// the `"#` of one).
public struct FileTypeMark: Equatable, Sendable {
    public let text: String
    public let red: UInt8
    public let green: UInt8
    public let blue: UInt8

    public init(_ text: String, _ red: UInt8, _ green: UInt8, _ blue: UInt8) {
        self.text = text
        self.red = red
        self.green = green
        self.blue = blue
    }
}

/// What a file is, by its extension (design 4.3). The colours are the table's, in light and dark alike; a type the
/// table does not name shows its own extension in capitals, at most four letters, in the table's grey.
public func fileTypeMark(for name: String) -> FileTypeMark {
    switch fileExtension(name) {
    case "pdf":
        return FileTypeMark("PDF", 0xE5, 0x48, 0x3B)
    case "doc", "docx", "docm", "dotx", "rtf", "odt", "pages":
        return FileTypeMark("W", 0x2F, 0x6F, 0xDE)
    case "xls", "xlsx", "xlsm", "xlsb", "ods", "numbers":
        return FileTypeMark("X", 0x1E, 0x8E, 0x4F)
    case "csv", "tsv":
        return FileTypeMark("CSV", 0x2E, 0x9E, 0x6B)
    case "ppt", "pptx", "pptm", "odp", "key":
        return FileTypeMark("P", 0xE4, 0x6A, 0x2C)
    case "zip", "rar", "7z", "tar", "gz", "tgz", "bz2", "xz":
        return FileTypeMark("ZIP", 0xB7, 0x86, 0x2C)
    case "txt", "log":
        return FileTypeMark("TXT", 0x7A, 0x85, 0x94)
    case "md", "markdown":
        return FileTypeMark("MD", 0x5F, 0x6B, 0x7A)
    case "py", "r", "js", "ts", "tsx", "jsx", "kt", "kts", "swift", "java", "c", "h", "cpp", "hpp", "cs", "go",
         "rs", "rb", "php", "sh", "ps1", "bat", "sql", "json", "yaml", "yml", "toml", "xml", "html", "htm", "css",
         "ipynb":
        return FileTypeMark("</>", 0x7A, 0x55, 0xD6)
    case "png", "jpg", "jpeg", "gif", "webp", "heic", "heif", "bmp", "tif", "tiff":
        return FileTypeMark("IMG", 0x12, 0xA3, 0xA3)
    case "svg":
        return FileTypeMark("SVG", 0x0E, 0x8F, 0x8F)
    case "mp3", "wav", "m4a", "aac", "flac", "ogg":
        return FileTypeMark("♪", 0xD2, 0x4C, 0x8E)
    case "mp4", "mov", "m4v", "avi", "mkv", "webm":
        return FileTypeMark("▶", 0x5B, 0x5B, 0xD6)
    case "apk":
        return FileTypeMark("APK", 0x3D, 0xA3, 0x5D)
    case "exe", "msi":
        return FileTypeMark("EXE", 0x4B, 0x55, 0x63)
    default:
        // 其他: the extension in capitals, at most four letters; nothing at all when the name has no extension.
        return FileTypeMark(String(fileExtension(name).uppercased().prefix(4)), 0x8B, 0x95, 0xA1)
    }
}
