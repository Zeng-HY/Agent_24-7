import SwiftUI
import TeleplyModel
import TeleplyState

@main
struct TeleplyApp: App {
    @State private var model: AppModel

    init() {
        let vault = KeychainVault()
        // The keychain outlives the app; a reinstall starts signed out (plan: 登录).
        vault.forgetAfterReinstall()
        CrashReports.shared.start()
        DiagnosticsLog.shared.note("启动 遥应 \(AppVersion.display)")
        let model = AppModel(services: AppServices(
            store: LocalStore(folder: StoreFolder.url()),
            vault: vault,
            transport: LaunchOptions.transport(),
            demo: { DemoHolder.shared.fresh() }))
        if LaunchOptions.usesDemo {
            model.openDemo()
        } else {
            model.start()
        }
        _model = State(initialValue: model)
    }

    var body: some Scene {
        WindowGroup {
            RootView(model: model)
        }
    }
}
