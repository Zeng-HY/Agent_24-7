import SwiftUI
import TeleplyModel
import TeleplyState

/// 查找消息 (web reading-ui.js; Android SearchSheet): a keyword, 查找, and the matches; a match opens the
/// conversation around it. A full, opaque sheet: it is read closely (spec 2.5).
struct SearchSheet: View {
    let model: AppModel
    @State private var query: String
    @FocusState private var focused: Bool
    @Environment(\.dismiss) private var dismiss

    init(model: AppModel) {
        self.model = model
        _query = State(initialValue: model.searchQuery)
    }

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 12) {
                    TextField("", text: $query, prompt: Text("消息关键词").foregroundStyle(Palette.muted))
                        .bodyFont()
                        .foregroundStyle(Palette.ink)
                        .focused($focused)
                        .submitLabel(.search)
                        .onSubmit(search)
                        .padding(.horizontal, 14)
                        .frame(minHeight: 48)
                        .background(Palette.sheet, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
                        .overlay(RoundedRectangle(cornerRadius: 16, style: .continuous).stroke(focused ? Palette.accent : Palette.line, lineWidth: 1))
                        .accessibilityLabel(Text("消息关键词"))
                    Button("查找", action: search)
                        .buttonStyle(PillStyle(kind: .primary))
                        .frame(maxWidth: .infinity)
                        .disabled(model.busy || query.trimmingCharacters(in: .whitespaces).isEmpty)
                    if model.searched {
                        if model.hits.isEmpty {
                            Text("没有找到匹配的消息")
                                .noteFont()
                                .foregroundStyle(Palette.muted)
                        } else {
                            VStack(spacing: 0) {
                                ForEach(Array(model.hits.enumerated()), id: \.element.id) { index, hit in
                                    if index > 0 { Rectangle().fill(Palette.line).frame(height: 1).padding(.leading, 16) }
                                    Button {
                                        dismiss()
                                        model.jump(to: hit)
                                    } label: {
                                        VStack(alignment: .leading, spacing: 2) {
                                            Text(hit.text)
                                                .bodyFont()
                                                .foregroundStyle(Palette.ink)
                                                .lineLimit(3)
                                                .multilineTextAlignment(.leading)
                                            Text(hit.role == "user" ? "你" : Labels.sourceName(model.app))
                                                .captionFont()
                                                .foregroundStyle(Palette.muted)
                                        }
                                        .frame(maxWidth: .infinity, alignment: .leading)
                                        .padding(.horizontal, 16)
                                        .padding(.vertical, 12)
                                    }
                                    .buttonStyle(RowPressStyle(radius: 0, pressed: Palette.groupPressed))
                                }
                            }
                            .background(Palette.controlFill, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
                            .clipShape(RoundedRectangle(cornerRadius: 16, style: .continuous))
                        }
                        if model.hitMore {
                            Button("更多结果") { model.searchHistory(model.searchQuery, more: true) }
                                .buttonStyle(PillStyle(kind: .text))
                                .disabled(model.busy)
                        }
                    }
                }
                .padding(.horizontal, 20)
                .padding(.vertical, 12)
            }
            .scrollDismissesKeyboard(.interactively)
            .navigationTitle("查找消息")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button(role: .close) { dismiss() }
                }
            }
        }
        .presentationBackground(Palette.sheet)
        .onAppear { focused = query.isEmpty }
    }

    private func search() {
        let words = query.trimmingCharacters(in: .whitespaces)
        guard !words.isEmpty, !model.busy else { return }
        model.searchHistory(words)
    }
}

/// 选择文字 (web #readerSheet; spec 4.3): the original text at 17 pt, line height 1.75, in the system's own text
/// view, so the selection handles, 查询, 翻译 and 共享 all work; 复制全部 below.
struct SelectTextSheet: View {
    let text: String
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            VStack(spacing: 12) {
                SelectableText(text: text)
                Button("复制全部") {
                    UIPasteboard.general.string = text
                    dismiss()
                }
                .buttonStyle(PillStyle(kind: .primary))
                .frame(maxWidth: .infinity)
            }
            .padding(.horizontal, 20)
            .padding(.bottom, 12)
            .navigationTitle("选择文字")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button(role: .close) { dismiss() }
                }
            }
        }
        .presentationBackground(Palette.sheet)
    }
}

