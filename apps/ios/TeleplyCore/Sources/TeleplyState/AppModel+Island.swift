import Foundation
import TeleplyIsland
import TeleplyModel

/// 灵动岛 (handoff 方案一; the real conversation islands come next): the phone starts an island itself and the relay
/// changes it with pushes. Everything here is a plain request; what the phone shows lives in the extension.
extension AppModel {
    /// The demo island's conversation id: not a real conversation, only a name on the island and in its URL.
    static let islandDemoChat = "island-demo"

    /// 设置 → 开发者选项 → 试一下灵动岛: starts one on this phone only, without the relay (so it also works signed out).
    /// The system shows it in the Dynamic Island when 遥应 is not in front, on the lock screen always.
    public func islandDemo() async {
        guard !island.working else { return }
        island.working = true
        island.note = nil
        defer { island.working = false }
        await islandReadEnabled()
        guard island.enabled != false else {
            island.note = "系统里关了遥应的实时活动：到系统设置 → 遥应 里打开。"
            return
        }
        let now = islandNow(), identity = demoIdentity()
        do {
            let state = IslandState(status: .working, since: now, turn: now)
            island.demo = try await services.island.start(identity, state)
            island.note = "岛开了。锁屏看看；点它会回到遥应。"
        } catch {
            island.note = describe(error)
        }
    }

    /// 设置 → 开发者选项 → 让中转改一下: starts the demo island (if needed), gives the relay its token and asks the
    /// relay for one update. The island turning into ✓ 好了 proves the APNs key may send the Live Activity topic —
    /// the question 3.5 could not settle with a made-up phone.
    public func islandRelayTest() async {
        guard !island.working else { return }
        island.working = true
        island.note = nil
        defer { island.working = false }
        guard let device, !fixture else {
            island.note = "先连上一台电脑，再用这个。"
            return
        }
        guard account != nil, !expired else {
            island.note = "先登录，再用这个。"
            return
        }
        await islandReadEnabled()
        guard island.enabled != false else {
            island.note = "系统里关了遥应的实时活动：到系统设置 → 遥应 里打开。"
            return
        }
        let now = islandNow(), identity = demoIdentity(), state = IslandState(status: .working, since: now, turn: now)
        do {
            let ref: IslandRef
            if let existing = island.demo {
                ref = existing
            } else {
                ref = try await services.island.start(identity, state)
                island.demo = ref
            }
            guard let token = await services.island.token(ref, seconds: 10) else {
                island.note = "没拿到这个岛的推送令牌，稍后再试一次。"
                return
            }
            try await client.islandRegister(IslandRegistration(token: token, device: device.id, app: identity.app,
                                                               chat: identity.chat, environment: services.island.environment,
                                                               state: state.state, since: state.since, turn: state.turn))
            island.note = try await client.islandTest(device: device.id, app: identity.app, chat: identity.chat)
        } catch {
            island.note = describe(error)
        }
    }

    /// 关掉试的岛 (the demo should not stay on the lock screen for ever).
    public func islandDemoEnd() async {
        guard !island.working else { return }
        island.working = true
        island.note = nil
        defer { island.working = false }
        let now = islandNow()
        if let ref = island.demo {
            await services.island.end(ref, IslandState(status: .done, since: now, turn: now), dismissIn: 0)
        }
        island.demo = nil
        island.note = "试的岛关掉了。"
    }

    /// Whether the system allows Live Activities (the switch in 设置 → 遥应).
    public func islandReadEnabled() async {
        island.enabled = await services.island.enabled()
    }

    /// The computer the demo names: the one in use, or a made-up one that only opens 遥应.
    private func demoIdentity() -> IslandIdentity {
        IslandIdentity(device: device?.id ?? String(repeating: "0", count: 32), app: "claude", chat: Self.islandDemoChat,
                       computer: device?.label ?? "我的电脑", title: "试一下灵动岛")
    }

    private func islandNow() -> Int {
        Int(services.now() / 1000)
    }
}
