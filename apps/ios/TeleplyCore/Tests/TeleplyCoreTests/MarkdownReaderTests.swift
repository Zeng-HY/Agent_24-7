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

        1. 甲

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
        #expect(blocks[0] == .heading(level: 1, text: "标题"))
        // Smart punctuation off: the quotes and the double hyphen stay as typed (spec B16).
        #expect(blocks[1] == .paragraph("段落里有 \"直引号\" -- 和短横线。"))
        #expect(blocks[2] == .list(ordered: false, items: [[.paragraph("一")], [.paragraph("二")]]))
        #expect(blocks[3] == .list(ordered: true, items: [[.paragraph("甲")]]))
        #expect(blocks[4] == .quote([.paragraph("引用")]))
        guard case .code(let language, let code) = blocks[5] else { Issue.record("expected code"); return }
        #expect(language == "swift")
        #expect(code.trimmingCharacters(in: .newlines) == "let x = 1")
        #expect(blocks[6] == .table(header: ["列", "值"], rows: [["a", "1"]]))
        #expect(blocks[7] == .rule)
        guard case .html(let raw) = blocks[8] else { Issue.record("expected html"); return }
        #expect(raw.trimmingCharacters(in: .whitespacesAndNewlines) == "<div>html</div>")
    }
}
