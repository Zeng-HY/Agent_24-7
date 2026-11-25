import Foundation

/// Stage C's rules (file-preview design §6.2, §5.4, §5.6, §5.7): when code is highlighted, the code page's address and
/// the files it may load, the table's RFC 4180 text, a zip's listing, and a media stream's address and cookie. Pure, so
/// they can be read in tests without a phone.
public let highlightLimit = 200 * 1024
public let zipEntryLimit = 2000
public let tableRowLimit = 5000
/// The largest CSV/TSV the table page asks for (§5.8): the computer sends the start of a bigger one instead.
public let tableTextLimit: Int64 = 5 * 1024 * 1024

/// The code page's own scheme and host; everything else is blocked by the page and the web view.
public let viewerScheme = "teleply-viewer"
public let viewerHost = "viewer"

/// The code page's address, exactly as Android's CodeView builds it: `dark`, `lang`, `line`, and when the text was cut,
/// `truncated`, `size` and `total` (§6.2).
public func codePageURLString(dark: Bool, lang: String, line: Int, truncated: Bool,
                              shownBytes: Int, totalBytes: Int) -> String {
    var parts = ["dark=" + (dark ? "1" : "0"), "lang=" + percentEncode(lang), "line=\(max(0, line))"]
    if truncated {
        parts.append("truncated=1")
        parts.append("size=\(max(0, shownBytes))")
        parts.append("total=\(max(shownBytes, totalBytes))")
    }
    return viewerScheme + "://" + viewerHost + "/code.html?" + parts.joined(separator: "&")
}

private func percentEncode(_ text: String) -> String {
    text.addingPercentEncoding(withAllowedCharacters: .alphanumerics) ?? ""
}

/// Past [highlightLimit] characters the page shows line numbers only (§6.2). The page checks this itself too.
public func shouldHighlight(_ characters: Int) -> Bool { characters <= highlightLimit }

/// A `line` from the computer, kept inside the text it has; zero when there is none.
public func jumpLine(_ requested: Int, lineCount: Int) -> Int {
    guard requested > 0, lineCount > 0 else { return 0 }
    return min(max(requested, 1), lineCount)
}

/// The language for highlight.js: the computer's `lang` when it gave one, else the file's ending (§5.1).
public func codeLanguage(_ lang: String, name: String) -> String {
    if !lang.isEmpty { return lang }
    let base = name.split(whereSeparator: { $0 == "/" || $0 == "\\" }).last.map(String.init) ?? name
    if base.lowercased() == "dockerfile" { return "dockerfile" }
    let ext = name.lastIndex(of: ".").map { name[name.index(after: $0)...].lowercased() } ?? ""
    switch ext {
    case "r": return "r"
    case "py": return "python"
    case "js", "mjs": return "javascript"
    case "ts": return "typescript"
    case "json": return "json"
    case "yaml", "yml": return "yaml"
    case "xml": return "xml"
    case "sql": return "sql"
    case "sh", "bash": return "bash"
    case "ps1": return "powershell"
    case "kt", "kts": return "kotlin"
    case "swift": return "swift"
    case "java": return "java"
    case "c", "h": return "c"
    case "cpp", "cc", "hpp": return "cpp"
    case "cs": return "csharp"
    case "go": return "go"
    case "rs": return "rust"
    case "css": return "css"
    case "md", "markdown": return "markdown"
    case "ini", "toml": return "ini"
    case "diff", "patch": return "diff"
    case "tex": return "latex"
    case "dockerfile": return "dockerfile"
    default: return "plaintext"
    }
}

/// What the page says when the computer sent only the start of a large text (§5.4, §6.2).
public func truncationNotice(shownBytes: Int64, totalBytes: Int64) -> String? {
    guard totalBytes > shownBytes, shownBytes > 0 else { return nil }
    return "只显示了开头 \(megabytes(shownBytes)) MB，共 \(megabytes(totalBytes)) MB，可以保存后看全文"
}

/// One decimal place, as Android's TextViewerRules.
public func megabytes(_ bytes: Int64) -> String {
    String(format: "%.1f", locale: Locale(identifier: "en_US_POSIX"),
           arguments: [Double(bytes) / 1_048_576])
}

