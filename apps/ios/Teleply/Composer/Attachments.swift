import AVFoundation
import ImageIO
import PhotosUI
import QuickLook
import SwiftUI
import TeleplyModel
import TeleplyState
import UniformTypeIdentifiers

/// A copy of a picked photo or file in a folder of our own, which the workspace uploads and then deletes.
nonisolated func stageUpload(_ source: URL, name: String? = nil) throws -> URL {
    let folder = FileManager.default.temporaryDirectory.appendingPathComponent("teleply-upload-" + UUID().uuidString)
    try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
    let target = folder.appendingPathComponent(name ?? source.lastPathComponent)
    try FileManager.default.copyItem(at: source, to: target)
    return target
}

/// A photo from the system picker, received as its file (HEIC stays HEIC; the computer takes it).
nonisolated struct StagedPhoto: Transferable, Sendable {
    let url: URL

    static var transferRepresentation: some TransferRepresentation {
        FileRepresentation(importedContentType: .image) { received in
            StagedPhoto(url: try stageUpload(received.file))
        }
    }
}

/// ＋ of both composers (spec 4.3, 4.4; Android AttachMenu): the camera, the phone's photos and files, the
/// computer's files, a conversation or a skill to refer to (no skills for DeepSeek). A picker's result goes to the
/// draft it was opened for; if the conversation changed meanwhile, it is dropped.
struct AttachButton: View {
    let model: AppModel
    let app: String
    let enabled: Bool
    @State private var photos: [PhotosPickerItem] = []
    @State private var photosShown = false
    @State private var filesShown = false
    @State private var cameraShown = false
    @State private var openedFor: ChatKey?

    var body: some View {
        let workspace = model.workspace
        Menu {
            Button("拍照", systemImage: "camera") { openCamera() }
            Button("手机照片", systemImage: "photo.on.rectangle") {
                openedFor = workspace.key
                photosShown = true
            }
            Button("手机文件", systemImage: "doc") {
                openedFor = workspace.key
                filesShown = true
            }
            Button("从电脑选择文件", systemImage: "desktopcomputer") { workspace.openPicker("remote") }
            Button("引用对话", systemImage: "bubble.left.and.bubble.right") { workspace.openPicker("chat") }
            if app != "deepseek" {
                Button("引用技能", systemImage: "wand.and.stars") { workspace.openPicker("skill") }
            }
        } label: {
            Image(systemName: "plus")
                .font(.system(size: 18, weight: .medium))
                .foregroundStyle(Palette.muted)
                .frame(width: 40, height: 40)
                .contentShape(Circle())
        }
        .menuOrder(.fixed)
        .disabled(!enabled)
        .accessibilityLabel(Text("添加附件或引用"))
        .photosPicker(isPresented: $photosShown, selection: $photos, maxSelectionCount: 5, matching: .images)
        .onChange(of: photos) {
            let picked = photos
            photos = []
            guard !picked.isEmpty else { return }
            Task { await importPhotos(picked) }
        }
        .fileImporter(isPresented: $filesShown, allowedContentTypes: [.item], allowsMultipleSelection: true) { result in
            guard case .success(let urls) = result else { return }
            Task { await importFiles(urls) }
        }
        .fullScreenCover(isPresented: $cameraShown) {
            CameraPicker { image in
                guard let image else { return }
                Task { await importShot(image) }
            }
            .ignoresSafeArea()
        }
    }

    private func openCamera() {
        guard UIImagePickerController.isSourceTypeAvailable(.camera) else {
            model.workspace.error = "这台手机没有可用的相机"
            return
        }
        if AVCaptureDevice.authorizationStatus(for: .video) == .denied || AVCaptureDevice.authorizationStatus(for: .video) == .restricted {
            model.workspace.error = "没有相机权限：到 设置 → 遥应 里打开相机；也可以从手机照片里选"
            return
        }
        openedFor = model.workspace.key
        cameraShown = true
    }

    private func importPhotos(_ picked: [PhotosPickerItem]) async {
        for item in picked {
            do {
                guard let photo = try await item.loadTransferable(type: StagedPhoto.self) else { continue }
                await hand(photo.url, image: true)
            } catch {
                model.workspace.error = "这张照片没读出来，请换一张或从手机文件里选"
            }
        }
    }

