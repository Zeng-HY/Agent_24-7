import Foundation

/// A file an answer names (file-preview design §5.1), as the computer lists it. `view` picks how the file page shows
/// it (`image`, `svg`, `code`, …); `version` is the `v` its addresses carry; `texts` are the words a `code` or `path`
/// file was found as, so that the words themselves can open it; `via` says how it was found (link, image, presented,
/// code, path, …), which decides whether it goes in the file strip. Null [Message.files] is an older computer.
public struct FileRef: Sendable, Equatable, Identifiable {
    public let id: String
    public var name: String
    public var path: String
    public var kind: String
    public var view: String
    public var size: Int64
    public var state: String
    public var version: String
    public var width: Int
    public var height: Int
    public var thumb: Bool
    public var line: Int
    public var lang: String
    public var texts: [String]
    public var via: [String]
    public var preview: String

    public init(id: String, name: String = "", path: String = "", kind: String = "", view: String = "",
                size: Int64 = 0, state: String = "", version: String = "", width: Int = 0, height: Int = 0,
                thumb: Bool = false, line: Int = 0, lang: String = "", texts: [String] = [], via: [String] = [],
                preview: String = "") {
        self.id = id
        self.name = name
        self.path = path
        self.kind = kind
        self.view = view
        self.size = size
        self.state = state
        self.version = version
        self.width = width
        self.height = height
        self.thumb = thumb
        self.line = line
        self.lang = lang
        self.texts = texts
        self.via = via
        self.preview = preview
    }

    /// A picture that can be drawn where the answer put it (§6.1): an image or SVG the computer can make a thumb of.
    public var picture: Bool { thumb && (view == "image" || view == "svg") }

    /// The entry a file page reads: the same keys the conversation's file list gives, plus what the answer side needs
    /// (`texts`, `via`), which the page leaves alone.
    public var pageJSON: JSONValue {
        var fields: [String: JSONValue] = [
            "id": .string(id), "name": .string(name), "path": .string(path), "kind": .string(kind),
            "view": .string(view), "size": .number(Double(size)), "state": .string(state), "v": .string(version),
        ]
        if width > 0 { fields["w"] = .number(Double(width)) }
        if height > 0 { fields["h"] = .number(Double(height)) }
        if thumb { fields["thumb"] = true }
        if line > 0 { fields["line"] = .number(Double(line)) }
        if !lang.isEmpty { fields["lang"] = .string(lang) }
        if !preview.isEmpty { fields["preview"] = .string(preview) }
        if !texts.isEmpty { fields["texts"] = .array(texts.map { .string($0) }) }
        if !via.isEmpty { fields["via"] = .array(via.map { .string($0) }) }
        return .object(fields)
    }
}

/// A link that looked like a file but cannot be given (file-preview design §5.1, 6.4). [href] is the address as the
/// answer wrote it, [reason] one of the design's reasons, [text] the computer's own words when it gave any.
public struct FileNote: Sendable, Equatable, Identifiable {
    public let href: String
    public let reason: String
    public let text: String

    public init(_ href: String, _ reason: String, _ text: String = "") {
        self.href = href
        self.reason = reason
        self.text = text
    }

    public var id: String { href + "\u{1F}" + reason + "\u{1F}" + text }
    public var short: String { fileNoteShort(reason) }
    public var full: String { fileNoteFull(reason, text) }
}

/// One file row of an answer, read the way Android parses it: a missing key is its default.
public func parseFileRef(_ json: JSONValue) -> FileRef {
    FileRef(id: json["id"].string(), name: json["name"].string(), path: json["path"].string(),
            kind: json["kind"].string(), view: json["view"].string(), size: json["size"].int64(),
            state: json["state"].string(), version: json["v"].string(), width: json["w"].int(),
            height: json["h"].int(), thumb: json["thumb"].bool(), line: json["line"].int(),
            lang: json["lang"].string(), texts: json["texts"].array.map { $0.string() },
            via: json["via"].array.map { $0.string() }, preview: json["preview"].string())
}

