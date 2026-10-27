import Foundation
import TeleplyModel

/// Photos and files from the phone (spec 4.3 ＋, 8.1, T08; Android WorkspaceController importUri): each shows as a
/// tile at once, goes up to the computer with its length, and the send waits until every one is there. A failure
/// stays beside its tile with why; nothing is left out quietly (B10).
extension WorkspaceModel {
    /// Uploads [file], a copy this model now owns (it is deleted once sent or dropped), as [name]. A new
    /// conversation's files go up under its draft's request id.
    /// Where a picture's preview waits while it goes with a message (its tile, and tapped, Quick Look; user 10-27): the
    /// app's caches, not backed up. The system may clear them; the tile then shows its icon.
    nonisolated public static let photoFolder = FileManager.default.urls(for: .cachesDirectory, in: .userDomainMask)[0]
        .appendingPathComponent("teleply-photos")

    /// [preview]: the file name of the picture's preview in [photoFolder], made by the app before the upload.
    public func importFile(_ file: URL, name: String, image: Bool, preview: String? = nil) {
        guard let key, let client, ready else {
            try? FileManager.default.removeItem(at: file)
            dropPreview(preview)
            return
        }
        let saved = current(key)
        let uploads = saved["uploads"].array
        if image && uploads.filter({ $0["image"].bool() }).count >= 5 {
            try? FileManager.default.removeItem(at: file)
            dropPreview(preview)
            error = "最多5张图片"
            return
        }
        let size = ((try? FileManager.default.attributesOfItem(atPath: file.path))?[.size] as? NSNumber)?.int64Value ?? 0
        let local = newID()
        var next = saved.object
        var row: [String: JSONValue] = ["local": .string(local), "name": .string(name), "image": .bool(image), "status": "uploading",
                                        "size": .number(Double(size))]
        if let preview { row["preview"] = .string(preview) }
        next["uploads"] = .array(uploads + [.object(row)])
        keep(key, .object(next))
        error = nil
        uploadTasks[local] = Task { [weak self] in
            defer { try? FileManager.default.removeItem(at: file) }
            let started = ContinuousClock.now
            let label = image ? "图片上传" : "文件上传"
            do {
                guard let self else { return }
                let target = key.chat == "@new" ? try await self.ensureNewID(key, client) : key.chat
                let meta = try await client.upload(device: key.device, app: key.app, chat: target, draft: key.chat == "@new", name: name,
                                                   file: file, size: size, image: image)
                self.timed(label, ContinuousClock.now - started, speedOutcome(meta))
                self.updateUpload(key, local) { row in
                    row["status"] = "ready"
                    row["meta"] = meta
                }
            } catch is CancellationError {
            } catch {
                guard let self else { return }
                self.timed(label, ContinuousClock.now - started, (error as? ServiceFailure).map { "HTTP \($0.status)" } ?? "网络失败")
                self.updateUpload(key, local) { row in
                    row["status"] = "failed"
                    row["error"] = .string(describe(error))
                }
                if self.key == key { self.error = describe(error) }
            }
            self?.uploadTasks[local] = nil
        }
    }

    /// A tile's ✕: its upload stops and only that row goes; the other attachments stay.
    public func removeUpload(_ local: String) {
        uploadTasks[local]?.cancel()
        uploadTasks[local] = nil
        guard let key else { return }
        let saved = current(key)
        for row in saved["uploads"].array where row["local"].string() == local { dropPreview(row["preview"].string()) }
        var next = saved.object
        next["uploads"] = .array(saved["uploads"].array.filter { $0["local"].string() != local })
        keep(key, .object(next))
    }

    /// A picture's preview goes with its row (removed, or sent).
    func dropPreview(_ name: String?) {
        guard let name, !name.isEmpty, !name.contains("/") else { return }
        try? FileManager.default.removeItem(at: Self.photoFolder.appendingPathComponent(name))
    }

    func updateUpload(_ key: ChatKey, _ local: String, _ change: (inout [String: JSONValue]) -> Void) {
        let saved = current(key)
        var next = saved.object
        next["uploads"] = .array(saved["uploads"].array.map { row in
            guard row["local"].string() == local, case .object(var fields) = row else { return row }
            change(&fields)
            return .object(fields)
        })
        keep(key, .object(next))
    }
}
