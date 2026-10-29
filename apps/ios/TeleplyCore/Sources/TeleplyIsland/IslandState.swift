import Foundation

/// 灵动岛的一个状态 (handoff 5.2): what the island shows, never what the conversation says.
///
/// The island's fixed part (`IslandAttributes` in Shared/IslandAttributes.swift) is set when it starts; this is the
/// part every push or the phone itself changes. Times are Unix seconds as integers, never `Date`: the system decodes
/// a push's content-state with a plain JSON decoder, which would read a `Date` as seconds since 2001.
///
/// Keys are the property names as they are (no snake_case). Every field that may be added later is optional, so a
/// push from an older relay still decodes.
public nonisolated struct IslandState: Codable, Hashable, Sendable {
    /// working | waiting | done | failed | offline | limited (IslandStatus).
    public var state: String
    /// Unix seconds: when this state began; the timer counts from here.
    public var since: Int
    /// Unix seconds: when this turn began; "用了 N 分" counts from here.
    public var turn: Int
    /// 方案二: the question's id (the computer's random id, never its words).
    public var ask: String?
    /// 方案二: permission | question.
    public var askType: String?
    /// 方案二: how many choices.
    public var choices: Int?
    /// 方案二 B: written by the phone alone; the relay never fills it.
    public var askText: String?
    /// 方案二 B: written by the phone alone.
    public var askOptions: [String]?
    /// 方案六: edit | run | search | read.
    public var step: String?
    /// 0.6.4: Unix seconds the turn ended; "用了 4 分钟" counts from turn to here, not to the clock.
    public var ended: Int?
    /// 方案七: Unix seconds the quota comes back.
    public var resets: Int?
    /// The conversations running on this computer, for the long-press list (user 10-28: every one with its model
    /// logo, title and time). The relay fills it; the phone also fills its own before the first push.
    public var peers: [IslandPeer]?
    /// 0.6.3: one island per computer. How many of its conversations are working, and how many are waiting for the
    /// user; both are nil on an island from an older relay (one per conversation).
    public var working: Int?
    public var waiting: Int?

    public init(state: String, since: Int, turn: Int, ask: String? = nil, askType: String? = nil, choices: Int? = nil,
                askText: String? = nil, askOptions: [String]? = nil, step: String? = nil, resets: Int? = nil,
                peers: [IslandPeer]? = nil, working: Int? = nil, waiting: Int? = nil, ended: Int? = nil) {
        self.state = state
        self.since = since
        self.turn = turn
        self.ask = ask
        self.askType = askType
        self.choices = choices
        self.askText = askText
        self.askOptions = askOptions
        self.step = step
        self.ended = ended
        self.resets = resets
        self.peers = peers
        self.working = working
        self.waiting = waiting
    }

    /// The usual way to make one: a known state.
    public init(status: IslandStatus, since: Int, turn: Int, ask: String? = nil, askType: String? = nil, choices: Int? = nil,
                askText: String? = nil, askOptions: [String]? = nil, step: String? = nil, resets: Int? = nil,
                peers: [IslandPeer]? = nil, working: Int? = nil, waiting: Int? = nil, ended: Int? = nil) {
        self.init(state: status.rawValue, since: since, turn: turn, ask: ask, askType: askType, choices: choices,
                  askText: askText, askOptions: askOptions, step: step, resets: resets, peers: peers,
                  working: working, waiting: waiting, ended: ended)
    }

    /// Nil for a state this build does not know (drawn as 在干活, still decoded).
    public var status: IslandStatus? { IslandStatus(rawValue: state) }
}

/// One running conversation in the long-press list. The title is what the phone or the computer calls it; the relay
/// carries it only because the user chose titles in the island (10-28).
public nonisolated struct IslandPeer: Codable, Hashable, Sendable {
    public var app: String
    public var chat: String
    public var title: String
    public var state: String
    public var since: Int
    public var turn: Int
    /// 0.6.4: what it is doing (edit | run | search | read), and when the turn ended for a finished one.
    public var step: String?
    public var ended: Int?

    public init(app: String, chat: String, title: String, state: String, since: Int, turn: Int,
                step: String? = nil, ended: Int? = nil) {
        self.app = app
        self.chat = chat
        self.title = title
        self.state = state
        self.since = since
        self.turn = turn
        self.step = step
        self.ended = ended
    }

    public var status: IslandStatus? { IslandStatus(rawValue: state) }
}

/// The states the island knows. A push naming another one still decodes; only the name is kept.
public nonisolated enum IslandStatus: String, CaseIterable, Codable, Hashable, Sendable {
    case working, waiting, done, failed, offline, limited

    public init?(_ name: String) {
        self.init(rawValue: name)
    }
}

/// The island's fixed part as both the app and the extension hold it, without ActivityKit: the app turns it into
/// `IslandAttributes` and the extension reads it back out. Every field is an id or a name the phone itself knows.
public nonisolated struct IslandIdentity: Codable, Hashable, Sendable {
    /// The computer's 32-hex id.
    public var device: String
    /// codex | claude | deepseek
    public var app: String
    /// The conversation's id.
    public var chat: String
    /// The computer's name; the phone's own list when it starts the island, the relay's `devices.label` when the
    /// relay starts a remote one (a title is then empty).
    public var computer: String
    /// The conversation's title; the phone writes it, never the relay.
    public var title: String

    public init(device: String, app: String, chat: String, computer: String, title: String) {
        self.device = device
        self.app = app
        self.chat = chat
        self.computer = computer
        self.title = title
    }
}

/// What the phone asks the relay (POST /account/push/activity), and what a push-to-start token registers.
public nonisolated struct IslandRegistration: Codable, Hashable, Sendable {
    public var op: String
    public var token: String
    public var device: String
    public var app: String
    public var chat: String
    public var environment: String
    public var state: String
    public var since: Int
    public var turn: Int
    /// The conversation's title, for the island's long-press list; empty when the phone does not know it.
    public var title: String

    public init(op: String = "register", token: String, device: String, app: String, chat: String, environment: String,
                state: String, since: Int, turn: Int, title: String = "") {
        self.op = op
        self.token = token
        self.device = device
        self.app = app
        self.chat = chat
        self.environment = environment
        self.state = state
        self.since = since
        self.turn = turn
        self.title = title
    }

    /// The island is gone (dismissed, ended, or the setting turned off): the relay forgets its token.
    public static func unregister(token: String, device: String, app: String, chat: String, environment: String) -> Self {
        Self(op: "unregister", token: token, device: device, app: app, chat: chat, environment: environment,
             state: "", since: 0, turn: 0)
    }
}

/// The push-to-start token, one per phone (POST /account/push/start-token).
public nonisolated struct IslandStartToken: Codable, Hashable, Sendable {
    public var token: String
    public var environment: String

    public init(token: String, environment: String) {
        self.token = token
        self.environment = environment
    }
}

/// One running island as the app holds it (Activity's own id, kept as a string so tests and data stay plain).
public nonisolated struct IslandRef: Hashable, Sendable, Codable {
    public var raw: String

    public init(raw: String) {
        self.raw = raw
    }
}

