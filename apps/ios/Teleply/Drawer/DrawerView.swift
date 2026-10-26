import SwiftUI
import TeleplyModel
import TeleplyState

/*
 * The sidebar (spec 4.2; web static/sidebar-ui.js; Android DrawerUi.kt): each source behind its own mark, its
 * projects behind a folder (其他对话 behind a speech bubble) with a chevron that turns, the conversations indented
 * with a breathing dot while they run. Opening brings the sources in one after another; folding fades.
 */

/// The drawer and the web's spring, cubic-bezier(.32,.72,0,1).
extension Animation {
    static func drawer(_ duration: Double = 0.34) -> Animation { .timingCurve(0.32, 0.72, 0, 1, duration: duration) }
}

/// Which groups are folded, kept on this phone (Android "folds"): "app:<app>" is a shut source; "open:project:…"
/// a project opened. Sources start open, projects shut (web sidebar).
@Observable
final class DrawerFolds {
    private(set) var keys: Set<String>
    @ObservationIgnored private let defaults: UserDefaults

    init(defaults: UserDefaults = .standard) {
        self.defaults = defaults
        keys = Set(defaults.stringArray(forKey: "teleply.drawer.folds") ?? [])
    }

    func toggle(_ key: String) {
        if keys.contains(key) { keys.remove(key) } else { keys.insert(key) }
        defaults.set(Array(keys).sorted(), forKey: "teleply.drawer.folds")
    }
}

struct DrawerView: View {
    let model: AppModel
    /// Goes up each time the drawer opens, to play the sources' arrival again (web lbrRowIn).
    let opening: Int
    let close: () -> Void
    @Environment(Chrome.self) private var chrome
    @State private var folds = DrawerFolds()

