import SwiftUI
import TeleplyModel

/// A CSV/TSV file's page (§5.4, §6.2): the computer's already-decoded text read as RFC 4180, the first row a header
/// that stays at the top, the table scrolls sideways, and only the first 5000 rows are drawn. A cut text says what part
/// of it is here.
struct TableViewer: View {
    let text: String
    let truncated: Bool
    let totalSize: Int64

    private var table: TableData { parseTable(text) }

    var body: some View {
        let data = table
        VStack(alignment: .leading, spacing: 0) {
            if let notice = truncationNotice(shownBytes: Int64(text.utf8.count), totalBytes: totalSize) {
                Text(notice)
                    .noteFont()
                    .foregroundStyle(Palette.muted)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(.horizontal, 16)
                    .padding(.vertical, 8)
            }
            if data.truncated {
                Text("只显示了前 \(tableRowLimit) 行，共 \(data.totalRows) 行")
                    .noteFont()
                    .foregroundStyle(Palette.muted)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(.horizontal, 16)
                    .padding(.vertical, 4)
            }
            if data.header.isEmpty {
                Text(text.isEmpty ? "文件是空的" : "这张表格读不出来")
                    .noteFont()
                    .foregroundStyle(Palette.muted)
                    .frame(maxWidth: .infinity)
                    .padding(.top, 60)
            } else {
                ScrollView(.horizontal) {
                    VStack(alignment: .leading, spacing: 0) {
                        row(data.header, header: true)
                        Rectangle().fill(Palette.line).frame(height: 1)
                        ScrollView(.vertical) {
                            LazyVStack(alignment: .leading, spacing: 0) {
                                ForEach(Array(data.rows.enumerated()), id: \.offset) { index, values in
                                    row(values, header: false)
                                    if index < data.rows.count - 1 {
                                        Rectangle().fill(Palette.line).frame(height: 0.5)
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
        .background(Palette.page)
    }

    private func row(_ values: [String], header: Bool) -> some View {
        HStack(alignment: .top, spacing: 0) {
            ForEach(Array(values.enumerated()), id: \.offset) { _, value in
                Text(value.isEmpty ? " " : value)
                    .font(.system(size: header ? 13 : 13, weight: header ? .semibold : .regular, design: .monospaced))
                    .foregroundStyle(header ? Palette.ink : Palette.ink.opacity(0.9))
                    .lineLimit(header ? 2 : nil)
                    .frame(width: 180, alignment: .leading)
                    .padding(.horizontal, 10)
                    .padding(.vertical, 7)
            }
        }
        .background(header ? Palette.panel : Color.clear)
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}
