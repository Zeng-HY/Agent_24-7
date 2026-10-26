import SwiftUI
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
            case .active: model.setForeground(true)
            case .background: model.setForeground(false)
            default: break
            }
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
/// and the swipe back work (spec 4.3). The stack follows the model: reading pushes, leaving pops.
private struct WorkspaceView: View {
    let model: AppModel
    @Environment(Chrome.self) private var chrome

    var body: some View {
        DrawerHost(model: model, enabled: model.screen == .chats) {
            NavigationStack(path: path) {
                ChatListView(model: model)
                    .navigationDestination(for: ReadingRoute.self) { _ in
                        ConversationView(model: model)
                    }
            }
        }
    }

    private var path: Binding<[ReadingRoute]> {
        Binding(get: { model.screen == .reading ? [ReadingRoute()] : [] },
                set: { routes in if routes.isEmpty, model.screen == .reading { model.back() } })
    }
}

private struct ReadingRoute: Hashable {}