    var body: some View {
        VStack(spacing: 0) {
            HStack {
                Text("电脑遥控")
                    .chatTitleFont()
                    .foregroundStyle(Palette.ink)
                    .accessibilityAddTraits(.isHeader)
                Spacer()
                Button(action: close) {
                    Image(systemName: "xmark")
                        .font(.system(size: 17, weight: .medium))
                        .frame(width: 30, height: 30)
                }
                .buttonStyle(.glass)
                .buttonBorderShape(.circle)
                .keyboardShortcut(.cancelAction)
                .accessibilityLabel(Text("关闭导航"))
            }
            .padding(.leading, 20)
            .padding(.trailing, 12)
            .padding(.top, 8)
            .padding(.bottom, 4)
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 0) {
                    tree
                }
                .padding(.horizontal, 8)
                .padding(.bottom, 12)
            }
            footer
        }
        .background {
            UnevenRoundedRectangle(cornerRadii: .init(bottomTrailing: 20, topTrailing: 20), style: .continuous)
                .fill(Palette.panel)
                .ignoresSafeArea()
        }
    }

    @ViewBuilder
    private var tree: some View {
        if let error = model.treeError {
            NoteBar(text: error, tone: .error, action: "重试", onAction: model.retrySources)
                .clipShape(RoundedRectangle(cornerRadius: 16, style: .continuous))
        }
        let apps = model.tree["apps"].array
        if apps.isEmpty && model.treeError == nil {
            Text(model.device == nil ? "先选择一台电脑" : "读取中…")
                .noteFont()
                .foregroundStyle(Palette.muted)
                .padding(12)
        }
        ForEach(Array(apps.enumerated()), id: \.offset) { index, group in
            let app = group["app"].string()
            let appKey = "app:" + app
            let appOpen = !folds.keys.contains(appKey)
            TreeApp(app: app, name: group["name"].string().isEmpty ? Labels.sourceName(app) : group["name"].string(), open: appOpen) {
                withAnimation(.drawer()) { folds.toggle(appKey) }
            }
            .modifier(Arrive(index: index + 1, serial: opening))
            if appOpen {
                let projects = group["projects"].array
                if projects.isEmpty {
                    Text("没有对话")
                        .noteFont()
                        .foregroundStyle(Palette.muted)
                        .padding(.leading, 12)
                        .padding(.vertical, 8)
                        .transition(.opacity)
                }
                ForEach(Array(projects.enumerated()), id: \.offset) { _, project in
                    projectRows(app: app, project: project)
                }
            }
        }
    }

    @ViewBuilder
    private func projectRows(app: String, project: JSONValue) -> some View {
        let key = "project:\(app):\(project["key"].string())"
        let open = folds.keys.contains("open:" + key)
        TreeProject(name: project["name"].string(), projectless: project["projectless"].bool(), open: open) {
            withAnimation(.drawer()) { folds.toggle("open:" + key) }
        }
        .transition(.opacity)
        if open {
            let items = project["items"].array
            ForEach(Array(items.enumerated()), id: \.offset) { _, row in
                let chat = treeChat(row, app: app)
                TreeChat(chat: chat, place: row["place"].string(), current: chat.id == model.chat?.id && chat.app == model.app) {
                    close()
                    model.open(chat)
                }
                .transition(.opacity)
            }
            let left = project["count"].int() - items.count
            if left > 0 {
                Button {
                    model.moreTree(app: app, project: project["key"].string())
                } label: {
                    Text("显示更多（还有 \(left) 个）")
                        .noteFont()
                        .foregroundStyle(Palette.accent)
                        .frame(maxWidth: .infinity, minHeight: 40, alignment: .leading)
                        .padding(.leading, 43)
                }
                .buttonStyle(RowPressStyle(radius: 12))
                .transition(.opacity)
            }
        }
    }

    private func treeChat(_ row: JSONValue, app: String) -> Chat {
        var chat = Chat(id: row["id"].string(), title: row["title"].string().isEmpty ? "未命名对话" : row["title"].string())
        chat.folder = row["folder"].string()
        chat.status = row["status"].string()
        chat.app = row["app"].string().isEmpty ? app : row["app"].string()
        chat.updated = row["updated"].int64()
        return chat
    }

    private var footer: some View {
        let (dot, text): (Color, String) = {
            if model.fixture { return (Palette.warning, "本地示例，未连接真实服务") }
            if model.expired { return (Palette.danger, "登录已失效") }
            guard let device = model.device else { return (Palette.muted, "没有选择电脑") }
            if model.error != nil { return (Palette.warning, "\(device.label) · 连接有问题") }
            return (Palette.success, "\(device.label) · 已连接")
        }()
        return HStack(spacing: 10) {
            Circle().fill(dot).frame(width: 10, height: 10)
            Text(text)
                .noteFont()
                .foregroundStyle(Palette.muted)
                .lineLimit(2)
                .frame(maxWidth: .infinity, alignment: .leading)
            GlassIconButton(symbol: "gearshape", label: "设置") {
                close()
                chrome.settings = true
            }
        }
        .padding(.leading, 20)
        .padding(.trailing, 12)
        .padding(.top, 4)
        .padding(.bottom, 8)
    }
}

/// A source arriving as the drawer opens (web lbrRowIn): 10 pt from the left over 300 ms, 24 ms after the one
/// above. Nothing moves with Reduce Motion.
private struct Arrive: ViewModifier {
    let index: Int
    let serial: Int
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var shown = true

    func body(content: Content) -> some View {
        content
            .opacity(shown ? 1 : 0)
            .offset(x: shown ? 0 : -10)
            .task(id: serial) {
                guard serial > 0, !reduceMotion else { return }
                var still = Transaction()
                still.disablesAnimations = true
                withTransaction(still) { shown = false }
                try? await Task.sleep(for: .milliseconds(20 + index * 24))
                withAnimation(.drawer(0.3)) { shown = true }
            }
    }
}

/// The chevron of a group: points right when shut, turns down as it opens (web .tree-chev, 340 ms).
private struct Chevron: View {
    let open: Bool

    var body: some View {
        Image(systemName: "chevron.right")
            .font(.system(size: 13, weight: .semibold))
            .foregroundStyle(Palette.muted)
            .rotationEffect(.degrees(open ? 90 : 0))
            .animation(.drawer(), value: open)
            .accessibilityHidden(true)
    }
}

/// A source (web .tree-app): its mark, its name, the chevron; a tap folds it.
private struct TreeApp: View {
    let app: String
    let name: String
    let open: Bool
    let toggle: () -> Void

