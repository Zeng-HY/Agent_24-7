import Foundation
import TeleplyModel

/// The bar under the list after a swipe (web .undo-bar): 对话已归档 with 撤销; [waiting] while Claude still reads it
/// back from its desktop. [serial] tells one archive's bar from the next.
public struct ArchiveUndo: Equatable, Sendable {
    public var chat: Chat
    public var index: Int
    public var waiting: Bool
    public var serial: Int
}

/// 左滑归档, 撤销 and 已归档对话 (spec 4.1, 4.6; web archive-ui.js; Android ReaderViewModel): the archive is made on
/// the computer; the row leaves the list at once and comes back if the computer says no.
extension AppModel {
    /// Archives [chat] on the computer. A running conversation is refused here, as the computer would.
    public func archive(_ chat: Chat) {
        guard let device, !chat.group, chat.kind.isEmpty, sourceOrder.contains(chat.app) else { return }
        if chat.status == "running" {
            notice = "这个对话正在运行，先停止这一轮再归档"
            return
        }
        let key = rowKey(chat)
        let index = max(0, chats.firstIndex { rowKey($0) == key } ?? 0)
        undoSerial += 1
        let serial = undoSerial
        hidden.insert(key)
        chats.removeAll { rowKey($0) == key }
        undo = ArchiveUndo(chat: chat, index: index, waiting: chat.app == "claude", serial: serial)
        let client = client
        archiving[key] = Task { [weak self] in
            do {
                _ = try await client.detail(device: device.id, route: "chat/archive", body: ["app": .string(chat.app), "id": .string(chat.id)])
                guard let self else { return true }
                if self.undo?.serial == serial { self.undo?.waiting = false }
                self.loadTree(force: true)
                self.archiving[key] = nil
                return true
            } catch {
                guard let self else { return false }
                self.comeBack(chat, at: index)
                if self.undo?.serial == serial { self.undo = nil }
                self.notice = (chat.app == "claude" ? "Claude：" : "没归档：") + describe(error)
                self.archiving[key] = nil
                return false
            }
        }
    }

    func comeBack(_ chat: Chat, at index: Int) {
        let key = rowKey(chat)
        hidden.remove(key)
        guard !chats.contains(where: { rowKey($0) == key }) else { return }
        chats.insert(chat, at: min(max(0, index), chats.count))
    }

    /// 撤销: back on the list at once, then restored on the computer once its archive is done.
    public func undoArchive() {
        guard let undo, !undo.waiting, let device else { return }
        self.undo = nil
        comeBack(undo.chat, at: undo.index)
        let key = rowKey(undo.chat)
        let pending = archiving[key]
        let client = client
        Task { [weak self] in
            if let pending, await pending.value == false { return }
            do {
                _ = try await client.detail(device: device.id, route: "chat/unarchive", body: ["app": .string(undo.chat.app), "id": .string(undo.chat.id)])
                self?.loadTree(force: true)
                self?.notice = "已恢复"
            } catch {
                guard let self else { return }
                self.hidden.insert(key)
                self.chats.removeAll { rowKey($0) == key }
                self.notice = (undo.chat.app == "claude" ? "Claude：" : "没恢复：") + describe(error)
            }
        }
    }

    /// The bar's six seconds are up (not while Claude still reads the archive back).
    public func dropUndo(_ serial: Int) {
        if let undo, undo.serial == serial, !undo.waiting { self.undo = nil }
    }

    /// A conversation restored from 已归档对话: back on the list.
    public func restored(app: String, id: String) {
        hidden.remove(app + ":" + id)
        loadTree(force: true)
        if screen == .chats { searchChats(query) }
    }

    /// The computer's voice service (web voice-ui.js): audio up, words back.
    public func voiceCall(_ route: String, query: [(String, String?)] = [], audio: Data = Data(), type: String = "application/octet-stream") async throws -> JSONValue {
        guard let device else { throw ReadFailure("先选择一台电脑") }
        return try await client.voice(device: device.id, route: route, query: query, audio: audio, type: type)
    }

    /// Whether this computer has its voice service on (web window.MACHINE.voice); asked once per computer. Only a
    /// 404 means off; another failure is not taken as an answer.
    public func voiceAvailable() async -> Bool {
        guard let id = device?.id else { return false }
        if let known = voiceOn[id] { return known }
        do {
            _ = try await deviceCall("voice/status")
            voiceOn[id] = true
            return true
        } catch let failure as ServiceFailure where failure.status == 404 {
            voiceOn[id] = false
            return false
        } catch {
            return true
        }
    }

    /// A request to the computer in use from a settings page: archived conversations, notifications, voice.
    public func deviceCall(_ route: String, query: [(String, String?)] = [], body: JSONValue? = nil) async throws -> JSONValue {
        guard let device else { throw ReadFailure("先选择一台电脑") }
        return try await client.detail(device: device.id, route: route, query: query, body: body)
    }
}
