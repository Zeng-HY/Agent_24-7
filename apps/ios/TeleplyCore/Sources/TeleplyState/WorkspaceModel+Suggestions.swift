import Foundation
import TeleplyModel

/// The box's / and $ lists of one conversation (0.6.6, user 10-31: "输入斜杠或者是美元符号的时候，能相应地弹出列表").
public struct ComposerLists: Equatable, Sendable {
    public var key: ChatKey?
    /// Every command the computer offers for this conversation (composer/commands); nil until read.
    public var commands: [JSONValue]?
    /// The skills that fit [skillQuery] (composer/references, kind skill); nil until read.
    public var skills: [JSONValue]?
    public var skillQuery = ""
    public var busy: Set<ComposerTrigger.Kind> = []
    public var failed: String?

    public init(key: ChatKey? = nil) {
        self.key = key
    }
}

extension WorkspaceModel {
    /// What the box asks for now. The commands are read once per conversation and kept (they change only with the
    /// source); the skills are asked for again as the words after $ change, as the 引用技能 search does.
    public func suggest(_ trigger: ComposerTrigger?) {
        guard let trigger, let key, let client, ready, !isNewPage(key.chat) else { return }
        if suggestions.key != key {
            for read in suggestionReads.values { read.cancel() }
            suggestionReads = [:]
            suggestions = ComposerLists(key: key)
        }
        switch trigger.kind {
        case .command:
            guard suggestions.commands == nil, suggestionReads[.command] == nil else { return }
            suggestions.busy.insert(.command)
            suggestions.failed = nil
            suggestionReads[.command] = Task { [weak self] in
                let value = try? await client.detail(device: key.device, route: "composer/commands",
                                                     query: [("app", key.app), ("id", key.chat)])
                guard let self, self.suggestions.key == key else { return }
                self.suggestionReads[.command] = nil
                self.suggestions.busy.remove(.command)
                if let value {
                    self.suggestions.commands = value["items"].array
                } else {
                    self.suggestions.failed = "读不到命令列表，请稍后再输入 / 试一次。"
                }
            }
        case .skill:
            // DeepSeek takes no skills (composer_references refuses them), so $ is only a character there.
            guard key.app != "deepseek", suggestions.skills == nil || suggestions.skillQuery != trigger.query else { return }
            suggestionReads[.skill]?.cancel()
            suggestions.busy.insert(.skill)
            suggestions.failed = nil
            let query = trigger.query
            let folder = current(key)["folder"].string()
            suggestionReads[.skill] = Task { [weak self] in
                let paging: [(String, String?)] = [("app", key.app), ("id", key.chat), ("kind", "skill"), ("query", query),
                                                   ("offset", "0"), ("fresh", "0"), ("scan_id", ""),
                                                   ("projectless", folder.isEmpty ? "1" : "0"), ("folder", folder)]
                let value = try? await client.detail(device: key.device, route: "composer/references", query: paging)
                guard let self, !Task.isCancelled, self.suggestions.key == key else { return }
                self.suggestionReads[.skill] = nil
                self.suggestions.busy.remove(.skill)
                if let value {
                    self.suggestions.skills = value["items"].array
                    self.suggestions.skillQuery = query
                } else {
                    self.suggestions.failed = "读不到技能列表，请稍后再输入 $ 试一次。"
                }
            }
        }
    }
}
