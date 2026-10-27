import Foundation
import TeleplyModel

/// Reading one conversation (spec 4.3; Android ReaderViewModel readChat, older, search, anchors).
extension AppModel {
    /// Opens a row: the list and the sidebar mix sources, so opening another source's row switches source.
    public func open(_ chat: Chat) {
        // Opened from the list: a job that made it is done with (web route).
        if let made = jobs.jobs.first(where: { job in
            job.accepted && job.createdID == chat.id && (job.pending["app"].string().isEmpty ? job.app : job.pending["app"].string()) == chat.app
        }) {
            jobs.drop(made)
        }
        operation { [weak self] g in
            guard let self else { return }
            await self.useSource(chat.app)
            try await self.readChat(g, chat, restorePosition: true)
        }
    }

    /// 打开新建对话 under a Codex reply that made a conversation (web remote.html: the conversation is read first, and
    /// only then opened; it may not be in the list yet). Read failing, this page stays and says why.
    public func openCreated(_ id: String) {
        operation { [weak self] g in
            guard let self, let device = self.device else { return }
            do {
                _ = try await self.client.history(device: device.id, app: "codex", chat: id, around: nil)
            } catch let failure as ServiceFailure where failure.status == 401 {
                throw failure
            } catch is CancellationError {
                throw CancellationError()
            } catch {
                throw ReadFailure("暂时无法打开这个对话：" + describe(error))
            }
            guard self.current(g) else { return }
            var chat = Chat(id: id, title: "新建对话")
            chat.app = "codex"
            await self.useSource(chat.app)
            try await self.readChat(g, chat, restorePosition: true)
        }
    }

    /// Points reading at [app] when it changes (the list's rows carry their own source).
    func useSource(_ source: String) async {
        guard !source.isEmpty, source != app, sourceOrder.contains(source) else { return }
        app = source
        clearReading()
        if !fixture { await services.store.setSource(source) }
    }

    func readChat(_ g: Int, _ chat: Chat, restorePosition: Bool) async throws {
        guard let device else { return }
        let same = self.chat?.id == chat.id
        screen = .reading
        self.chat = chat
        if let handoff, handoff.id != chat.id || handoff.app != app { self.handoff = nil }
        if !same {
            messages = []
            wholeMessages = [:]
            cursor = nil
            olderAvailable = false
            newerAvailable = false
            anchor = nil
            pageMeta = [:]
        }
        hits = []
        searched = false
        searchQuery = ""
        let key = ChatKey(scope: scope, device: device.id, app: app, chat: chat.id)
        let position = restorePosition ? await savedPosition(key) : nil
        let page = try await client.history(device: device.id, app: app, chat: chat.id, around: position?.message)
        guard current(g) else { return }
        messages = keepWhole(page.items, wholeMessages)
        cursor = page.cursor
        olderAvailable = page.hasMore
        newerAvailable = page.hasNewer
        anchor = position
        scrollRevision += 1
        pageMeta = page.meta
        if let title = Self.pageTitle(page.meta) { self.chat?.title = title }
        await persistSelection(scope: scope, device: device.id, chat: chat.id, title: self.chat?.title ?? chat.title)
    }

    /// The service's own title for an opened conversation, when it gives one.
    static func pageTitle(_ meta: JSONValue) -> String? {
        let title = meta["title"].string()
        return title.isEmpty ? nil : title
    }

    func savedPosition(_ key: ChatKey) async -> ChatRecord.Position? {
        if fixture { return demoPositions[key] }
        return await services.store.record(scope: key.scope, device: key.device, app: key.app, chat: key.chat).position
    }

    /// 加载更早消息.
    public func older() {
        operation { [weak self] g in
            guard let self, let cursor = self.cursor, let device = self.device, let chat = self.chat else { return }
            let page = try await self.client.history(device: device.id, app: self.app, chat: chat.id, before: cursor)
            guard self.current(g) else { return }
            if page.reset {
                self.error = "历史位置已变化，请回到最新消息后重试。"
                return
            }
            self.messages = keepWhole(mergeMessages(self.messages, page.items, prepend: true), self.wholeMessages)
            self.cursor = page.cursor
            self.olderAvailable = page.hasMore
        }
    }

