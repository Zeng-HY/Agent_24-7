import Foundation
import TeleplyModel

/// URLSession set up like the Android OkHttp client (RelayApi.kt): no cookie jar, no cache, no stored
/// credentials, redirects handed back instead of followed, nothing retried. The sign-in is added by RelayClient
/// from the keychain. The live stream has its own session: 25 s without a byte counts as dropped (the computer
/// sends a heartbeat every 8 s), and it may stay open for a day. Files go up and down on a third: up to 15
/// minutes in all, a minute of silence. An upload goes from its file with its length, never in chunks.
nonisolated final class URLSessionTransport: RelayStreamingTransport, RelayFileTransport {
    private let session: URLSession
    private let streamSession: URLSession
    private let fileSession: URLSession

    init() {
        session = URLSession(configuration: Self.configuration(idle: 30, total: 130), delegate: RedirectRefusal(), delegateQueue: nil)
        streamSession = URLSession(configuration: Self.configuration(idle: 25, total: 86_400), delegate: RedirectRefusal(), delegateQueue: nil)
        fileSession = URLSession(configuration: Self.configuration(idle: 60, total: 900), delegate: RedirectRefusal(), delegateQueue: nil)
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
        let upload = request.upload
        let session = upload == nil ? session : fileSession
        return try await withThrowingTaskGroup(of: RelayResponse?.self) { group in
            group.addTask {
                let answer: (Data, URLResponse)
                if let upload {
                    answer = try await session.upload(for: urlRequest, fromFile: upload)
                } else {
                    answer = try await session.data(for: urlRequest)
                }
                return Self.response(answer.0, answer.1)
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

    /// Downloads to a file of our own (the system deletes its own when this returns); one bigger than [limit] is
    /// refused rather than kept cut short.
    func download(_ request: RelayRequest, limit: Int64) async throws -> RelayDownload {
        let (temporary, response) = try await fileSession.download(for: Self.urlRequest(request))
        let status = (response as? HTTPURLResponse)?.statusCode ?? 0
        let folder = FileManager.default.temporaryDirectory.appendingPathComponent("teleply-file-" + UUID().uuidString)
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        let kept = folder.appendingPathComponent("download")
        try FileManager.default.moveItem(at: temporary, to: kept)
        guard (200..<300).contains(status) else {
            let body = (try? Data(contentsOf: kept)).map { Data($0.prefix(65_536)) } ?? Data()
            try? FileManager.default.removeItem(at: folder)
            return RelayDownload(status: status, body: body)
        }
        let size = ((try? FileManager.default.attributesOfItem(atPath: kept.path))?[.size] as? NSNumber)?.int64Value ?? 0
        guard size <= limit else {
            try? FileManager.default.removeItem(at: folder)
            throw ReadFailure("文件超过100MB，请在电脑上打开")
        }
        return RelayDownload(status: status, file: kept)
    }

    func stream(_ request: RelayRequest) async throws -> RelayStream {
        let (bytes, response) = try await streamSession.bytes(for: Self.urlRequest(request))
        let status = (response as? HTTPURLResponse)?.statusCode ?? 0
        let source = bytes
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