/// 待核对发送记录 (web workspace-ui.js; Android PendingSheet): sends whose result is not confirmed yet. 核对状态
/// reads the receipt again; 恢复提交快照 puts a send back in an empty box. Nothing is sent again.
struct PendingSheet: View {
    let model: AppModel
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        let chat = model.conversation
        let rows = chat.submissions.filter { ["提交中", "送达状态待确认", "已接收", "已排队"].contains($0.label) }
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 12) {
                    Text("这些消息的结果还没确认。核对只读取回执，不会重新发送。")
                        .noteFont()
                        .foregroundStyle(Palette.muted)
                    if rows.isEmpty {
                        Text("没有待核对的记录")
                            .noteFont()
                            .foregroundStyle(Palette.muted)
                    }
                    ForEach(rows) { record in
                        VStack(alignment: .leading, spacing: 10) {
                            Text(record.label)
                                .buttonFont()
                                .foregroundStyle(record.label == "送达状态待确认" ? Palette.warning : Palette.ink)
                            Text(record.text)
                                .scaledFont(15, relativeTo: .callout, lineHeight: 1.6)
                                .foregroundStyle(Palette.ink)
                                .lineLimit(4)
                            HStack(spacing: 8) {
                                Button("核对状态") { chat.check(record) }
                                    .buttonStyle(PillStyle())
                                    .disabled(chat.submitting)
                                if record.action == "send" {
                                    Button("恢复提交快照") { chat.restore(record) }
                                        .buttonStyle(PillStyle(kind: .text))
                                        .disabled(!chat.draft.isEmpty || chat.submitting)
                                }
                            }
                        }
                        .padding(16)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .background(Palette.sheet, in: RoundedRectangle(cornerRadius: 20, style: .continuous))
                        .overlay(RoundedRectangle(cornerRadius: 20, style: .continuous).stroke(Palette.line, lineWidth: 1))
                    }
                }
                .padding(.horizontal, 20)
                .padding(.vertical, 12)
            }
            .navigationTitle("待核对发送记录")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    Text("\(rows.count) 条")
                        .captionFont()
                        .foregroundStyle(Palette.muted)
                }
                .sharedBackgroundVisibility(.hidden)
                ToolbarItem(placement: .topBarTrailing) {
                    Button(role: .close) { dismiss() }
                }
            }
        }
        .presentationBackground(Palette.sheet)
    }
}

/// One saved prompt (web prompt library).
private struct Prompt: Codable, Equatable {
    var name: String
    var text: String
}

/// 常用提示语 (web prompt library; Android PromptLibrarySheet): insert into the draft; add, edit and delete. Kept on
/// this phone only.
struct PromptLibrarySheet: View {
    let model: AppModel
    @State private var items: [Prompt] = PromptLibrarySheet.load()
    @State private var editing: Int?
    @State private var name = ""
    @State private var text = ""
    @State private var removing: Int?
    @Environment(\.dismiss) private var dismiss

    private static let key = "teleply.prompts"

    private static func load() -> [Prompt] {
        guard let data = UserDefaults.standard.data(forKey: key) else { return [] }
        return (try? JSONDecoder().decode([Prompt].self, from: data)) ?? []
    }

