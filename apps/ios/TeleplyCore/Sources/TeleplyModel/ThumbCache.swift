import Foundation

/// The answer thumbnails on this phone (file-preview design §7): one file per (computer, file id, `v`, width), under a
/// folder of its own in the caches and a subfolder per computer, so that forgetting a computer can clear just its own.
/// An address whose `v` did not change never asks the computer again. A fetched picture is written under a temporary
/// name first and renamed when whole, the way SentPictures' copies are; reading touches it, and past [maxBytes] the
/// least recently used go. Pure Foundation, so it can be read in tests without a phone.
public struct ThumbCache: Sendable {
    /// The folder under the app's caches that holds answer thumbnails, apart from the pictures sent with messages.
    public static let folderName = "answer-thumbs"
    /// What answer thumbnails may take all together on the phone (§7): 200 MB, the least recently used going first.
    public static let limit: Int64 = 200 * 1024 * 1024
    public static let suffix = ".thumb"

    public let folder: URL
    public let maxBytes: Int64

    public init(folder: URL, maxBytes: Int64 = ThumbCache.limit) {
        self.folder = folder
        self.maxBytes = maxBytes
    }

    /// Where the thumb of one address lives (whether or not it is there yet).
    public func entry(computer: String, file: String, version: String, width: Int) -> URL {
        folder.appendingPathComponent(Self.computerFolder(computer), isDirectory: true)
            .appendingPathComponent(Self.name(file: file, version: version, width: width))
    }

    /// The thumb's bytes, touching it as used; nil when it is not kept here.
    public func read(computer: String, file: String, version: String, width: Int) -> Data? {
        let kept = entry(computer: computer, file: file, version: version, width: width)
        guard let bytes = try? Data(contentsOf: kept), !bytes.isEmpty else { return nil }
        try? FileManager.default.setAttributes([.modificationDate: Date()], ofItemAtPath: kept.path)
        return bytes
    }

    /// Marks a kept thumb as used just now, so the least recently seen go first (a cached picture is not read again).
    public func touch(computer: String, file: String, version: String, width: Int) {
        try? FileManager.default.setAttributes([.modificationDate: Date()],
                                               ofItemAtPath: entry(computer: computer, file: file, version: version, width: width).path)
    }

    /// Keeps [bytes] as this address's thumb, written aside first; nil when it could not be kept.
    @discardableResult
    public func keep(_ bytes: Data, computer: String, file: String, version: String, width: Int) -> URL? {
        guard !bytes.isEmpty else { return nil }
        let kept = entry(computer: computer, file: file, version: version, width: width)
        let part = kept.deletingLastPathComponent().appendingPathComponent(".part-" + UUID().uuidString)
        do {
            try FileManager.default.createDirectory(at: kept.deletingLastPathComponent(), withIntermediateDirectories: true)
            try bytes.write(to: part)
            try? FileManager.default.removeItem(at: kept)
            try FileManager.default.moveItem(at: part, to: kept)
            trim()
            return kept
        } catch {
            try? FileManager.default.removeItem(at: part)
            return nil
        }
    }

    /// Keeps an already fetched file as this address's thumb, moving it into place (a copy when the move fails);
    /// nil when it could not be kept.
    @discardableResult
    public func keep(fileAt source: URL, computer: String, file: String, version: String, width: Int) -> URL? {
        let kept = entry(computer: computer, file: file, version: version, width: width)
        do {
            try FileManager.default.createDirectory(at: kept.deletingLastPathComponent(), withIntermediateDirectories: true)
            try? FileManager.default.removeItem(at: kept)
            do {
                try FileManager.default.moveItem(at: source, to: kept)
            } catch {
                try FileManager.default.copyItem(at: source, to: kept)
                try? FileManager.default.removeItem(at: source)
            }
            trim()
            return kept
        } catch {
            try? FileManager.default.removeItem(at: source)
            return nil
        }
    }

    /// Past [maxBytes], the least recently read or written files go until the folder fits again.
    public func trim() {
        let all = files()
        var total = all.reduce(Int64(0)) { $0 + $1.size }
        guard total > maxBytes else { return }
        for old in all.sorted(by: { $0.modified < $1.modified }) {
            guard total > maxBytes else { break }
            if (try? FileManager.default.removeItem(at: old.url)) != nil { total -= old.size }
        }
    }

    /// What the whole folder takes, for the tests and 存储.
    public func totalBytes() -> Int64 { files().reduce(Int64(0)) { $0 + $1.size } }

    /// 移除一台电脑: its thumbs go, the others stay.
    public func clear(computer: String) {
        try? FileManager.default.removeItem(at: folder.appendingPathComponent(Self.computerFolder(computer), isDirectory: true))
    }

    /// 退出登录: all thumbs go.
    public func clearAll() {
        try? FileManager.default.removeItem(at: folder)
    }

    private func files() -> [(url: URL, size: Int64, modified: Date)] {
        guard let walk = FileManager.default.enumerator(at: folder, includingPropertiesForKeys: [.isRegularFileKey, .fileSizeKey, .contentModificationDateKey]) else {
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

    /// A folder name for one computer: only letters, digits, `-` and `_`, so no id ever leaves the folder it belongs to.
    static func computerFolder(_ computer: String) -> String {
        let safe = computer.filter { $0.isLetter || $0.isNumber || $0 == "-" || $0 == "_" }
        return safe.isEmpty ? "computer" : safe
    }

    /// The file name of one address: a digest, so that no file id, `v` or width is written out as the phone's name.
    public static func name(file: String, version: String, width: Int) -> String {
        digest("\(file)\n\(version)\n\(width)") + suffix
    }

    /// A short stable digest for file names only (not a secret): two 64-bit FNV-1a passes over different offsets.
    static func digest(_ text: String) -> String {
        func fnv(_ seed: UInt64) -> UInt64 {
            var hash = seed
            for byte in text.utf8 {
                hash ^= UInt64(byte)
                hash = hash &* 0x100000001b3
            }
            return hash
        }
        return String(format: "%016llx%016llx", fnv(0xcbf29ce484222325), fnv(0x84222325cbf29ce4))
    }
}
