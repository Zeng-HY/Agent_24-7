import Foundation
import Testing
@testable import TeleplyModel

struct MarkdownReaderTests {
    @Test func readsTheBlocksAndroidDraws() throws {
        let blocks = MarkdownReader.blocks("""
        # 标题

        段落里有 "直引号" -- 和短横线。

        - 一
        - 二

        3. 甲

        > 引用

        ```swift
        let x = 1
        ```

        | 列 | 值 |
        |---|---|
        | a | 1 |

        ---

        <div>html</div>
        """)
        try #require(blocks.count == 9)
        #expect(blocks[0] == .heading(level: 1, runs: [InlineRun("标题")]))
        // Smart punctuation off: the quotes and the double hyphen stay as typed (spec B16).
        guard case .paragraph(let runs) = blocks[1] else { Issue.record("expected a paragraph"); return }
        #expect(runs.plain == "段落里有 \"直引号\" -- 和短横线。")
        #expect(blocks[2] == .list(ordered: false, start: 1, items: [[.paragraph([InlineRun("一")])], [.paragraph([InlineRun("二")])]]))
        #expect(blocks[3] == .list(ordered: true, start: 3, items: [[.paragraph([InlineRun("甲")])]]))
        #expect(blocks[4] == .quote([.paragraph([InlineRun("引用")])]))
        guard case .code(let language, let code) = blocks[5] else { Issue.record("expected code"); return }
        #expect(language == "swift")
        #expect(code.trimmingCharacters(in: .newlines) == "let x = 1")
        #expect(blocks[6] == .table(header: ["列", "值"], rows: [["a", "1"]]))
        #expect(blocks[7] == .rule)
        guard case .html(let raw) = blocks[8] else { Issue.record("expected html"); return }
        #expect(raw.trimmingCharacters(in: .whitespacesAndNewlines) == "<div>html</div>")
    }

    @Test func inlineLooksAndOnlyWebLinksOpen() {
        let blocks = MarkdownReader.blocks("**粗** *斜* `码` [网页](https://example.com) [文件](file:///etc/passwd) ![图](a.png)")
        guard case .paragraph(let runs) = blocks.first else { Issue.record("expected a paragraph"); return }
        #expect(runs.contains(InlineRun("粗", bold: true)))
        #expect(runs.contains(InlineRun("斜", italic: true)))
        #expect(runs.contains(InlineRun("码", code: true)))
        #expect(runs.contains(InlineRun("网页", link: "https://example.com")))
        #expect(runs.contains(InlineRun("（链接未开放）")))
        #expect(runs.plain.contains("[图片：图 · 可在当前文件中查看已授权资源]"))
    }
}
