import Foundation
import TeleplyModel

/// Photos and files from the phone (spec 4.3 ＋, 8.1, T08; Android WorkspaceController importUri): each shows as a
/// tile at once, goes up to the computer with its length, and the send waits until every one is there. A failure
/// stays beside its tile with why; nothing is left out quietly (B10).
extension WorkspaceModel {
    /// Uploads [file], a copy this model now owns (it is deleted once sent or dropped), as [name]. A new
    /// conversation's files go up under its draft's request id.
    public func importFile(_ file: URL, name: String, image: Bool) {
        guard let key, let client, ready else {
            try? FileManager.default.removeItem(at: file)
            return
        }
        let saved = current(key)
        let uploads = saved["uploads"].array
        if image && uploads.filter({ $0["image"].bool() }).count >= 5 {
            try? FileManager.default.removeItem(at: file)
            error = "最多5张图片"
            return
        }
        let size = ((try? FileManager.default.attributesOfItem(atPath: file.path))?[.size] as? NSNumber)?.int64Value ?? 0
        let local = newID()
        var next = saved.object
        next["uploads"] = .array(uploads + [["local": .string(local), "name": .string(name), "image": .bool(image), "status": "uploading",
                                             "size": .number(Double(size))]])
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
        var next = saved.object
        next["uploads"] = .array(saved["uploads"].array.filter { $0["local"].string() != local })
        keep(key, .object(next))
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
