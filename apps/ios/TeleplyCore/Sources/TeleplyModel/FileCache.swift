import Foundation

/// The folder under the app's caches that holds the original files the phone keeps (§7, second point).
public let answerFileFolderName = "answer-files"

/// What the kept originals may take on the phone, all computers together (§7): 500 MB, the least recently used going.
public let answerFileLimit: Int64 = 500 * 1024 * 1024

/// The original files this phone keeps (file-preview design §7): one file per (computer, file id, version), under a
/// folder per computer so that removing a computer can drop its own. A fetched file is moved into place first and the
/// cache trimmed when it is whole; reading touches it, and past [maxBytes] the least recently used go. Pure Foundation,
/// so it can be read in tests without a phone.
public struct FileCache: Sendable {
    public let root: URL
    public let maxBytes: Int64

    public init(root: URL, maxBytes: Int64 = answerFileLimit) {
        self.root = root
        self.maxBytes = maxBytes
    }

    /// Where one file of one computer lives (whether or not it is there yet); [ext] keeps Quick Look's type right.
    public func entry(computer: String, file: String, version: String, ext: String) -> URL {
        root.appendingPathComponent(ThumbCache.computerFolder(computer), isDirectory: true)
            .appendingPathComponent(Self.name(file: file, version: version, ext: ext))
    }

    /// The kept file, touching it as used; nil when it is not here.
    public func read(computer: String, file: String, version: String, ext: String) -> URL? {
        let kept = entry(computer: computer, file: file, version: version, ext: ext)
        guard FileManager.default.fileExists(atPath: kept.path) else { return nil }
        try? FileManager.default.setAttributes([.modificationDate: Date()], ofItemAtPath: kept.path)
        return kept
    }

    /// Keeps an already downloaded file, moving it into place (a copy when the move fails); nil when it could not be
    /// kept whole.
    @discardableResult
    public func keep(fileAt source: URL, computer: String, file: String, version: String, ext: String) -> URL? {
        let kept = entry(computer: computer, file: file, version: version, ext: ext)
        let folder = kept.deletingLastPathComponent()
        do {
            try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
            let part = folder.appendingPathComponent(".part-" + UUID().uuidString)
            do {
                try FileManager.default.moveItem(at: source, to: part)
            } catch {
                try FileManager.default.copyItem(at: source, to: part)
                try? FileManager.default.removeItem(at: source)
            }
            try? FileManager.default.removeItem(at: kept)
            try FileManager.default.moveItem(at: part, to: kept)
            try? FileManager.default.setAttributes([.modificationDate: Date()], ofItemAtPath: kept.path)
            trim()
            return kept
        } catch {
            try? FileManager.default.removeItem(at: source)
            return nil
        }
    }

    /// Past [maxBytes], the least recently read or written files go until the cache fits again.
    public func trim() {
        let all = files()
        var total = all.reduce(Int64(0)) { $0 + $1.size }
        guard total > maxBytes else { return }
        for old in all.sorted(by: { $0.modified < $1.modified }) {
            guard total > maxBytes else { break }
            if (try? FileManager.default.removeItem(at: old.url)) != nil { total -= old.size }
        }
    }

    /// What the whole cache takes, for the tests and 存储.
    public func totalBytes() -> Int64 { files().reduce(Int64(0)) { $0 + $1.size } }

    /// 移除一台电脑: everything kept of it goes.
    public func clear(computer: String) {
        try? FileManager.default.removeItem(at: root.appendingPathComponent(ThumbCache.computerFolder(computer), isDirectory: true))
    }

    /// 退出登录: everything goes.
    public func clearAll() {
        try? FileManager.default.removeItem(at: root)
    }

    private func files() -> [(url: URL, size: Int64, modified: Date)] {
        guard let walk = FileManager.default.enumerator(at: root, includingPropertiesForKeys: [.isRegularFileKey, .fileSizeKey, .contentModificationDateKey]) else {
            return []
        }
        var found: [(url: URL, size: Int64, modified: Date)] = []
        for case let url as URL in walk {
            guard let values = try? url.resourceValues(forKeys: [.isRegularFileKey, .fileSizeKey, .contentModificationDateKey]),
                  values.isRegularFile == true else { continue }
            found.append((url: url, size: Int64(values.fileSize ?? 0), modified: values.contentModificationDate ?? .distantPast))
        }
        return found
    }

    /// The file name of one version: a digest, so no file id or version is written out as the phone's name, then the
    /// extension Quick Look and the share sheet need.
    public static func name(file: String, version: String, ext: String) -> String {
        ThumbCache.digest("\(file)\n\(version)") + "." + cleanExt(ext)
    }

    /// The extension for a kept file, from a whole file name: letters and digits only, at most 8, else `bin`.
    public static func safeExt(_ name: String) -> String {
        guard let dot = name.lastIndex(of: "."), dot != name.startIndex else { return "bin" }
        return cleanExt(String(name[name.index(after: dot)...]))
    }

    /// An extension already on its own (no dot), cleaned the same way: `png` stays `png`, `a very long one` becomes
    /// `bin`, so `name` may be given either a file name's extension or just `png`.
    private static func cleanExt(_ ext: String) -> String {
        let clean = ext.lowercased().filter { character in
            (character.isLetter || character.isNumber) && character.unicodeScalars.allSatisfy { $0.isASCII }
        }
        return clean.count >= 1 && clean.count <= 8 ? clean : "bin"
    }
}

/// The version a file's cache is kept by (§7): the computer's `v`; without one (an older computer) its size and
/// modification time; nil when even those are unknown, in which case nothing is kept and the file is fetched again.
public func fileVersion(version: String, size: Int64, modified: Int64) -> String? {
    if !version.isEmpty { return version }
    if size > 0, modified > 0 { return "s\(size)-m\(modified)" }
    return nil
}

/// 退出登录 and 移除一台电脑 clear this computer's caches, and with the whole account all of it (§7).
public enum AnswerCaches {
    public static func clearComputer(caches: URL, computer: String) {
        ThumbCache(folder: caches.appendingPathComponent(ThumbCache.folderName, isDirectory: true)).clear(computer: computer)
        FileCache(root: caches.appendingPathComponent(answerFileFolderName, isDirectory: true)).clear(computer: computer)
    }

    public static func clearAll(caches: URL) {
        ThumbCache(folder: caches.appendingPathComponent(ThumbCache.folderName, isDirectory: true)).clearAll()
        FileCache(root: caches.appendingPathComponent(answerFileFolderName, isDirectory: true)).clearAll()
    }
}
