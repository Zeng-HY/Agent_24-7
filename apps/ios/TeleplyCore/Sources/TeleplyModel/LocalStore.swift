import Foundation

/// Where the app stood last (Android Preferences): the service, the sign-in scope, the computer, the
/// conversation and its title, the source in use, and the appearance.
public struct Place: Codable, Sendable, Equatable {
    public var origin = ""
    public var theme = "system"
    public var scope = ""
    public var device = ""
    public var chat = ""
    public var title = ""
    public var app = "codex"

    public init() {}
}

/// One conversation's records (Android Room tables chat_draft, reading_position, interaction_draft), keyed by
/// sign-in scope, computer, source and conversation (spec B01). Message text is never kept.
public struct ChatRecord: Codable, Sendable, Equatable {
    public struct Position: Codable, Sendable, Equatable {
        public var message: String
        public var offset: Int

        public init(message: String, offset: Int) {
            self.message = message
            self.offset = offset
        }
    }

    public var version = 1
    public var draft = ""
    public var position: Position?
    /// JSON values by kind (Android interaction_draft): sources, new_jobs, claude_catalog, workspace…
    public var details: [String: String] = [:]

    public init() {}
}

/// What this phone keeps, as small JSON files in one folder the app keeps out of backups (Android disables
/// backup too). Each file is written whole and atomically, so a crash never leaves half of one; a file that
/// cannot be read is moved aside, not overwritten (plan: 手机上的记录).
public actor LocalStore {
    private let folder: URL
    private var cache: [String: ChatRecord] = [:]

    public init(folder: URL) {
        self.folder = folder
    }

    // MARK: Where the app stood

    public func place() -> Place {
        read(Place.self, at: url("place.json")) ?? Place()
    }

    public func savePlace(_ place: Place) {
        write(place, to: url("place.json"))
    }

    /// Another service starts with no place: the saved computer and conversation belong to the old one.
    public func setOrigin(_ origin: String) {
        var place = place()
        place.origin = origin
        place.scope = ""
        place.device = ""
        place.chat = ""
        place.title = ""
        place.app = "codex"
        savePlace(place)
    }

    public func setSelection(scope: String, device: String, chat: String = "", title: String = "") {
        var place = place()
        place.scope = scope
        place.device = device
        place.chat = chat
        place.title = title
        savePlace(place)
    }

    public func setSource(_ app: String) {
        var place = place()
        place.app = app
        place.chat = ""
        place.title = ""
        savePlace(place)
    }

    public func setTheme(_ theme: String) {
        var place = place()
        place.theme = theme
        savePlace(place)
    }

    // MARK: One conversation's records

    public func record(scope: String, device: String, app: String, chat: String) -> ChatRecord {
        let key = Self.recordName(scope: scope, device: device, app: app, chat: chat)
        if let kept = cache[key] { return kept }
        let found = read(ChatRecord.self, at: url("chats/\(key).json")) ?? ChatRecord()
        cache[key] = found
        return found
    }

    public func update(scope: String, device: String, app: String, chat: String, _ change: @Sendable (inout ChatRecord) -> Void) {
        let key = Self.recordName(scope: scope, device: device, app: app, chat: chat)
        var record = record(scope: scope, device: device, app: app, chat: chat)
        change(&record)
        cache[key] = record
        write(record, to: url("chats/\(key).json"))
    }

    public func detail(scope: String, device: String, app: String, chat: String, kind: String) -> String? {
        record(scope: scope, device: device, app: app, chat: chat).details[kind]
    }

    public func setDetail(scope: String, device: String, app: String, chat: String, kind: String, value: String?) {
        update(scope: scope, device: device, app: app, chat: chat) { $0.details[kind] = value }
    }

    /// File names from the key (ids like "new:…" carry colons and slashes): base64url of the four parts.
    static func recordName(scope: String, device: String, app: String, chat: String) -> String {
        Data([scope, device, app, chat].joined(separator: "\n").utf8).base64EncodedString()
            .replacingOccurrences(of: "+", with: "-").replacingOccurrences(of: "/", with: "_").replacingOccurrences(of: "=", with: "")
    }

    // MARK: Files

    private func url(_ name: String) -> URL {
        folder.appendingPathComponent(name)
    }

    private func read<T: Decodable>(_ type: T.Type, at file: URL) -> T? {
        guard let data = try? Data(contentsOf: file) else { return nil }
        if let value = try? JSONDecoder().decode(type, from: data) { return value }
        let aside = file.deletingPathExtension().appendingPathExtension("unreadable-\(Int(Date().timeIntervalSince1970)).json")
        try? FileManager.default.moveItem(at: file, to: aside)
        return nil
    }

    private func write<T: Encodable>(_ value: T, to file: URL) {
        do {
            try FileManager.default.createDirectory(at: file.deletingLastPathComponent(), withIntermediateDirectories: true)
            let encoder = JSONEncoder()
            encoder.outputFormatting = [.sortedKeys]
            try encoder.encode(value).write(to: file, options: .atomic)
        } catch {
            // Keeping going is better than stopping the app over a record; the next write tries again.
        }
    }
}
