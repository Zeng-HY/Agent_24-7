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