public func parseFileNote(_ json: JSONValue) -> FileNote {
    FileNote(json["href"].string(), json["reason"].string(), json["text"].string())
}

/// The short grey note after a link, §6.1: the design's reason in a few words.
public func fileNoteShort(_ reason: String) -> String {
    switch reason {
    case "missing": return "文件已删除"
    case "changed": return "文件刚改过"
    case "not_found": return "找不到文件"
    case "not_local": return "网络位置"
    case "denied": return "不开放"
    case "folder": return "这是文件夹"
    case "too_large": return "文件太大"
    case "unsupported": return "不能直接显示"
    case "decode": return "读不出编码"
    case "offline": return "电脑离线"
    case "old_pc": return "电脑端版本较旧"
    case "local_web": return "电脑本机网址"
    default: return "给不了"
    }
}

/// The whole reason, in the design's own words (§6.4), for the dialog a grey note opens.
public func fileNoteFull(_ reason: String, _ text: String = "") -> String {
    switch reason {
    case "missing": return "文件已移动或删除"
    case "changed": return "文件刚改过，重新打开就是新的"
    case "not_found": return "电脑上没找到这个文件（回答写的是相对位置，在对话文件夹里没找到）"
    case "not_local": return "文件在网络位置或别的电脑上，遥应只读这台电脑自己的磁盘"
    case "denied": return "出于安全，遥应不让手机读这个文件（可能含密钥或登录信息）"
    case "folder": return "这是文件夹，可以在「电脑上的文件」里看"
    case "too_large": return text.isEmpty ? "文件太大，超过手机上直接看的上限；可以保存或用其他应用打开" : text
    case "unsupported": return "这种文件手机上不能直接显示；可以保存或用其他应用打开"
    case "decode": return "读不出这个文件的文字编码；可以保存后用其他应用打开"
    case "offline": return "电脑离线，连上后再试"
    case "old_pc": return "电脑端版本较旧，更新到 dev.55 或以后才能看"
    case "local_web": return "这是电脑本机的网址，手机打不开"
    default: return text.isEmpty ? "这个文件现在给不了" : text
    }
}

/// The schemes a link of an answer carries on screen. A file entry is the very row the computer listed (§5.1), so the
/// page opens with it instead of reading the conversation's whole file list first; a grey note's link shows its whole
/// reason (§6.4). Both carry their data %-escaped, so no address or file name is ever mistaken for a scheme's syntax.
private let itemScheme = "teleply-item:"
private let whyScheme = "teleply-why:"

public func answerItemLink(_ file: FileRef) -> String {
    guard !file.id.isEmpty, let data = try? file.pageJSON.encoded() else { return itemScheme }
    let text = String(decoding: data, as: UTF8.self)
    return itemScheme + (text.addingPercentEncoding(withAllowedCharacters: .alphanumerics) ?? "")
}

public func answerItem(_ url: URL) -> FileRef? {
    let text = url.absoluteString
    guard text.hasPrefix(itemScheme) else { return nil }
    guard let decoded = String(text.dropFirst(itemScheme.count)).removingPercentEncoding,
          let data = decoded.data(using: .utf8), let json = try? JSONValue.parse(data), json.isObject else { return nil }
    let file = parseFileRef(json)
    return file.id.isEmpty ? nil : file
}

public func answerNoteLink(_ note: FileNote) -> String {
    let json: JSONValue = ["href": .string(note.href), "reason": .string(note.reason), "text": .string(note.text)]
    guard let data = try? json.encoded() else { return whyScheme }
    let text = String(decoding: data, as: UTF8.self)
    return whyScheme + (text.addingPercentEncoding(withAllowedCharacters: .alphanumerics) ?? "")
}

public func answerNote(_ url: URL) -> FileNote? {
    let text = url.absoluteString
    guard text.hasPrefix(whyScheme) else { return nil }
    guard let decoded = String(text.dropFirst(whyScheme.count)).removingPercentEncoding,
          let data = decoded.data(using: .utf8), let json = try? JSONValue.parse(data), json.isObject else { return nil }
    return parseFileNote(json)
}

