import Foundation
import TeleplyModel

/// The last part of a Windows or POSIX path (a project's folder name).
func lastPathPart(_ path: String) -> String {
    path.split(whereSeparator: { $0 == "/" || $0 == "\\" }).last.map(String.init) ?? path
}

/// The panes and the new-conversation sheet (spec 4.4; Android WorkspaceController, web new-chat-ui.js).
extension WorkspaceModel {
    /// Opens a pane; the new-conversation sheet opens at once with what this phone has.
    public func panel(_ name: String) {
        paneRead?.cancel()
        paneGeneration += 1
        dropFile()
        pane = name
        data = [:]
        paneBusy = false
        paneError = nil
        if name == "new" {
            newNote = nil
            openNew()
        } else {
            refresh(name)
        }
    }

    /// Closes whichever pane is open; the drafts stay.
    public func close() {
        paneRead?.cancel()
        paneGeneration += 1
        pane = nil
        data = [:]
        paneBusy = false
        paneError = nil
        dropFile()
    }

    /// 新建对话 opens at once (0.8, web openNewSheet): the folders and models of last time are there already, the
    /// computer's folder list comes in behind and replaces them, and the draft's request id is asked for meanwhile.
    /// Models and DeepSeek's permissions are read when their menu opens. Nothing here shows a progress bar.
    func openNew() {
        guard let key, let client, key.chat == "@new" else { return }
        loadNewFolders()
        newIDRead = Task { [weak self] in _ = try? await self?.ensureNewID(key, client) }
    }

    public func loadNewFolders() {
        loadNewList("folders") { key, client in try await client.detail(device: key.device, route: "chat/folders", query: [("app", key.app)]) }
    }

    /// The models a new conversation may start on; the computer answers from what its menus showed before (cheap).
    public func loadNewModels() {
        loadNewList("models") { key, client in try await client.detail(device: key.device, route: "chat/new/options", query: [("app", key.app)]) }
    }

    public func loadNewPermissions() {
        loadNewList("permissions") { key, client in try await client.detail(device: key.device, route: "deepseek/permissions") }
    }

    func loadNewList(_ name: String, _ read: @escaping (ChatKey, RelayClient) async throws -> JSONValue) {
        guard let key, let client, key.chat == "@new", newReads[name] == nil else { return }
        let synthetic = synthetic
        newReads[name] = Task { [weak self] in
            do {
                let value = try await read(key, client)
                guard let self else { return }
                self.newReads[name] = nil
                guard self.key == key else { return }
                var next = (self.lists[key] ?? [:]).object
                next[name] = value
                self.lists[key] = .object(next)
                self.newData = .object(next)
                if name == "folders" { self.newNote = nil }
                if !synthetic {
                    await self.store?.setDetail(scope: key.scope, device: key.device, app: key.app, chat: key.chat, kind: "new_lists", value: jsonText(.object(next)))
                }
            } catch {
                guard let self else { return }
                self.newReads[name] = nil
                guard self.key == key, !(error is CancellationError) else { return }
                let what = name == "folders" ? "项目文件夹" : name == "models" ? "模型列表" : "权限选项"
                self.newNote = "电脑上的\(what)这次没读到：\(describe(error))，先用手机上记着的"
            }
        }
    }

    /// The draft's request id: asked once, kept with the draft until the first message goes.
    func ensureNewID(_ key: ChatKey, _ client: RelayClient) async throws -> String {
        let old = current(key)["new_id"].string()
        if !old.isEmpty { return old }
        if let asking = draftIDs[key] { return try await asking.value }
        let asking = Task { () async throws -> String in
            let reply = try await client.detail(device: key.device, route: "chat/new/draft", body: [:])
            let id = reply["request_id"].string()
            guard id.utf8.count == 32, id.utf8.allSatisfy({ (0x30...0x39).contains($0) || (0x61...0x66).contains($0) }) else {
                throw ReadFailure("电脑给的请求编号不对，请重试")
            }
            return id
        }
        draftIDs[key] = asking
        defer { draftIDs[key] = nil }
        let id = try await asking.value
        if current(key)["new_id"].string().isEmpty {
            var next = current(key).object
            next["new_id"] = .string(id)
            await persist(key, .object(next))
        }
        return current(key)["new_id"].string()
    }

