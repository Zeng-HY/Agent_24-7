import Foundation
import Markdown

/// A stretch of inline text with its look (Android Markdown.kt inline: bold, italic, inline code, links).
public struct InlineRun: Sendable, Equatable {
    public var text: String
    public var bold = false
    public var italic = false
    public var code = false
    public var strike = false
    /// Only http and https addresses without a user part open (Android safeWebLink).
    public var link: String?

    public init(_ text: String, bold: Bool = false, italic: Bool = false, code: Bool = false, strike: Bool = false, link: String? = nil) {
        self.text = text
        self.bold = bold
        self.italic = italic
        self.code = code
        self.strike = strike
        self.link = link
    }
}

extension Array where Element == InlineRun {
    /// The text without its look: what 复制 and the screen reader get.
    public var plain: String { map(\.text).joined() }
}

/// Markdown in the shapes the native renderer draws, the same set as Android's Markdown.kt: headings,
/// paragraphs, code, quotes, lists, tables and rules. HTML stays literal text; images are not loaded.
public indirect enum MarkdownBlock: Sendable, Equatable {
    case heading(level: Int, runs: [InlineRun])
    case paragraph([InlineRun])
    case code(language: String, text: String)
    case quote([MarkdownBlock])
    case list(ordered: Bool, start: Int, items: [[MarkdownBlock]])
    case table(header: [String], rows: [[String]])
    case rule
    case html(String)
}

public enum MarkdownReader {
    /// Smart punctuation stays off: straight quotes and dashes keep the original text (spec B16).
    public static func blocks(_ source: String) -> [MarkdownBlock] {
        let document = Document(parsing: source, options: [.disableSmartOpts])
        return document.children.compactMap(block)
    }

    static func block(_ markup: any Markup) -> MarkdownBlock? {
        switch markup {
        case let heading as Heading:
            return .heading(level: heading.level, runs: runs(heading.children))
        case let paragraph as Paragraph:
            return .paragraph(runs(paragraph.children))
        case let code as CodeBlock:
            return .code(language: code.language ?? "", text: code.code)
        case let quote as BlockQuote:
            return .quote(quote.children.compactMap(block))
        case let list as UnorderedList:
            return .list(ordered: false, start: 1, items: list.listItems.map { $0.children.compactMap(block) })
        case let list as OrderedList:
            return .list(ordered: true, start: Int(list.startIndex), items: list.listItems.map { $0.children.compactMap(block) })
        case let table as Table:
            // The types pick the eager map: cells and rows are lazy sequences in swift-markdown.
            let header: [String] = table.head.cells.map { $0.plainText }
            let rows: [[String]] = table.body.rows.map { row in row.cells.map { $0.plainText } }
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
    }

    static func runs(_ children: MarkupChildren, _ look: Look = Look()) -> [InlineRun] {
        children.flatMap { child -> [InlineRun] in
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
                guard let safe = safeWebLink(link.destination) else {
                    return runs(link.children, look) + [InlineRun("（链接未开放）")]
                }
                var inner = look; inner.link = safe
                return runs(link.children, inner)
            case let image as Image:
                return [InlineRun("[图片：\(image.plainText.isEmpty ? (image.source ?? "") : image.plainText) · 可在当前文件中查看已授权资源]")]
            case let html as InlineHTML:
                return [InlineRun(html.rawHTML)]
            default:
                return [InlineRun(child.format())]
            }
        }
    }

    /// Opens only http and https addresses without a user part (Android Markdown.kt safeWebLink).
    public static func safeWebLink(_ destination: String?) -> String? {
        guard let destination, let parts = URLComponents(string: destination), let scheme = parts.scheme?.lowercased(),
              scheme == "http" || scheme == "https", parts.host?.isEmpty == false, parts.user == nil, parts.password == nil else { return nil }
        return destination
    }
}
