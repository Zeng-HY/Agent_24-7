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

    static func blocks(_ source: String, files: [FileRef]? = nil, notes: [FileNote] = [],
                       resources: Bool = false) -> [MarkdownBlock] {
        let key = cacheKey(source, files, notes, resources)
        clock += 1
        if let hit = entries[key] {
            entries[key]?.used = clock
            return hit.blocks
        }
        let parsed = MarkdownReader.answerBlocks(source, files: files, notes: notes, resources: resources)
        let size = key.utf8.count
        guard size <= room / 4 else { return parsed }
        entries[key] = (parsed, clock)
        kept += size
        if kept > room { trim() }
        return parsed
    }

    /// One text with an older computer's answer is the key; with a computer's files, what the drawings and links rest on
    /// is part of it, so a file that changed its `v` is parsed again. A Markdown file's reading view is another key.
    private static func cacheKey(_ source: String, _ files: [FileRef]?, _ notes: [FileNote], _ resources: Bool) -> String {
        guard let files else { return resources ? source + "\u{1F}resources" : source }
        var key = source + "\u{1F}files"
        for file in files {
            key += "\u{1F}\(file.id)|\(file.path)|\(file.version)|\(file.view)|\(file.thumb ? 1 : 0)|\(file.kind)"
            key += "|" + file.texts.joined(separator: "\u{1E}")
        }
        key += "\u{1F}notes"
        for note in notes { key += "\u{1F}\(note.href)|\(note.reason)" }
        return key
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
/// code panels, quotes, lists, tables and rules. HTML stays text and is never run. With the answer's `files` (§5.1), a
/// picture the computer can thumb is drawn in place and a link opens that very entry; without them (an older computer)
/// the text is exactly 0.9.0's.
struct MarkdownView: View {
    let source: String
    var look = MarkdownLook()
    /// Answers take the reading width; a bubble hugs its text.
    var fill = true
    /// The answer's files and the reasons for those it cannot give (§5.1, §6.4); nil is an older computer.
    var files: [FileRef]? = nil
    var notes: [FileNote] = []
    /// How a picture in the text is fetched: its entry and a width, as thumb bytes (§6.1).
    var thumb: ((FileRef, Int) async -> Data?)? = nil
    /// A tap on a picture opens the answer's pictures at that one (§6.2); nil keeps the file page's own link.
    var openPicture: ((FileRef) -> Bool)? = nil
    /// A Markdown file's reading view: relative pictures are fetched from the file's own folder (§5.6).
    var resources = false
    var resource: ((String) async -> Data?)? = nil

    var body: some View {
        let blocks = MarkdownCache.blocks(source, files: files, notes: notes, resources: resources)
        VStack(alignment: .leading, spacing: 12) {
            ForEach(Array(blocks.enumerated()), id: \.offset) { index, block in
                MarkdownBlockView(block: block, first: index == 0, look: look, files: files, notes: notes,
                                  thumb: thumb, openPicture: openPicture, resource: resource)
            }
        }
        .frame(maxWidth: fill ? .infinity : nil, alignment: .leading)
    }
}

/// Inline runs as styled text: bold, italic, code, strikethrough and links that open in the browser or, with an
/// answer's files, that very file's page. A code or path file's words become links too (§5.1 `texts`); words already
/// in a link keep that one. The page's font applies, so it grows with the system text size.
func styledText(_ runs: [InlineRun], look: MarkdownLook, files: [FileRef]? = nil) -> AttributedString {
    var result = AttributedString()
    for run in linkingFileTexts(runs, files: files) {
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
        }
        if run.muted { piece.foregroundColor = Palette.muted }
        else if run.link != nil { piece.foregroundColor = look.link }
        result += piece
    }
    return result
}

private struct MarkdownBlockView: View {
    let block: MarkdownBlock
    let first: Bool
    let look: MarkdownLook
    let files: [FileRef]?
    let notes: [FileNote]
    let thumb: ((FileRef, Int) async -> Data?)?
    let openPicture: ((FileRef) -> Bool)?
    let resource: ((String) async -> Data?)?

    var body: some View {
        switch block {
        case .heading(let level, let runs):
            Group {
                switch level {
                case 1: Text(styledText(runs, look: look, files: files)).scaledFont(18, .semibold, relativeTo: .title3, lineHeight: 1.45)
                case 2: Text(styledText(runs, look: look, files: files)).scaledFont(16, .semibold, relativeTo: .headline, lineHeight: 1.5)
                default: Text(styledText(runs, look: look, files: files)).scaledFont(16, .semibold, relativeTo: .body, lineHeight: 1.7)
                }
            }
            .padding(.top, first ? 0 : 8)
            .accessibilityAddTraits(.isHeader)
        case .paragraph(let runs):
            Text(styledText(runs, look: look, files: files))
                .readingFont()
                .fixedSize(horizontal: false, vertical: true)
        case .pictureParagraph(let pieces):
            // A picture where the answer put it, with the words before and after it (§6.1).
            VStack(alignment: .leading, spacing: 8) {
                ForEach(Array(pieces.enumerated()), id: \.offset) { _, piece in
                    switch piece {
                    case .words(let runs):
                        if !runs.isEmpty {
                            Text(styledText(runs, look: look, files: files))
                                .readingFont()
                                .fixedSize(horizontal: false, vertical: true)
                        }
                    case .picture(let file):
                        AnswerPicture(file: file, thumb: thumb, openPicture: openPicture)
                    case .resource(let source):
                        ResourcePicture(source: source, loader: resource)
                    }
                }
            }
        case .code(let language, let text):
            CodePanel(label: language.isEmpty ? "代码" : language, code: text,
                      copyLabel: language.isEmpty ? "复制代码" : "复制 \(language) 代码")
        case .quote(let children):
            HStack(alignment: .top, spacing: 12) {
                Rectangle().fill(Palette.line).frame(width: 3)
                VStack(alignment: .leading, spacing: 8) {
                    ForEach(Array(children.enumerated()), id: \.offset) { _, child in
                        MarkdownBlockView(block: child, first: false, look: look, files: files, notes: notes, thumb: thumb, openPicture: openPicture, resource: resource)
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
                                MarkdownBlockView(block: child, first: false, look: look, files: files, notes: notes, thumb: thumb, openPicture: openPicture, resource: resource)
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
                Text(L(label))
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
