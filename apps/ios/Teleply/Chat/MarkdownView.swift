import SwiftUI
import TeleplyModel

/// Parsed texts, so that a redraw or scrolling back does not parse again (Android MarkdownCache). Bounded by the
/// text kept, about 4 MB, not by a count: a long page (60 records with many steps) is more than the 64 texts kept
/// before, and with the oldest going first every redraw parsed the whole page again (10-27). The least recently used
/// go first.
@MainActor
private enum MarkdownCache {
    private static let room = 4 * 1024 * 1024
    private static var entries: [String: (blocks: [MarkdownBlock], used: Int)] = [:]
    private static var kept = 0
    private static var clock = 0

    static func blocks(_ source: String) -> [MarkdownBlock] {
        clock += 1
        if let hit = entries[source] {
            entries[source]?.used = clock
            return hit.blocks
        }
        let parsed = MarkdownReader.blocks(source)
        let size = source.utf8.count
        guard size <= room / 4 else { return parsed }
        entries[source] = (parsed, clock)
        kept += size
        if kept > room { trim() }
        return parsed
    }

    /// Drops the least recently used texts until a quarter of the room is free, so this runs once in many misses.
    private static func trim() {
        for (source, _) in entries.sorted(by: { $0.value.used < $1.value.used }) {
            guard kept > room * 3 / 4 else { break }
            entries[source] = nil
            kept -= source.utf8.count
        }
    }
}

/// How a message's text looks: answers 16 pt at line height 1.7; links and inline code take the colours the
/// surface needs (the blue user bubble has its own).
struct MarkdownLook {
    var link = Palette.accent
    var code = Palette.codeFill
}

/// Native Markdown blocks in the web's reading style (spec 4.3, 8.3; Android Markdown.kt): headings, paragraphs,
/// code panels, quotes, lists, tables and rules. HTML stays text and is never run; images are not loaded.
struct MarkdownView: View {
    let source: String
    var look = MarkdownLook()
    /// Answers take the reading width; a bubble hugs its text.
    var fill = true

    var body: some View {
        let blocks = MarkdownCache.blocks(source)
        VStack(alignment: .leading, spacing: 12) {
            ForEach(Array(blocks.enumerated()), id: \.offset) { index, block in
                MarkdownBlockView(block: block, first: index == 0, look: look)
            }
        }
        .frame(maxWidth: fill ? .infinity : nil, alignment: .leading)
    }
}

/// Inline runs as styled text: bold, italic, code, strikethrough and links that open in the browser. The page's
/// font applies, so it grows with the system text size.
func styledText(_ runs: [InlineRun], look: MarkdownLook) -> AttributedString {
    var result = AttributedString()
    for run in runs {
        var piece = AttributedString(run.text)
        var intent: InlinePresentationIntent = []
        if run.bold { intent.insert(.stronglyEmphasized) }
        if run.italic { intent.insert(.emphasized) }
        if run.code { intent.insert(.code) }
        if run.strike { intent.insert(.strikethrough) }
        if !intent.isEmpty { piece.inlinePresentationIntent = intent }
        if run.code { piece.backgroundColor = look.code }
        if let link = run.link, let url = URL(string: link) {
            piece.link = url
            piece.foregroundColor = look.link
        }
        result += piece
    }
    return result
}

private struct MarkdownBlockView: View {
    let block: MarkdownBlock
    let first: Bool
    let look: MarkdownLook

    var body: some View {
        switch block {
        case .heading(let level, let runs):
            Group {
                switch level {
                case 1: Text(styledText(runs, look: look)).scaledFont(18, .semibold, relativeTo: .title3, lineHeight: 1.45)
                case 2: Text(styledText(runs, look: look)).scaledFont(16, .semibold, relativeTo: .headline, lineHeight: 1.5)
                default: Text(styledText(runs, look: look)).scaledFont(16, .semibold, relativeTo: .body, lineHeight: 1.7)
                }
            }
            .padding(.top, first ? 0 : 8)
            .accessibilityAddTraits(.isHeader)
        case .paragraph(let runs):
            Text(styledText(runs, look: look))
                .readingFont()
                .fixedSize(horizontal: false, vertical: true)
        case .code(let language, let text):
            CodePanel(label: language.isEmpty ? "代码" : language, code: text,
                      copyLabel: language.isEmpty ? "复制代码" : "复制 \(language) 代码")
        case .quote(let children):
            HStack(alignment: .top, spacing: 12) {
                Rectangle().fill(Palette.line).frame(width: 3)
                VStack(alignment: .leading, spacing: 8) {
                    ForEach(Array(children.enumerated()), id: \.offset) { _, child in
                        MarkdownBlockView(block: child, first: false, look: look)
                    }
                }
            }
            .fixedSize(horizontal: false, vertical: true)
        case .list(let ordered, let start, let items):
            VStack(alignment: .leading, spacing: 6) {
                ForEach(Array(items.enumerated()), id: \.offset) { index, item in
                    HStack(alignment: .firstTextBaseline, spacing: 0) {
                        Text(verbatim: ordered ? "\(start + index)." : "•")
                            .readingFont()
                            .frame(minWidth: 20, alignment: .leading)
                        VStack(alignment: .leading, spacing: 6) {
                            ForEach(Array(item.enumerated()), id: \.offset) { _, child in
                                MarkdownBlockView(block: child, first: false, look: look)
                            }
                        }
                    }
                }
            }
        case .table(let header, let rows):
            MarkdownTable(header: header, rows: rows)
        case .rule:
            Rectangle().fill(Palette.line).frame(height: 1)
        case .html(let raw):
            // Native text, never executable HTML.
            Text(verbatim: raw)
                .smallBodyFont()
        }
    }
}

