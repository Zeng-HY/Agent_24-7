import Foundation
import TeleplyModel

/// The local demo's service (spec 4.6 本地示例; Android FixtureApi). Fixed answers that never reach a real
/// service, with the 示例网络 delay. Phase 0 answers only the launch check; the full demo world (测试电脑 A/B,
/// conversations, special inputs) is ported in phase 1.
public struct DemoTransport: RelayTransport {
    public struct Unreachable: Error {}

    public var delay: Duration
    /// The whole demo service down, so screenshot tests can show the launch page's "连不上服务器" state.
    public var unreachable: Bool

    public init(delay: Duration = .zero, unreachable: Bool = false) {
        self.delay = delay
        self.unreachable = unreachable
    }

    public func send(_ request: RelayRequest) async throws -> RelayResponse {
        if delay > .zero { try await Task.sleep(for: delay) }
        if unreachable { throw Unreachable() }
        switch (request.method, request.url.path) {
        case (.get, "/account/config"):
            return .json(#"{"version":"fixture","email_enabled":false}"#)
        default:
            return .json(#"{"error":"本地示例没有这个地址"}"#, status: 404)
        }
    }
}
