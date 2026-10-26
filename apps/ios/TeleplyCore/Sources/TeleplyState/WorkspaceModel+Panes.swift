import Foundation
import TeleplyModel

/// References, computer files and conversation files (spec 4.3 ＋, 4.5; Android WorkspaceController refresh).
extension WorkspaceModel {
    /// Reads what a pane lists. A newer read (or another pane) drops this one's answer.
    func readPane(_ name: String, query: String, offset: String, fresh: Bool) {
        guard let key, let client else { return }
        paneRead?.cancel()
        paneGeneration += 1
        let g = paneGeneration
        paneBusy = true
        paneError = nil
        let folder = current(key)["folder"].string()
        let scan = data["scan_id"].string()
        paneRead = Task { [weak self] in
            do {
                let ids: [(String, String?)] = [("app", key.app), ("id", key.chat)]
                let value: JSONValue
                switch name {
                case "files":
                    value = try await client.detail(device: key.device, route: "chat/files", query: ids)
                case "remote":
                    value = query.isEmpty
                        ? try await client.detail(device: key.device, route: "files/places", query: ids)
                        : try await client.detail(device: key.device, route: "files/list", query: ids + [("path", query), ("offset", offset)])
                case "chat", "skill":
                    let paging: [(String, String?)] = [("kind", name), ("query", query), ("offset", fresh ? "0" : offset), ("fresh", fresh ? "1" : "0"),
                                                       ("scan_id", offset != "0" && !fresh ? scan : ""), ("projectless", folder.isEmpty ? "1" : "0"), ("folder", folder)]
                    value = try await client.detail(device: key.device, route: key.chat == "@new" ? "chat/new/references" : "composer/references", query: ids + paging)
                default:
                    value = [:]
                }
                guard let self, g == self.paneGeneration, self.pane == name || self.picker == name else { return }
                self.data = value
                self.paneBusy = false
            } catch is CancellationError {
            } catch {
                guard let self, g == self.paneGeneration else { return }
                self.paneError = name == "skill" ? "技能读取失败，请重试。若仍失败，请检查电脑端连接。" : describe(error)
                self.paneBusy = false
            }
        }
    }

    /// A conversation file's page (spec 4.5; Android file): what it is, its text for a text file, and for a picture
    /// or PDF up to 20 MB a copy on this phone for Quick Look. It shows the file as it is now (当前文件).
    public func file(_ file: JSONValue) {
        guard let key, let client else { return }
        paneRead?.cancel()
        paneGeneration += 1
        let g = paneGeneration
        pane = "file"
        data = file
        paneBusy = true
        paneError = nil
        fileText = ""
        dropPreview()
        result = ""
        paneRead = Task { [weak self] in
            do {
                let id = file["id"].string()
                let ids: [(String, String?)] = [("app", key.app), ("id", key.chat), ("file", id)]
                let meta = try await client.detail(device: key.device, route: "file/meta", query: ids)
                let kind = meta["kind"].string()
                let text = kind == "text" ? try await client.detail(device: key.device, route: "file/text", query: ids)["text"].string() : ""
                let copy = ["image", "pdf"].contains(kind) && meta["size"].int64() <= 20 * 1024 * 1024
                    ? try await client.download(device: key.device, app: key.app, chat: key.chat, file: id) : nil
                guard let self, g == self.paneGeneration else {
                    if let copy { try? FileManager.default.removeItem(at: copy) }
                    return
                }
                var fields = file.object
                fields["meta"] = meta
                self.data = .object(fields)
                self.fileText = text
                self.preview = copy
                self.paneBusy = false
            } catch is CancellationError {
            } catch {
                guard let self, g == self.paneGeneration else { return }
                self.paneError = describe(error)
                self.paneBusy = false
            }
        }
    }

