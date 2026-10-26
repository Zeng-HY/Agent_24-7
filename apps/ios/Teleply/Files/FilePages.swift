import QuickLook
import SwiftUI
import TeleplyModel
import TeleplyState

/// What a file's state means, in the web's words (operationLabel).
func operationLabel(_ value: String) -> String {
    switch value {
    case "pending": return "待回答"
    case "answered": return "已回答"
    case "draft": return "草稿"
    case "submitting", "creating", "dispatching": return "正在提交，结果可核对"
    case "unconfirmed", "unknown": return "结果待确认"
    case "accepted": return "已接收"
    case "failed": return "失败"
    case "current": return "当前版本"
    case "updated": return "文件已更新"
    case "missing": return "文件缺失"
    default: return value
    }
}

/// 1.2 KB for 1,234 bytes.
func byteSize(_ bytes: Int64) -> String {
    ByteCountFormatter.string(fromByteCount: bytes, countStyle: .file)
}

/// 对话文件 (web files-ui.js; Android FilesPane): the files this conversation names, as they are now, or those one
/// message presented (查看成果文件). Which turn changed what is the timeline's 本轮差异 (spec 4.5, B12). With none,
/// a file can be picked from the computer instead (Android 1.0.2).
struct FilesSheet: View {
    let model: AppModel
    /// 从电脑选择文件: this sheet goes and the picker comes.
    var pickFromComputer: () -> Void = {}
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        let workspace = model.workspace
        let items = workspace.data["items"].array
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 12) {
                    if workspace.paneBusy { ProgressView().frame(maxWidth: .infinity) }
                    if let error = workspace.paneError {
                        Text(error)
                            .noteFont()
                            .foregroundStyle(Palette.danger)
                    }
                    Text("这里打开的是文件现在的样子；某一轮改了什么，请从时间线里那一步的「本轮差异」进入。")
                        .noteFont()
                        .foregroundStyle(Palette.muted)
                    if items.isEmpty && !workspace.paneBusy && workspace.paneError == nil {
                        Text("暂未识别到本对话的成果文件，可从电脑目录选择并保存到手机。")
                            .noteFont()
                            .foregroundStyle(Palette.muted)
                        Button("从电脑选择文件", systemImage: "desktopcomputer", action: pickFromComputer)
                            .buttonStyle(PillStyle())
                    } else if !items.isEmpty {
                        VStack(spacing: 0) {
                            ForEach(Array(items.enumerated()), id: \.offset) { index, file in
                                if index > 0 { Rectangle().fill(Palette.line).frame(height: 1).padding(.leading, 52) }
                                let missing = file["state"].string() == "missing"
                                Button {
                                    workspace.file(file)
                                } label: {
                                    HStack(spacing: 12) {
                                        Image(systemName: file["kind"].string() == "image" ? "photo" : "doc.text")
                                            .font(.system(size: 17))
                                            .foregroundStyle(Palette.muted)
                                            .frame(width: 24)
                                        VStack(alignment: .leading, spacing: 2) {
                                            Text(file["name"].string())
                                                .bodyFont()
                                                .foregroundStyle(Palette.ink)
                                                .lineLimit(2)
                                            Text(operationLabel(file["state"].string()) + " · " + byteSize(file["size"].int64()))
                                                .captionFont()
                                                .foregroundStyle(Palette.muted)
                                        }
                                        .frame(maxWidth: .infinity, alignment: .leading)
                                        Image(systemName: "chevron.right")
                                            .font(.system(size: 13, weight: .semibold))
                                            .foregroundStyle(Palette.muted)
                                    }
                                    .padding(.horizontal, 16)
                                    .padding(.vertical, 12)
                                    .frame(minHeight: 56)
                                    .contentShape(Rectangle())
                                    .opacity(missing ? 0.45 : 1)
                                }
                                .buttonStyle(RowPressStyle(radius: 0, pressed: Palette.groupPressed))
                                .disabled(missing)
                            }
                        }
                        .background(Palette.controlFill, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
                        .clipShape(RoundedRectangle(cornerRadius: 16, style: .continuous))
                    }
                }
                .padding(.horizontal, 20)
                .padding(.vertical, 12)
            }
            .navigationTitle("对话文件")
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

/// A file's page (spec 4.5; web artifact-preview.js; Android FilePage): the system back and a centred title, the
/// file as it is now. HTML opens as a page with 查看源码 beside it, Markdown as text to read; other text in a code
/// panel; pictures and PDFs in Quick Look. 保存到文件 and 分享 hand a copy to the system. A file the page cannot
/// show (a Word file, a file from the computer) has them in the page too, with Quick Look for what the system can
/// show (Android 1.0.2). A download shows how far it got and can be stopped; a saved file can be opened from where
/// it went. A computer file's page also adds it to the message.
struct FilePage: View {
    let model: AppModel
    @State private var rendered = true
    @State private var quickLook: URL?
    @State private var saving: URL?
    @State private var sharing: URL?
    @State private var note: String?
    /// Where 保存到文件 put the last copy, to open it from there.
    @State private var saved: URL?
    /// The saved copy being looked at, while the system lets this app read it.
    @State private var reading: URL?

