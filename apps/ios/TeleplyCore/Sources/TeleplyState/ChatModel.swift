import Foundation
import Observation
import TeleplyModel

/// The open conversation's live side (Android ChatController.bind): a fresh state read on entering, then the
/// live stream; Claude and DeepSeek also poll their state (every 5 s and 2.5 s, without fresh, never while a tap
/// waits on the computer). A dropped connection is tried again after 1 s, doubling up to 15 s; a 401, 403 or
/// 404 stops it. In the background nothing runs. Sending arrives in phase 2.
@Observable
public final class ChatModel {
    public internal(set) var key: ChatKey?
    public internal(set) var control = Control()
    public internal(set) var connection = "实时连接未启动"
    /// Goes up when a frame brings messages, so the page can follow new output.
    public internal(set) var revision = 0

    /// True while a tap waits on the computer (web claude-ui.js `choosing`): no state poll then.
    @ObservationIgnored public var pollPaused: @MainActor () -> Bool = { false }

    @ObservationIgnored let pacer: any Pacer
    @ObservationIgnored var client: RelayClient?
    @ObservationIgnored var clientGeneration = -1
    @ObservationIgnored var foreground = false
    @ObservationIgnored var synthetic = false
    @ObservationIgnored var task: Task<Void, Never>?
    @ObservationIgnored var token = 0
    @ObservationIgnored var retryDelay: Duration = .seconds(1)
    @ObservationIgnored var onFrame: (LiveFrame, ChatKey) -> Void = { _, _ in }

    init(pacer: any Pacer) {
        self.pacer = pacer
    }

    /// Waits for the current round to stop (tests; a round waiting to reconnect never does).
    public func settle() async {
        await task?.value
    }

    func bind(_ next: ChatKey?, client: RelayClient, clientGeneration: Int, active: Bool, synthetic: Bool,
              onFrame: @escaping (LiveFrame, ChatKey) -> Void) {
        if next == key && clientGeneration == self.clientGeneration && active == foreground && synthetic == self.synthetic { return }
        task?.cancel()
        token += 1
        let t = token
        let changed = next != key || clientGeneration != self.clientGeneration
        key = next
        self.client = client
        self.clientGeneration = clientGeneration
        foreground = active
        self.synthetic = synthetic
        self.onFrame = onFrame
        if changed {
            control = Control()
            connection = "实时连接未启动"
            revision = 0
        }
        guard let next else { return }
        guard active else {
            connection = "已暂停实时连接"
            control.available = false
            return
        }
        task = Task { [weak self] in await self?.run(next, client, t) }
    }

    func run(_ key: ChatKey, _ client: RelayClient, _ t: Int) async {
        retryDelay = .seconds(1)
        while !Task.isCancelled && t == token {
            do {
                connection = "正在核对实时状态"
                control.available = false
                let state = try await client.control(device: key.device, app: key.app, chat: key.chat)
                guard t == token else { return }
                control = mergeControl(previous: control, incoming: state)
                // The local demo has no live stream (Android: an empty flow).
                if synthetic {
                    connection = "本地固定场景"
                    return
                }
                try await withThrowingTaskGroup(of: Void.self) { group in
                    if key.app != "codex" {
                        let every: Duration = key.app == "claude" ? .seconds(5) : .milliseconds(2_500)
                        group.addTask { [weak self] in try await self?.poll(key, client, t, every) }
                    }
                    group.addTask { [weak self] in try await self?.listen(key, client, t) }
                    // The stream ending (or failing) ends the round; polling stops with it.
                    _ = try await group.next()
                    group.cancelAll()
                }
                guard t == token else { return }
                connection = "实时连接已结束"
                return
            } catch is CancellationError {
                return
            } catch {
                guard t == token else { return }
                let status = (error as? ServiceFailure)?.status
                connection = status == 401 ? "登录失效，请返回账号页重新登录" : "连接中断，正在重连"
                control.available = false
                if let status, [401, 403, 404].contains(status) { return }
                do { try await pacer.wait(retryDelay) } catch { return }
                retryDelay = min(retryDelay * 2, .seconds(15))
            }
        }
    }

    func listen(_ key: ChatKey, _ client: RelayClient, _ t: Int) async throws {
        for try await frame in try client.events(device: key.device, app: key.app, chat: key.chat) {
            guard t == token else { return }
            onFrame(frame, key)
            connection = "实时连接正常"
            if let incoming = frame.control { control = mergeControl(previous: control, incoming: incoming) }
            if !frame.messages.isEmpty { revision += 1 }
            retryDelay = .seconds(1)
        }
    }

    func poll(_ key: ChatKey, _ client: RelayClient, _ t: Int, _ every: Duration) async throws {
        while !Task.isCancelled {
            try await pacer.wait(every)
            if pollPaused() { continue }
            let state = try await client.control(device: key.device, app: key.app, chat: key.chat, fresh: false)
            if t == token { control = mergeControl(previous: control, incoming: state) }
        }
    }
}
