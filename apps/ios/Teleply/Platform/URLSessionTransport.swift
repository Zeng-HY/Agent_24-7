import Foundation
import TeleplyModel

/// URLSession set up like the Android OkHttp client (RelayApi.kt): no cookie jar, no cache, no stored
/// credentials, redirects handed back instead of followed, nothing retried. The login cookie is added by hand
/// from the keychain (phase 1).
nonisolated final class URLSessionTransport: RelayTransport {
    private let session: URLSession

    init() {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.httpCookieStorage = nil
        configuration.httpCookieAcceptPolicy = .never
        configuration.httpShouldSetCookies = false
        configuration.urlCache = nil
        configuration.requestCachePolicy = .reloadIgnoringLocalCacheData
        configuration.urlCredentialStorage = nil
        configuration.waitsForConnectivity = false
        configuration.timeoutIntervalForRequest = 30
        configuration.timeoutIntervalForResource = 130
        session = URLSession(configuration: configuration, delegate: RedirectRefusal(), delegateQueue: nil)
    }

    func send(_ request: RelayRequest) async throws -> RelayResponse {
        var urlRequest = URLRequest(url: request.url, timeoutInterval: request.deadline)
        urlRequest.httpMethod = request.method.rawValue
        urlRequest.httpBody = request.body
        for (name, value) in request.headers {
            urlRequest.setValue(value, forHTTPHeaderField: name)
        }
        let (data, response) = try await session.data(for: urlRequest)
        guard let http = response as? HTTPURLResponse else { throw URLError(.badServerResponse) }
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