    var body: some View {
        let workspace = model.workspace
        let data = workspace.data
        let meta = data["meta"]
        let name = data["name"].string().isEmpty ? "文件" : data["name"].string()
        let lower = name.lowercased()
        let html = lower.hasSuffix(".html") || lower.hasSuffix(".htm")
        let markdown = lower.hasSuffix(".md") || lower.hasSuffix(".markdown")
        let loaded = !workspace.paneBusy && workspace.paneError == nil
        ScrollView {
            VStack(alignment: .leading, spacing: 12) {
                Text("当前文件 · " + operationLabel(meta["state"].string()) + (meta.has("size") ? " · " + byteSize(meta["size"].int64()) : ""))
                    .captionFont()
                    .foregroundStyle(Palette.muted)
                if workspace.paneBusy { ProgressView().frame(maxWidth: .infinity) }
                if let error = workspace.paneError {
                    Text(error)
                        .noteFont()
                        .foregroundStyle(Palette.danger)
                }
                let text = workspace.fileText
                if !text.isEmpty {
                    if html || markdown {
                        Picker("显示", selection: $rendered) {
                            Text(html ? "查看页面" : "阅读视图").tag(true)
                            Text("查看源码").tag(false)
                        }
                        .pickerStyle(.segmented)
                        if !rendered {
                            CodePanel(label: name, code: text, copyLabel: "复制文件内容")
                        } else if html {
                            HtmlPreview(model: model, source: text, file: data)
                                .frame(height: 520)
                                .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
                                .overlay(RoundedRectangle(cornerRadius: 12, style: .continuous).stroke(Palette.codeEdge, lineWidth: 1))
                                .accessibilityLabel(Text("网页预览：" + name))
                            Text("按网页打开：脚本和网上的图片照常加载；它拿不到这个应用的登录信息和手机里的文件，点链接用 Safari 打开。")
                                .noteFont()
                                .foregroundStyle(Palette.muted)
                        } else {
                            MarkdownView(source: text)
                        }
                    } else {
                        CodePanel(label: name, code: text, copyLabel: "复制文件内容")
                    }
                }
                if let preview = workspace.preview {
                    if meta["kind"].string() == "image", let image = UIImage(contentsOfFile: preview.path) {
                        Button { quickLook = preview } label: {
                            Image(uiImage: image)
                                .resizable()
                                .scaledToFit()
                                .frame(maxWidth: .infinity)
                                .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
                        }
                        .buttonStyle(.plain)
                        .accessibilityLabel(Text("图片：\(name)，点按放大"))
                    }
                    Button("用快速查看打开", systemImage: "eye") { quickLook = preview }
                        .buttonStyle(PillStyle())
                }
                if meta["size"].int64() > 20 * 1024 * 1024 && ["image", "pdf"].contains(meta["kind"].string()) {
                    Text("文件超过20MB预览上限，可保存后用系统应用打开。")
                        .noteFont()
                        .foregroundStyle(Palette.muted)
                }
                if !workspace.fileNote.isEmpty {
                    Text(workspace.fileNote)
                        .noteFont()
                        .foregroundStyle(Palette.muted)
                }
                if loaded && text.isEmpty && workspace.preview == nil {
                    unshown(lower)
                }
                if data["reference"].isObject {
                    Button("添加到消息", systemImage: "plus.circle") { workspace.addComputerFile() }
                        .buttonStyle(PillStyle(wide: true))
                        .disabled(workspace.transferring)
                }
                transferLine(name)
            }
            .padding(.horizontal, 16)
            .padding(.vertical, 12)
        }
        .background(Palette.page)
        .navigationTitle(name)
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItemGroup(placement: .topBarTrailing) {
                Button("保存到文件", systemImage: "square.and.arrow.down") { copy { saving = $0 } }
                    .disabled(workspace.transferring || workspace.paneBusy)
                Button("分享", systemImage: "square.and.arrow.up") { copy { sharing = $0 } }
                    .disabled(workspace.transferring || workspace.paneBusy)
            }
        }
        .quickLookPreview($quickLook)
        .onChange(of: quickLook) {
            if quickLook == nil, let reading {
                reading.stopAccessingSecurityScopedResource()
                self.reading = nil
            }
        }
        .fileMover(isPresented: Binding(get: { saving != nil }, set: { if !$0 { saving = nil } }), file: saving) { result in
            switch result {
            case .success(let url):
                saved = url
                note = "已保存到所选位置：" + name
            case .failure:
                note = "没保存"
            }
            saving = nil
        }
        .sheet(isPresented: Binding(get: { sharing != nil }, set: { if !$0 { sharing = nil } })) {
            if let sharing {
                ShareSheet(items: [sharing]) { done in note = done ? "已分享" : nil }
                    .presentationDetents([.medium, .large])
            }
        }
    }

    /// A file the page cannot show: what can be done with it, in the page and not only in the bar above.
    @ViewBuilder
    private func unshown(_ lower: String) -> some View {
        let workspace = model.workspace
        let looks = Self.quickLooks(lower)
        Button("保存到文件", systemImage: "square.and.arrow.down") { copy { saving = $0 } }
            .buttonStyle(PillStyle(kind: .primary, wide: true))
            .disabled(workspace.transferring)
        if looks {
            Button("用快速查看打开", systemImage: "eye") { copy { quickLook = $0 } }
                .buttonStyle(PillStyle(wide: true))
                .disabled(workspace.transferring)
        }
        Text(looks ? "这类文件不在页面里显示；可以用快速查看打开，或保存到文件、分享给其他应用。" : "这类文件不在页面里显示；可以保存到文件，或分享给其他应用打开。")
            .noteFont()
            .foregroundStyle(Palette.muted)
    }

    /// How far a download got, with 取消; then how the save or share went.
    @ViewBuilder
    private func transferLine(_ name: String) -> some View {
        let workspace = model.workspace
        if workspace.transferring {
            HStack(spacing: 12) {
                ProgressView()
                Text(workspace.transfer.isEmpty ? "正在准备…" : workspace.transfer)
                    .noteFont()
                    .monospacedDigit()
                    .foregroundStyle(Palette.muted)
                Spacer(minLength: 0)
                Button("取消") { workspace.cancelCopy() }
                    .buttonStyle(PillStyle(kind: .text))
            }
        } else if let note {
            Text(note)
                .noteFont()
                .foregroundStyle(Palette.muted)
                .task(id: note) { AccessibilityNotification.Announcement(note).post() }
            if saved != nil && note.hasPrefix("已保存到所选位置") {
                Button("打开已保存的文件", systemImage: "eye") { openSaved() }
                    .buttonStyle(PillStyle(kind: .text))
            }
        }
    }

    /// What Quick Look shows on a phone: Office and iWork documents, PDFs, pictures, text, sound and video.
    static func quickLooks(_ name: String) -> Bool {
        guard let dot = name.lastIndex(of: ".") else { return false }
        return ["doc", "docx", "xls", "xlsx", "ppt", "pptx", "pages", "numbers", "key", "rtf", "csv", "txt", "md", "pdf",
                "png", "jpg", "jpeg", "heic", "gif", "webp", "tif", "tiff", "mp3", "m4a", "wav", "mp4", "mov", "m4v", "usdz"]
            .contains(String(name[name.index(after: dot)...]))
    }

    /// A copy of the file to hand to the system; one at a time, its download shown on the page.
    private func copy(_ then: @escaping (URL) -> Void) {
        guard !model.workspace.transferring else { return }
        note = nil
        Task {
            do {
                then(try await model.workspace.fileCopy())
            } catch is CancellationError {
                note = "已取消下载"
            } catch {
                note = describe(error)
            }
        }
    }

    /// The copy where 保存到文件 put it, in Quick Look, while the system lets this app read it there.
    private func openSaved() {
        guard let saved else { return }
        if saved.startAccessingSecurityScopedResource() { reading = saved }
        quickLook = saved
    }
}