    var body: some View {
        Button(action: toggle) {
            HStack(spacing: 9) {
                SourceMark(app: app)
                Text(name)
                    .scaledFont(14, .semibold, relativeTo: .subheadline)
                    .foregroundStyle(Palette.ink)
                    .lineLimit(1)
                    .frame(maxWidth: .infinity, alignment: .leading)
                Chevron(open: open)
            }
            .padding(.horizontal, 12)
            .frame(minHeight: 42)
        }
        .buttonStyle(RowPressStyle(radius: 12))
        .padding(.top, 12)
        .accessibilityValue(Text(open ? "已展开" : "已收起"))
    }
}

/// A project (web .tree-proj): the folder (or the bubble of 其他对话), its name and the chevron. The ＋ for a new
/// conversation there arrives with 新建对话 in 0.4.0.
private struct TreeProject: View {
    let name: String
    let projectless: Bool
    let open: Bool
    let toggle: () -> Void
    @Environment(\.colorScheme) private var scheme

    var body: some View {
        Button(action: toggle) {
            HStack(spacing: 9) {
                Image(systemName: projectless ? "bubble.left" : "folder")
                    .font(.system(size: 17, weight: .regular))
                    .foregroundStyle(scheme == .dark ? Palette.muted : Color(red: 0x60 / 255, green: 0x69 / 255, blue: 0x75 / 255))
                    .frame(width: 24, height: 24)
                    .accessibilityHidden(true)
                Text(name)
                    .scaledFont(15, .medium, relativeTo: .callout)
                    .foregroundStyle(Palette.ink)
                    .lineLimit(1)
                    .frame(maxWidth: .infinity, alignment: .leading)
                Chevron(open: open)
            }
            .padding(.horizontal, 12)
            .frame(minHeight: 44)
        }
        .buttonStyle(RowPressStyle(radius: 12))
        .accessibilityValue(Text(open ? "已展开" : "已收起"))
    }
}

/// A conversation (web .tree-item): indented, a breathing green dot while it runs (amber while it waits), its time.
private struct TreeChat: View {
    let chat: Chat
    let place: String
    let current: Bool
    let open: () -> Void

    var body: some View {
        Button(action: open) {
            ZStack(alignment: .leading) {
                if chat.status == "running" || chat.status == "waiting" {
                    StatusDot(running: chat.status == "running")
                        .padding(.leading, 22.5)
                }
                HStack(spacing: 8) {
                    VStack(alignment: .leading, spacing: 0) {
                        Text(chat.title)
                            .scaledFont(14, relativeTo: .subheadline)
                            .foregroundStyle(current ? Palette.selectedInk : Palette.ink)
                            .lineLimit(1)
                        if !place.isEmpty {
                            Text(place)
                                .captionFont()
                                .foregroundStyle(Palette.muted)
                                .lineLimit(1)
                        }
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                    let ago = Labels.ago(chat.updated)
                    if !ago.isEmpty {
                        Text(ago)
                            .captionFont()
                            .monospacedDigit()
                            .foregroundStyle(Palette.muted)
                            .lineLimit(1)
                    }
                }
                .padding(.leading, 43)
                .padding(.trailing, 12)
                .padding(.vertical, 8)
            }
            .frame(maxWidth: .infinity, minHeight: 40, alignment: .leading)
            .background(current ? Palette.selectedFill : .clear, in: RoundedRectangle(cornerRadius: 12, style: .continuous))
        }
        .buttonStyle(RowPressStyle(radius: 12))
        .accessibilityAddTraits(current ? .isSelected : [])
    }
}

/// 7 pt; while running a ring breathes out of it every 1.8 s (web .tree-dot::after lbrPing). No ring with
/// Reduce Motion.
struct StatusDot: View {
    let running: Bool
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var ping = false

    var body: some View {
        let color = running ? Palette.success : Palette.warning
        ZStack {
            if running && !reduceMotion {
                Circle()
                    .fill(color)
                    .frame(width: 7, height: 7)
                    .scaleEffect(ping ? 2.8 : 1)
                    .opacity(ping ? 0 : 0.55)
                    .onAppear {
                        withAnimation(.drawer(1.8).repeatForever(autoreverses: false)) { ping = true }
                    }
            }
            Circle().fill(color).frame(width: 7, height: 7)
        }
        .frame(width: 7, height: 7)
        .accessibilityElement()
        .accessibilityLabel(Text(running ? "运行中" : "等待你处理"))
    }
}
