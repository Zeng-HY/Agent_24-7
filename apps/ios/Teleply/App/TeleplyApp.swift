import SwiftUI
import TeleplyModel
import TeleplyState

@main
struct TeleplyApp: App {
    @State private var launch = LaunchModel(client: RelayClient(origin: .default, transport: LaunchOptions.transport()))

    var body: some Scene {
        WindowGroup {
            LaunchView(model: launch)
                .preferredColorScheme(LaunchOptions.colorScheme)
        }
    }
}
