import Foundation
import TeleplyModel

actor RequestLog {
    private(set) var items: [RelayRequest] = []

    func add(_ request: RelayRequest) {
        items.append(request)
    }
}

/// Answers every call with [reply] and keeps what was sent, like MockWebServer in the Android tests.
struct RecordingTransport: RelayTransport {
    let log = RequestLog()
    let reply: @Sendable (RelayRequest) -> RelayResponse

    func send(_ request: RelayRequest) async throws -> RelayResponse {
        await log.add(request)
        return reply(request)
    }
}

/// A service that cannot be reached at all.
struct UnreachableTransport: RelayTransport {
    struct Offline: Error {}

    func send(_ request: RelayRequest) async throws -> RelayResponse {
        throw Offline()
    }
}
