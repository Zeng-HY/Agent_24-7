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

    /// A file on the computer that an answer links to opens its page (web markdown-ui.js local links), line numbers
    /// and %-escapes aside; a picture on the computer too.
    @Test func filesOnTheComputerOpenTheirPage() {
        let blocks = MarkdownReader.blocks(#"[确认单](D:\Personal\语言桥\确认单.docx) [第 3 行](D:/a/%E8%AF%B4%E6%98%8E.md:3) ![图](C:\pics\a.png)"#)
        guard case .paragraph(let runs) = blocks.first else { Issue.record("expected a paragraph"); return }
        let links = runs.compactMap(\.link).compactMap(URL.init(string:)).compactMap(MarkdownReader.fileLinkPath)
        #expect(links == [#"D:\Personal\语言桥\确认单.docx"#, "D:/a/说明.md", #"C:\pics\a.png"#])
        #expect(runs.first { $0.text == "确认单" }?.link?.hasPrefix("teleply-file:") == true)
        #expect(!runs.plain.contains("链接未开放"))
        #expect(MarkdownReader.fileLinkPath(URL(string: "https://example.com")!) == nil)
    }

    /// Codex's own notes (user 10-27): memory citations go; a file citation becomes a link to its file.
    @Test func codexCitationsBecomeNothingOrAFileLink() {
        let answer = """
        已合并为一份。

        :codex-file-citation{path="D:\\Personal\\语言桥\\合并稿.docx" purpose="output"}

        <oai-mem-citation>
        <citation_entries>
        MEMORY.md:694-696|note=[used Windows Word rendering fallback workflow]
        </citation_entries>
        <rollout_ids>
        01a0bef3-b1d0-79d3-b7e4-4251056b2729
        </rollout_ids>
        </oai-mem-citation>
        """
        let tidy = MarkdownReader.tidy(answer)
        #expect(!tidy.contains("oai-mem-citation") && !tidy.contains("MEMORY.md") && !tidy.contains("codex-file-citation"))
        #expect(tidy.contains(#"[合并稿.docx](<D:\Personal\语言桥\合并稿.docx>)"#))
        let blocks = MarkdownReader.blocks(answer)
        #expect(blocks.count == 2)
        guard case .paragraph(let runs) = blocks.last else { Issue.record("expected the file's paragraph"); return }
        #expect(runs.first.flatMap { $0.link }.flatMap(URL.init(string:)).flatMap(MarkdownReader.fileLinkPath) == #"D:\Personal\语言桥\合并稿.docx"#)
        #expect(MarkdownReader.tidy("没有注记") == "没有注记")
    }

    /// Codex names a conversation it made on a line of its own (user 10-27: it showed raw on the phone); the web
    /// draws 打开新建对话 under the text instead. Inside code the line stays; a clientThreadId one is not made yet.
    @Test func aConversationCodexMadeIsAButtonNotALine() {
        let answer = "已新建对话。\n\n::created-thread{threadId=\"0000-made-1\"}"
        #expect(MarkdownReader.tidy(answer) == "已新建对话。\n")
        #expect(MarkdownReader.createdThreads(answer) == [CreatedThread(id: "0000-made-1", ready: true)])
        #expect(MarkdownReader.createdThreads("  ::created-thread{clientThreadId=\"c-1\"}\r") == [CreatedThread(id: "c-1", ready: false)])
        let code = "```text\n::created-thread{threadId=\"x\"}\n```"
        #expect(MarkdownReader.tidy(code) == code && MarkdownReader.createdThreads(code).isEmpty)
        #expect(MarkdownReader.createdThreads("见 ::created-thread{threadId=\"x\"}").isEmpty)
        #expect(MarkdownReader.createdThreads("::created-thread{threadId=\"a b\"}").isEmpty)
        #expect(MarkdownReader.tidy("<proposed_plan>\n# 计划\n</proposed_plan>") == "# 计划")
        #expect(MarkdownReader.blocks(answer) == [.paragraph([InlineRun("已新建对话。")])])
    }
}
