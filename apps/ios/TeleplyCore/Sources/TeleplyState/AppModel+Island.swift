import Foundation
import TeleplyIsland
import TeleplyModel

/// 灵动岛 (handoff 方案一; the real conversation islands come next): the phone starts an island itself and the relay
/// changes it with pushes. Everything here is a plain request; what the phone shows lives in the extension.
extension AppModel {
    /// The demo island's conversation id: not a real conversation, only a name on the island and in its URL.
    static let islandDemoChat = "island-demo"

    // MARK: 真实对话的岛（阶段一）

    /// At launch and each return to the front: watch the system's islands and bring the relay up to date. Safe to
    /// call often; the watching itself starts once.
    public func islandLaunch() async {
        island.wanted = services.island.wanted()
        if !island.observing {
            island.observing = true
            services.island.observe { [weak self] event in self?.islandEvent(event) }
        }
        guard island.wanted else {
            // A remote-started island may have arrived while this phone had the switch off: take it down, but leave
            // 试一下灵动岛's demo alone (it is a developer's tool, not a conversation).
            for snap in await services.island.running() where snap.identity.chat != Self.islandDemoChat {
                await services.island.end(snap.ref, snap.state, dismissIn: 0)
            }
            return
        }
        await islandReadEnabled()
        guard island.enabled != false, account != nil, !expired, !fixture else { return }
        await islandReconcile()
        await islandRefreshFromRelay()
        await islandRegisterStartToken()
    }

    /// 0.6.5: at launch and each return to the front, read the relay's current summary for each computer island and
    /// apply it in the app. The app's own update costs no push, so the island is right even after pushes were missed.
    func islandRefreshFromRelay() async {
        guard island.wanted, !fixture, !expired, account != nil else { return }
        for (raw, track) in island.live where track.identity.chat.isEmpty {
            guard let state = try? await client.islandState(device: track.identity.device) else { continue }
            var stored = track
            stored.state = state
            island.live[raw] = stored
            await services.island.update(IslandRef(raw: raw), state)
        }
    }

    /// 设置 → 开发者选项 → 灵动岛: the switch (0.6.0 前只在这里，默认关). Off ends every island and forgets its token.
    public func islandSetWanted(_ on: Bool) async {
        guard !island.working else { return }
        island.working = true
        island.note = nil
        defer { island.working = false }
        if on {
            await islandReadEnabled()
            guard island.enabled != false else {
                island.note = "系统里关了遥应的实时活动：到系统设置 → 遥应 里打开。"
                return
            }
        }
        island.wanted = on
        services.island.setWanted(on)
        if on {
            await islandRegisterStartToken()
            await islandReconcile()
            island.note = "打开了。手机发出去的对话会出现岛；电脑上开始的跑过一分钟也会。"
        } else {
            await islandStopAll()
            island.note = "关掉了，所有岛都收起来了。"
        }
    }

    /// A message was taken by the computer (已接收 / 已送达 / 已排队): this computer's island starts or is brought
    /// back to 在干活 (0.6.3: one island for the whole computer).
    func islandSendStarted(_ record: Submission) {
        guard island.wanted, !fixture, !expired, account != nil else { return }
        // Only a send made now: a receipt read again for an old one (opening the app, a state poll) must not open an
        // island for a conversation that has long been over.
        guard services.now() - record.created < 120_000 else { return }
        let now = islandNow()
        let identity = IslandIdentity(device: record.device, app: "", chat: "", computer: computerLabel(record.device),
                                      title: "")
        let peer = IslandPeer(app: record.app, chat: record.chat, title: chatTitle(record.chat), state: "working",
                              since: now, turn: now)
        islandStart(identity, peer)
    }

    /// 新建对话's first message was accepted (0.6.2): the conversation the computer made gets its island too. Before
    /// this only a send made inside an existing conversation did, so a conversation started on the phone had none.
    func islandNewChatStarted(_ job: NewJob) {
        guard island.wanted, !fixture, !expired, account != nil, let device, job.accepted else { return }
        let made = job.pending["app"].string()
        let title = job.pending["title"].string()
        let words = oneLine(job.text, limit: 40)
        let now = islandNow()
        let identity = IslandIdentity(device: device.id, app: "", chat: "", computer: device.label, title: "")
        let peer = IslandPeer(app: made.isEmpty ? job.app : made, chat: job.createdID,
                              title: title.isEmpty ? words : title, state: "working", since: now, turn: now)
        islandStart(identity, peer)
    }