    private func importFiles(_ urls: [URL]) async {
        for url in urls {
            let copy = await Task.detached { () -> URL? in
                let access = url.startAccessingSecurityScopedResource()
                defer { if access { url.stopAccessingSecurityScopedResource() } }
                return try? stageUpload(url)
            }.value
            guard let copy else {
                model.workspace.error = "无法读取所选文件，请重新选择"
                continue
            }
            let image = UTType(filenameExtension: copy.pathExtension)?.conforms(to: .image) == true
                && ["jpg", "jpeg", "png", "heic", "heif", "gif", "webp"].contains(copy.pathExtension.lowercased())
            await hand(copy, image: image)
        }
    }

    private func importShot(_ image: UIImage) async {
        guard let data = image.jpegData(compressionQuality: 0.9) else { return }
        let stamp = Int(Date().timeIntervalSince1970)
        let folder = FileManager.default.temporaryDirectory.appendingPathComponent("teleply-upload-" + UUID().uuidString)
        do {
            try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
            let file = folder.appendingPathComponent("拍照-\(stamp).jpg")
            try data.write(to: file)
            await hand(file, image: true)
        } catch {
            model.workspace.error = "照片没存下来，请再拍一次"
        }
    }

    /// The staged copy goes to the draft the picker was opened for, or away. A picture first gets its preview for the
    /// tile (made away from the screen: a large photo takes a moment).
    private func hand(_ file: URL, image: Bool) async {
        guard model.workspace.key == openedFor else {
            try? FileManager.default.removeItem(at: file.deletingLastPathComponent())
            return
        }
        var preview: String?
        if image { preview = await Task.detached { photoPreview(of: file) }.value }
        guard model.workspace.key == openedFor else {
            try? FileManager.default.removeItem(at: file.deletingLastPathComponent())
            if let preview { try? FileManager.default.removeItem(at: WorkspaceModel.photoFolder.appendingPathComponent(preview)) }
            return
        }
        model.workspace.importFile(file, name: file.lastPathComponent, image: image, preview: preview)
    }
}

/// The system camera (photo only); the shot comes back as an image, a cancel as nil.
struct CameraPicker: UIViewControllerRepresentable {
    let done: (UIImage?) -> Void
    @Environment(\.dismiss) private var dismiss

    func makeUIViewController(context: Context) -> UIImagePickerController {
        let picker = UIImagePickerController()
        picker.sourceType = .camera
        picker.cameraCaptureMode = .photo
        picker.delegate = context.coordinator
        return picker
    }

    func updateUIViewController(_ controller: UIImagePickerController, context: Context) {}

    func makeCoordinator() -> Coordinator {
        Coordinator { image in
            done(image)
            dismiss()
        }
    }

    final class Coordinator: NSObject, UIImagePickerControllerDelegate, UINavigationControllerDelegate {
        let finish: (UIImage?) -> Void

        init(finish: @escaping (UIImage?) -> Void) {
            self.finish = finish
        }

        func imagePickerController(_ picker: UIImagePickerController, didFinishPickingMediaWithInfo info: [UIImagePickerController.InfoKey: Any]) {
            finish(info[.originalImage] as? UIImage)
        }

        func imagePickerControllerDidCancel(_ picker: UIImagePickerController) {
            finish(nil)
        }
    }
}

/// The attachments and references inside a card (spec 8.1, 8.2): each removable; one going up says so, one that
/// failed says why. A picture shows itself and opens large when tapped (user 10-27).
struct AttachmentTiles: View {
    let workspace: WorkspaceModel
    let saved: JSONValue
    @State private var looking: URL?

