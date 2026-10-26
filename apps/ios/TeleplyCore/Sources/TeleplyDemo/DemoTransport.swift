import Foundation
import TeleplyModel

/// The local demo's service (spec 4.6 本地示例; Android FixtureApi). Fixed answers that never reach a real
/// service, with the 示例网络 delay. Phase 0 answers only the launch check; the full demo world (测试电脑 A/B,
/// conversations, special inputs) is ported in phase 1.
public struct DemoTransport: RelayTransport {
    public var delay: Duration

    public init(delay: Duration = .zero) {
        self.delay = delay
    }

    public func send(_ request: RelayRequest) async throws -> RelayResponse {
        if delay > .zero { try await Task.sleep(for: delay) }
        switch (request.method, request.url.path) {
        case (.get, "/account/config"):
            return .json(#"{"version":"fixture","email_enabled":false}"#)
        default:
            return .json(#"{"error":"本地示例没有这个地址"}"#, status: 404)
        }
    }
}
