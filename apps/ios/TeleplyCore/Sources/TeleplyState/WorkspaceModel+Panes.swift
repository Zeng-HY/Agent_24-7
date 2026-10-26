import Foundation
import TeleplyModel

/// A file name safe to use on this phone: no folder separators, never empty.
func safeFileName(_ name: String) -> String {
    let safe = name.replacingOccurrences(of: "/", with: "_").replacingOccurrences(of: ":", with: "_")
    return safe.trimmingCharacters(in: .whitespaces).isEmpty ? "文件" : safe
}

/// A downloaded copy moved to the file's own name, so Quick Look knows what it is; left as it was if it cannot be.
func renamed(_ copy: URL, to name: String) -> URL {
    let target = copy.deletingLastPathComponent().appendingPathComponent(safeFileName(name))
    do {
        try FileManager.default.moveItem(at: copy, to: target)
        return target
    } catch {
        return copy
    }
}

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
                    // [query] is a message: only the files it presented (DeepSeek's 成果文件, Android 1.0.2).
                    value = try await client.detail(device: key.device, route: "chat/files", query: ids + [("message", query.isEmpty ? nil : query)])
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

    /// 查看成果文件 under a DeepSeek deliverables message: 对话文件 with only the files that message presented.
    public func filesOf(message: String) {
        dropFile()
        pane = "files"
        data = [:]
        paneError = nil
        readPane("files", query: message, offset: "0", fresh: false)
    }

    /// A conversation file's page (spec 4.5; Android file): what it is, its text for a text file, and for a picture
    /// or PDF up to 20 MB a copy on this phone for Quick Look. It shows the file as it is now (当前文件).
    public func file(_ file: JSONValue) {
        guard key != nil, client != nil else { return }
        pane = "file"
        load(file)
    }

    /// A file picked in 从电脑选择文件 (Android 1.0.2): its page over the picker, to save it to the phone or add it to
    /// the message. The computer gives each file a signed download ticket; a computer too old to give one says so.
    /// The folder's listing is kept for the way back.
    public func computerFile(_ reference: JSONValue) {
        guard key != nil, client != nil, picker == "remote" else { return }
        let ticket = reference["download_id"].string()
        guard !ticket.isEmpty else {
            paneError = "请更新电脑端后下载文件"
            return
        }
        var page = reference.object
        page["id"] = .string(ticket)
        page["reference"] = reference
        folderListing = data
        picker = "file"
        load(.object(page))
    }

    /// From a computer file's page back to its folder, as it was listed.
    public func leaveComputerFile() {
        guard picker == "file" else { return }
        paneRead?.cancel()
        paneGeneration += 1
        dropFile()
        picker = "remote"
        data = folderListing
        folderListing = [:]
        paneBusy = false
        paneError = nil
    }

    /// 添加到消息 on a computer file's page: the file goes with the next message (or the new conversation) and the
    /// picker closes, as picking it did before 1.0.2.
    public func addComputerFile() {
        let reference = data["reference"]
        guard picker == "file", reference.isObject else { return }
        addReference(reference)
        closePicker()
    }

    /// Reads a file page: its facts first, then its text or picture. A preview that does not load leaves the file to
    /// be saved all the same (Android 1.0.2), with a line saying so.
    func load(_ file: JSONValue) {
        guard let key, let client else { return }
        paneRead?.cancel()
        paneGeneration += 1
        let g = paneGeneration
        data = file
        paneBusy = true
        paneError = nil
        dropFile()
        result = ""
        paneRead = Task { [weak self] in
            do {
                let id = file["id"].string()
                let ids: [(String, String?)] = [("app", key.app), ("id", key.chat), ("file", id)]
                let meta = try await client.detail(device: key.device, route: "file/meta", query: ids)
                let kind = meta["kind"].string()
                var text = ""
                var copy: URL?
                var note = ""
                do {
                    if kind == "text" { text = try await client.detail(device: key.device, route: "file/text", query: ids)["text"].string() }
                    if ["image", "pdf"].contains(kind) && meta["size"].int64() <= 20 * 1024 * 1024 {
                        let name = file["name"].string().isEmpty ? meta["name"].string() : file["name"].string()
                        copy = renamed(try await client.download(device: key.device, app: key.app, chat: key.chat, file: id), to: name)
                    }
                } catch is CancellationError {
                    throw CancellationError()
                } catch {
                    note = "预览未能加载，仍可尝试保存原文件。"
                }
                guard let self, g == self.paneGeneration else {
                    if let copy { try? FileManager.default.removeItem(at: copy) }
                    return
                }
                var fields = file.object
                fields["meta"] = meta
                fields["kind"] = .string(kind)
                if fields["name"]?.string().isEmpty ?? true { fields["name"] = meta["name"] }
                self.data = .object(fields)
                self.fileText = text
                self.preview = copy
                self.fileNote = note
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

    /// A copy of the open file on this phone to save, share or look at (保存到文件, 分享, 用快速查看打开): the preview
    /// when there is one, otherwise downloaded now, with how far it got in [transfer]. One at a time; 取消 or leaving
    /// the page stops it. The caller may move or delete the copy it gets.
    public func fileCopy() async throws -> URL {
        guard let key, let client, pane == "file" || picker == "file" else { throw ReadFailure("文件页已关闭") }
        guard copyTask == nil else { throw ReadFailure("文件还在下载，请稍候") }
        let file = data
        let name = safeFileName(file["name"].string())
        let size = file["meta"]["size"].int64()
        let preview = preview
        let g = paneGeneration
        transferring = true
        transfer = preview == nil ? "正在下载…" : ""
        // Held only while the download runs.
        let report: @Sendable (Int64, Int64) -> Void = { got, total in
            Task { @MainActor in self.downloaded(got, of: total > 0 ? total : size, generation: g) }
        }
        let task = Task<URL, any Error> {
            let source: URL
            if let preview {
                source = preview
            } else {
                source = try await client.download(device: key.device, app: key.app, chat: key.chat, file: file["id"].string(), progress: report)
            }
            // Under the file's own name, so the system's sheets and the saved file carry it.
            let folder = FileManager.default.temporaryDirectory.appendingPathComponent("teleply-share-" + UUID().uuidString)
            try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
            let named = folder.appendingPathComponent(name)
            try FileManager.default.copyItem(at: source, to: named)
            if source != preview { try? FileManager.default.removeItem(at: source) }
            return named
        }
        copyTask = task
        defer {
            if copyTask == task {
                copyTask = nil
                transferring = false
                transfer = ""
            }
        }
        do {
            return try await task.value
        } catch {
            if task.isCancelled { throw CancellationError() }
            throw error
        }
    }

    /// How far a download for 保存到文件 or 分享 got: a share of the file's size, or megabytes when it is not known.
    func downloaded(_ got: Int64, of total: Int64, generation g: Int) {
        guard transferring, g == paneGeneration else { return }
        transfer = total > 0 ? "正在下载 \(min(100, got * 100 / total))%" : "已接收 \(got / 1_048_576) MB"
    }

    /// 取消: stops the copy under way.
    public func cancelCopy() {
        copyTask?.cancel()
        copyTask = nil
        transferring = false
        transfer = ""
    }

    /// A file page's own things go with it: its text, its preview's copy, a copy under way.
    func dropFile() {
        cancelCopy()
        fileText = ""
        fileNote = ""
        dropPreview()
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

    /// 引用对话, 引用技能 or 从电脑选择文件 (＋): over the conversation or the new-conversation sheet, which stays.
    public func openPicker(_ name: String) {
        picker = name
        data = [:]
        folderListing = [:]
        readPane(name, query: "", offset: "0", fresh: false)
    }

    public func closePicker() {
        paneRead?.cancel()
        paneGeneration += 1
        if picker == "file" { dropFile() }
        picker = nil
        data = [:]
        folderListing = [:]
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
