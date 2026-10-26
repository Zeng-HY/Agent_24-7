import Foundation
import TeleplyModel

/// 遥应通知 (relay_push.py; plan "Teleply - iOS 原生推送方案"): the service keeps this phone's push token for the
/// signed-in account and has Apple deliver "Claude · 我的电脑：有个对话好了" when a computer of the account says so; a tap
/// opens that conversation. The words are the service's, never the conversation's. The token follows the account,
/// not the sign-in: one that runs out after 7 days keeps them coming, and 退出登录 ends them.
extension AppModel {
    /// 设置 → 手机通知 shown, or the app back from the system's settings: the switch there, and whether the service
    /// has this phone for the account.
    public func pushRefresh() async {
        let permission = await services.push.permission()
        guard permission != .denied else {
            push.phase = .denied
            return
        }
        guard account != nil else {
            push.phase = .off
            return
        }
        do {
            let state = try await client.pushState(token: push.token)
            push.phase = !state.available ? .unavailable
                : state.registered && services.push.wanted() && permission == .allowed ? .on : .off
        } catch {
            if push.phase == .checking { push.phase = .off }
            push.note = describe(error)
        }
    }

    /// 打开并试推一条: the system's question (it shows once), this phone's push token kept by the service for the
    /// account, and one sent to try.
    public func pushTurnOn() async {
        guard !push.working else { return }
        push.working = true
        defer { push.working = false }
        push.note = nil
        var permission = await services.push.permission()
        if permission == .notAsked { permission = await services.push.ask() ? .allowed : .denied }
        guard permission == .allowed else {
            push.phase = .denied
            push.note = "系统里关了遥应的通知：到系统设置里打开以后再回来。"
            return
        }
        services.push.setWanted(true)
        guard let token = await pushTokenNow() else { return }
        do {
            try await client.pushRegister(token: token, environment: services.push.environment, label: services.push.label,
                                          version: services.push.version)
            push.phase = .on
            push.note = try await client.pushTest(token: token)
        } catch {
            pushFailed(error)
        }
    }

    /// 试推一条.
    public func pushTest() async {
        guard !push.working, let token = push.token else { return }
        push.working = true
        defer { push.working = false }
        push.note = nil
        do {
            push.note = try await client.pushTest(token: token)
        } catch {
            pushFailed(error)
        }
    }

    /// 关掉: the service forgets this phone for the account. Bark and the system's switch stay as they are; when the
    /// service cannot be told, it stays on, to be turned off again.
    public func pushTurnOff() async {
        guard !push.working else { return }
        push.working = true
        defer { push.working = false }
        push.note = nil
        do {
            if let token = push.token { try await client.pushUnregister(token: token) }
            services.push.setWanted(false)
            push.phase = .off
            push.note = "已关掉，这部 iPhone 不再收遥应通知。"
        } catch {
            push.note = describe(error)
        }
    }

    /// iOS gave this launch's push token (asked for at launch while 遥应通知 is wanted, and when it is turned on).
    public func pushToken(_ hex: String) {
        push.token = hex
        pushSync()
    }

    /// iOS gave no token: said where 打开 waits for one.
    public func pushTokenFailed(_ text: String) {
        push.tokenFailure = text.isEmpty ? "iOS 没有给出推送令牌" : text
    }

    /// Signed in (at launch or 登录) with 遥应通知 wanted: the account gets this phone again. The service keeps one row
    /// per token, so this is quiet and harmless; one that fails is tried at the next launch.
    public func pushSync() {
        guard services.push.wanted(), let token = push.token, account != nil, !expired, !fixture else { return }
        let client = client, platform = services.push
        Task { [weak self] in
            guard (try? await client.pushRegister(token: token, environment: platform.environment, label: platform.label,
                                                  version: platform.version)) != nil else { return }
            if self?.push.phase != .denied { self?.push.phase = .on }
        }
    }

    /// The token, asked of iOS when this launch has none yet; nil after 15 s or when iOS says why not.
    func pushTokenNow() async -> String? {
        if let token = push.token { return token }
        push.tokenFailure = nil
        services.push.register()
        for _ in 0..<75 {
            if let token = push.token { return token }
            if let failure = push.tokenFailure {
                push.note = "没拿到这部 iPhone 的推送令牌：" + failure
                return nil
            }
            try? await Task.sleep(for: .milliseconds(200))
        }
        if push.token == nil { push.note = "没拿到这部 iPhone 的推送令牌，请稍后再试。" }
        return push.token
    }

    func pushFailed(_ error: any Error) {
        if let failure = error as? ServiceFailure, failure.code == "push_unavailable" { push.phase = .unavailable }
        push.note = describe(error)
    }

    /// 退出登录: the service forgets this phone for the account first, while the sign-in still works.
    func pushSignOut() async {
        guard services.push.wanted() else { return }
        services.push.setWanted(false)
        push.phase = .off
        if let token = push.token { try? await client.pushUnregister(token: token) }
    }

    // MARK: A tapped notification

    /// A notification of 遥应's own was tapped: its conversation opens once the launch or a sign-in is done.
    public func openNotification(_ target: PushTarget) {
        push.waiting = target
        resumeNotification()
    }

    /// Opens the tapped one when nothing else is under way and someone is signed in (RootView calls it again when
    /// the page's work is done or the screen changes).
    public func resumeNotification() {
        guard let target = push.waiting, !busy, screen != .launch, screen != .login, !fixture else { return }
        push.waiting = nil
        operation { [weak self] g in try await self?.openTarget(g, target) }
    }

    /// While 遥应 is in front showing this very conversation, its notification is not shown again.
    public func isShowing(_ target: PushTarget) -> Bool {
        foreground && screen == .reading && !expired && device?.id == target.device && app == target.app && chat?.id == target.chat
    }

    /// The account must still have the computer; it must be online. Then the computer is used and the conversation
    /// opened, as 连接 and a row of the list would.
    func openTarget(_ g: Int, _ target: PushTarget) async throws {
        let account: Account
        do {
            account = try await client.account()
        } catch let failure as ServiceFailure where failure.status == 401 {
            push.waiting = target  // opened once signed in again
            throw failure
        }
        guard current(g) else { return }
        self.account = account
        guard let computer = account.devices.first(where: { $0.id == target.device }) else {
            if device == nil { screen = .devices }
            throw ReadFailure("这条通知来自别的账号的电脑，或者这台电脑已经移除。")
        }
        guard computer.connectable else {
            if device?.id != computer.id { screen = .devices }
            throw ReadFailure("电脑已离线，请稍后刷新。")
        }
        if device?.id != computer.id {
            let known = await cachedSources(scope: scope, device: computer.id)
            guard current(g) else { return }
            let filter = listSource == "all" || known?.contains(listSource) == true ? listSource : "all"
            device = nil
            chats = []
            clearReading()
            query = ""
            listCursor = nil
            listMore = false
            tree = [:]
            treeError = nil
            listSource = filter
            sources = SourceInfo(device: computer.id, apps: known, loading: true, cached: known != nil)
            treeTask?.cancel()
            treeMore = [:]
            treeAt = nil
            try await client.select(device: computer.id)
            guard current(g) else { return }
            device = computer
            loadTree(force: true)
            await persistSelection(scope: scope, device: computer.id)
            guard current(g) else { return }
        }
        await useSource(target.app)
        try await readChat(g, Chat(id: target.chat, title: "对话"), restorePosition: true)
    }
}
