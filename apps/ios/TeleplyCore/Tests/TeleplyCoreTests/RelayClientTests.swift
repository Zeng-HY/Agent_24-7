import Foundation
import Testing
@testable import TeleplyModel

struct RelayClientTests {
    @Test func getAsksForJSONWithoutOriginOrBody() async throws {
        let transport = RecordingTransport { _ in .json(#"{"version":"0.27.0-dev.16","email_enabled":true}"#) }
        let client = RelayClient(origin: .default, transport: transport)
        #expect(try await client.accountConfig() == AccountConfig(version: "0.27.0-dev.16", emailEnabled: true))
        let sent = await transport.log.items
        #expect(sent.count == 1)
        #expect(sent.first?.method == .get)
        #expect(sent.first?.url.absoluteString == "https://app.pocketagentdesk.com/account/config")
        #expect(sent.first?.headers == ["Accept": "application/json"])
        #expect(sent.first?.body == nil)
        #expect(sent.first?.deadline == 40)
    }

    @Test func postCarriesTheExactOrigin() throws {
        let client = RelayClient(origin: .default, transport: RecordingTransport { _ in .json("{}") })
        let request = try client.post("/account/select", json: ["id": "0123456789abcdef0123456789abcdef"])
        #expect(request.method == .post)
        #expect(request.headers["Origin"] == "https://app.pocketagentdesk.com")
        #expect(request.headers["Accept"] == "application/json")
        #expect(request.headers["Content-Type"] == "application/json; charset=utf-8")
        let body = try JSONValue.parse(try #require(request.body))
        #expect(body["id"].string() == "0123456789abcdef0123456789abcdef")
    }

    @Test func failuresKeepTheComputersWords() async {
        let client = RelayClient(origin: .default, transport: RecordingTransport { _ in
            .json(#"{"error":"电脑已离线，请等待上线后再连接","code":"device_offline"}"#, status: 409)
        })
        await #expect(throws: ServiceFailure(status: 409, code: "device_offline", detail: "电脑已离线，请等待上线后再连接")) {
            _ = try await client.accountConfig()
        }
    }

    @Test func failureMessagesMatchAndroid() {
        #expect(ServiceFailure(status: 401).message == "登录已失效，请重新登录；当前阅读位置已保留。")
        #expect(ServiceFailure(status: 409, code: "device_offline").message == "电脑已离线，请稍后刷新电脑列表。")
        #expect(ServiceFailure(status: 503).message == "电脑已离线，请稍后刷新电脑列表。")
        #expect(ServiceFailure(status: 403).message == "服务拒绝访问，请核对服务地址或账号权限。")
        #expect(ServiceFailure(status: 404).message == "记录或电脑已不可用，请刷新列表。")
        #expect(ServiceFailure(status: 302).message == "服务返回了跳转，请在设置中填写正确的 HTTPS 服务地址。")
        #expect(ServiceFailure(status: 500, detail: "电脑上的服务出错").message == "电脑上的服务出错")
        #expect(ServiceFailure(status: 500).message == "请求失败（HTTP 500），请核对后重试。")
    }

    @Test func refusesOversizedOrUnreadableAnswers() async {
        let big = RelayClient(origin: .default, transport: RecordingTransport { _ in
            RelayResponse(status: 200, body: Data(count: RelayClient.jsonLimit + 1))
        })
        await #expect(throws: RelayError.tooLarge) { _ = try await big.accountConfig() }
        let page = RelayClient(origin: .default, transport: RecordingTransport { _ in RelayResponse(status: 200, body: Data("<html>".utf8)) })
        await #expect(throws: RelayError.unreadable) { _ = try await page.accountConfig() }
    }
}
