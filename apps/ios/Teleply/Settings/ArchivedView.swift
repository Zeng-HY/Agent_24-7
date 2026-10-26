import SwiftUI
import TeleplyModel
import TeleplyState

/// 设置 → 已归档对话 (spec 4.6; web archive-ui.js archivedSheet; Android ArchivedSheet): by source, 恢复 brings one
/// back. Codex's can be ticked and deleted for good after a confirmation; DeepSeek has no delete, so its rows only
/// restore; Claude's restore when the computer is unlocked.
struct ArchivedView: View {
    let model: AppModel
    @State private var data: JSONValue?
    @State private var picked: Set<String> = []
    @State private var busy = false
    @State private var confirming = false
    @State private var note: String?

    var body: some View {
        let items = data?["items"].array ?? []
        let deletable = Set((data?["deletable"].array ?? []).map { $0.string() })
        let apps = (data?["apps"].array ?? []).map { $0.string() }
        let canDelete = items.filter { $0["can_delete"].bool() && deletable.contains($0["app"].string()) }
        List {
            Section {
                if busy { ProgressView().frame(maxWidth: .infinity) }
                let explain = [
                    apps.contains("codex") ? "Codex 的可以恢复，也可以勾选后删除；删除后电脑上也找不回来。" : "",
                    apps.contains("deepseek") ? "DeepSeek 没有删除对话的功能，只能恢复。" : "",
                    apps.contains("claude") ? "Claude 可以归档和恢复，需电脑解锁；有工作副本的会话请在电脑上归档。暂不支持删除。" : "",
                ].joined()
                if !explain.isEmpty {
                    Text(explain)
                        .captionFont()
                        .foregroundStyle(Palette.muted)
                }
                if let note {
                    Text(note)
                        .noteFont()
                        .foregroundStyle(Palette.muted)
                        .task(id: note) { AccessibilityNotification.Announcement(note).post() }
                }
                if data == nil {
                    Text("读取中…")
                        .noteFont()
                        .foregroundStyle(Palette.muted)
                }
                ForEach(Array((data?["problems"].array ?? []).enumerated()), id: \.offset) { _, problem in
                    Text("读不到 " + problem.string())
                        .noteFont()
                        .foregroundStyle(Palette.danger)
                }
                if data != nil && items.isEmpty && (data?["problems"].array ?? []).isEmpty {
                    Text("没有已归档的对话。\n在对话列表里把一行往左滑，就能归档。")
                        .noteFont()
                        .foregroundStyle(Palette.muted)
                }
            }
            .listRowBackground(Color.clear)
            ForEach(groups(items), id: \.app) { group in
                Section(Labels.sourceName(group.app)) {
                    ForEach(Array(group.rows.enumerated()), id: \.offset) { _, row in
                        let key = row["app"].string() + ":" + row["id"].string()
                        ArchivedRow(row: row, picked: picked.contains(key), canPick: row["can_delete"].bool() && deletable.contains(row["app"].string()) && !busy,
                                    enabled: !busy) {
                            if picked.contains(key) { picked.remove(key) } else { picked.insert(key) }
                        } restore: {
                            restore(row)
                        }
                    }
                }
                .listRowBackground(Palette.controlFill)
            }
            if !canDelete.isEmpty {
                Section {
                    HStack(spacing: 8) {
                        let all = canDelete.allSatisfy { picked.contains($0["app"].string() + ":" + $0["id"].string()) }
                        Button(all ? "全不选" : "全选") {
                            picked = all ? [] : Set(canDelete.map { $0["app"].string() + ":" + $0["id"].string() })
                        }
                        .buttonStyle(PillStyle(wide: true))
                        Button(picked.isEmpty ? "删除" : "删除（\(picked.count)）") { confirming = true }
                            .buttonStyle(PillStyle(kind: .danger, wide: true))
                            .disabled(picked.isEmpty)
                    }
                    .disabled(busy)
                }
                .listRowBackground(Color.clear)
            }
        }
        .scrollContentBackground(.hidden)
        .background(Palette.page)
        .navigationTitle("已归档对话")
        .navigationBarTitleDisplayMode(.inline)
        .task { await load() }
        .refreshable { await load() }
        .alert("删除这 \(picked.count) 个对话？", isPresented: $confirming) {
            Button("取消", role: .cancel) {}
            Button("删除", role: .destructive) { delete(items) }
        } message: {
            Text("删除后在电脑上也找不回来。")
        }
    }

    private struct SourceRows {
        let app: String
        let rows: [JSONValue]
    }

