import SwiftUI
import TeleplyModel
import TeleplyState
import UIKit

/// The window: the opening pages (spec 4.8) or the workspace (the list with the conversation pushed on it, the
/// sidebar over them), with 设置 as a sheet from anywhere. The appearance follows 外观. On an iPad whose window is
/// wide enough the workspace is two columns: the list on the left, the conversation on the right (the view tells the
/// model with [AppModel.setSideBySide], so the list keeps being read there).
struct RootView: View {
    let model: AppModel
    @State private var chrome = Chrome()
    @Environment(\.scenePhase) private var scenePhase
    /// 调试用: show the app as if the window were narrow (a developer switch, or the screenshot tour's launch
    /// argument `-TeleplyForceNarrow`). Always false in a release build.
    @AppStorage("TeleplyForceNarrow") private var forceNarrowSetting = false

    private var forceNarrow: Bool {
        #if DEBUG
        // A debug build's switch stays behind: a TestFlight or App Store build must never open as a narrow column.
        return forceNarrowSetting || LaunchOptions.forceNarrow
        #else
        return false
        #endif
    }

    private enum Page: Hashable { case launch, login, devices, workspace }

    /// Below this width an iPad window shows one page at a time, as the phone does. iPad mini portrait is about 744
    /// points and already two columns; a half or third of the screen is narrower and stays one.
    private static let columnsFrom: CGFloat = 700
    /// The narrow preview's width, about a phone's.
    private static let narrowPreview: CGFloat = 480

    private var page: Page {
        switch model.screen {
        case .launch: return .launch
        case .login: return .login
        case .devices: return .devices
        case .chats, .reading: return .workspace
        }
    }

    var body: some View {
        GeometryReader { geometry in
            let wide = isWide(for: geometry.size.width)
            content(wide: wide, windowWidth: geometry.size.width)
                // The model runs the list's 10 s read beside an open conversation only in this mode.
                .onChange(of: wide, initial: true) { _, on in model.setSideBySide(on) }
                .frame(maxWidth: forceNarrow ? Self.narrowPreview : .infinity)
                .frame(maxWidth: .infinity, maxHeight: .infinity)
        }
        .background(Palette.page)
    }

    /// Two columns are an iPad's, and only from [columnsFrom] on; an iPhone, portrait or landscape, always stays on
    /// the page it showed before.
    private func isWide(for width: CGFloat) -> Bool {
        UIDevice.current.userInterfaceIdiom == .pad && width >= Self.columnsFrom && !forceNarrow
    }

    @ViewBuilder
    private func content(wide: Bool, windowWidth: CGFloat) -> some View {
        ZStack {
            switch page {
            case .launch: LaunchView()
            case .login: LoginView(model: model)
            case .devices: DevicesView(model: model)
            case .workspace: WorkspaceView(model: model, wide: wide, windowWidth: windowWidth)
            }
        }
        .animation(.easeOut(duration: 0.2), value: page)
        .overlay(alignment: .top) { SpeedToast() }
        .environment(chrome)
        .sheet(isPresented: $chrome.settings) {
            SettingsView(model: model)
                .environment(chrome)
                .preferredColorScheme(colorScheme)
        }
        .preferredColorScheme(colorScheme)
        // Only a real move to the background stops the live connection; Control Center pulled down for a
        // moment (inactive) keeps it (plan: 真正退到后台才断开).
        .onChange(of: scenePhase) {
            switch scenePhase {
            case .active:
                model.setForeground(true)
                Task { await model.islandLaunch() }
            case .background: model.setForeground(false)
            default: break
            }
        }
        .task { await model.islandLaunch() }
        // A tap on the island opens teleply://open?d=…&a=…&c=… (handoff 5.3): only 遥应's own three ids are taken,
        // and the computer and source are checked once signed in.
        .onOpenURL { url in
            if let target = PushTarget(url: url) { model.openNotification(target) }
            else if let target = IslandListTarget(url: url) { model.openIslandList(target) }
        }
        // A tapped notification waits for the launch or a sign-in (AppModel+Push); signed in, the account gets
        // this phone's 遥应通知 again when it is wanted.
        .onChange(of: model.busy) { model.resumeNotification() }
        .onChange(of: model.screen) { before, _ in
            model.resumeNotification()
            if before == .launch || before == .login { model.pushSync() }
            Task { await model.islandLaunch() }
        }
    }

    private var colorScheme: ColorScheme? {
        if let forced = LaunchOptions.colorScheme { return forced }
        switch model.theme {
        case "light": return .light
        case "dark": return .dark
        default: return nil
        }
    }
}