/// The files the code page may load from its own folder, and the one `/text`; anything else, `..` included, is refused.
public let viewerResources = ["code.html", "code.js", "highlight.min.js", "highlight.r.min.js",
                              "highlight.powershell.min.js", "highlight.latex.min.js", "highlight.dockerfile.min.js",
                              "code-light.css", "code-dark.css", "text"]

/// The name the scheme handler may serve for [path], or nil (404) for anything outside [viewerResources] and `..`.
public func viewerResourceName(_ path: String) -> String? {
    var text = path
    if text.hasPrefix("/") { text.removeFirst() }
    guard !text.isEmpty, !text.contains(".."), !text.contains("\\") else { return nil }
    guard !text.contains("/") else { return nil }
    return viewerResources.contains(text) ? text : nil
}

/// The type each of the page's own files goes as.
public func viewerResourceMime(_ name: String) -> String {
    switch name {
    case "code.html": return "text/html"
    case "code.js", "highlight.min.js", "highlight.r.min.js", "highlight.powershell.min.js",
         "highlight.latex.min.js", "highlight.dockerfile.min.js": return "text/javascript"
    case "code-light.css", "code-dark.css": return "text/css"
    default: return "text/plain"
    }
}

/// Whether a picture in a Markdown file's reading view is a resource beside it: a relative path, not a computer path.
public func markdownRelativeResource(_ destination: String) -> Bool {
    MarkdownReader.localPath(destination) == nil && relativeResource(destination)
}

// MARK: The table (§5.4, §6.2)

/// A table page's rows: the first row is the header, then at most [tableRowLimit] data rows. [truncated] says the text
/// held more rows than are shown.
public struct TableData: Sendable, Equatable {
    public var header: [String]
    public var rows: [[String]]
    public var truncated: Bool
    public var totalRows: Int

    public init(header: [String] = [], rows: [[String]] = [], truncated: Bool = false, totalRows: Int = 0) {
        self.header = header
        self.rows = rows
        self.truncated = truncated
        self.totalRows = totalRows
    }
}

/// CSV/TSV text as RFC 4180 reads it: quotes, a comma inside quotes, a newline inside quotes, and doubled quotes.
/// The first row is the header; after [maxRows] data rows the rest say only that they were left out.
public func parseTable(_ text: String, maxRows: Int = tableRowLimit) -> TableData {
    if text.isEmpty { return TableData() }
    var rows: [[String]] = []
    var row: [String] = []
    var field = ""
    var quoted = false
    let characters = Array(text)
    var i = 0
    while i < characters.count {
        let c = characters[i]
        if quoted {
            if c == "\"" {
                if i + 1 < characters.count, characters[i + 1] == "\"" {
                    field.append("\"")
                    i += 2
                    continue
                }
                quoted = false
                i += 1
                continue
            }
            field.append(c)
            i += 1
            continue
        }
        switch c {
        case "\"":
            if field.isEmpty { quoted = true } else { field.append(c) }
        case ",":
            row.append(field)
            field = ""
        case "\n":
            row.append(field)
            rows.append(row)
            row = []
            field = ""
        case "\r":
            row.append(field)
            rows.append(row)
            row = []
            field = ""
            if i + 1 < characters.count, characters[i + 1] == "\n" { i += 1 }
        default:
            field.append(c)
        }
        i += 1
    }
    if !field.isEmpty || !row.isEmpty {
        row.append(field)
        rows.append(row)
    }
    guard let header = rows.first else { return TableData() }
    let data = Array(rows.dropFirst())
    return TableData(header: header, rows: Array(data.prefix(max(0, maxRows))),
                     truncated: data.count > max(0, maxRows), totalRows: data.count)
}

// MARK: A zip's listing (§5.7)

public struct ZipEntry: Sendable, Equatable, Identifiable {
    public var name: String
    public var size: Int64
    public var packed: Int64
    /// Milliseconds since 1970, in the computer's clock.
    public var modified: Int64
    public var dir: Bool

    public var id: String { name }

    public init(name: String, size: Int64 = 0, packed: Int64 = 0, modified: Int64 = 0, dir: Bool = false) {
        self.name = name
        self.size = size
        self.packed = packed
        self.modified = modified
        self.dir = dir
    }
}

public struct ZipListing: Sendable, Equatable {
    public var entries: [ZipEntry]
    public var total: Int
    public var truncated: Bool
    public var unpackedBytes: Int64

