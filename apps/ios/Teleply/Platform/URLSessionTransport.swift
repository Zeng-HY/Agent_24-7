import Foundation
import TeleplyModel

/// URLSession set up like the Android OkHttp client (RelayApi.kt): no cookie jar, no cache, no stored
/// credentials, redirects handed back instead of followed, nothing retried. The sign-in is added by RelayClient
/// from the keychain. The live stream has its own session: 25 s without a byte counts as dropped (the computer
/// sends a heartbeat every 8 s), and it may stay open for a day.
nonisolated final class URLSessionTransport: RelayStreamingTransport {
    private let session: URLSession
    private let streamSession: URLSession

    init() {
        session = URLSession(configuration: Self.configuration(idle: 30, total: 130), delegate: RedirectRefusal(), delegateQueue: nil)
        streamSession = URLSession(configuration: Self.configuration(idle: 25, total: 86_400), delegate: RedirectRefusal(), delegateQueue: nil)
    }

    static func configuration(idle: TimeInterval, total: TimeInterval) -> URLSessionConfiguration {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.httpCookieStorage = nil
        configuration.httpCookieAcceptPolicy = .never
        configuration.httpShouldSetCookies = false
        configuration.urlCache = nil
        configuration.requestCachePolicy = .reloadIgnoringLocalCacheData
        configuration.urlCredentialStorage = nil
        configuration.waitsForConnectivity = false
        configuration.timeoutIntervalForRequest = idle
        configuration.timeoutIntervalForResource = total
        return configuration
    }

    func send(_ request: RelayRequest) async throws -> RelayResponse {
        let urlRequest = Self.urlRequest(request)
        // The whole call has a deadline (Android callTimeout); the session's own timeout only covers silence.
        let session = session
        return try await withThrowingTaskGroup(of: RelayResponse?.self) { group in
            group.addTask {
                let (data, response) = try await session.data(for: urlRequest)
                return Self.response(data, response)
            }
            group.addTask {
                try await Task.sleep(for: .seconds(request.deadline))
                return nil
            }
            defer { group.cancelAll() }
            guard let first = try await group.next(), let answer = first else { throw URLError(.timedOut) }
            return answer
        }
    }

    func stream(_ request: RelayRequest) async throws -> RelayStream {
        let (bytes, response) = try await streamSession.bytes(for: Self.urlRequest(request))
        let status = (response as? HTTPURLResponse)?.statusCode ?? 0
        nonisolated(unsafe) let source = bytes
        let chunks = AsyncThrowingStream<[UInt8], any Error> { continuation in
            let reader = Task {
                var buffer: [UInt8] = []
                buffer.reserveCapacity(4_096)
                do {
                    for try await byte in source {
                        buffer.append(byte)
                        // Each line goes on at once: an event ends with an empty line, and frames must not wait.
                        if byte == 0x0A || buffer.count >= 65_536 {
                            continuation.yield(buffer)
                            buffer.removeAll(keepingCapacity: true)
                        }
                    }
                    if !buffer.isEmpty { continuation.yield(buffer) }
                    continuation.finish()
                } catch {
                    continuation.finish(throwing: error)
                }
            }
            continuation.onTermination = { _ in reader.cancel() }
        }
        return RelayStream(status: status, chunks: chunks)
    }

    static func urlRequest(_ request: RelayRequest) -> URLRequest {
        var urlRequest = URLRequest(url: request.url)
        urlRequest.httpMethod = request.method.rawValue
        urlRequest.httpBody = request.body
        for (name, value) in request.headers {
            urlRequest.setValue(value, forHTTPHeaderField: name)
        }
        return urlRequest
    }

    static func response(_ data: Data, _ response: URLResponse) -> RelayResponse {
        guard let http = response as? HTTPURLResponse else { return RelayResponse(status: 0, body: data) }
        var headers: [String: String] = [:]
        for (name, value) in http.allHeaderFields {
            if let name = name as? String, let value = value as? String { headers[name.lowercased()] = value }
        }
        return RelayResponse(status: http.statusCode, headers: headers, body: data)
    }
}

/// Hands a redirect back as the answer (a 3xx becomes an error upstream), like followRedirects(false).
/// The completion-handler form on purpose: Xcode 27.1's compiler crashes generating the bridge for the
/// async form of this delegate method (build 6adec0d6…, SILGen emitNativeToForeignThunk).
nonisolated final class RedirectRefusal: NSObject, URLSessionTaskDelegate, Sendable {
    func urlSession(_ session: URLSession, task: URLSessionTask, willPerformHTTPRedirection response: HTTPURLResponse,
                    newRequest request: URLRequest, completionHandler: @escaping @Sendable (URLRequest?) -> Void) {
        completionHandler(nil)
    }
}