    /// 回到最新.
    public func latest() {
        operation { [weak self] g in
            guard let self, let chat = self.chat else { return }
            try await self.readChat(g, chat, restorePosition: false)
        }
    }

    /// 展开全文: the whole of a message the page cut short, kept whole when the page is read again.
    public func expand(_ message: Message) {
        operation { [weak self] g in
            guard let self, let device = self.device, let chat = self.chat else { return }
            let full = try await self.client.message(device: device.id, app: self.app, chat: chat.id, message: message.id)
            guard self.current(g) else { return }
            self.wholeMessages[full.id] = full
            self.messages = keepWhole(self.messages, self.wholeMessages)
        }
    }

    /// 复制 · 选择文字 · 分享 of a message: its whole words, read from the computer first when the page cut it short
    /// (web reading-ui.js fullText). [use] runs only when nothing newer was asked meanwhile.
    public func whole(_ message: Message, _ use: @escaping (Message) -> Void) {
        guard message.truncated else { return use(message) }
        operation { [weak self] g in
            guard let self, let device = self.device, let chat = self.chat else { return }
            let full = try await self.client.message(device: device.id, app: self.app, chat: chat.id, message: message.id)
            guard self.current(g) else { return }
            use(full)
        }
    }

    /// 查找消息 inside the open conversation.
    public func searchHistory(_ words: String, more: Bool = false) {
        operation { [weak self] g in
            guard let self, let device = self.device, let chat = self.chat else { return }
            let words = words.trimmingCharacters(in: .whitespacesAndNewlines)
            guard !words.isEmpty else { throw ReadFailure("请输入要查找的内容。") }
            if !more {
                self.hits = []
                self.hitCursor = nil
                self.hitMore = false
                self.searched = false
                self.searchQuery = words
            }
            let page = try await self.client.search(device: device.id, app: self.app, chat: chat.id, query: words, cursor: more ? self.hitCursor : nil)
            guard self.current(g) else { return }
            var seen = Set<String>()
            self.hits = ((more ? self.hits : []) + page.items).filter { seen.insert($0.id).inserted }
            self.hitCursor = page.cursor
            self.hitMore = page.hasMore
            self.searched = true
        }
    }

    /// Opens the conversation around a found message.
    public func jump(to message: Message) {
        operation { [weak self] g in
            guard let self, let device = self.device, let chat = self.chat else { return }
            let page = try await self.client.history(device: device.id, app: self.app, chat: chat.id, around: message.id)
            guard self.current(g) else { return }
            self.messages = keepWhole(page.items, self.wholeMessages)
            self.cursor = page.cursor
            self.olderAvailable = page.hasMore
            self.newerAvailable = page.hasNewer
            self.anchor = ChatRecord.Position(message: message.id, offset: 0)
            self.scrollRevision += 1
            self.hits = []
            self.searched = false
            self.pageMeta = page.meta
        }
    }

    /// The reading position, kept 400 ms after scrolling stops and when leaving (Android saveAnchor). Only for
    /// the conversation it was taken in.
    public func saveAnchor(message: String, offset: Int) {
        guard let device, let chat, !scope.isEmpty, messages.contains(where: { $0.id == message }) else { return }
        let key = ChatKey(scope: scope, device: device.id, app: app, chat: chat.id)
        let position = ChatRecord.Position(message: message, offset: offset)
        anchor = position
        if fixture {
            demoPositions[key] = position
        } else {
            Task { await services.store.update(scope: key.scope, device: key.device, app: key.app, chat: key.chat) { $0.position = position } }
        }
    }

    /// A live frame for the conversation on screen merges in; a frame for another one is dropped.
    func apply(_ frame: LiveFrame, for key: ChatKey) {
        guard screen == .reading, app == key.app, scope == key.scope, device?.id == key.device, chat?.id == key.chat else { return }
        messages = keepWhole(mergeLive(messages, frame.messages), wholeMessages)
    }
}