    var body: some View {
        let uploads = saved["uploads"].array
        let references = saved["references"].array
        if !uploads.isEmpty || !references.isEmpty {
            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: 6) {
                    ForEach(Array(uploads.enumerated()), id: \.offset) { _, row in
                        let status = row["status"].string()
                        let failed = status != "ready" && status != "uploading" && status != "checking"
                        let preview = row["preview"].string().isEmpty ? nil : WorkspaceModel.photoFolder.appendingPathComponent(row["preview"].string())
                        Tile(symbol: row["image"].bool() ? "photo" : "doc", name: row["name"].string(),
                             status: status == "ready" ? nil : failed ? (row["error"].string().isEmpty ? "上传失败" : row["error"].string()) : "上传中",
                             failed: failed, removeLabel: "移除附件 " + row["name"].string(), preview: preview, look: { looking = $0 }) {
                            workspace.removeUpload(row["local"].string())
                        }
                    }
                    ForEach(Array(references.enumerated()), id: \.offset) { _, reference in
                        let kind = reference["kind"].string()
                        let name = reference["name"].string().isEmpty ? reference["title"].string() : reference["name"].string()
                        Tile(symbol: kind == "skill" ? "wand.and.stars" : kind == "chat" ? "bubble.left" : kind == "folder" ? "folder" : "doc",
                             name: name, status: nil, failed: false, removeLabel: "移除引用 " + name) {
                            workspace.removeReference(reference["id"].string())
                        }
                    }
                }
                .padding(.horizontal, 6)
                .padding(.top, 4)
            }
            .quickLookPreview($looking)
        }
    }
}

private struct Tile: View {
    let symbol: String
    let name: String
    let status: String?
    let failed: Bool
    let removeLabel: String
    /// A picture's preview: shown in place of its icon and name, opened large when tapped.
    var preview: URL?
    var look: (URL) -> Void = { _ in }
    let remove: () -> Void
    @State private var thumbnail: UIImage?