    private func groups(_ items: [JSONValue]) -> [SourceRows] {
        var order: [String] = []
        var rows: [String: [JSONValue]] = [:]
        for item in items {
            let app = item["app"].string()
            if rows[app] == nil { order.append(app) }
            rows[app, default: []].append(item)
        }
        return order.map { SourceRows(app: $0, rows: rows[$0] ?? []) }
    }

    private func load() async {
        do {
            data = try await model.deviceCall("chat/archived")
        } catch {
            data = ["items": [], "problems": [.string(describe(error))]]
        }
        let keys = Set((data?["items"].array ?? []).map { $0["app"].string() + ":" + $0["id"].string() })
        picked = picked.filter { keys.contains($0) }
    }

    private func restore(_ row: JSONValue) {
        busy = true
        Task {
            do {
                _ = try await model.deviceCall("chat/unarchive", body: ["app": row["app"], "id": row["id"]])
                note = "已恢复，回到对话列表里了"
                model.restored(app: row["app"].string(), id: row["id"].string())
            } catch {
                note = (row["app"].string() == "claude" ? "Claude：" : "没恢复：") + describe(error)
            }
            busy = false
            await load()
        }
    }

    private func delete(_ items: [JSONValue]) {
        let chosen = items.filter { picked.contains($0["app"].string() + ":" + $0["id"].string()) }
        busy = true
        Task {
            do {
                let reply = try await model.deviceCall("chat/delete", body: ["items": .array(chosen.map { ["app": $0["app"], "id": $0["id"]] }), "confirmed": true])
                let failed = reply["results"].array.filter { !$0["ok"].bool() }
                note = failed.isEmpty ? "已删除 \(reply["deleted"].int64()) 个对话"
                    : "删了 \(reply["deleted"].int64()) 个，\(failed.count) 个没删：" + (failed.first?["error"].string() ?? "")
            } catch {
                note = "没删除：" + describe(error)
            }
            busy = false
            picked = []
            await load()
        }
    }
}

/// One archived conversation: a round mark to tick it for deleting (only where deleting is possible), its title,
/// its folder and when it was archived, and 恢复.
private struct ArchivedRow: View {
    let row: JSONValue
    let picked: Bool
    let canPick: Bool
    let enabled: Bool
    let pick: () -> Void
    let restore: () -> Void
    @Environment(\.colorScheme) private var scheme

    var body: some View {
        let title = row["title"].string().isEmpty ? "未命名对话" : row["title"].string()
        HStack(spacing: 8) {
            if canPick {
                Button(action: pick) {
                    ZStack {
                        Circle()
                            .fill(picked ? Palette.danger : .clear)
                            .overlay(Circle().stroke(picked ? Palette.danger : (scheme == .dark ? Palette.controlBorder : Color(red: 0xC4 / 255, green: 0xC9 / 255, blue: 0xD4 / 255)), lineWidth: 1.5))
                            .frame(width: 22, height: 22)
                        if picked {
                            Image(systemName: "checkmark")
                                .font(.system(size: 11, weight: .bold))
                                .foregroundStyle(.white)
                        }
                    }
                    .frame(width: 36, height: 44)
                    .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .accessibilityLabel(Text((picked ? "不删除 " : "选中删除 ") + title))
                .accessibilityAddTraits(picked ? .isSelected : [])
            }
            VStack(alignment: .leading, spacing: 2) {
                Text(title)
                    .scaledFont(15, .medium, relativeTo: .callout)
                    .foregroundStyle(Palette.ink)
                    .lineLimit(1)
                let archived = row["archived_at"].int64()
                let updated = row["updated"].int64()
                let when = archived > 0 ? "归档于 " + Labels.ago(stamp(archived)) : updated > 0 ? "最后活动 " + Labels.ago(stamp(updated)) : ""
                let line = [row["folder"].string(), when].filter { !$0.isEmpty }.joined(separator: " · ")
                if !line.isEmpty {
                    Text(line)
                        .captionFont()
                        .foregroundStyle(Palette.muted)
                        .lineLimit(1)
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            Button("恢复", action: restore)
                .buttonStyle(PillStyle(minHeight: 36))
                .disabled(!enabled)
                .accessibilityLabel(Text("恢复 " + title))
        }
        .frame(minHeight: 52)
    }

    /// Seconds or milliseconds since 1970, as milliseconds.
    private func stamp(_ value: Int64) -> Int64 {
        value < 10_000_000_000 ? value * 1000 : value
    }
}