    private func save() {
        UserDefaults.standard.set(try? JSONEncoder().encode(items), forKey: Self.key)
    }

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 12) {
                    if let editing {
                        editor(editing)
                    } else {
                        if items.isEmpty {
                            Text("还没有提示语。点下面的按钮加一条，以后可以一点插入草稿。")
                                .noteFont()
                                .foregroundStyle(Palette.muted)
                        }
                        ForEach(Array(items.enumerated()), id: \.offset) { index, item in
                            VStack(alignment: .leading, spacing: 8) {
                                Text(item.name)
                                    .scaledFont(14, .semibold, relativeTo: .subheadline)
                                    .foregroundStyle(Palette.ink)
                                Text(item.text)
                                    .smallBodyFont()
                                    .foregroundStyle(Palette.muted)
                                    .lineLimit(3)
                                HStack(spacing: 8) {
                                    Button("插入") {
                                        let current = model.conversation.draft
                                        let trimmed = current.replacingOccurrences(of: "\\s+$", with: "", options: .regularExpression)
                                        model.conversation.replaceDraft(current.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ? item.text : trimmed + "\n" + item.text)
                                        dismiss()
                                    }
                                    .buttonStyle(PillStyle(kind: .primary))
                                    Button("编辑") {
                                        name = item.name
                                        text = item.text
                                        self.editing = index
                                    }
                                    .buttonStyle(PillStyle())
                                    Button("删除") { removing = index }
                                        .buttonStyle(PillStyle(kind: .text))
                                }
                            }
                            .padding(16)
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .background(Palette.sheet, in: RoundedRectangle(cornerRadius: 20, style: .continuous))
                            .overlay(RoundedRectangle(cornerRadius: 20, style: .continuous).stroke(Palette.line, lineWidth: 1))
                        }
                        Button {
                            name = ""
                            text = ""
                            editing = -1
                        } label: {
                            Label("添加提示语", systemImage: "plus")
                                .frame(maxWidth: .infinity)
                        }
                        .buttonStyle(PillStyle())
                    }
                }
                .padding(.horizontal, 20)
                .padding(.vertical, 12)
            }
            .navigationTitle("常用提示语")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button(role: .close) { dismiss() }
                }
            }
        }
        .presentationBackground(Palette.sheet)
        .alert("删除这条提示语？", isPresented: Binding(get: { removing != nil }, set: { if !$0 { removing = nil } }), presenting: removing) { index in
            Button("取消", role: .cancel) {}
            Button("删除", role: .destructive) {
                if items.indices.contains(index) { items.remove(at: index) }
                save()
            }
        } message: { index in
            Text("「\(items.indices.contains(index) ? items[index].name : "")」会从这台手机上删除。")
        }
    }

    @ViewBuilder
    private func editor(_ index: Int) -> some View {
        TextField("", text: $name, prompt: Text("名称").foregroundStyle(Palette.muted))
            .bodyFont()
            .padding(.horizontal, 14)
            .frame(minHeight: 48)
            .background(Palette.sheet, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
            .overlay(RoundedRectangle(cornerRadius: 16, style: .continuous).stroke(Palette.line, lineWidth: 1))
            .accessibilityLabel(Text("名称"))
        TextField("", text: $text, prompt: Text("内容").foregroundStyle(Palette.muted), axis: .vertical)
            .bodyFont()
            .lineLimit(3...8)
            .padding(14)
            .background(Palette.sheet, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
            .overlay(RoundedRectangle(cornerRadius: 16, style: .continuous).stroke(Palette.line, lineWidth: 1))
            .accessibilityLabel(Text("内容"))
        HStack(spacing: 8) {
            Button("保存") {
                let item = Prompt(name: name.trimmingCharacters(in: .whitespaces), text: text)
                if index >= 0, items.indices.contains(index) { items[index] = item } else { items.append(item) }
                save()
                editing = nil
            }
            .buttonStyle(PillStyle(kind: .primary))
            .disabled(name.trimmingCharacters(in: .whitespaces).isEmpty || text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
            Button("取消") { editing = nil }
                .buttonStyle(PillStyle())
        }
    }
}

private struct SelectableText: UIViewRepresentable {
    let text: String

    func makeUIView(context: Context) -> UITextView {
        let view = UITextView()
        view.isEditable = false
        view.isSelectable = true
        view.backgroundColor = .clear
        view.textContainerInset = UIEdgeInsets(top: 8, left: 0, bottom: 8, right: 0)
        view.textContainer.lineFragmentPadding = 0
        view.adjustsFontForContentSizeCategory = true
        view.alwaysBounceVertical = true
        return view
    }

    func updateUIView(_ view: UITextView, context: Context) {
        let font = UIFontMetrics(forTextStyle: .body).scaledFont(for: .systemFont(ofSize: 17))
        let paragraph = NSMutableParagraphStyle()
        paragraph.lineSpacing = max(0, font.pointSize * 1.75 - font.lineHeight)
        view.attributedText = NSAttributedString(string: text, attributes: [
            .font: font,
            .foregroundColor: UIColor(named: "Ink") ?? .label,
            .paragraphStyle: paragraph,
        ])
    }
}
