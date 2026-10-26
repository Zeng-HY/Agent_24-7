import Observation
import TeleplyModel

/// The 0.1.0 logo page: one GET /account/config proves the service's certificate and the phone's network
/// settings on a real iPhone before the read-only app is built on top (plan, phase 0). Becomes the spec 4.8
/// launch step (saved service, login or 我的电脑) in phase 1.
@Observable
public final class LaunchModel {
    // A plain value, usable off the main actor too (this module defaults to the main actor).
    public nonisolated enum Phase: Equatable, Sendable {
        case checking
        case reachable(version: String)
        case unreachable(message: String)
    }

    public private(set) var phase: Phase = .checking
    private let client: RelayClient

    public init(client: RelayClient) {
        self.client = client
    }

    public func check() async {
        phase = .checking
        do {
            let config = try await client.accountConfig()
            phase = .reachable(version: config.version.isEmpty ? "未知" : config.version)
        } catch {
            phase = .unreachable(message: "连不上服务器，请检查网络后重试。")
        }
    }
}