/// A table that scrolls sideways inside its own box; the message never moves sideways (B16). Cells are 200 pt,
/// wider with larger text; the header row has the panel colour.
private struct MarkdownTable: View {
    let header: [String]
    let rows: [[String]]
    @ScaledMetric(relativeTo: .subheadline) private var cell: CGFloat = 200

    var body: some View {
        ScrollView(.horizontal) {
            VStack(alignment: .leading, spacing: 0) {
                row(header, head: true)
                ForEach(Array(rows.enumerated()), id: \.offset) { _, values in
                    row(values, head: false)
                }
            }
        }
        .scrollIndicators(.automatic)
    }

    private func row(_ values: [String], head: Bool) -> some View {
        VStack(spacing: 0) {
            HStack(alignment: .top, spacing: 0) {
                ForEach(Array(values.enumerated()), id: \.offset) { _, value in
                    Text(verbatim: value)
                        .smallBodyFont(head ? .semibold : .regular)
                        .foregroundStyle(Palette.ink)
                        .frame(width: min(cell, 320), alignment: .leading)
                        .padding(12)
                }
            }
            .background(head ? Palette.panel : Palette.page)
            Rectangle().fill(Palette.line).frame(height: 1)
        }
    }
}

/// Code and command panel (web .code-wrap; Android CodePanel): light grey, thin edge, 12 pt corners; a header with
/// the label, 原始行 / 自动换行 and 复制 that does not scroll. Wraps by default; 原始行 keeps lines and scrolls
/// sideways. 复制 always takes the complete original text (B16).
struct CodePanel: View {
    let label: String
    let code: String
    let copyLabel: String
    @State private var original = false
    @State private var copied = false

    var body: some View {
        let full = code.hasSuffix("\n") ? String(code.dropLast()) : code
        VStack(alignment: .leading, spacing: 0) {
            HStack(spacing: 0) {
                Text(label)
                    .noteFont()
                    .foregroundStyle(Palette.muted)
                    .lineLimit(1)
                    .frame(maxWidth: .infinity, alignment: .leading)
                Button(original ? "自动换行" : "原始行") { original.toggle() }
                    .noteFont()
                    .foregroundStyle(Palette.muted)
                    .padding(.horizontal, 8)
                    .frame(minHeight: 44)
                Button(copied ? "已复制" : "复制") {
                    UIPasteboard.general.string = full
                    copied = true
                }
                .noteFont()
                .foregroundStyle(Palette.muted)
                .padding(.horizontal, 8)
                .frame(minHeight: 44)
                .accessibilityLabel(Text(copyLabel))
                .task(id: copied) {
                    guard copied else { return }
                    try? await Task.sleep(for: .seconds(1.5))
                    copied = false
                }
            }
            .padding(.leading, 12)
            .padding(.trailing, 4)
            Rectangle().fill(Palette.codeEdge).frame(height: 1)
            if original {
                ScrollView(.horizontal) {
                    Text(verbatim: full)
                        .codeFont()
                        .foregroundStyle(Palette.ink)
                        .fixedSize()
                        .padding(12)
                }
            } else {
                Text(verbatim: full)
                    .codeFont()
                    .foregroundStyle(Palette.ink)
                    .fixedSize(horizontal: false, vertical: true)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(12)
            }
        }
        .background(Palette.codeFill, in: RoundedRectangle(cornerRadius: 12, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: 12, style: .continuous).stroke(Palette.codeEdge, lineWidth: 1))
    }
}
