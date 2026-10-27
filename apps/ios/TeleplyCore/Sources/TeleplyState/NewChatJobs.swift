import Foundation
import Observation
import TeleplyModel

/// The first messages of one computer under way (Android NewChatJobs; web new-chat-ui.js jobs), kept on this phone
/// until they are opened or removed (a day for one that went through). Each is sent once; then the computer is
/// asked where it stands: every 0.5 s while its page is open, every 1.5 s otherwise, every 6 s while its result is
/// unknown (30 s after two minutes), until it is accepted or failed. Nothing is ever sent again by itself:
/// 继续发送 resends the same request, which the computer creates only once (B14).
@Observable
public final class NewChatJobs {
    public internal(set) var jobs: [NewJob] = []
    /// The job page on screen (its preview id): looked at at once and every half second; it becomes its
    /// conversation when ready.
    public var onScreen: String? {
        didSet {
            guard onScreen != oldValue, let job = jobs.first(where: { $0.preview == onScreen }) else { return }
            check(job)
        }
    }
    /// An accepted job whose page is on screen: open its conversation.
    @ObservationIgnored public var settle: (NewJob) -> Void = { _ in }
    /// 诊断测速 (开发者选项): a first message's time and what it came to.
    @ObservationIgnored public var timed: (_ label: String, _ elapsed: Duration, _ outcome: String) -> Void = { _, _, _ in }

    @ObservationIgnored let pacer: any Pacer
    @ObservationIgnored let store: LocalStore?
    @ObservationIgnored let now: @Sendable () -> Int64
    @ObservationIgnored var owner: ChatKey?
    @ObservationIgnored var client: RelayClient?
    @ObservationIgnored var synthetic = false
    @ObservationIgnored var foreground = false
    @ObservationIgnored var loading: Task<Void, Never>?
    @ObservationIgnored var timers: [String: Task<Void, Never>] = [:]
    @ObservationIgnored var checking: Set<String> = []
    @ObservationIgnored var sending: Set<String> = []
    /// Requests and checks under way (tests wait for them).
    @ObservationIgnored var working: [String: Task<Void, Never>] = [:]
    @ObservationIgnored var writing: Task<Void, Never>?
    @ObservationIgnored var demo: [ChatKey: [NewJob]] = [:]

    init(pacer: any Pacer, store: LocalStore? = nil, now: @escaping @Sendable () -> Int64 = { Int64(Date().timeIntervalSince1970 * 1000) }) {
        self.pacer = pacer
        self.store = store
        self.now = now
    }

    /// Waits for the jobs' requests, checks and writes under way (not the next look's wait).
    public func settle() async {
        await loading?.value
        while let next = working.values.first {
            await next.value
            if working.values.first == next { break }
        }
        await writing?.value
    }

    func bind(scope: String, device: String?, client: RelayClient, synthetic: Bool) {
        let next = device.flatMap { scope.isEmpty ? nil : ChatKey(scope: scope, device: $0, app: "@jobs", chat: "all") }
        self.client = client
        self.synthetic = synthetic
        guard next != owner else { return }
        for timer in timers.values { timer.cancel() }
        timers = [:]
        loading?.cancel()
        owner = next
        jobs = []
        guard let next else { return }
        loading = Task { [weak self] in
            guard let self else { return }
            let kept: [NewJob]
            if synthetic {
                kept = self.demo[next] ?? []
            } else {
                let text = await self.store?.detail(scope: next.scope, device: next.device, app: next.app, chat: next.chat, kind: "new_jobs")
                kept = text.flatMap { try? JSONDecoder().decode([NewJob].self, from: Data($0.utf8)) } ?? []
            }
            guard self.owner == next, !Task.isCancelled else { return }
            // A day on, a job that went through is in the list as its conversation (web).
            let now = self.now()
            self.jobs = kept.filter { !($0.accepted && now - $0.created > 86_400_000) } + self.jobs.filter { job in !kept.contains { $0.request == job.request } }
            if self.foreground {
                for job in self.jobs where !self.settled(job) { self.check(job) }
            }
        }
    }

    /// Looked at while the app is in front only (web: not while the page is hidden).
    func setForeground(_ on: Bool) {
        guard on != foreground else { return }
        foreground = on
        if on {
            for job in jobs where !settled(job) { check(job) }
        } else {
            for timer in timers.values { timer.cancel() }
            timers = [:]
        }
    }

    func settled(_ job: NewJob) -> Bool {
        job.state == "accepted" || job.state == "failed"
    }

    public func current(_ request: String) -> NewJob? {
        jobs.first { $0.request == request }
    }

    /// Sends a first message once and follows it (web send).
    func submit(_ job: NewJob) {
        put(job)
        guard let client, let owner else { return }
        let rid = job.request
        sending.insert(rid)
        working[rid] = Task { [weak self] in
            let pending: JSONValue
            let started = ContinuousClock.now
            do {
                pending = try await client.detail(device: owner.device, route: "chat/new", body: job.body)
                self?.timed("新对话提交", ContinuousClock.now - started, speedOutcome(pending))
            } catch {
                let refused = (error as? ServiceFailure)?.notSubmitted == true
                pending = ["state": .string(refused ? "failed" : "unconfirmed"), "message": .string(describe(error))]
                self?.timed("新对话提交", ContinuousClock.now - started, (error as? ServiceFailure).map { "HTTP \($0.status)" } ?? "网络失败")
            }
            guard let self else { return }
            self.sending.remove(rid)
            self.working[rid] = nil
            guard self.owner == owner, var now = self.current(rid) else { return }
            now.pending = pending
            now.note = ""
            self.put(now)
            if now.state != "failed" { self.check(now) }
        }
    }