    /// Whether the computer said there were more names than are shown.
    public var more: Bool { truncated || total > entries.count }

    public init(entries: [ZipEntry] = [], total: Int = 0, truncated: Bool = false) {
        self.entries = entries
        self.total = total
        self.truncated = truncated
        self.unpackedBytes = entries.reduce(Int64(0)) { $0 + $1.size }
    }
}

/// A zip's listing as `/api/file/zip` gives it: folders first, then by path, at most [zipEntryLimit] items.
public func parseZipListing(_ json: JSONValue) -> ZipListing {
    let entries = json["entries"].array.prefix(zipEntryLimit).map { row in
        ZipEntry(name: row["name"].string(), size: row["size"].int64(), packed: row["packed"].int64(),
                 modified: row["modified"].int64(), dir: row["dir"].bool())
    }.sorted { a, b in
        if a.dir != b.dir { return a.dir }
        return a.name.lowercased() < b.name.lowercased()
    }
    let total = json["total"].int() > 0 ? json["total"].int() : entries.count
    return ZipListing(entries: Array(entries), total: total, truncated: json["truncated"].bool())
}

/// The archive kinds §5.7 reads; 7z and rar stay a file card.
public func zipFile(_ name: String) -> Bool {
    guard let dot = name.lastIndex(of: ".") else { return false }
    return name[name.index(after: dot)...].lowercased() == "zip"
}

// MARK: Audio and video (§6.2)

/// What a file plays as: audio, video, or nothing this page should hand to the system player.
public func mediaKind(_ name: String) -> String? {
    guard let dot = name.lastIndex(of: ".") else { return nil }
    switch name[name.index(after: dot)...].lowercased() {
    case "mp3", "m4a", "aac", "wav", "flac", "ogg": return "audio"
    case "mp4", "m4v", "mov", "webm", "mkv": return "video"
    default: return nil
    }
}

/// The file's streaming address for AVPlayer: `/api/file` with `app`, `id`, `file`, `v` and the protocol handshake the
/// computer reads from the query (§6.2). No `download=1`; the player streams it itself.
public func mediaFileURL(origin: ServiceOrigin, device: String, app: String, chat: String,
                         file: String, version: String) throws -> URL {
    var query: [(String, String?)] = [("app", app), ("id", chat), ("file", file)]
    if !version.isEmpty { query.append(("v", version)) }
    query.append(("protocol", String(TeleplyClient.protocolVersion)))
    return origin.url(try RelayClient.devicePath(device, "/api/file"), query: query)
}

/// The sign-in as an `HTTPCookie` for `AVURLAssetHTTPCookiesKey`: the relay's own host, secure, path `/`, until it runs
/// out. Nil when there is no sign-in or it has expired.
public func mediaCookie(origin: ServiceOrigin, cookie: SessionCookie?, now: Date = Date()) -> HTTPCookie? {
    guard let cookie, cookie.header(at: now) != nil else { return nil }
    var properties: [HTTPCookiePropertyKey: Any] = [
        .name: SessionCookie.name,
        .value: cookie.value,
        .path: "/",
        .secure: "TRUE",
    ]
    if let host = URLComponents(string: origin.header)?.host { properties[.domain] = host }
    if let expires = cookie.expires { properties[.expires] = expires }
    return HTTPCookie(properties: properties)
}

/// Whether a page's own resource should be asked from `/api/file/resource` (§5.6): a newer computer's file entry has a
/// `view`; an older computer's does not, and the conversation's file list is read as before.
public func usesFileResource(view: String, id: String) -> Bool {
    !view.isEmpty && !id.isEmpty
}

/// The relative path the resource route wants: a web view resolves `style.css` against the page's own address, so the
/// path arrives as the page's whole path; the computer checks the path relative to the page's folder.
public func resourcePath(_ path: String, pagePath: String) -> String {
    let page = pagePath.replacingOccurrences(of: "\\", with: "/")
    guard let slash = page.lastIndex(of: "/") else { return path }
    let folder = String(page[..<slash])
    let candidate = path.replacingOccurrences(of: "\\", with: "/")
    guard candidate.hasPrefix(folder + "/") else { return path }
    return String(candidate.dropFirst(folder.count + 1))
}
