import Foundation

/// Where the app stood last (Android Preferences): the service, the sign-in scope, the computer, the
/// conversation and its title, the source in use, and the appearance.
public struct Place: Codable, Sendable, Equatable {
    /// "" for Teleply's own service, whatever its address is now.
    public var origin = ""
    public var theme = "system"
    public var scope = ""
    public var device = ""
    public var chat = ""
    public var title = ""
    public var app = "codex"
    /// The default service's move from its IP to its domain was done on this phone (AppModel.moveToDomain), so an
    /// address set by hand afterwards, the IP included, stays.
    public var movedToDomain = false

    public init() {}

    /// Fields missing from an older file take their defaults instead of making the file unreadable.
    public init(from decoder: any Decoder) throws {
        let fields = try decoder.container(keyedBy: CodingKeys.self)
        origin = try fields.decodeIfPresent(String.self, forKey: .origin) ?? ""
        theme = try fields.decodeIfPresent(String.self, forKey: .theme) ?? "system"
        scope = try fields.decodeIfPresent(String.self, forKey: .scope) ?? ""
        device = try fields.decodeIfPresent(String.self, forKey: .device) ?? ""
        chat = try fields.decodeIfPresent(String.self, forKey: .chat) ?? ""
        title = try fields.decodeIfPresent(String.self, forKey: .title) ?? ""
        app = try fields.decodeIfPresent(String.self, forKey: .app) ?? "codex"
        movedToDomain = try fields.decodeIfPresent(Bool.self, forKey: .movedToDomain) ?? false
    }
}

/// A send's local copy (Android chat_submission): kept before the request goes out, then changed only by what
/// receipts and the source's record show; never posted again by itself (spec B03, B04). [body] is the request as
/// JSON text, with the phone's own notes (_claude_offset …) that never go out. [created] is milliseconds.
public struct Submission: Codable, Sendable, Equatable, Identifiable {
    public var request: String
    public var scope: String
    public var device: String
    public var app: String
    public var chat: String
    public var text: String
    public var action: String
    public var turn: String
    public var body: String
    public var label: String
    public var created: Int64

    public var id: String { request }
    public var key: ChatKey { ChatKey(scope: scope, device: device, app: app, chat: chat) }

    public init(request: String, key: ChatKey, text: String, action: String, turn: String, body: String,
                label: String = "提交中", created: Int64) {
        self.request = request
        scope = key.scope
        device = key.device
        app = key.app
        chat = key.chat
        self.text = text
        self.action = action
        self.turn = turn
        self.body = body
        self.label = label
        self.created = created
    }
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
    /// Where reading stopped, as builds before 10-27 kept it. Every conversation now opens at its latest messages,
    /// so nothing writes or reads it; it stays so those files still read.
    public var position: Position?
    /// JSON values by kind (Android interaction_draft): sources, new_jobs, claude_catalog, workspace…
    public var details: [String: String] = [:]
    /// Sends of this conversation, newest first; the oldest go once there are more than [submissionLimit].
    public var submissions: [Submission] = []

    public static let submissionLimit = 100

    public init() {}

    /// Fields missing from an older file take their defaults instead of making the file unreadable.
    public init(from decoder: any Decoder) throws {
        let fields = try decoder.container(keyedBy: CodingKeys.self)
        version = try fields.decodeIfPresent(Int.self, forKey: .version) ?? 1
        draft = try fields.decodeIfPresent(String.self, forKey: .draft) ?? ""
        position = try fields.decodeIfPresent(Position.self, forKey: .position)
        details = try fields.decodeIfPresent([String: String].self, forKey: .details) ?? [:]
        submissions = try fields.decodeIfPresent([Submission].self, forKey: .submissions) ?? []
    }
}

