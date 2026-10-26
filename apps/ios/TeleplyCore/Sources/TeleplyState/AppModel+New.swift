import Foundation
import TeleplyModel

/// A new conversation waiting for its sheet (Android NewTarget): from a project's ＋ (its folder), the list's ✎, a
/// source switch inside the sheet ([text] the words carried over, [switching] keeps the sheet up), or 恢复草稿.
public struct NewTarget: Equatable, Sendable {
    public var app: String
    public var folder: String
    public var projectless: Bool
    public var text: String
    public var switching: Bool
    public var restore: NewJob?
}

/// A conversation just made from its job: its first message shows until the record has it (web handoff).
public struct NewHandoff: Equatable, Sendable {
    public var app: String
    public var id: String
    public var text: String
}

/// New conversations (spec 4.4; Android ReaderViewModel, web new-chat-ui.js): the sheet opens at once, a first
/// message becomes a job, its page shows the message with a line saying where it stands, and the page becomes the
/// conversation when the computer made it.
extension AppModel {
    /// Opens the new-conversation sheet for [wanted] (the source in use by default); a computer without it starts
    /// in an app it has. Nothing waits here: the sheet opens with what this phone has.
    public func startNew(app wanted: String? = nil, folder: String = "", projectless: Bool = false, text: String = "",
                         switching: Bool = false, restore: NewJob? = nil) {
        let asked = wanted ?? app
        let target = newApp(asked)
        let fromReading = screen == .reading
        // From a conversation: a read of it still under way must not bring its page back over the list.
        if fromReading { cancelWork() }
        let switched = target != app && sourceOrder.contains(target)
        if switched {
            app = target
            clearReading()
        }
        let keepFolder = target == asked
        // The list's ✎ with the sheet's draft already bound: it opens in this frame.
        if !fromReading && !switched && folder.isEmpty && !projectless && text.isEmpty && restore == nil
            && workspace.ready && workspace.key?.chat == "@new" && workspace.key?.app == target {
            workspace.panel("new")
            return
        }
        if fromReading {
            screen = .chats
            clearReading()
        }
        pendingNew = NewTarget(app: target, folder: keepFolder ? folder : "", projectless: keepFolder && projectless, text: text,
                               switching: switching, restore: restore)
        let place = (scope, device?.id ?? "")
        if switched && !fixture { Task { await services.store.setSource(target) } }
        if fromReading { Task { await self.persistSelection(scope: place.0, device: place.1) } }
        live()
        applyPendingNew()
        if fromReading && chats.isEmpty { operation { [weak self] g in try await self?.loadChats(g) } }
    }

    /// Once the workspace holds the new conversation's draft for the target: the project, the carried words or the
    /// restored draft go in, and the sheet opens.
    func applyPendingNew() {
        guard pendingNew != nil else { return }
        Task { [weak self] in
            guard let self else { return }
            await self.workspace.read?.value
            guard let target = self.pendingNew, let key = self.workspace.key, key.app == target.app, key.chat == "@new", self.workspace.ready else { return }
            if let restore = target.restore { self.workspace.restoreNew(restore) }
            if !target.folder.isEmpty || target.projectless {
                self.workspace.chooseFolder(target.folder, projectless: target.projectless && target.app != "deepseek")
            }
            if !target.text.isEmpty {
                let draft = self.workspace.saved["first_message"].string()
                let kept = draft.replacingOccurrences(of: "\\s+$", with: "", options: .regularExpression)
                self.workspace.edit("first_message", .string(kept.isEmpty ? target.text : kept + "\n" + target.text))
            }
            self.workspace.panel("new")
            self.pendingNew = nil
        }
    }

    /// The sheet went away (dragged down or ✕): its draft stays.
    public func consumeNew() {
        pendingNew = nil
    }

    func jobCreated(_ job: NewJob) {
        workspace.close()
        jobs.submit(job)
        openPreview(job)
    }