    /// Starts this computer's island, or updates the one it already has: the new conversation joins its list and
    /// 在干活 count. The relay's next push replaces these local numbers with the computer's own (0.6.3).
    func islandStart(_ identity: IslandIdentity, _ peer: IslandPeer) {
        if let existing = island.live.first(where: { $0.value.identity.device == identity.device }) {
            var state = existing.value.state
            var peers = state.peers ?? []
            let known = peers.contains { $0.app == peer.app && $0.chat == peer.chat }
            if let index = peers.firstIndex(where: { $0.app == peer.app && $0.chat == peer.chat }) {
                peers[index] = peer
            } else {
                peers.insert(peer, at: 0)
            }
            state.peers = Array(peers.prefix(3))
            if !known { state.working = max(1, (state.working ?? max(0, peers.count - 1)) + 1) }
            state.waiting = max(0, state.waiting ?? 0)
            state.state = (state.waiting ?? 0) > 0 ? "waiting" : "working"
            var track = existing.value
            track.state = state
            track.registered = false
            island.live[existing.key] = track
            Task { [weak self] in
                guard let self else { return }
                await services.island.update(IslandRef(raw: existing.key), state)
                await islandRegister(IslandRef(raw: existing.key))
            }
            return
        }
        if island.live.count >= 3 {  // three computers at most; the oldest finished one makes way
            guard let finished = island.live.first(where: { $0.value.state.status == .done }) else { return }
            island.live.removeValue(forKey: finished.key)
            Task { await services.island.end(IslandRef(raw: finished.key), finished.value.state, dismissIn: 0) }
        }
        let state = IslandState(status: .working, since: peer.since, turn: peer.turn, peers: [peer], working: 1,
                                waiting: 0)
        Task { [weak self] in
            guard let self else { return }
            await islandEndDemo()  // a left-over 试一下灵动岛 must not sit ahead of the real conversation
            do {
                let ref = try await services.island.start(identity, state)
                island.live[ref.raw] = IslandTrack(identity: identity, state: state)
                islandFetchToken(ref)
            } catch {
                island.note = describe(error)
            }
        }
    }

    /// What the system says changed: a remote start, a token (new or another), an island gone.
    func islandEvent(_ event: IslandEvent) {
        switch event {
        case let .started(ref, identity, state):
            guard island.wanted, !fixture, !expired else {
                Task { await services.island.end(ref, state, dismissIn: 0) }
                return
            }
            island.live[ref.raw] = IslandTrack(identity: identity, state: state)  // the relay's list comes with it
            islandFetchToken(ref)
        case let .token(ref, token):
            guard var track = island.live[ref.raw] else { return }
            track.token = token
            track.registered = false
            island.live[ref.raw] = track
            Task { await islandRegister(ref) }
        case let .dismissed(ref):
            guard let track = island.live.removeValue(forKey: ref.raw) else { return }
            Task { await islandUnregister(track) }
        }
    }

    /// The token is made a moment after the island starts; then the relay gets it.
    func islandFetchToken(_ ref: IslandRef) {
        Task { [weak self] in
            guard let self else { return }
            guard let token = await services.island.token(ref, seconds: 10) else { return }
            if var track = island.live[ref.raw] {
                track.token = token
                island.live[ref.raw] = track
            }
            await islandRegister(ref)
        }
    }

    func islandRegister(_ ref: IslandRef) async {
        guard island.wanted, !fixture, !expired, let track = island.live[ref.raw], let token = track.token else { return }
        guard account?.devices.contains(where: { $0.id == track.identity.device }) == true else { return }
        do {
            try await client.islandRegister(IslandRegistration(
                token: token, device: track.identity.device, app: track.identity.app, chat: track.identity.chat,
                environment: services.island.environment, state: track.state.state, since: track.state.since,
                turn: track.state.turn, title: track.identity.title, language: IslandWords.language))
            if var stored = island.live[ref.raw] {
                stored.registered = true
                island.live[ref.raw] = stored
            }
        } catch {
            island.note = describe(error)
        }
    }

    func islandUnregister(_ track: IslandTrack) async {
        guard let token = track.token else { return }
        try? await client.islandRegister(.unregister(token: token, device: track.identity.device, app: track.identity.app,
                                                      chat: track.identity.chat, environment: services.island.environment))
    }

