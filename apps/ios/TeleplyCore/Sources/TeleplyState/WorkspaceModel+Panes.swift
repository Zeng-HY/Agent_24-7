import Foundation
import TeleplyModel

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
                    value = try await client.detail(device: key.device, route: "chat/files", query: ids)
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
                guard let self, g == self.paneGeneration, self.pane == name else { return }
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