/// The list as the root of a navigation stack and the open conversation pushed on it, so the system back button
/// and the swipe back work (spec 4.3). The stack follows the model: reading pushes, leaving pops. 新建对话 and a
/// new conversation's result sheet come up over either. In a wide window on an iPad the list and the conversation
/// stand side by side instead, each in its own place: the list column on the left, the conversation (and a file or
/// 本轮差异 over it) in a stack on the right.
private struct WorkspaceView: View {
    let model: AppModel
    /// The window is wide enough for both columns.
    let wide: Bool
    /// The window's width, which sizes the list column.
    let windowWidth: CGFloat
    @Environment(Chrome.self) private var chrome

    var body: some View {
        Group {
            if wide { columns } else { single }
        }
        .sheet(isPresented: newShown) { NewChatSheet(model: model) }
        .sheet(item: jobSheet) { route in NewJobSheet(model: model, request: route.id) }
    }

    /// One page at a time: exactly the way a phone shows the list and the conversation pushed on it.
    private var single: some View {
        DrawerHost(model: model, enabled: model.screen == .chats) {
            NavigationStack(path: path) {
                ChatListView(model: model)
                    .navigationDestination(for: WorkspaceRoute.self) { route in destination(route) }
            }
        }
    }

    /// The list on the left, the conversation on the right. Pulling the sidebar out stays the list page's gesture,
    /// so it cannot fight the conversation's swipe back; the list's ☰ is always there.
    private var columns: some View {
        DrawerHost(model: model, enabled: model.screen == .chats) {
            HStack(spacing: 0) {
                ChatListView(model: model)
                    .frame(width: columnWidth)
                Rectangle()
                    .fill(Palette.line)
                    .frame(width: 1)
                NavigationStack(path: path) {
                    WidePlaceholder()
                        .navigationDestination(for: WorkspaceRoute.self) { route in destination(route) }
                }
            }
        }
    }

    /// 320 points is the sidebar's own width, and enough for the list's title bar and rows; 380 at most, so the
    /// conversation keeps the room.
    private var columnWidth: CGFloat { min(380, max(320, windowWidth * 0.36)) }

    @ViewBuilder
    private func destination(_ route: WorkspaceRoute) -> some View {
        switch route {
        case .reading:
            ConversationView(model: model)
                // Two columns have no page to go back to: another row on the left replaces this one.
                .navigationBarBackButtonHidden(wide)
        case .detail:
            DetailPage(model: model)
        }
    }

    /// A file's page and 本轮差异 are pushed over the conversation (spec 4.5): the system back leaves them.
    private var path: Binding<[WorkspaceRoute]> {
        Binding(get: {
            guard model.screen == .reading else { return [] }
            return ["file", "diff"].contains(model.workspace.pane ?? "") ? [.reading, .detail] : [.reading]
        }, set: { routes in
            if routes.isEmpty, model.screen == .reading {
                model.back()
            } else if routes.count == 1, ["file", "diff"].contains(model.workspace.pane ?? "") {
                model.workspace.close()
            }
        })
    }

    /// Up while the workspace holds the sheet open, and while a source switch inside it binds another source.
    private var newShown: Binding<Bool> {
        Binding(get: { model.workspace.pane == "new" || model.pendingNew?.switching == true },
                set: { shown in
                    guard !shown else { return }
                    model.workspace.close()
                    model.consumeNew()
                })
    }

    private var jobSheet: Binding<JobSheetRoute?> {
        Binding(get: { model.jobSheet.map(JobSheetRoute.init) }, set: { if $0 == nil { model.closeJobSheet() } })
    }
}

/// The right column with no conversation open: a quiet place, not a blank page.
private struct WidePlaceholder: View {
    var body: some View {
        VStack(spacing: 14) {
            Image(systemName: "bubble.left.and.bubble.right")
                .font(.system(size: 34, weight: .light))
                .foregroundStyle(Palette.muted)
            Text("从左边选一个对话")
                .bodyFont()
                .foregroundStyle(Palette.muted)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(Palette.page)
        .navigationTitle("")
        .navigationBarTitleDisplayMode(.inline)
    }
}

private enum WorkspaceRoute: Hashable {
    case reading
    case detail
}

/// The page pushed over the conversation: a file or 本轮差异, whichever the workspace holds.
private struct DetailPage: View {
    let model: AppModel

    var body: some View {
        if model.workspace.pane == "diff" {
            DiffPage(model: model)
        } else {
            FilePage(model: model)
        }
    }
}

private struct JobSheetRoute: Identifiable {
    let id: String
}
