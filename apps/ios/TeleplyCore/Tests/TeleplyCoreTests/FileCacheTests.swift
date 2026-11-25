import Foundation
import Testing
@testable import TeleplyModel

/// The kept originals (file-preview design §7, second point): a version decides the name, an older computer's size and
/// modification time stand in for it, nothing is kept without either, and the cache is 500 MB over all computers with
/// the least recently used going first.
struct FileCacheTests {
    private func tempFolder() -> URL {
        let folder = FileManager.default.temporaryDirectory.appendingPathComponent("teleply-files-\(UUID().uuidString)")
        try? FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        return folder
    }

    private func write(_ bytes: Int, to source: URL) throws -> URL {
        try Data(repeating: 7, count: bytes).write(to: source)
        return source
    }

    @Test func aVersionNamesTheKeptFileAndKeepsItsExtension() {
        #expect(answerFileLimit == 500 * 1024 * 1024)
        #expect(ThumbCache.limit == 200 * 1024 * 1024)
        let withV = FileCache.name(file: "file-1", version: "v9", ext: "png")
        #expect(withV.hasSuffix(".png"))
        #expect(withV == FileCache.name(file: "file-1", version: "v9", ext: "png"))
        #expect(withV != FileCache.name(file: "file-1", version: "v10", ext: "png"))
        #expect(withV != FileCache.name(file: "file-2", version: "v9", ext: "png"))
        #expect(!withV.contains("file-1") && !withV.contains("v9"))
        #expect(FileCache.safeExt("报告.PNG") == "png")
        #expect(FileCache.safeExt("没有扩展名") == "bin")
        #expect(FileCache.safeExt("末尾是点.") == "bin")
        #expect(FileCache.safeExt("a.verylongextension") == "bin")
    }

    @Test func anOlderComputerVersionsBySizeAndTimeAndKeepsNothingWithoutThem() {
        #expect(fileVersion(version: "v1", size: 10, modified: 20) == "v1")
        #expect(fileVersion(version: "", size: 10, modified: 20) == "s10-m20")
        #expect(fileVersion(version: "", size: 0, modified: 20) == nil)
        #expect(fileVersion(version: "", size: 10, modified: 0) == nil)
        #expect(fileVersion(version: "", size: 0, modified: 0) == nil)
        // A FileRef uses the same rule, with `v`, size and `modified` from the computer.
        let file = FileRef(id: "f", name: "图.png", size: 10, modified: 20)
        #expect(file.stableVersion == "s10-m20")
        #expect(FileRef(id: "f", name: "图.png").stableVersion == nil)
    }

    @Test func aKeptFileIsByComputerAndVersionUnderItsOwnExtension() throws {
        let dir = tempFolder()
        defer { try? FileManager.default.removeItem(at: dir) }
        let cache = FileCache(root: dir, maxBytes: 1_000)
        let source = try write(60, to: dir.appendingPathComponent("download"))
        let kept = try #require(cache.keep(fileAt: source, computer: "pc-a", file: "file-1", version: "v1", ext: "png"))
        #expect(kept.pathExtension == "png")
        #expect(kept.deletingLastPathComponent().lastPathComponent == "pc-a")
        #expect(cache.read(computer: "pc-a", file: "file-1", version: "v1", ext: "png") == kept)
        #expect(cache.read(computer: "pc-b", file: "file-1", version: "v1", ext: "png") == nil)
        #expect(cache.read(computer: "pc-a", file: "file-1", version: "v2", ext: "png") == nil)
        // The fetched file was moved, and no temporary name is left.
        #expect(!FileManager.default.fileExists(atPath: source.path))
        let all = FileManager.default.enumerator(at: dir, includingPropertiesForKeys: nil)?.allObjects ?? []
        let names = (all as? [URL] ?? []).map(\.lastPathComponent)
        #expect(!names.contains { $0.hasSuffix(".part") })
    }

    @Test func pastTheLimitTheLeastRecentlyUsedGo() throws {
        let dir = tempFolder()
        defer { try? FileManager.default.removeItem(at: dir) }
        let cache = FileCache(root: dir, maxBytes: 100)
        let oldSource = try write(60, to: dir.appendingPathComponent("old"))
        #expect(cache.keep(fileAt: oldSource, computer: "pc", file: "old", version: "v1", ext: "png") != nil)
        let old = cache.entry(computer: "pc", file: "old", version: "v1", ext: "png")
        try? FileManager.default.setAttributes([.modificationDate: Date(timeIntervalSince1970: 1_000)], ofItemAtPath: old.path)
        let newSource = try write(60, to: dir.appendingPathComponent("new"))
        #expect(cache.keep(fileAt: newSource, computer: "pc", file: "new", version: "v1", ext: "png") != nil)
        let fresh = cache.entry(computer: "pc", file: "new", version: "v1", ext: "png")
        #expect(cache.totalBytes() <= 100)
        #expect(!FileManager.default.fileExists(atPath: old.path))
        #expect(FileManager.default.fileExists(atPath: fresh.path))
        #expect(cache.read(computer: "pc", file: "new", version: "v1", ext: "png") != nil)
        let touched = (try? FileManager.default.attributesOfItem(atPath: fresh.path))?[.modificationDate] as? Date
        #expect((touched ?? .distantPast) > Date(timeIntervalSince1970: 1_000))
    }

    @Test func clearingOneComputerLeavesTheOthersAndTheThumbsUntouched() throws {
        let root = tempFolder()
        defer { try? FileManager.default.removeItem(at: root) }
        let thumbs = ThumbCache(folder: root.appendingPathComponent(ThumbCache.folderName))
        let files = FileCache(root: root.appendingPathComponent(answerFileFolderName))
        #expect(thumbs.keep(Data(repeating: 1, count: 60), computer: "pc-a", file: "f", version: "v", width: 320) != nil)
        #expect(thumbs.keep(Data(repeating: 1, count: 60), computer: "pc-b", file: "f", version: "v", width: 320) != nil)
        let a = try write(20, to: root.appendingPathComponent("a.bin"))
        let b = try write(20, to: root.appendingPathComponent("b.bin"))
        #expect(files.keep(fileAt: a, computer: "pc-a", file: "f", version: "v", ext: "bin") != nil)
        #expect(files.keep(fileAt: b, computer: "pc-b", file: "f", version: "v", ext: "bin") != nil)

        AnswerCaches.clearComputer(caches: root, computer: "pc-a")
        #expect(thumbs.read(computer: "pc-a", file: "f", version: "v", width: 320) == nil)
        #expect(files.read(computer: "pc-a", file: "f", version: "v", ext: "bin") == nil)
        #expect(thumbs.read(computer: "pc-b", file: "f", version: "v", width: 320) != nil)
        #expect(files.read(computer: "pc-b", file: "f", version: "v", ext: "bin") != nil)

        AnswerCaches.clearAll(caches: root)
        #expect(thumbs.read(computer: "pc-b", file: "f", version: "v", width: 320) == nil)
        #expect(files.read(computer: "pc-b", file: "f", version: "v", ext: "bin") == nil)
    }
}
