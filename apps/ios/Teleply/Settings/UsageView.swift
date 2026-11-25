import SwiftUI
import TeleplyModel
import TeleplyState

/// 设置 → 用量 (spec 4.6; Android UsageSheet): Codex's and Claude's limits and when each resets, read when the page
/// opens and on pull-to-refresh (never polled), and Codex's reset credits. Using one always goes through a
/// confirmation, and a request id keeps a retry from using a second.
struct UsageView: View {
    let model: AppModel
    @State private var data: JSONValue?
    @State private var failure: String?
    @State private var loading = false
    @State private var asking = false
    @State private var sending = false
    @State private var note: String?
    @State private var noteIsError = false
    @State private var noteMuted = false
    @State private var unconfirmed = false
    @State private var picked: ResetCredit?
    @State private var attempt = ResetAttempt()

    private let zone = TimeZone.current

    var body: some View {
        let report = data.map(UsageReport.parse) ?? UsageReport()
        List {
            statusRows
            codexSection(report.codex, now: report.now)
            claudeSection(report.claude)
            ForEach(agentUsageOrder(report, catalog: model.catalog), id: \.self) { id in
                agentSection(id: id, agent: report.agents[id] ?? AgentUsage(id: id), now: report.now)
            }
        }
        .scrollContentBackground(.hidden)
        .background(Palette.page)
        .navigationTitle("用量")
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .topBarTrailing) {
                Button("刷新") { Task { await load() } }
                    .disabled(loading || sending)
            }
        }
        .task { await load() }
        .refreshable { await load() }
        .alert("用掉 1 次 Codex 重置？", isPresented: $asking) {
            Button("先不用", role: .cancel) {}
            Button("用掉 1 次", role: .destructive) { use(picked) }
        } message: {
            Text(confirmText(picked, windows: report.codex.windows, zone: zone))
        }
    }

    // MARK: What just happened

    @ViewBuilder private var statusRows: some View {
        if (loading && data == nil) || failure != nil || note != nil || sending || unconfirmed {
            Section {
                if loading && data == nil {
                    Text("读取中…")
                        .noteFont()
                        .foregroundStyle(Palette.muted)
                }
                if let failure {
                    Text(failure)
                        .noteFont()
                        .foregroundStyle(Palette.danger)
                }
                if let note {
                    Text(note)
                        .noteFont()
                        // Red is for failures only: a reset reads as ordinary text, the other outcomes in grey.
                        .foregroundStyle(noteIsError ? Palette.danger : (noteMuted ? Palette.muted : Palette.ink))
                }
                if sending {
                    Text("正在用…")
                        .noteFont()
                        .foregroundStyle(Palette.muted)
                }
                if unconfirmed {
                    Button("再试一次（不会多用）") { use(picked) }
                        .buttonStyle(PillStyle(wide: true))
                        .disabled(sending)
                }
            }
            .listRowBackground(Color.clear)
        }
    }

    // MARK: Codex

    @ViewBuilder private func codexSection(_ codex: CodexUsage, now: Int64) -> some View {
        Section("Codex") {
            if !codex.available {
                Text(codex.reason.isEmpty ? "读不到 Codex 的用量" : codex.reason)
                    .noteFont()
                    .foregroundStyle(Palette.muted)
            } else {
                if codex.reached != nil {
                    Text("Codex 的用量用完了")
                        .noteFont()
                        .foregroundStyle(Palette.danger)
                }
                ForEach(Array(codex.windows.enumerated()), id: \.offset) { _, window in
                    windowRow(window, line: resetLine(window, source: codex.source, nowMs: now, zone: zone))
                }
                let from = sourceLine(source: codex.source, asOf: codex.asOf, nowMs: now, zone: zone)
                if !from.isEmpty {
                    Text(from)
                        .captionFont()
                        .foregroundStyle(Palette.muted)
                }
                if !codex.liveError.isEmpty {
                    Text("读不到实时用量：" + codex.liveError)
                        .captionFont()
                        .foregroundStyle(Palette.muted)
                }
                resetsRows(codex)
            }
        }
        .listRowBackground(Palette.controlFill)
    }

    @ViewBuilder private func resetsRows(_ codex: CodexUsage) -> some View {
        if !codex.resets {
            if codex.source == "records" {
                Text("重置次数要实时读到才显示，下拉刷新试试")
                    .captionFont()
                    .foregroundStyle(Palette.muted)
            }
        } else if codex.resetsAvailable == 0 {
            Text("没有可用的重置次数")
                .noteFont()
                .foregroundStyle(Palette.muted)
        } else {
            Text("可用重置：" + "\(codex.resetsAvailable ?? codex.credits?.count ?? 0)" + " 次")
            if let credits = codex.credits {
                ForEach(Array(credits.enumerated()), id: \.offset) { _, credit in
                    HStack(spacing: 8) {
                        VStack(alignment: .leading, spacing: 2) {
                            Text(credit.title.isEmpty ? "用量重置" : credit.title)
                            Text(resetExpiryLine(credit, zone: zone))
                                .captionFont()
                                .foregroundStyle(Palette.muted)
                        }
                        .frame(maxWidth: .infinity, alignment: .leading)
                        Button("用掉这一次") { ask(credit) }
                            .buttonStyle(PillStyle(minHeight: 36))
                            .disabled(sending)
                    }
                }
            } else {
                Button("用掉一次") { ask(nil) }
                    .buttonStyle(PillStyle(wide: true))
                    .disabled(sending)
            }
        }
    }

    // MARK: Claude

    @ViewBuilder private func claudeSection(_ claude: ClaudeUsage) -> some View {
        Section("Claude") {
            if !claude.available {
                Text(claude.reason.isEmpty ? "读不到 Claude 的用量" : claude.reason)
                    .noteFont()
                    .foregroundStyle(Palette.muted)
            } else {
                if claude.windows.isEmpty {
                    if !claude.text.isEmpty { Text(claude.text) }
                } else {
                    ForEach(Array(claude.windows.enumerated()), id: \.offset) { _, window in
                        windowRow(window, line: window.resetsText.isEmpty ? "" : window.resetsText + " 重置")
                    }
                }
                Text("读自电脑上的 Claude 窗口。Claude 只显示最紧的那一档。"
                     + (claude.minimized ? "Claude 窗口最小化了，数字可能是旧的。" : ""))
                    .captionFont()
                    .foregroundStyle(Palette.muted)
            }
        }
        .listRowBackground(Palette.controlFill)
    }

    /// A new assistant's limits (§3.3): its catalog name, the windows the computer gave, and its own reason when it
    /// could not be read. The old three keep the sections above exactly as before.
    @ViewBuilder private func agentSection(id: String, agent: AgentUsage, now: Int64) -> some View {
        let name = model.catalog.name(id)
        Section {
            if !agent.available {
                Text(agentUsageLine(agent, name: name))
                    .noteFont()
                    .foregroundStyle(Palette.muted)
            } else if agent.windows.isEmpty {
                if !agent.text.isEmpty { Text(agent.text) }
            } else {
                ForEach(Array(agent.windows.enumerated()), id: \.offset) { _, window in
                    windowRow(window, line: agentWindowLine(window, source: agent.source, nowMs: now, zone: zone))
                }
            }
        } header: {
            Text(name)
        }
        .listRowBackground(Palette.controlFill)
    }

    /// One limit: its name and how much is used, a bar, and the line under it.
    private func windowRow(_ window: UsageWindow, line: String) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            HStack(spacing: 6) {
                Text(window.name)
                Text("已用 \(window.usedPercent)%")
            }
            ProgressView(value: Double(window.usedPercent), total: 100)
                .tint(window.usedPercent >= 90 ? Palette.danger : Palette.accent)
            if !line.isEmpty {
                Text(line)
                    .captionFont()
                    .foregroundStyle(Palette.muted)
            }
        }
    }

    // MARK: Acting

    private func ask(_ credit: ResetCredit?) {
        picked = credit
        asking = true
    }

    private func use(_ credit: ResetCredit?) {
        guard !sending else { return }
        sending = true
        note = nil
        noteIsError = false
        noteMuted = false
        unconfirmed = false
        picked = credit
        Task {
            do {
                var fields: [String: JSONValue] = ["request_id": .string(attempt.id()), "confirmed": true]
                if let credit { fields["credit_id"] = .string(credit.id) }
                let answer = try await model.deviceCall("usage/codex-reset", body: .object(fields))
                attempt.done()
                note = Hints.text(answer["text"].string())
                noteMuted = answer["outcome"].string() != "reset"
                var whole = (data ?? JSONValue.object([:])).object
                if answer["usage"].isObject, !whole.isEmpty {
                    whole["codex"] = answer["usage"]
                    data = .object(whole)
                } else {
                    await load()
                }
            } catch {
                if attempt.keepsId(error) {
                    unconfirmed = true
                    note = Hints.text("没确认这次用成了没有。")
                } else {
                    attempt.done()
                    note = describe(error)
                }
                noteIsError = true
                noteMuted = false
            }
            sending = false
        }
    }

    private func load() async {
        loading = true
        failure = nil
        do {
            data = try await model.deviceCall("usage", query: [("live", "1")])
        } catch {
            failure = describe(error)
        }
        loading = false
    }
}
