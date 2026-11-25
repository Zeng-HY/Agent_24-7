import ActivityKit
import TeleplyIsland

/// One island's fixed part (handoff 5.2): set when the island starts, never changed after.
///
/// Both the app and the extension compile this file, so the type and its name are the same on both sides; a push
/// that starts an island remotely names it as `IslandAttributes`, exactly as this type is spelt.
///
/// `nonisolated` on purpose: the targets default to the main actor, and ActivityKit decodes the push's JSON off it
/// (the same reason ProcessGroup and TimelineRole are written this way).
nonisolated struct IslandAttributes: ActivityAttributes {
    /// The computer's 32-hex id.
    var device: String
    /// codex | claude | deepseek, or a new assistant's id.
    var app: String
    /// The conversation's id.
    var chat: String
    /// The computer's name; empty title falls back to "Claude · 我的电脑".
    var computer: String
    /// The conversation's title, written by the phone only.
    var title: String
    /// A new assistant's own name, colour and mark (handoff 3.5): optional, so a push from a relay that sends none —
    /// and every island of the three — decodes and draws exactly as before.
    var sourceName: String?
    var tint: String?
    var markKey: String?
    typealias ContentState = IslandState

    init(device: String, app: String, chat: String, computer: String, title: String,
         sourceName: String? = nil, tint: String? = nil, markKey: String? = nil) {
        self.device = device
        self.app = app
        self.chat = chat
        self.computer = computer
        self.title = title
        self.sourceName = sourceName
        self.tint = tint
        self.markKey = markKey
    }

    init(_ identity: IslandIdentity) {
        self.init(device: identity.device, app: identity.app, chat: identity.chat,
                  computer: identity.computer, title: identity.title,
                  sourceName: identity.sourceName, tint: identity.tint, markKey: identity.markKey)
    }

    var identity: IslandIdentity {
        IslandIdentity(device: device, app: app, chat: chat, computer: computer, title: title,
                       sourceName: sourceName, tint: tint, markKey: markKey)
    }
}