    /// 创建并发送 (web new-chat-ui.js send, 10-16): the draft becomes a job of its own and the sheet starts afresh at
    /// once, keeping the source, project and picks; the job is sent and followed outside the sheet, so nothing here
    /// waits on the computer but the draft's request id.
    public func create() {
        guard let key, let client, ready, key.chat == "@new", !busy else { return }
        busy = true
        error = nil
        work = Task { [weak self] in
            guard let self else { return }
            do {
                let rid = try await self.ensureNewID(key, client)
                guard self.key == key else { throw ReadFailure("来源已切换，未提交") }
                let saved = self.current(key)
                let extras = try self.sendExtras()
                let text = saved["first_message"].string().trimmingCharacters(in: .whitespacesAndNewlines)
                let references = extras["references"]
                let images = saved["uploads"].array.filter { $0["image"].bool() && $0["meta"].isObject }.map { $0["meta"] }
                guard !text.isEmpty || !images.isEmpty || !references.array.isEmpty else { throw ReadFailure("请输入首条消息") }
                // No folder is 无项目, as the sheet shows it; DeepSeek always needs one of its workspaces.
                let folder = saved["folder"].string()
                let projectless = key.app != "deepseek" && (saved["projectless"].bool() || folder.isEmpty)
                guard !folder.isEmpty || projectless else { throw ReadFailure("DeepSeek 要选一个工作区") }
                var body: [String: JSONValue] = ["request_id": .string(rid), "app": .string(key.app), "folder": .string(projectless ? "" : folder),
                                                 "text": .string(text), "attachments": extras["attachments"], "references": references]
                if projectless { body["projectless"] = true }
                let model = saved["new_model"].string()
                if !model.isEmpty {
                    let effort = saved["new_effort"].string()
                    body["settings"] = ["model": .string(model), "effort": effort.isEmpty ? .null : .string(effort)]
                }
                if key.app == "deepseek", !saved["new_permission"].string().isEmpty {
                    body["permission"] = saved["new_permission"]
                    body["permission_confirmed"] = .bool(saved["permission_confirmed"].bool())
                }
                let name = self.newData["folders"]["items"].array.first { $0["path"].string() == folder }?["name"].string() ?? ""
                let job = NewJob(request: rid, app: key.app, folder: projectless ? "" : folder, projectless: projectless,
                                 label: projectless ? "" : (name.isEmpty ? lastPathPart(folder) : name), text: text,
                                 references: references, images: .array(images), body: .object(body),
                                 pending: ["state": "creating", "message": "正在创建对话…"], created: self.now())
                // The sheet starts afresh: same source, project and picks; the words, files and request id go with the job.
                var fresh = saved.object
                for field in ["new_id", "first_message", "uploads", "references"] { fresh[field] = nil }
                await self.persist(key, .object(fresh))
                self.busy = false
                self.created(job)
            } catch {
                if self.key == key { self.error = "还没发出，草稿还在：" + describe(error) }
            }
            if self.key == key { self.busy = false }
        }
    }

    /// 恢复草稿 (web restore): a first message that was not sent goes back into the sheet to change and send again.
    /// Its pictures went up under the old request and cannot follow; the sheet says so.
    public func restoreNew(_ job: NewJob) {
        guard let key, key.chat == "@new", key.app == job.app else { return }
        var next = current(key).object
        next["first_message"] = .string(job.text)
        next["folder"] = .string(job.folder)
        next["projectless"] = .bool(job.projectless)
        next["references"] = job.references.array.isEmpty ? [] : job.references
        next["uploads"] = []
        next["new_id"] = nil
        keep(key, .object(next))
        if !job.images.array.isEmpty { newNote = "照片没有跟着恢复，请重新添加" }
    }

    /// 项目 of a new conversation: a folder, or 无项目. Chosen skills belong to the old folder and are dropped (web).
    public func chooseFolder(_ path: String, projectless: Bool) {
        guard let key, ready, !busy else { return }
        let saved = current(key)
        if saved["folder"].string() == path && saved["projectless"].bool() == projectless { return }
        paneRead?.cancel()
        paneGeneration += 1
        var next = saved.object
        next["folder"] = .string(path)
        next["projectless"] = .bool(projectless)
        next["references"] = .array(saved["references"].array.filter { $0["kind"].string() != "skill" })
        keep(key, .object(next))
    }

    /// DeepSeek's 权限 for a new conversation; an empty option is 默认权限.
    public func setNewPermission(_ option: JSONValue) {
        guard let key, ready else { return }
        var next = current(key).object
        next["new_permission"] = .string(option["value"].string())
        next["new_permission_name"] = .string(option["name"].string())
        next["permission_confirmed"] = .bool(option["confirm"].bool())
        keep(key, .object(next))
    }

    /// A pane's list read again (references, computer files, conversation files).
    public func refresh(_ name: String? = nil, query: String = "", offset: String = "0", fresh: Bool = false) {
        let name = name ?? pane ?? ""
        if name == "new" {
            loadNewFolders()
            return
        }
        readPane(name, query: query, offset: offset, fresh: fresh)
    }
}
