import Foundation
import Markdown

/// A stretch of inline text with its look (Android Markdown.kt inline: bold, italic, inline code, links). [muted] is
/// the grey of a note saying why a link cannot be opened (§6.1).
public struct InlineRun: Sendable, Equatable {
    public var text: String
    public var bold = false
    public var italic = false
    public var code = false
    public var strike = false
    /// Only http and https addresses without a user part open (Android safeWebLink); a file entry and a grey note's
    /// reason carry a `teleply-` address instead (AnswerFiles.swift).
    public var link: String?
    public var muted = false

    public init(_ text: String, bold: Bool = false, italic: Bool = false, code: Bool = false, strike: Bool = false,
                link: String? = nil, muted: Bool = false) {
        self.text = text
        self.bold = bold
        self.italic = italic
        self.code = code
        self.strike = strike
        self.link = link
        self.muted = muted
    }
}

extension Array where Element == InlineRun {
    /// The text without its look: what 复制 and the screen reader get.
    public var plain: String { map(\.text).joined() }
}

/// A paragraph split around the pictures an answer draws where it put them (§6.1): its words, then a picture, then more
/// words. The test is by Markdown node, not by searching the words for `![` (an image's alt text never contains it).
public enum MarkdownPiece: Sendable, Equatable {
    case words([InlineRun])
    case picture(FileRef)
    /// A relative picture in a Markdown file's reading view, fetched through `/api/file/resource` (§5.6).
    case resource(String)
}

/// Markdown in the shapes the native renderer draws, the same set as Android's Markdown.kt: headings,
/// paragraphs, code, quotes, lists, tables and rules. HTML stays literal text; a picture is drawn only when the
/// computer listed it as one it can thumb ([pictureParagraph]); otherwise it stays a line of words, as in 0.9.0.
public indirect enum MarkdownBlock: Sendable, Equatable {
    case heading(level: Int, runs: [InlineRun])
    case paragraph([InlineRun])
    /// A paragraph with a picture drawn in place (§6.1).
    case pictureParagraph([MarkdownPiece])
    case code(language: String, text: String)
    case quote([MarkdownBlock])
    case list(ordered: Bool, start: Int, items: [[MarkdownBlock]])
    case table(header: [String], rows: [[String]])
    case rule
    case html(String)
}

/// A conversation a Codex reply says it made (web remote.html assistantMarkdown): a `threadId` one opens; a
/// `clientThreadId` one is still being made.
public struct CreatedThread: Sendable, Equatable {
    public let id: String
    public let ready: Bool

    public init(id: String, ready: Bool) {
        self.id = id
        self.ready = ready
    }
}

public enum MarkdownReader {
    /// Smart punctuation stays off: straight quotes and dashes keep the original text (spec B16).
    public static func blocks(_ source: String) -> [MarkdownBlock] {
        blocks(source, Look())
    }

    /// An answer's blocks with the files the computer listed for it (§5.1): a link opens the very entry, a picture the
    /// computer can thumb is drawn where the answer put it, and a link that cannot be given says why in grey (§6.1).
    /// [files] nil is an older computer, and the blocks are exactly 0.9.0's.
    public static func answerBlocks(_ source: String, files: [FileRef]?, notes: [FileNote] = [],
                                    resources: Bool = false) -> [MarkdownBlock] {
        var look = Look()
        look.files = files
        look.notes = notes
        look.resources = resources
        return blocks(source, look)
    }

    private static func blocks(_ source: String, _ look: Look) -> [MarkdownBlock] {
        let document = Document(parsing: tidy(source), options: [.disableSmartOpts])
        return document.children.compactMap { block($0, look) }
    }