    /// A row above the list, or a job's page: the conversation when ready, the sheet for a problem, else its page.
    public func openJob(_ job: NewJob) {
        if job.accepted {
            finishJob(job)
        } else if job.problem {
            jobSheet = job.request
        } else {
            openPreview(job)
        }
    }

    /// The page of a first message under way: the message, a line under it, and a box to write the next one in.
    func openPreview(_ job: NewJob) {
        operation { [weak self] g in
            guard let self else { return }
            await self.useSource(job.app)
            guard self.current(g) else { return }
            let words = oneLine(job.text, limit: 50)
            var chat = Chat(id: job.preview, title: words.isEmpty ? "新对话" : words)
            chat.folder = job.label
            chat.status = "creating"
            chat.app = job.app
            self.clearReading()
            self.chat = chat
            self.screen = .reading
        }
    }

    /// The computer made it: its page becomes the conversation, and words written there go along (web finish).
    public func finishJob(_ job: NewJob) {
        let id = job.createdID
        guard !id.isEmpty, let device else { return }
        let made = job.pending["app"].string()
        let app = made.isEmpty ? job.app : made
        let from = ChatKey(scope: scope, device: device.id, app: job.app, chat: job.preview)
        let to = ChatKey(scope: scope, device: device.id, app: app, chat: id)
        operation { [weak self] g in
            guard let self else { return }
            await self.conversation.moveDraft(from: from, to: to)
            self.jobs.drop(job)
            await self.useSource(app)
            guard self.current(g) else { return }
            self.jobSheet = nil
            self.handoff = NewHandoff(app: app, id: id, text: job.text)
            let title = job.pending["title"].string()
            let words = oneLine(job.text, limit: 50)
            var chat = Chat(id: id, title: !title.isEmpty ? title : words.isEmpty ? "新对话" : words)
            let folder = job.pending["folder"].string()
            chat.folder = folder.isEmpty ? job.label : folder
            chat.status = "running"
            chat.app = app
            try await self.readChat(g, chat, restorePosition: false)
        }
    }

    public func closeJobSheet() {
        jobSheet = nil
    }

    /// 核对结果: asks the computer where it stands now; never sends it again.
    public func checkJob(_ job: NewJob) {
        if let now = jobs.current(job.request) { jobs.check(now) }
    }

    /// 继续发送: the same request, which the computer makes only once.
    public func retryJob(_ job: NewJob) {
        if let now = jobs.current(job.request) { jobs.retry(now) }
    }

    /// 打开对话: the conversation the computer reported, even before it was confirmed (web newOpen).
    public func openJobChat(_ job: NewJob) {
        let id = job.createdID
        guard !id.isEmpty else { return }
        if job.accepted {
            finishJob(job)
            return
        }
        jobSheet = nil
        let title = job.pending["title"].string()
        let words = oneLine(job.text, limit: 50)
        var chat = Chat(id: id, title: !title.isEmpty ? title : words.isEmpty ? "新对话" : words)
        let folder = job.pending["folder"].string()
        chat.folder = folder.isEmpty ? job.label : folder
        chat.status = "idle"
        chat.app = job.app
        open(chat)
    }

    /// 移除: the phone stops following it; a conversation the computer made still shows in the list.
    public func removeJob(_ job: NewJob) {
        jobs.drop(job)
        jobSheet = nil
        if chat?.id == job.preview { back() }
    }

    /// 恢复草稿: a first message that did not go out goes back into the sheet, to change and send again.
    public func restoreJob(_ job: NewJob) {
        guard job.state == "failed" else { return }
        jobs.drop(job)
        jobSheet = nil
        if chat?.id == job.preview { back() }
        startNew(app: job.app, restore: job)
    }

    /// The jobs to show above the list: those whose page is not the one open.
    public var dockJobs: [NewJob] {
        jobs.jobs.filter { $0.preview != chat?.id }
    }
}
