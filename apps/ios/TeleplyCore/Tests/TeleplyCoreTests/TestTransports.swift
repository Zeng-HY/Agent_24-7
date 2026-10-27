import Foundation
import TeleplyDemo
import TeleplyModel

actor RequestLog {
    private(set) var items: [RelayRequest] = []

    func add(_ request: RelayRequest) {
        items.append(request)
    }
}

/// The value of [name] in a request's address, nil when it has none.
func queryValue(_ request: RelayRequest, _ name: String) -> String? {
    URLComponents(url: request.url, resolvingAgainstBaseURL: false)?.queryItems?.first { $0.name == name }?.value
}

/// The demo computer, keeping every request and download as it was asked for.
struct WatchedTransport: RelayFileTransport {
    let demo: DemoTransport
    let log = RequestLog()

    init(world: DemoWorld = DemoWorld()) {
        demo = DemoTransport(world: world)
    }

    func send(_ request: RelayRequest) async throws -> RelayResponse {
        await log.add(request)
        return try await demo.send(request)
    }

    func download(_ request: RelayRequest, limit: Int64, progress: (@Sendable (Int64, Int64) -> Void)?) async throws -> RelayDownload {
        await log.add(request)
        return try await demo.download(request, limit: limit, progress: progress)
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

/// Answers every download with [status] and [bytes] (a file for a 2xx, the body otherwise) and keeps what was asked.
struct FileAnswerTransport: RelayFileTransport {
    let log = RequestLog()
    let status: Int
    let bytes: Data

    func send(_ request: RelayRequest) async throws -> RelayResponse {
        await log.add(request)
        return RelayResponse(status: 404)
    }

    func download(_ request: RelayRequest, limit: Int64, progress: (@Sendable (Int64, Int64) -> Void)?) async throws -> RelayDownload {
        await log.add(request)
        guard (200..<300).contains(status) else { return RelayDownload(status: status, body: bytes) }
        let file = FileManager.default.temporaryDirectory.appendingPathComponent("teleply-answer-\(UUID().uuidString)")
        try bytes.write(to: file)
        return RelayDownload(status: status, file: file)
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