/// The system share sheet; [done] says whether the user finished it (not just closed it).
struct ShareSheet: UIViewControllerRepresentable {
    let items: [Any]
    let done: (Bool) -> Void

    func makeUIViewController(context: Context) -> UIActivityViewController {
        let controller = UIActivityViewController(activityItems: items, applicationActivities: nil)
        controller.completionWithItemsHandler = { _, completed, _, _ in done(completed) }
        return controller
    }

    func updateUIViewController(_ controller: UIActivityViewController, context: Context) {}
}

/// 本轮差异 (spec 4.5, B12; Android DiffPage): what the source's record says the turn changed, unified, with line
/// numbers and + / − so it does not rest on red and green. Long lines scroll sideways inside their block; ⋯ wraps
/// them instead.
struct DiffPage: View {
    let model: AppModel
    @State private var wrap = false

    var body: some View {
        let workspace = model.workspace
        let data = workspace.data
        ScrollView {
            VStack(alignment: .leading, spacing: 12) {
                if !data["path"].string().isEmpty {
                    Text(data["path"].string())
                        .captionFont()
                        .foregroundStyle(Palette.muted)
                        .textSelection(.enabled)
                }
                if workspace.paneBusy { ProgressView().frame(maxWidth: .infinity) }
                if let error = workspace.paneError {
                    Text(error)
                        .noteFont()
                        .foregroundStyle(Palette.danger)
                }
                Text("来源记录提供的本轮差异；不根据当前文件猜测旧版本。")
                    .noteFont()
                    .foregroundStyle(Palette.muted)
                ForEach(Array(data["hunks"].array.enumerated()), id: \.offset) { _, hunk in
                    DiffHunk(text: hunk.string(), wrap: wrap)
                }
                if data.has("next") {
                    Button("下一页差异") { workspace.diff(data["ref"].string(), offset: Int(data["next"].int64())) }
                        .buttonStyle(PillStyle())
                        .disabled(workspace.paneBusy)
                }
            }
            .padding(.horizontal, 16)
            .padding(.vertical, 12)
        }
        .background(Palette.page)
        .navigationTitle("本轮差异")
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .topBarTrailing) {
                Menu {
                    Toggle("自动换行", isOn: $wrap)
                } label: {
                    Image(systemName: "ellipsis")
                }
                .accessibilityLabel(Text("差异显示"))
            }
        }
    }
}

