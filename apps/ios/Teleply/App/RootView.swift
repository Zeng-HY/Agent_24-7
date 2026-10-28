import SwiftUI
import TeleplyModel
import TeleplyState

/// The window: the opening pages (spec 4.8) or the workspace (the list with the conversation pushed on it, the
/// sidebar over them), with 设置 as a sheet from anywhere. The appearance follows 外观.
struct RootView: View {
    let model: AppModel
    @State private var chrome = Chrome()
    @Environment(\.scenePhase) private var scenePhase

    private enum Page: Hashable { case launch, login, devices, workspace }

    private var page: Page {
        switch model.screen {
        case .launch: return .launch
        case .login: return .login
        case .devices: return .devices
        case .chats, .reading: return .workspace
        }
    }

    var body: some View {
        ZStack {
            switch page {
            case .launch: LaunchView()
            case .login: LoginView(model: model)
            case .devices: DevicesView(model: model)
            case .workspace: WorkspaceView(model: model)
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
/// new conversation's result sheet come up over either.
private struct WorkspaceView: View {
    let model: AppModel
    @Environment(Chrome.self) private var chrome

    var body: some View {
        DrawerHost(model: model, enabled: model.screen == .chats) {
            NavigationStack(path: path) {
                ChatListView(model: model)
                    .navigationDestination(for: WorkspaceRoute.self) { route in
                        switch route {
                        case .reading: ConversationView(model: model)
                        case .detail: DetailPage(model: model)
                        }
                    }
            }
        }
        .sheet(isPresented: newShown) { NewChatSheet(model: model) }
        .sheet(item: jobSheet) { route in NewJobSheet(model: model, request: route.id) }
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
