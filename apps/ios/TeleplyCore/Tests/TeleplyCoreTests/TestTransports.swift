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

/// Plays a live stream: the given status, then the chunks as they would arrive.
struct StreamingTransport: RelayStreamingTransport {
    let log = RequestLog()
    let status: Int
    let chunks: [[UInt8]]

    func send(_ request: RelayRequest) async throws -> RelayResponse {
        await log.add(request)
        return RelayResponse(status: 404)
    }

    func stream(_ request: RelayRequest) async throws -> RelayStream {
        await log.add(request)
        let chunks = chunks
        return RelayStream(status: status, chunks: AsyncThrowingStream { continuation in
            for chunk in chunks { continuation.yield(chunk) }
            continuation.finish()
        })
    }
}

/// A service that cannot be reached at all.
struct UnreachableTransport: RelayTransport {
    struct Offline: Error {}

    func send(_ request: RelayRequest) async throws -> RelayResponse {
        throw Offline()
    }
}