/// What this phone keeps, as small JSON files in one folder the app keeps out of backups (Android disables
/// backup too). Each file is written whole and atomically, so a crash never leaves half of one; a file that
/// cannot be read is moved aside, not overwritten (plan: 手机上的记录).
public actor LocalStore {
    private let folder: URL
    private var cache: [String: ChatRecord] = [:]
    /// Sign-ins whose records were deleted in this run of the app (删除账号): a write that comes late for one (a draft
    /// typed a moment before, a send's receipt, a new conversation's job) is dropped, so nothing of it comes back.
    private var forgotten: Set<String> = []

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

    /// The move to the domain is done (AppModel.moveToDomain): [origin] is the address from now on, "" for the
    /// default. Unlike another service, the place stays: the same accounts and computers answer on both addresses.
    public func setMovedToDomain(origin: String) {
        var place = place()
        place.origin = origin
        place.movedToDomain = true
        savePlace(place)
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
        guard !forgotten.contains(scope) else { return }
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

    /// 删除账号: every record of one sign-in leaves this phone — drafts, sends, and each conversation's details (the
    /// computers' cached sources and lists, settings, new conversations under way), those moved aside as unreadable
    /// too — and later writes for it are dropped. Other sign-ins' records stay.
    public func forget(scope: String) {
        guard !scope.isEmpty else { return }
        forgotten.insert(scope)
        cache = cache.filter { Self.recordParts($0.key)?.first != scope }
        guard let names = try? FileManager.default.contentsOfDirectory(atPath: url("chats").path) else { return }
        // A record moved aside carries a second extension after its name.
        for name in names where Self.recordParts(String(name.prefix { $0 != "." }))?.first == scope {
            try? FileManager.default.removeItem(at: url("chats/" + name))
        }
    }

    // MARK: Drafts and sends (spec B01, B03, B10)

    public func draft(_ key: ChatKey) -> String {
        record(scope: key.scope, device: key.device, app: key.app, chat: key.chat).draft
    }

    public func setDraft(_ key: ChatKey, _ text: String) {
        update(scope: key.scope, device: key.device, app: key.app, chat: key.chat) { $0.draft = text }
    }

    /// The unsent words of every conversation of one sign-in and computer (the list's 草稿). Records not open
    /// already are read without being kept in memory.
    public func drafts(scope: String, device: String) -> [ChatKey: String] {
        guard let names = try? FileManager.default.contentsOfDirectory(atPath: url("chats").path) else { return [:] }
        var found: [ChatKey: String] = [:]
        for name in names where name.hasSuffix(".json") {
            let stem = String(name.dropLast(5))
            // A record moved aside as unreadable carries a second extension.
            guard !stem.contains("."), let parts = Self.recordParts(stem), parts.count == 4, parts[0] == scope, parts[1] == device else { continue }
            let draft = (cache[stem] ?? read(ChatRecord.self, at: url("chats/\(name)")))?.draft ?? ""
            if !draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                found[ChatKey(scope: scope, device: device, app: parts[2], chat: parts[3])] = draft
            }
        }
        return found
    }

    public func submissions(_ key: ChatKey) -> [Submission] {
        record(scope: key.scope, device: key.device, app: key.app, chat: key.chat).submissions
    }

    /// The local copy of a send that is about to go out, and the draft it came from cleared, in one write
    /// (Android ReadingDao.begin).
    public func begin(_ submission: Submission) {
        update(scope: submission.scope, device: submission.device, app: submission.app, chat: submission.chat) { record in
            Self.put(submission, into: &record)
            if submission.action == "send" { record.draft = "" }
        }
    }

    /// A send's new label (or notes), in place of its earlier copy.
    public func saveSubmission(_ submission: Submission) {
        update(scope: submission.scope, device: submission.device, app: submission.app, chat: submission.chat) { record in
            Self.put(submission, into: &record)
        }
    }

    private static func put(_ submission: Submission, into record: inout ChatRecord) {
        var rows = record.submissions.filter { $0.request != submission.request }
        rows.append(submission)
        rows.sort { $0.created > $1.created }
        record.submissions = Array(rows.prefix(ChatRecord.submissionLimit))
    }

    /// File names from the key (ids like "new:…" carry colons and slashes): base64url of the four parts.
    static func recordName(scope: String, device: String, app: String, chat: String) -> String {
        Data([scope, device, app, chat].joined(separator: "\n").utf8).base64EncodedString()
            .replacingOccurrences(of: "+", with: "-").replacingOccurrences(of: "/", with: "_").replacingOccurrences(of: "=", with: "")
    }

    /// The four parts back from a record's file name; nil for a name that is not one.
    static func recordParts(_ name: String) -> [String]? {
        var text = name.replacingOccurrences(of: "-", with: "+").replacingOccurrences(of: "_", with: "/")
        text += String(repeating: "=", count: (4 - text.count % 4) % 4)
        guard let data = Data(base64Encoded: text), let joined = String(data: data, encoding: .utf8) else { return nil }
        return joined.components(separatedBy: "\n")
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