    /// What Codex writes for itself goes before an answer is shown, copied or shared (user 10-27, a phone user asked
    /// what the lines at the bottom were): its memory citations go whole, and a file citation becomes a link to the
    /// file, which opens like any file link. A conversation it made goes from the text too, to a button under it
    /// ([createdThreads]), and so do its plan's `<proposed_plan>` tags (web assistantMarkdown).
    public static func tidy(_ source: String) -> String {
        let source = directives(source).text
        guard source.contains("oai-mem-citation") || source.contains(":codex-file-citation") else { return source }
        var text = source.replacingOccurrences(of: #"\s*<oai-mem-citation>[\s\S]*?</oai-mem-citation>"#, with: "", options: .regularExpression)
        guard let directive = try? NSRegularExpression(pattern: #":codex-file-citation\{[^}]*?path="([^"]+)"[^}]*\}"#) else { return text }
        for match in directive.matches(in: text, range: NSRange(text.startIndex..., in: text)).reversed() {
            guard let whole = Range(match.range, in: text), let found = Range(match.range(at: 1), in: text) else { continue }
            let path = String(text[found])
            let name = path.split(whereSeparator: { $0 == "/" || $0 == "\\" }).last.map(String.init) ?? path
            text.replaceSubrange(whole, with: "[\(name)](<\(path)>)")
        }
        return text
    }

    /// The conversations a reply says it made, in order: 打开新建对话 under the text for each (user 10-27: the line
    /// `::created-thread{threadId="…"}` showed raw on the phone; the web draws a button).
    public static func createdThreads(_ source: String) -> [CreatedThread] {
        directives(source).threads
    }

    /// The lines Codex writes for its desktop, outside code (web remote.html assistantMarkdown): a line of its own
    /// `::created-thread{threadId="…"}` (or `clientThreadId`) and `<proposed_plan>` tags leave the text.
    static func directives(_ source: String) -> (text: String, threads: [CreatedThread]) {
        guard source.contains("::created-thread{") || source.contains("proposed_plan>") else { return (source, []) }
        var lines: [Substring] = []
        var threads: [CreatedThread] = []
        var fence: Character?
        for line in source.split(separator: "\n", omittingEmptySubsequences: false) {
            let bare = line.trimmingCharacters(in: .whitespacesAndNewlines)
            if let mark = bare.first, mark == "`" || mark == "~", bare.hasPrefix(String(repeating: mark, count: 3)) {
                if fence == nil { fence = mark } else if fence == mark { fence = nil }
                lines.append(line)
                continue
            }
            if fence == nil {
                if bare.range(of: #"^::created-thread\{(threadId|clientThreadId)="[a-zA-Z0-9-]+"\}$"#, options: .regularExpression) != nil,
                   let quote = bare.firstIndex(of: "\"") {
                    let id = bare[bare.index(after: quote)...].prefix { $0 != "\"" }
                    threads.append(CreatedThread(id: String(id), ready: bare.hasPrefix("::created-thread{threadId=")))
                    continue
                }
                if bare == "<proposed_plan>" || bare == "</proposed_plan>" { continue }
            }
            lines.append(line)
        }
        return (lines.joined(separator: "\n"), threads)
    }

    /// A Windows path an answer links to (web markdown-ui.js local): the drive letter and a slash, after any %-escapes.
    public static func localPath(_ destination: String?) -> String? {
        guard let destination else { return nil }
        let path = destination.removingPercentEncoding ?? destination
        guard path.range(of: #"^[A-Za-z]:[\\/]"#, options: .regularExpression) != nil else { return nil }
        // A line number after the file (report.md:12 or :12-20) names the same file (message_files.references).
        return path.replacingOccurrences(of: #":\d+(?:-\d+)?$"#, with: "", options: .regularExpression)
    }

    /// The link a file in an answer carries on screen; the conversation page opens its file page (fileLinkPath).
    public static func fileLink(_ path: String) -> String {
        "teleply-file:" + (path.addingPercentEncoding(withAllowedCharacters: .alphanumerics) ?? "")
    }

    /// The path behind a file link drawn by [fileLink]; nil for any other address.
    public static func fileLinkPath(_ url: URL) -> String? {
        let text = url.absoluteString
        guard text.hasPrefix("teleply-file:") else { return nil }
        return String(text.dropFirst("teleply-file:".count)).removingPercentEncoding
    }

    static func block(_ markup: any Markup) -> MarkdownBlock? { block(markup, Look()) }

    static func block(_ markup: any Markup, _ look: Look) -> MarkdownBlock? {
        switch markup {
        case let heading as Heading:
            return .heading(level: heading.level, runs: runs(heading.children, look))
        case let paragraph as Paragraph:
            // A paragraph with a picture the computer can thumb is split around it; one without stays exactly as
            // 0.9.0 drew it.
            if containsImage(paragraph) && (look.files != nil || look.resources) {
                return .pictureParagraph(paragraphPieces(paragraph, look))
            }
            return .paragraph(runs(paragraph.children, look))
        case let code as CodeBlock:
            return .code(language: code.language ?? "", text: code.code)
        case let quote as BlockQuote:
            return .quote(quote.children.compactMap { block($0, look) })
        case let list as UnorderedList:
            return .list(ordered: false, start: 1, items: list.listItems.map { $0.children.compactMap { block($0, look) } })
        case let list as OrderedList:
            return .list(ordered: true, start: Int(list.startIndex), items: list.listItems.map { $0.children.compactMap { block($0, look) } })
        case let table as Table:
            // The types pick the eager map: cells and rows are lazy sequences in swift-markdown.
            let header: [String] = table.head.cells.map { cellText($0) }
            let rows: [[String]] = table.body.rows.map { row in row.cells.map { cellText($0) } }
            return .table(header: header, rows: rows)
        case is ThematicBreak:
            return .rule
        case let html as HTMLBlock:
            return .html(html.rawHTML)
        default:
            return nil
        }
    }

    struct Look {
        var bold = false, italic = false, strike = false
        var link: String?
        /// The answer's files and the reasons for those it cannot give (§5.1); nil files is an older computer.
        var files: [FileRef]?
        var notes: [FileNote] = []
        /// A Markdown file's reading view: relative pictures are resources beside the file (§5.6).
        var resources = false
    }

    /// A cell's words without their marks: plainText keeps the backticks round inline code.
    static func cellText(_ cell: Table.Cell) -> String {
        runs(cell.children).map(\.text).joined()
    }

    /// Whether a node holds an `Image` anywhere: a link or emphasis wrapped around one counts (§6.1).
    static func containsImage(_ markup: any Markup) -> Bool {
        for child in markup.children {
            if child is Image || containsImage(child) { return true }
        }
        return false
    }

    /// The picture a node is, or wraps whole (a link or emphasis whose only child is the picture).
    static func wrappedImage(_ markup: any Markup) -> Image? {
        if let image = markup as? Image { return image }
        guard markup is Link || markup is Emphasis || markup is Strong else { return nil }
        let children = Array(markup.children)
        guard children.count == 1 else { return nil }
        return wrappedImage(children[0])
    }

    /// A paragraph split around the pictures drawn where it put them (§6.1). The test is by node, not by its words: an
    /// image's alt text never contains `![`, and a code sample does.
    static func paragraphPieces(_ paragraph: Paragraph, _ look: Look) -> [MarkdownPiece] {
        var pieces: [MarkdownPiece] = []
        var words: [any Markup] = []
        func flush() {
            guard !words.isEmpty else { return }
            let runs = runs(nodes: words, look: look)
            if !runs.isEmpty { pieces.append(.words(runs)) }
            words.removeAll()
        }
        for child in paragraph.children {
            let image = wrappedImage(child)
            let destination = image?.source ?? ""
            let file = image.flatMap { _ in look.files.flatMap { fileForLink($0, destination) } }
            let picture = file.flatMap { $0.picture ? $0 : nil }
            let resource = image != nil && look.files == nil && look.resources && markdownRelativeResource(destination)
            if let picture {
                flush()
                pieces.append(.picture(picture))
            } else if resource {
                flush()
                pieces.append(.resource(destination))
            } else {
                words.append(child)
            }
        }
        flush()
        return pieces
    }

    static func runs(_ children: MarkupChildren, _ look: Look = Look()) -> [InlineRun] {
        runs(nodes: Array(children), look: look)
    }

    static func runs(nodes: [any Markup], look: Look = Look()) -> [InlineRun] {
        nodes.flatMap { child -> [InlineRun] in
            switch child {
            case let text as Text:
                return [InlineRun(text.string, bold: look.bold, italic: look.italic, strike: look.strike, link: look.link)]
            case is SoftBreak:
                return [InlineRun(" ", bold: look.bold, italic: look.italic, link: look.link)]
            case is LineBreak:
                return [InlineRun("\n")]
            case let strong as Strong:
                var inner = look; inner.bold = true
                return runs(strong.children, inner)
            case let emphasis as Emphasis:
                var inner = look; inner.italic = true
                return runs(emphasis.children, inner)
            case let strike as Strikethrough:
                var inner = look; inner.strike = true
                return runs(strike.children, inner)
            case let code as InlineCode:
                return [InlineRun(code.code, code: true, link: look.link)]
            case let link as Link:
                return linkRuns(link, look)
            case let image as Image:
                return imageRuns(image, look)
            case let html as InlineHTML:
                return [InlineRun(html.rawHTML)]
            default:
                return [InlineRun(child.format())]
            }
        }
    }

    /// One link, the way §6.1 shows it: the answer's own file entry when there is one, otherwise the 0.9.0 file page,
    /// a grey note with the reason, a web address, or words only. `#`, `mailto:` and other protocols are words only.
    private static func linkRuns(_ link: Link, _ look: Look) -> [InlineRun] {
        let destination = link.destination ?? ""
        let file = look.files.flatMap { fileForLink($0, destination) }
        let note = look.files != nil ? noteForLink(look.notes, destination) : nil
        let path = localPath(destination)
        // A file on the computer opens its page, to look at or save (web: a local link downloads).
        if let file {
            var inner = look; inner.link = answerItemLink(file)
            return runs(link.children, inner)
        }
        if let path, look.files == nil {
            var inner = look; inner.link = fileLink(path)
            return runs(link.children, inner)
        }
        if path != nil {
            // A newer computer did not list it; its note says why, if it gave one.
            var words = runs(link.children, look)
            words.append(InlineRun(" "))
            if let note {
                words.append(InlineRun("（\(note.short)）", link: answerNoteLink(note), muted: true))
            } else {
                words.append(InlineRun("（找不到文件）", muted: true))
            }
            return words
        }
        // A link that looked like a file but cannot be given: its words stay, the reason follows in grey.
        if let note {
            var inner = look; inner.link = answerNoteLink(note)
            var words = runs(link.children, inner)
            words.append(InlineRun(" "))
            words.append(InlineRun("（\(note.short)）", link: answerNoteLink(note), muted: true))
            return words
        }
        if localWebLink(destination) {
            var words = runs(link.children, look)
            words.append(InlineRun(" "))
            words.append(InlineRun("（电脑本机网址，手机打不开）", muted: true))
            return words
        }
        if let safe = safeWebLink(destination) {
            var inner = look; inner.link = safe
            return runs(link.children, inner)
        }
        // An older computer keeps 0.9.0's words for an address that looks like a file; #, mailto: and the rest are
        // words only (§6.1).
        var words = runs(link.children, look)
        if look.files == nil && fileLikeLink(destination) {
            words.append(InlineRun("（链接未开放）"))
        }
        return words
    }

    private static func imageRuns(_ image: Image, _ look: Look) -> [InlineRun] {
        let label = image.plainText.isEmpty ? (image.source ?? "") : image.plainText
        if let files = look.files, let file = fileForLink(files, image.source ?? "") {
            return [InlineRun("[图片：\(label)]", link: answerItemLink(file))]
        }
        if let path = localPath(image.source) {
            return [InlineRun("[图片：\(label)]", link: fileLink(path))]
        }
        return [InlineRun("[图片：\(label) · 可在当前文件中查看已授权资源]")]
    }

    /// Opens only http and https addresses without a user part (Android Markdown.kt safeWebLink).
    public static func safeWebLink(_ destination: String?) -> String? {
        guard let destination, let parts = URLComponents(string: destination), let scheme = parts.scheme?.lowercased(),
              scheme == "http" || scheme == "https", parts.host?.isEmpty == false, parts.user == nil, parts.password == nil else { return nil }
        return destination
    }
}