/// The file a link in an answer names: the link's path folded as [normalizePath] and compared with each `path`
/// (slashes and case do not matter, §5.1). Nil when the link is not a path at all or nothing matches.
public func fileForLink(_ files: [FileRef], _ destination: String) -> FileRef? {
    guard let path = MarkdownReader.localPath(destination) else { return nil }
    let wanted = normalizePath(path)
    return files.first { !$0.id.isEmpty && !$0.path.isEmpty && normalizePath($0.path) == wanted }
}

/// The file an `![…](…)` in an answer draws in place: an image or SVG the computer can make a thumb of (§6.1).
public func pictureForImage(_ files: [FileRef], _ destination: String) -> FileRef? {
    fileForLink(files, destination).flatMap { $0.picture ? $0 : nil }
}

/// The note that says why a link cannot be given: its `href`, %-decoded, equals the link's (§5.1).
public func noteForLink(_ notes: [FileNote], _ destination: String) -> FileNote? {
    let wanted = decodedHref(destination)
    if let exact = notes.first(where: { decodedHref($0.href) == wanted }) { return exact }
    let folded = { (href: String) in decodedHref(href).replacingOccurrences(of: "\\", with: "/") }
    return notes.first { folded($0.href) == folded(wanted) }
}

private func decodedHref(_ href: String) -> String { href.removingPercentEncoding ?? href }

/// `#…`, `mailto:` and the rest: the words show, but they are not a link the app can open (§6.1).
public func plainLink(_ destination: String) -> Bool {
    if destination.hasPrefix("#") { return true }
    guard let scheme = URLComponents(string: destination)?.scheme?.lowercased() else { return true }
    return scheme != "http" && scheme != "https"
}

/// A web address on the computer itself (`localhost`, `127.0.0.1`, `[::1]`): it says so after the words (§6.1).
public func localWebLink(_ destination: String) -> Bool {
    guard let parts = URLComponents(string: destination), let scheme = parts.scheme?.lowercased(),
          scheme == "http" || scheme == "https" else { return false }
    let host = (parts.host ?? "").lowercased()
    return ["localhost", "127.0.0.1", "[::1]", "::1"].contains(host)
}