    /// Checks what the system still has against what the app keeps: remote-started islands are picked up, islands
    /// gone since are dropped, and finished ones that have been out for ten minutes are ended.
    func islandReconcile() async {
        guard island.wanted, !fixture, !expired, account != nil else {
            if !island.wanted { await islandStopAll() }
            return
        }
        let snaps = await services.island.running()
        let now = islandNow()
        var kept: [IslandSnapshot] = []
        for snap in snaps {
            // 0.6.3 upgrade: the per-conversation islands of 0.6.2 give way to one island for the whole computer.
            if !snap.identity.chat.isEmpty && snap.identity.chat != Self.islandDemoChat {
                await services.island.end(snap.ref, snap.state, dismissIn: 0)
                island.live.removeValue(forKey: snap.ref.raw)
            } else {
                kept.append(snap)
            }
        }
        for snap in kept where island.live[snap.ref.raw] == nil {
            island.live[snap.ref.raw] = IslandTrack(identity: snap.identity, state: snap.state)
            islandFetchToken(snap.ref)
        }
        for snap in kept {
            guard var track = island.live[snap.ref.raw] else { continue }
            track.state = snap.state
            island.live[snap.ref.raw] = track
        }
        let refs = Set(kept.map(\.ref.raw))
        for key in Array(island.live.keys) where !refs.contains(key) { island.live.removeValue(forKey: key) }
        for snap in kept {
            guard let status = snap.state.status, status == .done || status == .failed else { continue }
            if now - snap.state.since > 10 * 60 {
                await services.island.end(snap.ref, snap.state, dismissIn: 0)
                island.live.removeValue(forKey: snap.ref.raw)
            }
        }
    }

    func islandRegisterStartToken() async {
        guard island.wanted, !fixture, !expired, account != nil else { return }
        guard let token = await services.island.startToken(seconds: 5) else { return }
        try? await client.islandStartToken(IslandStartToken(token: token, environment: services.island.environment, language: IslandWords.language))
    }

    func islandStopAll() async {
        await services.island.endAll()
        let tracks = island.live.values
        island.live.removeAll()
        for track in tracks { await islandUnregister(track) }
    }

    private func computerLabel(_ id: String) -> String {
        account?.devices.first(where: { $0.id == id })?.label ?? device?.label ?? "我的电脑"
    }

    private func chatTitle(_ id: String) -> String {
        chats.first(where: { $0.id == id })?.title ?? ""
    }

    // MARK: 试岛（阶段零留下的开发者选项）

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
        await islandEndDemo()
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
        await islandEndDemo()
        do {
            let ref = try await services.island.start(identity, state)
            island.demo = ref
            guard let token = await services.island.token(ref, seconds: 10) else {
                island.note = "没拿到这个岛的推送令牌，稍后再试一次。"
                return
            }
            try await client.islandRegister(IslandRegistration(token: token, device: device.id, app: identity.app,
                                                               chat: identity.chat, environment: services.island.environment,
                                                               state: state.state, since: state.since, turn: state.turn,
                                                               title: identity.title, language: IslandWords.language))
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
        await islandEndDemo()
        island.note = "试的岛关掉了。"
    }

    /// Ends every 试一下灵动岛 island the system still has, so an old demo cannot sit in the island ahead of a real
    /// conversation (or pile up when the button is pressed again).
    func islandEndDemo() async {
        for snap in await services.island.running() where snap.identity.chat == Self.islandDemoChat {
            await services.island.end(snap.ref, snap.state, dismissIn: 0)
        }
        island.demo = nil
    }

    /// Whether the system allows Live Activities (the switch in 设置 → 遥应).
    public func islandReadEnabled() async {
        island.enabled = await services.island.enabled()
    }

    /// 试岛 uses the source in use (a DeepSeek conversation's demo shows DeepSeek's mark), and a made-up conversation
    /// id so it never collides with that conversation's real island.
    private func demoIdentity() -> IslandIdentity {
        IslandIdentity(device: device?.id ?? String(repeating: "0", count: 32), app: chat == nil ? "claude" : app,
                       chat: Self.islandDemoChat, computer: device?.label ?? "我的电脑", title: "试一下灵动岛")
    }

    private func islandNow() -> Int {
        Int(services.now() / 1000)
    }
}