    /// Asks the computer where the job stands (web check), then again in a moment while it is under way.
    public func check(_ job: NewJob) {
        guard let client, let owner else { return }
        let rid = job.request
        guard !checking.contains(rid), !sending.contains(rid), current(rid) != nil else { return }
        timers[rid]?.cancel()
        timers[rid] = nil
        checking.insert(rid)
        working[rid] = Task { [weak self] in
            var again: Duration = .milliseconds(500)
            var done = false
            do {
                let reply = try await client.detail(device: owner.device, route: "chat/new/state", query: [("request_id", rid)])
                guard let self, self.owner == owner, var now = self.current(rid) else {
                    self?.checking.remove(rid)
                    self?.working[rid] = nil
                    return
                }
                let echoed = reply["request_id"].string()
                guard echoed.isEmpty || echoed == rid else { throw ReadFailure("回执身份不匹配") }
                var pending = reply
                // The computer has no submission for it: the same request may be sent on, it would not be made twice.
                if reply["state"].string() == "draft", case .object(var fields) = reply {
                    fields["state"] = "unconfirmed"
                    fields["can_submit"] = true
                    fields["message"] = "服务器尚无提交记录。可继续发送同一请求，不会重复创建。"
                    pending = .object(fields)
                }
                now.pending = pending
                now.note = ""
                self.put(now)
                switch now.state {
                case "accepted":
                    done = true
                    if self.onScreen == now.preview { self.settle(now) }
                case "failed":
                    done = true
                case "unconfirmed":
                    again = self.now() - now.created < 120_000 ? .seconds(6) : .seconds(30)
                default:
                    if self.onScreen != now.preview { again = .milliseconds(1_500) }
                }
            } catch is CancellationError {
                done = true
            } catch {
                if let self, var now = self.current(rid) {
                    now.note = "暂时无法核对，内容还在手机上；恢复连接后继续核对"
                    self.put(now)
                }
                again = .seconds(5)
            }
            guard let self else { return }
            self.checking.remove(rid)
            self.working[rid] = nil
            guard !done, self.owner == owner, let still = self.current(rid), !self.settled(still), self.foreground else { return }
            let pacer = self.pacer
            self.timers[rid] = Task { [weak self] in
                do { try await pacer.wait(again) } catch { return }
                guard let self else { return }
                self.timers[rid] = nil
                if let job = self.current(rid) { self.check(job) }
            }
        }
    }

    /// 继续发送 (web retry): the same request again; the computer creates it once whatever happened before.
    public func retry(_ job: NewJob) {
        guard let client, let owner else { return }
        let rid = job.request
        let previous = job.pending
        guard job.retryable, !sending.contains(rid), !checking.contains(rid) else { return }
        sending.insert(rid)
        var going = job
        var fields = previous.object
        fields["state"] = "creating"
        fields["message"] = "正在继续原请求…"
        going.pending = .object(fields)
        going.note = ""
        put(going)
        working[rid] = Task { [weak self] in
            let pending: JSONValue
            let started = ContinuousClock.now
            let label = previous["can_submit"].bool() ? "新对话提交" : "新对话重试"
            do {
                pending = previous["can_submit"].bool()
                    ? try await client.detail(device: owner.device, route: "chat/new", body: job.body)
                    : try await client.detail(device: owner.device, route: "chat/new/retry", body: ["request_id": .string(rid)])
                self?.timed(label, ContinuousClock.now - started, speedOutcome(pending))
            } catch {
                self?.timed(label, ContinuousClock.now - started, (error as? ServiceFailure).map { "HTTP \($0.status)" } ?? "网络失败")
                var unknown = previous.object
                unknown["state"] = "unconfirmed"
                unknown["can_submit"] = false
                unknown["not_submitted"] = false
                unknown["message"] = .string("继续发送的结果尚未确认，请核对结果：" + describe(error))
                pending = .object(unknown)
            }
            guard let self else { return }
            self.sending.remove(rid)
            self.working[rid] = nil
            guard self.owner == owner, var now = self.current(rid) else { return }
            now.pending = pending
            self.put(now)
            self.check(now)
        }
    }

    /// 移除 / opened: the phone stops following it; nothing on the computer changes.
    public func drop(_ job: NewJob) {
        timers[job.request]?.cancel()
        timers[job.request] = nil
        jobs.removeAll { $0.request == job.request }
        save()
    }

    func put(_ job: NewJob) {
        if let index = jobs.firstIndex(where: { $0.request == job.request }) {
            // A look that changes nothing writes nothing (as ChatModel.take).
            guard jobs[index] != job else { return }
            jobs[index] = job
        } else {
            jobs.append(job)
        }
        save()
    }

    func save() {
        guard let owner else { return }
        let value = jobs
        if synthetic {
            demo[owner] = value
            return
        }
        let previous = writing
        let store = store
        writing = Task {
            await previous?.value
            guard let data = try? JSONEncoder().encode(value) else { return }
            await store?.setDetail(scope: owner.scope, device: owner.device, app: owner.app, chat: owner.chat, kind: "new_jobs",
                                   value: String(decoding: data, as: UTF8.self))
        }
    }
}
