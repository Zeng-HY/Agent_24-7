import Foundation
import TeleplyModel

/// Where a file's bytes stream from for the system player, and the sign-in cookie that player must send itself (§6.2).
public struct MediaSource {
    public let url: URL
    public let cookies: [HTTPCookie]

    public init(url: URL, cookies: [HTTPCookie] = []) {
        self.url = url
        self.cookies = cookies
    }
}

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

    /// A file an answer links to (web reading-ui.js referencedFile): its page, found among the files the computer lists
    /// for this conversation by its exact path; the computer lists only files an answer names (message_files).
    public func openLinkedFile(_ path: String) {
        guard let key, let client else { return }
        let target = normalizePath(path)
        error = nil
        linkRead?.cancel()
        linkRead = Task { [weak self] in
            do {
                let listed = try await client.detail(device: key.device, route: "chat/files", query: [("app", key.app), ("id", key.chat)])
                guard let self, self.key == key else { return }
                guard let match = listed["items"].array.first(where: { normalizePath($0["path"].string()) == target }) else {
                    self.error = "这个文件不在电脑列出的对话文件里，现在打不开；电脑端更新后再试"
                    return
                }
                if match["state"].string() == "missing" {
                    self.error = "文件已移动或删除"
                    return
                }
                self.file(match)
            } catch is CancellationError {
            } catch {
                guard let self, self.key == key else { return }
                self.error = describe(error)
            }
        }
    }

    /// A file the answer listed with it (`files`, §5.1) opens its page directly, carrying that very entry: no read of
    /// the conversation's whole file list first, and the page still reads the file's meta and bytes as before.
    public func openAnswerFile(_ file: FileRef) {
        guard key != nil, client != nil, !file.id.isEmpty else { return }
        if file.state == "missing" {
            error = "文件已移动或删除"
            return
        }
        error = nil
        self.file(file.pageJSON)
    }

    /// Where answer thumbnails and kept originals live on this phone: folders of their own in the caches, a subfolder
    /// per computer (file-preview design §7).
    nonisolated public static let cachesRoot = FileManager.default.urls(for: .cachesDirectory, in: .userDomainMask)[0]
    nonisolated public static let answerThumbFolder = WorkspaceModel.cachesRoot.appendingPathComponent(ThumbCache.folderName)
    nonisolated public static let answerFileFolder = WorkspaceModel.cachesRoot.appendingPathComponent(answerFileFolderName)

    nonisolated static let answerThumbs = ThumbCache(folder: WorkspaceModel.answerThumbFolder)
    nonisolated static let answerFiles = FileCache(root: WorkspaceModel.answerFileFolder)

    /// A picture in an answer (§6.1): the computer's thumb at about [width] pixels (320 in a strip, 640 or 1280 in the
    /// text, 2048 or 4096 in the viewer), kept on this phone by (computer, file id, version, width) (§7). Without a
    /// version nothing is kept (an older computer): the same address could be a newer picture, so it is asked every time.
    public func answerThumb(_ file: FileRef, width: Int) async -> Data? {
        guard let key, let client, !file.id.isEmpty else { return nil }
        let bucket = answerThumbWidth(width)
        let version = file.stableVersion
        let cache = Self.answerThumbs
        if let version, let kept = cache.read(computer: key.device, file: file.id, version: version, width: bucket) {
            return kept
        }
        do {
            let fetched = try await client.thumb(device: key.device, app: key.app, chat: key.chat,
                                                 file: file.id, width: bucket, version: version ?? "")
            if let version { cache.keep(fetched, computer: key.device, file: file.id, version: version, width: bucket) }
            return fetched
        } catch is CancellationError {
            return nil
        } catch {
            return nil
        }
    }

    /// The original of a file the answer listed, kept under `answer-files` per computer (§7): the same file is not
    /// downloaded twice for its page, the viewer, saving or sharing. Nil when the version is unknown (an older computer
    /// without size and time: nothing may be kept, or a newer file would be served from the old copy) or the fetch fails.
    public func cachedAnswerFile(_ file: FileRef) async -> URL? {
        guard let key, let client, !file.id.isEmpty, let version = file.stableVersion else { return nil }
        let cache = Self.answerFiles
        let ext = FileCache.safeExt(file.name)
        if let kept = cache.read(computer: key.device, file: file.id, version: version, ext: ext) { return kept }
        do {
            let fetched = try await client.download(device: key.device, app: key.app, chat: key.chat, file: file.id)
            return cache.keep(fileAt: fetched, computer: key.device, file: file.id, version: version, ext: ext)
        } catch is CancellationError {
            return nil
        } catch {
            return nil
        }
    }

    /// A copy of one file for saving or sharing from the viewer, where no file page is open: the kept original when
    /// there is one, else a download; under the file's own name for the system's sheets.
    public func copyForViewer(_ file: FileRef) async throws -> URL {
        guard let key, let client, !file.id.isEmpty else { throw ReadFailure("没有活动会话") }
        guard copyTask == nil else { throw ReadFailure("文件还在下载，请稍候") }
        let name = safeFileName(file.name.isEmpty ? "文件" : file.name)
        let kept = await cachedAnswerFile(file)
        let size = file.size
        guard kept != nil || size <= RelayClient.downloadLimit else { throw ReadFailure(RelayClient.tooLargeToDownload) }
        let g = paneGeneration
        transferring = true
        transfer = kept == nil ? "正在下载…" : ""
        let report: @Sendable (Int64, Int64) -> Void = { got, total in
            Task { @MainActor in self.downloaded(got, of: total > 0 ? total : size, generation: g) }
        }
        let task = Task<URL, any Error> {
            let source: URL
            if let kept {
                source = kept
            } else {
                source = try await client.download(device: key.device, app: key.app, chat: key.chat, file: file.id, progress: report)
            }
            return try Self.namedCopy(source: source, name: name, deleteSource: kept == nil)
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

    /// The pictures of one answer, in the order it shows them, in the viewer (§6.2): a full-screen page of its own.
    public func openPictures(_ files: [FileRef], index: Int) {
        guard key != nil, client != nil else { return }
        let pictures = files.filter { $0.picture }
        guard !pictures.isEmpty else { return }
        paneRead?.cancel()
        paneGeneration += 1
        dropFile()
        pane = "picture"
        data = [:]
        paneBusy = false
        paneError = nil
        error = nil
        pictureFiles = pictures
        pictureIndex = min(max(index, 0), pictures.count - 1)
    }

    /// A copy under the file's own name in a temporary folder; the caller's copy, to move or delete.
    static func namedCopy(source: URL, name: String, deleteSource: Bool) throws -> URL {
        let folder = FileManager.default.temporaryDirectory.appendingPathComponent("teleply-share-" + UUID().uuidString)
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        let named = folder.appendingPathComponent(name)
        try FileManager.default.copyItem(at: source, to: named)
        if deleteSource { try? FileManager.default.removeItem(at: source) }
        return named
    }

    /// Where pictures sent with messages are kept once fetched: a folder per picture, the small copy and the whole one
    /// under its own name (Quick Look shows the name and needs the extension).
    nonisolated public static let sentPictureFolder = FileManager.default.urls(for: .cachesDirectory, in: .userDomainMask)[0]
        .appendingPathComponent("teleply-sent-pictures")

    /// A picture sent with a message (state `images`, web codex-ui.js renderImages and previewImage): its small copy
    /// for the bubble, or the whole one to look at, fetched from the computer once and kept in the caches. Nil when it
    /// cannot be had; for the whole one the page says why.
    public func sentPicture(_ picture: SentPicture, whole: Bool) async -> URL? {
        guard let key, let client else { return nil }
        var base = picture.name.filter { !"/\\:*?\"<>|".contains($0) }
        if let dot = base.lastIndex(of: "."), dot != base.startIndex { base = String(base[..<dot]) }  // it comes back a PNG
        let kept = Self.sentPictureFolder.appendingPathComponent(picture.id)
            .appendingPathComponent(whole ? (base.isEmpty ? "图片" : base) + ".png" : "small.png")
        if FileManager.default.fileExists(atPath: kept.path) { return kept }
        do {
            let fetched = try await client.sentPicture(device: key.device, id: picture.id, small: !whole)
            try FileManager.default.createDirectory(at: kept.deletingLastPathComponent(), withIntermediateDirectories: true)
            try? FileManager.default.removeItem(at: kept)
            try FileManager.default.moveItem(at: fetched, to: kept)
            return kept
        } catch {
            if whole { self.error = describe(error) }
            return nil
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

    /// A conversation file's page (spec 4.5; Android file): what it is, its text for a text file, and for a picture,
    /// a PDF or another file the page shows itself (showsInPage) a copy on this phone, up to 20 MB. It shows the file
    /// as it is now (当前文件).
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

    /// Reads a file page: its facts first, then its text, or a copy of what the page shows itself. A picture, PDF or
    /// Office file of a versioned file is kept on disk (§7) and reused by saving and sharing; an older computer's file
    /// with no version is a temporary copy, as before. A preview that does not load leaves the file to be saved.
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
                let view = file["view"].string()
                let name = file["name"].string().isEmpty ? meta["name"].string() : file["name"].string()
                let size = meta["size"].int64() > 0 ? meta["size"].int64() : file["size"].int64()
                let version = file["v"].string().isEmpty ? meta["v"].string() : file["v"].string()
                let modified = file["modified"].int64() > 0 ? file["modified"].int64() : meta["modified"].int64()
                let shown = ["image", "pdf"].contains(kind) || (kind == "download" && Self.showsInPage(name))
                let limit = Self.pagePreviewLimit(kind: kind, name: name)
                var text = ""
                var textTruncated = false
                var textTotalSize: Int64 = 0
                var textLang = ""
                var textLine = 0
                var kept: URL?
                var temp: URL?
                var note = ""
                // A zip lists what is inside (§5.7); audio and video stream from the file route themselves (§6.2).
                if view == "archive", zipFile(name) {
                    let listing = try? await client.zip(device: key.device, app: key.app, chat: key.chat, file: id)
                    guard let self, g == self.paneGeneration else { return }
                    var fields = file.object
                    fields["meta"] = meta
                    fields["kind"] = .string(kind)
                    if fields["name"]?.string().isEmpty ?? true { fields["name"] = meta["name"] }
                    if !version.isEmpty { fields["v"] = .string(version) }
                    fields["zip"] = listing ?? .null
                    self.data = .object(fields)
                    self.fileNote = listing == nil ? "这个压缩包读不了，可以保存后用其他应用打开。" : ""
                    self.paneBusy = false
                    return
                }
                if view == "audio" || view == "video" {
                    guard let self, g == self.paneGeneration else { return }
                    var fields = file.object
                    fields["meta"] = meta
                    fields["kind"] = .string(kind)
                    if fields["name"]?.string().isEmpty ?? true { fields["name"] = meta["name"] }
                    if !version.isEmpty { fields["v"] = .string(version) }
                    self.data = .object(fields)
                    self.paneBusy = false
                    return
                }
                do {
                    if kind == "text" || view == "table" {
                        let reply = try await client.detail(device: key.device, route: "file/text", query: ids)
                        text = reply["text"].string()
                        textTruncated = reply["truncated"].bool()
                        textTotalSize = reply["total_size"].int64()
                        textLang = reply["lang"].string()
                        textLine = reply["line"].int()
                    }
                    // Pictures, PDFs, Word and Excel stay on disk (§7), not whole in memory; a file too big for the page
                    // is only saved or shared.
                    if shown && (size <= 0 || size <= limit) {
                        if fileVersion(version: version, size: size, modified: modified) != nil {
                            let ref = FileRef(id: id, name: name, size: size, modified: modified, version: version)
                            if let self { kept = await self.cachedAnswerFile(ref) }
                        }
                        if kept == nil {
                            temp = renamed(try await client.download(device: key.device, app: key.app, chat: key.chat, file: id), to: name)
                        }
                    }
                } catch is CancellationError {
                    throw CancellationError()
                } catch {
                    note = "预览未能加载，仍可尝试保存原文件。"
                }
                guard let self, g == self.paneGeneration else {
                    if let temp { try? FileManager.default.removeItem(at: temp) }
                    return
                }
                var fields = file.object
                fields["meta"] = meta
                fields["kind"] = .string(kind)
                if fields["name"]?.string().isEmpty ?? true { fields["name"] = meta["name"] }
                if !version.isEmpty { fields["v"] = .string(version) }
                if modified > 0 { fields["modified"] = .number(Double(modified)) }
                if !textLang.isEmpty, fields["lang"]?.string().isEmpty ?? true { fields["lang"] = .string(textLang) }
                if textLine > 0, fields["line"].int() <= 0 { fields["line"] = .number(Double(textLine)) }
                self.data = .object(fields)
                self.fileText = text
                self.fileTextTruncated = textTruncated
                self.fileTextTotalSize = textTotalSize
                self.preview = temp
                self.previewFile = kept
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

    /// §5.8's per-type limit for what a file page shows itself: a picture 30 MB, a PDF 100 MB, Office and the rest of
    /// what the page draws 30 MB.
    nonisolated public static func pagePreviewLimit(kind: String, name: String) -> Int64 {
        if kind == "image" { return RelayClient.picturePreviewLimit }
        if kind == "pdf" { return RelayClient.pdfPreviewLimit }
        return RelayClient.officePreviewLimit
    }

    /// What a file's page shows by itself besides text, pictures and PDFs, from a copy on this phone (user 10-28:
    /// "点开直接调用快速预览，不要这样转换了"): Word, Excel and PowerPoint files the way 快速查看 draws them, the
    /// pictures the computer lists as plain files, sound and video. The computer's PDF of an Office file ("preview":
    /// "pdf", Windows dev.26) is for the web and Android; this phone does not ask for it.
    nonisolated public static func showsInPage(_ name: String) -> Bool {
        guard let dot = name.lastIndex(of: ".") else { return false }
        return ["doc", "docx", "xls", "xlsx", "ppt", "pptx", "gif", "heic", "heif", "tif", "tiff", "bmp",
                "mp3", "m4a", "wav", "aac", "mp4", "mov", "m4v"].contains(name[name.index(after: dot)...].lowercased())
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

    /// A copy of the open file on this phone to save, share or look at (保存到文件, 分享, 用快速查看打开): the kept
    /// original when there is one, then the page's temporary copy, otherwise downloaded now, with how far it got in
    /// [transfer]. One at a time; 取消 or leaving the page stops it. The caller may move or delete the copy it gets.
    public func fileCopy() async throws -> URL {
        guard let key, let client, pane == "file" || picker == "file" else { throw ReadFailure("文件页已关闭") }
        guard copyTask == nil else { throw ReadFailure("文件还在下载，请稍候") }
        let file = data
        let name = safeFileName(file["name"].string())
        let size = file["meta"]["size"].int64() > 0 ? file["meta"]["size"].int64() : file["size"].int64()
        let cached = previewFile ?? cachedFileFor(file)
        let temp = preview
        // 11-15: a file the page already knows is too big is refused here; it used to come all the way down first
        guard cached != nil || temp != nil || size <= RelayClient.downloadLimit else { throw ReadFailure(RelayClient.tooLargeToDownload) }
        let g = paneGeneration
        transferring = true
        transfer = cached == nil && temp == nil ? "正在下载…" : ""
        // Held only while the download runs.
        let report: @Sendable (Int64, Int64) -> Void = { got, total in
            Task { @MainActor in self.downloaded(got, of: total > 0 ? total : size, generation: g) }
        }
        let task = Task<URL, any Error> {
            let source: URL
            if let cached {
                source = cached
            } else if let temp {
                source = temp
            } else {
                source = try await client.download(device: key.device, app: key.app, chat: key.chat, file: file["id"].string(), progress: report)
            }
            return try Self.namedCopy(source: source, name: name, deleteSource: cached == nil && temp == nil)
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

    /// The kept original of a page's file, when there is one already: saving and sharing then copy it, no second fetch.
    /// Nil for a file without a version (an older computer), which is never kept.
    func cachedFileFor(_ file: JSONValue) -> URL? {
        guard let key, !file["id"].string().isEmpty else { return nil }
        let meta = file["meta"]
        let size = file["size"].int64() > 0 ? file["size"].int64() : meta["size"].int64()
        let modified = file["modified"].int64() > 0 ? file["modified"].int64() : meta["modified"].int64()
        let version = fileVersion(version: file["v"].string(), size: size, modified: modified)
        guard let version else { return nil }
        return Self.answerFiles.read(computer: key.device, file: file["id"].string(), version: version,
                                     ext: FileCache.safeExt(file["name"].string()))
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

    /// A file page's own things go with it: its text, its temporary copy, a copy under way. A kept original stays in
    /// the cache (§7), so the next page, save or share finds it there.
    func dropFile() {
        cancelCopy()
        fileText = ""
        fileTextTruncated = false
        fileTextTotalSize = 0
        fileNote = ""
        previewFile = nil
        dropPreview()
    }

    /// Where the system player streams an audio or video file (§6.2): the file route with the same sign-in as every
    /// request, or for the local demo a kept copy on this phone. Nil when it cannot be played.
    public func mediaSource(_ file: FileRef) async -> MediaSource? {
        guard !file.id.isEmpty else { return nil }
        // The local demo has no stream of its own: its made-up clip is played from the phone's kept copy.
        if synthetic {
            guard let kept = await cachedAnswerFile(file) else { return nil }
            return MediaSource(url: kept)
        }
        guard let key, let client else { return nil }
        guard let url = try? mediaFileURL(origin: client.origin, device: key.device, app: key.app,
                                          chat: key.chat, file: file.id, version: file.version) else { return nil }
        let cookie = mediaCookie(origin: client.origin, cookie: client.sessionCookie())
        return MediaSource(url: url, cookies: cookie.map { [$0] } ?? [])
    }

    /// A file an HTML page names beside itself (web artifact-preview resource): a newer computer reads it through
    /// `/api/file/resource`; an older one, or a 404, still goes through the conversation's file list.
    public func previewResource(for file: JSONValue, path: String) async -> Data? {
        guard let key, let client, !path.isEmpty, !file["path"].string().isEmpty else { return nil }
        let id = file["id"].string()
        if usesFileResource(view: file["view"].string(), id: id) {
            do {
                let relative = resourcePath(path, pagePath: file["path"].string())
                return try await client.resourceData(device: key.device, app: key.app, chat: key.chat, file: id, path: relative)
            } catch is CancellationError {
                throw CancellationError()
            } catch let failure as ServiceFailure where failure.status != 404 {
                return nil
            } catch {
                // A computer too old for the resource route: the file list below is the 0.9.0 way.
            }
        }
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

    /// The temporary copy goes when the page does; a kept original in the cache stays.
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
