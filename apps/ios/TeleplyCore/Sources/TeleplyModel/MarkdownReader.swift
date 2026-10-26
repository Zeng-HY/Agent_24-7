import Markdown

/// Markdown in the shapes the native renderer draws, the same set as Android's Markdown.kt: headings,
/// paragraphs, code, quotes, lists, tables and rules. HTML stays literal text; images are not loaded.
/// Inline styling (bold, code, links) arrives with the reading screen in phase 1.
public indirect enum MarkdownBlock: Sendable, Equatable {
    case heading(level: Int, text: String)
    case paragraph(String)
    case code(language: String, text: String)
    case quote([MarkdownBlock])
    case list(ordered: Bool, items: [[MarkdownBlock]])
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
            return .heading(level: heading.level, text: heading.plainText)
        case let paragraph as Paragraph:
            return .paragraph(paragraph.plainText)
        case let code as CodeBlock:
            return .code(language: code.language ?? "", text: code.code)
        case let quote as BlockQuote:
            return .quote(quote.children.compactMap(block))
        case let list as UnorderedList:
            return .list(ordered: false, items: list.listItems.map { $0.children.compactMap(block) })
        case let list as OrderedList:
            return .list(ordered: true, items: list.listItems.map { $0.children.compactMap(block) })
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
}