    var body: some View {
        HStack(spacing: 6) {
            if let preview, let thumbnail {
                Button { look(preview) } label: {
                    Image(uiImage: thumbnail)
                        .resizable()
                        .scaledToFill()
                        .frame(width: 40, height: 40)
                        .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
                }
                .buttonStyle(.plain)
                .padding(.vertical, 4)
                .accessibilityLabel(Text("放大看 " + name))
            } else {
                Image(systemName: symbol)
                    .font(.system(size: 14, weight: .medium))
                    .foregroundStyle(failed ? Palette.danger : Palette.muted)
                    .accessibilityHidden(true)
            }
            VStack(alignment: .leading, spacing: 0) {
                if thumbnail == nil {
                    Text(name)
                        .captionFont()
                        .foregroundStyle(Palette.ink)
                        .lineLimit(1)
                }
                if let status {
                    Text(status)
                        .scaledFont(11, relativeTo: .caption2)
                        .foregroundStyle(failed ? Palette.danger : Palette.muted)
                        .lineLimit(1)
                }
            }
            Button(action: remove) {
                Image(systemName: "xmark")
                    .font(.system(size: 11, weight: .semibold))
                    .foregroundStyle(Palette.muted)
                    .frame(width: 32, height: 36)
                    .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .accessibilityLabel(Text(removeLabel))
        }
        .padding(.leading, thumbnail == nil ? 10 : 4)
        .frame(maxWidth: 200, alignment: .leading)
        .background(failed ? Palette.stopFill : Palette.panel, in: RoundedRectangle(cornerRadius: 12, style: .continuous))
        .accessibilityElement(children: .contain)
        .accessibilityLabel(Text(name + (status.map { "，" + $0 } ?? "")))
        // Drawn small from the preview, away from the screen.
        .task(id: preview) {
            guard let preview else { return }
            thumbnail = await UIImage(contentsOfFile: preview.path)?.byPreparingThumbnail(ofSize: CGSize(width: 120, height: 120))
        }
    }
}

/// A picture's preview for its tile and Quick Look: at most 1600 px, written to WorkspaceModel.photoFolder. Its file
/// name, or nil when the picture cannot be read (the tile then shows its icon).
nonisolated func photoPreview(of file: URL) -> String? {
    guard let source = CGImageSourceCreateWithURL(file as CFURL, nil) else { return nil }
    let options: [CFString: Any] = [kCGImageSourceCreateThumbnailFromImageAlways: true, kCGImageSourceCreateThumbnailWithTransform: true,
                                    kCGImageSourceThumbnailMaxPixelSize: 1600]
    guard let image = CGImageSourceCreateThumbnailAtIndex(source, 0, options as CFDictionary) else { return nil }
    let folder = WorkspaceModel.photoFolder
    try? FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
    let name = UUID().uuidString + ".jpg"
    guard let target = CGImageDestinationCreateWithURL(folder.appendingPathComponent(name) as CFURL, UTType.jpeg.identifier as CFString, 1, nil) else {
        return nil
    }
    CGImageDestinationAddImage(target, image, [kCGImageDestinationLossyCompressionQuality: 0.8] as CFDictionary)
    return CGImageDestinationFinalize(target) ? name : nil
}

/// The one page a picker pushes: the computer file the workspace holds.
private struct PickedFile: Hashable {}

/// 引用对话, 引用技能 and 从电脑选择文件 (web references-ui.js, files-ui.js; Android ReferencesPane, RemotePane): a
/// search, the matches, a page more. A computer folder opens; a computer file opens its page, to save it to the phone
/// or add it to the message (Android 1.0.2); the folder itself can be referred to. Picking a reference closes the
/// sheet; the conversation or the new-conversation sheet behind stays as it was.
struct PickerSheet: View {
    let model: AppModel
    @State private var query = ""
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        let workspace = model.workspace
        // Under a computer file's page, its folder as it was listed.
        let name = workspace.picker == "file" ? "remote" : workspace.picker ?? ""
        let data = workspace.picker == "file" ? workspace.folderListing : workspace.data
        NavigationStack(path: filePath) {
            ScrollView {
                VStack(alignment: .leading, spacing: 12) {
                    if workspace.paneBusy && workspace.picker != "file" { ProgressView().frame(maxWidth: .infinity) }
                    if let error = workspace.paneError, workspace.picker != "file" {
                        Text(error)
                            .noteFont()
                            .foregroundStyle(Palette.danger)
                    }
                    if name == "remote" {
                        remote(data)
                    } else {
                        references(name, data)
                    }
                }
                .padding(.horizontal, 20)
                .padding(.vertical, 12)
            }
            .scrollDismissesKeyboard(.interactively)
            .navigationTitle(name == "remote" ? "从电脑选择文件" : name == "skill" ? "引用技能" : "引用对话")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button(role: .close) { dismiss() }
                }
            }
            .navigationDestination(for: PickedFile.self) { _ in
                FilePage(model: model)
            }
        }
        .presentationBackground(Palette.sheet)
    }

    /// A computer file's page is pushed over its folder; the system back returns to the folder.
    private var filePath: Binding<[PickedFile]> {
        Binding(get: { model.workspace.picker == "file" ? [PickedFile()] : [] },
                set: { if $0.isEmpty && model.workspace.picker == "file" { model.workspace.leaveComputerFile() } })
    }

    @ViewBuilder
    private func references(_ name: String, _ data: JSONValue) -> some View {
        let workspace = model.workspace
        let items = data["items"].array
        HStack(spacing: 8) {
            TextField("", text: $query, prompt: Text(name == "skill" ? "搜索技能" : "搜索对话").foregroundStyle(Palette.muted))
                .submitLabel(.search)
                .onSubmit { workspace.refresh(name, query: query) }
                .fieldBox()
                .accessibilityLabel(Text(name == "skill" ? "搜索技能" : "搜索对话"))
            Button("搜索") { workspace.refresh(name, query: query) }
                .buttonStyle(PillStyle())
                .disabled(workspace.paneBusy)
        }
        if name == "skill" {
            Button("重新读取") { workspace.refresh(name, query: query, fresh: true) }
                .buttonStyle(PillStyle(kind: .text))
                .disabled(workspace.paneBusy)
            let note = skillNote(data, items: items, busy: workspace.paneBusy, failed: workspace.paneError != nil)
            if !note.isEmpty {
                Text(note)
                    .noteFont()
                    .foregroundStyle(Palette.muted)
            }
            if data["page_reset"].bool() {
                Text("技能列表已变化，已返回第一页。")
                    .noteFont()
                    .foregroundStyle(Palette.muted)
            }
        }
        if !items.isEmpty {
            rows(items) { reference in
                let title = reference["name"].string().isEmpty ? reference["title"].string() : reference["name"].string()
                let detail = reference["description"].string()
                return (title, detail.isEmpty ? nil : detail, "plus.circle")
            } pick: { reference in
                workspace.addReference(reference)
                dismiss()
            }
        } else if !workspace.paneBusy && workspace.paneError == nil && data.has("items") && name == "chat" {
            Text("没有找到匹配的对话。")
                .noteFont()
                .foregroundStyle(Palette.muted)
        }
        if data["has_more"].bool() {
            Button("下一页") { workspace.refresh(name, query: query, offset: data["next_offset"].string()) }
                .buttonStyle(PillStyle(kind: .text))
                .disabled(workspace.paneBusy)
        }
    }

    private func skillNote(_ data: JSONValue, items: [JSONValue], busy: Bool, failed: Bool) -> String {
        let status = data["scan_status"].string()
        if failed && !items.isEmpty { return "刷新失败，以下仍是上次读取的结果。" }
        if busy { return items.isEmpty ? "正在读取技能…" : "正在读取，以下暂为上次结果。" }
        if status == "failed" { return "技能读取失败，请重试；若仍失败，请检查电脑端技能配置。" }
        if status == "partial" { return items.isEmpty ? "已加载的技能中没有匹配项，部分来源未能读取。" : "部分技能未能读取，其余技能仍可选择。" }
        if !failed && data.has("items") && items.isEmpty { return "未找到匹配技能。" }
        return ""
    }

    @ViewBuilder
    private func remote(_ data: JSONValue) -> some View {
        let workspace = model.workspace
        let path = data["path"].string()
        if !path.isEmpty {
            Text(path)
                .noteFont()
                .foregroundStyle(Palette.muted)
                .textSelection(.enabled)
        }
        HStack(spacing: 8) {
            if !data["parent"].string().isEmpty {
                Button("上一级") { workspace.refresh("remote", query: data["parent"].string()) }
                    .buttonStyle(PillStyle())
            }
            if data["folder"].isObject {
                Button("引用此文件夹") {
                    workspace.addReference(data["folder"])
                    dismiss()
                }
                .buttonStyle(PillStyle())
            }
        }
        .disabled(workspace.paneBusy)
        let items = data["items"].array
        if !items.isEmpty {
            rows(items) { row in
                let file = row["kind"].string() == "file"
                return (row["name"].string(), file && row.has("size") ? byteSize(row["size"].int64()) : nil, file ? "doc" : "folder")
            } pick: { row in
                if row["kind"].string() == "file" {
                    workspace.computerFile(row)
                } else {
                    workspace.refresh("remote", query: row["path"].string())
                }
            }
        }
        if data["has_more"].bool() {
            Button("下一页") { workspace.refresh("remote", query: path, offset: data["next_offset"].string()) }
                .buttonStyle(PillStyle(kind: .text))
                .disabled(workspace.paneBusy)
        }
    }

    /// The rows of a list, in one grouped card (web .setting-group).
    private func rows(_ items: [JSONValue], label: @escaping (JSONValue) -> (String, String?, String), pick: @escaping (JSONValue) -> Void) -> some View {
        VStack(spacing: 0) {
            ForEach(Array(items.enumerated()), id: \.offset) { index, item in
                if index > 0 { Rectangle().fill(Palette.line).frame(height: 1).padding(.leading, 52) }
                let (title, detail, symbol) = label(item)
                Button {
                    pick(item)
                } label: {
                    HStack(spacing: 12) {
                        Image(systemName: symbol)
                            .font(.system(size: 17))
                            .foregroundStyle(Palette.muted)
                            .frame(width: 24)
                        VStack(alignment: .leading, spacing: 2) {
                            Text(title)
                                .bodyFont()
                                .foregroundStyle(Palette.ink)
                                .lineLimit(2)
                                .multilineTextAlignment(.leading)
                            if let detail {
                                Text(detail)
                                    .captionFont()
                                    .foregroundStyle(Palette.muted)
                                    .lineLimit(2)
                                    .multilineTextAlignment(.leading)
                            }
                        }
                        .frame(maxWidth: .infinity, alignment: .leading)
                    }
                    .padding(.horizontal, 16)
                    .padding(.vertical, 12)
                    .frame(minHeight: 52)
                    .contentShape(Rectangle())
                }
                .buttonStyle(RowPressStyle(radius: 0, pressed: Palette.groupPressed))
                .disabled(model.workspace.paneBusy)
            }
        }
        .background(Palette.controlFill, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
        .clipShape(RoundedRectangle(cornerRadius: 16, style: .continuous))
    }
}