/// One hunk: the old and new line numbers, the sign, the line. Each line's colour runs the block's whole width.
private struct DiffHunk: View {
    let text: String
    let wrap: Bool
    @State private var width: CGFloat = 0

    struct Line: Identifiable {
        let id: Int
        let old: String
        let new: String
        let sign: String
        let text: String
    }

    var body: some View {
        let lines = Self.lines(text)
        let rows = VStack(alignment: .leading, spacing: 0) {
            ForEach(lines) { line in
                HStack(alignment: .top, spacing: 0) {
                    Text(line.old).frame(width: 34, alignment: .trailing)
                    Text(line.new).frame(width: 34, alignment: .trailing)
                    Text(line.sign == "@" ? "" : line.sign).frame(width: 18)
                    Text(line.text.isEmpty ? " " : line.text)
                        .fixedSize(horizontal: !wrap, vertical: true)
                        .padding(.trailing, 12)
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .codeFont()
                .foregroundStyle(line.sign == "@" ? Palette.muted : line.sign == "+" ? Palette.success : line.sign == "−" ? Palette.danger : Palette.ink)
                .padding(.vertical, 1)
                .background(line.sign == "+" ? Palette.success.opacity(0.12) : line.sign == "−" ? Palette.danger.opacity(0.10) : .clear)
                .accessibilityElement(children: .ignore)
                .accessibilityLabel(Text(Self.spoken(line)))
            }
        }
        .padding(.vertical, 8)
        .frame(minWidth: width, alignment: .leading)
        Group {
            if wrap {
                rows
            } else {
                ScrollView(.horizontal, showsIndicators: false) { rows }
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .onGeometryChange(for: CGFloat.self) { $0.size.width } action: { width = $0 }
        .background(Palette.codeFill, in: RoundedRectangle(cornerRadius: 12, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: 12, style: .continuous).stroke(Palette.codeEdge, lineWidth: 1))
        .textSelection(.enabled)
    }

    static func spoken(_ line: Line) -> String {
        switch line.sign {
        case "+": return "新增第\(line.new)行：" + line.text
        case "−": return "删除原第\(line.old)行：" + line.text
        case "@": return line.text
        default: return "第\(line.new)行：" + line.text
        }
    }

    /// Lines with their numbers, counted from each @@ -a,b +c,d @@ header.
    static func lines(_ hunk: String) -> [Line] {
        var old = 0
        var new = 0
        var result: [Line] = []
        for (index, raw) in hunk.split(separator: "\n", omittingEmptySubsequences: false).enumerated() {
            let line = String(raw)
            if line.hasPrefix("@@") {
                let numbers = line.split(separator: " ").dropFirst().prefix(2).map { part in
                    Int(part.dropFirst().split(separator: ",").first ?? "") ?? 0
                }
                old = numbers.first ?? 0
                new = numbers.count > 1 ? numbers[1] : 0
                result.append(Line(id: index, old: "", new: "", sign: "@", text: line))
            } else if line.hasPrefix("+") {
                result.append(Line(id: index, old: "", new: String(new), sign: "+", text: String(line.dropFirst())))
                new += 1
            } else if line.hasPrefix("-") {
                result.append(Line(id: index, old: String(old), new: "", sign: "−", text: String(line.dropFirst())))
                old += 1
            } else {
                result.append(Line(id: index, old: String(old), new: String(new), sign: "", text: line.hasPrefix(" ") ? String(line.dropFirst()) : line))
                old += 1
                new += 1
            }
        }
        return result
    }
}