    /// 本轮差异 (spec 4.5, B12): what the source's record says the turn changed, a page at a time; never guessed from
    /// the file as it is now.
    public func diff(_ ref: String, offset: Int = 0) {
        guard let key, let client, !ref.isEmpty else { return }
        paneRead?.cancel()
        paneGeneration += 1
        let g = paneGeneration
        pane = "diff"
        if offset == 0 { data = [:] }
        paneBusy = true
        paneError = nil
        paneRead = Task { [weak self] in
            do {
                let page = try await client.detail(device: key.device, route: "chat/diff",
                                                   query: [("app", key.app), ("id", key.chat), ("ref", ref), ("offset", String(offset))])
                guard let self, g == self.paneGeneration else { return }
                self.data = page
                self.paneBusy = false
            } catch is CancellationError {
            } catch {
                guard let self, g == self.paneGeneration else { return }
                self.paneError = describe(error)
                self.paneBusy = false
            }
        }
    }

    /// A copy of the open file on this phone to save or share (保存到文件, 分享): the preview when there is one,
    /// otherwise downloaded now. The caller may move or delete the copy it gets.
    public func fileCopy() async throws -> URL {
        guard let key, let client, pane == "file" else { throw ReadFailure("文件页已关闭") }
        let file = data
        let name = file["name"].string().isEmpty ? "文件" : file["name"].string()
        let source: URL
        if let preview {
            source = preview
        } else {
            source = try await client.download(device: key.device, app: key.app, chat: key.chat, file: file["id"].string())
        }
        // Under the file's own name, so the system's sheets and the saved file carry it.
        let folder = FileManager.default.temporaryDirectory.appendingPathComponent("teleply-share-" + UUID().uuidString)
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        let named = folder.appendingPathComponent(name)
        try FileManager.default.copyItem(at: source, to: named)
        if source != preview { try? FileManager.default.removeItem(at: source) }
        return named
    }

    /// A file an HTML page names beside itself (web artifact-preview resource): only one this conversation lists,
    /// matched exactly by its path, at most 4 MB. Nil for anything else, so the page shows it as missing.
    public func previewResource(for file: JSONValue, path: String) async -> Data? {
        guard let key, let client, !path.isEmpty, !file["path"].string().isEmpty else { return nil }
        let items: [JSONValue]
        if let listing, listing.key == key {
            items = listing.items
        } else {
            guard let read = try? await client.detail(device: key.device, route: "chat/files", query: [("app", key.app), ("id", key.chat)]) else { return nil }
            items = read["items"].array
            listing = (key, items)
        }
        let target = normalizePath(path)
        guard let match = items.first(where: { !$0["id"].string().isEmpty && !$0["path"].string().isEmpty && normalizePath($0["path"].string()) == target }),
              match["size"].int64() <= 4 * 1024 * 1024, match["state"].string() != "missing",
              let copy = try? await client.download(device: key.device, app: key.app, chat: key.chat, file: match["id"].string()) else { return nil }
        defer { try? FileManager.default.removeItem(at: copy) }
        return try? Data(contentsOf: copy)
    }

    /// The preview's copy goes when the page does.
    func dropPreview() {
        if let preview { try? FileManager.default.removeItem(at: preview) }
        preview = nil
    }

    /// 引用对话, 引用技能 or 电脑上的文件 (＋): over the conversation or the new-conversation sheet, which stays.
    public func openPicker(_ name: String) {
        picker = name
        data = [:]
        readPane(name, query: "", offset: "0", fresh: false)
    }

    public func closePicker() {
        paneRead?.cancel()
        paneGeneration += 1
        picker = nil
        data = [:]
        paneBusy = false
        paneError = nil
    }

    /// A conversation, skill, computer file or folder goes with the next message (or the new conversation).
    public func addReference(_ reference: JSONValue) {
        guard let key, ready else { return }
        let saved = current(key)
        let references = saved["references"].array
        guard !references.contains(where: { $0["id"].string() == reference["id"].string() && $0["kind"].string() == reference["kind"].string() }) else { return }
        var next = saved.object
        next["references"] = .array(references + [reference])
        keep(key, .object(next))
    }

    public func removeReference(_ id: String) {
        guard let key, ready else { return }
        let saved = current(key)
        var next = saved.object
        next["references"] = .array(saved["references"].array.filter { $0["id"].string() != id })
        keep(key, .object(next))
    }
}
