import Foundation

public enum HTTPMethod: String, Sendable {
    case get = "GET"
    case post = "POST"
}

/// One call to the relay, built here and carried out by a RelayTransport (URLSession on the phone, a fake in
/// tests and the local demo).
public struct RelayRequest: Sendable, Equatable {
    public var method: HTTPMethod
    public var url: URL
    public var headers: [String: String]
    public var body: Data?
    /// Seconds the whole call may take (Android callTimeout: 40 s, longer for the slow routes).
    public var deadline: TimeInterval

    public init(method: HTTPMethod, url: URL, headers: [String: String], body: Data? = nil, deadline: TimeInterval) {
        self.method = method
        self.url = url
        self.headers = headers
        self.body = body
        self.deadline = deadline
    }
}

public struct RelayResponse: Sendable, Equatable {
    public var status: Int
    /// Header names in lower case.
    public var headers: [String: String]
    public var body: Data

    public init(status: Int, headers: [String: String] = [:], body: Data = Data()) {
        self.status = status
        self.headers = headers
        self.body = body
    }

    public static func json(_ text: String, status: Int = 200) -> RelayResponse {
        RelayResponse(status: status, headers: ["content-type": "application/json"], body: Data(text.utf8))
    }
}

public protocol RelayTransport: Sendable {
    func send(_ request: RelayRequest) async throws -> RelayResponse
}

/// Builds requests the way the relay's guard wants them (relay_service.py): every call asks for JSON, a GET
/// carries no body and no Origin, a POST carries Origin equal to the service address. Nothing is followed or
/// retried here; writes are never sent twice (Android RelayApi).
public struct RelayClient: Sendable {
    public static let jsonLimit = 8 * 1024 * 1024
    public static let defaultDeadline: TimeInterval = 40

    public let origin: ServiceOrigin
    public let transport: any RelayTransport

    public init(origin: ServiceOrigin, transport: any RelayTransport) {
        self.origin = origin
        self.transport = transport
    }

    public func get(_ path: String, query: [(String, String?)] = [], deadline: TimeInterval = defaultDeadline) -> RelayRequest {
        RelayRequest(method: .get, url: origin.url(path, query: query), headers: ["Accept": "application/json"], deadline: deadline)
    }

    public func post(_ path: String, json: JSONValue, query: [(String, String?)] = [], deadline: TimeInterval = defaultDeadline) throws -> RelayRequest {
        RelayRequest(method: .post, url: origin.url(path, query: query),
                     headers: ["Accept": "application/json", "Content-Type": "application/json; charset=utf-8", "Origin": origin.header],
                     body: try json.encoded(), deadline: deadline)
    }

    /// Sends and reads a JSON answer; a status outside 2xx (redirects included) becomes a ServiceFailure.
    public func json(_ request: RelayRequest) async throws -> JSONValue {
        let response = try await transport.send(request)
        guard response.body.count <= Self.jsonLimit else { throw RelayError.tooLarge }
        guard (200..<300).contains(response.status) else { throw ServiceFailure(status: response.status, body: response.body) }
        do { return try JSONValue.parse(response.body) } catch { throw RelayError.unreadable }
    }

    /// The service version and whether email sign-up and resets are open (web account page).
    public func accountConfig() async throws -> AccountConfig {
        AccountConfig(try await json(get("/account/config")))
    }
}

public enum RelayError: Error, Sendable, Equatable {
    case tooLarge
    case unreadable

    public var message: String {
        switch self {
        case .tooLarge: return "内容过大，请缩小读取范围"
        case .unreadable: return "服务返回的内容读不出来，请稍后重试。"
        }
    }
}

/// An answer outside 2xx, with the computer's own error text when it gave one (Android ServiceFailure).
/// [draft] is the text found in Claude's box on the computer when that turned a send away (desktop_draft).
public struct ServiceFailure: Error, Sendable, Equatable {
    public let status: Int
    public let code: String
    public let detail: String
    public let notSubmitted: Bool
    public let draft: String

    public init(status: Int, code: String = "", detail: String = "", notSubmitted: Bool = false, draft: String = "") {
        self.status = status
        self.code = code
        self.detail = detail
        self.notSubmitted = notSubmitted
        self.draft = draft
    }

    public init(status: Int, body: Data) {
        let error = (try? JSONValue.parse(body)) ?? .null
        self.init(status: status, code: error["code"].string(), detail: error["error"].string(),
                  notSubmitted: error["not_submitted"].bool(), draft: error["draft"].string())
    }

    public var message: String {
        if status == 401 { return "登录已失效，请重新登录；当前阅读位置已保留。" }
        if (status == 409 && code == "device_offline") || status == 503 { return "电脑已离线，请稍后刷新电脑列表。" }
        if status == 403 { return "服务拒绝访问，请核对服务地址或账号权限。" }
        if status == 404 { return "记录或电脑已不可用，请刷新列表。" }
        if (300...399).contains(status) { return "服务返回了跳转，请在设置中填写正确的 HTTPS 服务地址。" }
        let shown = String(detail.prefix(500))
        return shown.isEmpty ? "请求失败（HTTP \(status)），请核对后重试。" : shown
    }
}