/// An address that looks like a file on the computer, even though [MarkdownReader.localPath] did not match it: a
/// relative path with slashes, `/D:/…`, `file:` or `~`. An older computer says （链接未开放） after such a link, as
/// 0.9.0 did; `#…`, `mailto:` and other protocols are plainly not files and stay without it (§6.1).
public func fileLikeLink(_ destination: String) -> Bool {
    if destination.hasPrefix("#") { return false }
    let lower = destination.lowercased()
    if lower.hasPrefix("mailto:") { return false }
    if lower.hasPrefix("file:") { return true }
    if destination.hasPrefix("~") { return true }
    if destination.range(of: #"^/[A-Za-z]:[\\/]"#, options: .regularExpression) != nil { return true }
    // Any other scheme names something that is not a path (http is handled before this is asked).
    if URLComponents(string: destination)?.scheme != nil { return false }
    return destination.contains("/") || destination.contains("\\")
}

/// The thumbnail width for a bubble that is [pixels] wide: 640 up to there, 1280 past it (§6.3, §7). In pixels, not
/// points: a 411 pt phone at 3× draws a bubble over 1,000 px wide, where 640 would be soft.
public func pictureWidth(_ pixels: Double) -> Int { pixels <= 640 ? 640 : 1280 }

/// What a thumbnail is actually asked for: the strip's 320, or the text's 640 / 1280 (§5.3 accepts these widths).
public func answerThumbWidth(_ pixels: Int) -> Int {
    if pixels <= 320 { return 320 }
    if pixels <= 640 { return 640 }
    return 1280
}

/// The ways a file reaches the strip: linked, cited or sent by an agent, not a path written in code (§6.1).
public let fileStripVias: Set<String> = ["link", "citation", "presented", "tool"]

/// At most this many file cards in one answer's strip; more say 还有 N 个.
public let fileStripMax = 8

/// The files under an answer (§6.1, second point): those from link, citation, presented or tool, by `id` deduplicated
/// in the order the computer listed them, without the pictures drawn where the answer put them ([drawn]). `code` and
/// `path` files are left out on purpose: their words open them, and a code answer would otherwise end in cards.
public func fileStripFiles(_ message: Message, drawn: Set<String> = []) -> [FileRef] {
    guard let files = message.files else { return [] }
    var seen = Set<String>()
    return files.filter { file in
        !file.id.isEmpty && !drawn.contains(file.id)
            && (file.via.isEmpty || file.via.contains { fileStripVias.contains($0) })
    }.filter { seen.insert($0.id).inserted }
}

/// How many files the strip does not show: 还有 N 个.
public func fileStripExtra(_ files: [FileRef]) -> Int { max(files.count - fileStripMax, 0) }

/// The ids of the pictures the answer draws in place: each `![…](…)` matched with the files. The test is by Markdown
/// node, not by searching the words for `![`: an image's alt text never contains it, and a code sample does.
public func drawnPictureIDs(_ message: Message) -> Set<String> {
    guard message.files != nil else { return [] }
    var ids = Set<String>()
    collectPictures(MarkdownReader.answerBlocks(message.text, files: message.files, notes: message.fileNotes), into: &ids)
    return ids
}

private func collectPictures(_ blocks: [MarkdownBlock], into ids: inout Set<String>) {
    for block in blocks {
        switch block {
        case .pictureParagraph(let pieces):
            for piece in pieces {
                if case .picture(let file) = piece { ids.insert(file.id) }
            }
        case .quote(let children):
            collectPictures(children, into: &ids)
        case .list(_, _, let items):
            for item in items { collectPictures(item, into: &ids) }
        default:
            break
        }
    }
}

/// The words of a `code` or `path` file (§5.1 `texts`): each as the answer wrote it becomes a link to that file. Words
/// already inside another link stay as that link: one piece of text never carries two targets.
public func linkingFileTexts(_ runs: [InlineRun], files: [FileRef]?) -> [InlineRun] {
    guard let files, !runs.isEmpty else { return runs }
    var result = runs
    for file in files {
        for words in file.texts where !words.isEmpty {
            let text = result.map(\.text).joined()
            var search = text.startIndex
            while let found = text.range(of: words, range: search..<text.endIndex) {
                let lower = text.distance(from: text.startIndex, to: found.lowerBound)
                let upper = lower + text[found].count
                if let linked = linkCharacters(result, lower..<upper, url: answerItemLink(file)) { result = linked }
                search = found.upperBound
            }
        }
    }
    return result
}

/// [runs] with [range] linked, split at its ends; nil when any covered word already has a link.
private func linkCharacters(_ runs: [InlineRun], _ range: Range<Int>, url: String) -> [InlineRun]? {
    var bounds: [(Int, Int)] = []
    var at = 0
    for run in runs {
        let next = at + run.text.count
        bounds.append((at, next))
        at = next
    }
    guard range.lowerBound >= 0, range.upperBound <= at, range.lowerBound < range.upperBound else { return nil }
    for (index, run) in runs.enumerated()
    where bounds[index].0 < range.upperBound && bounds[index].1 > range.lowerBound && run.link != nil {
        return nil
    }
    var out: [InlineRun] = []
    for (index, run) in runs.enumerated() {
        let (low, high) = bounds[index]
        let start = max(low, range.lowerBound)
        let end = min(high, range.upperBound)
        guard start < end else {
            out.append(run)
            continue
        }
        let text = run.text
        let first = text.index(text.startIndex, offsetBy: start - low)
        let last = text.index(text.startIndex, offsetBy: end - low)
        if start > low { out.append(run.copy(String(text[text.startIndex..<first]))) }
        out.append(run.copy(String(text[first..<last]), link: url))
        if end < high { out.append(run.copy(String(text[last..<text.endIndex]))) }
    }
    return out
}

private extension InlineRun {
    func copy(_ text: String, link: String? = nil) -> InlineRun {
        InlineRun(text, bold: bold, italic: italic, code: code, strike: strike, link: link ?? self.link, muted: muted)
    }
}
