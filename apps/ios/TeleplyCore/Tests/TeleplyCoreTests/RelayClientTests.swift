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
        #expect(sent.first?.url.absoluteString == "https://8.166.15.235/account/config")
        #expect(sent.first?.headers == ["Accept": "application/json"])
        #expect(sent.first?.body == nil)
        #expect(sent.first?.deadline == 40)
    }

    @Test func postCarriesTheExactOrigin() throws {
        let client = RelayClient(origin: .default, transport: RecordingTransport { _ in .json("{}") })
        let request = try client.post("/account/select", json: ["id": "0123456789abcdef0123456789abcdef"])
        #expect(request.method == .post)
        #expect(request.headers["Origin"] == "https://8.166.15.235")
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

    /// GET /api/file/pdf (Windows dev.26): the long deadline of a download; the computer's refusal keeps its words; what
    /// is not a PDF, or more than 20 MB of one, is refused here.
    @Test func anOfficeFilesPDFIsAskedForOnceAndChecked() async throws {
        let device = String(repeating: "a", count: 32)
        let pdf = FileAnswerTransport(status: 200, bytes: Data("%PDF-1.4\n%%EOF\n".utf8))
        let file = try await RelayClient(origin: .default, transport: pdf).pdfPreview(device: device, app: "deepseek", chat: "c1", file: "f1")
        #expect(try Data(contentsOf: file) == Data("%PDF-1.4\n%%EOF\n".utf8))
        let asked = await pdf.log.items
        #expect(asked.count == 1)
        #expect(asked.first?.method == .get && asked.first?.url.path == "/d/\(device)/api/file/pdf" && asked.first?.deadline == 300)
        #expect(asked.first.map { [queryValue($0, "app"), queryValue($0, "id"), queryValue($0, "file")] } == ["deepseek", "c1", "f1"])
        let refused = FileAnswerTransport(status: 503, bytes: Data(#"{"error":"这台电脑没有装 Office，不能转成 PDF"}"#.utf8))
        await #expect(throws: ServiceFailure(status: 503, detail: "这台电脑没有装 Office，不能转成 PDF")) {
            _ = try await RelayClient(origin: .default, transport: refused).pdfPreview(device: device, app: "codex", chat: "c1", file: "f1")
        }
        let page = FileAnswerTransport(status: 200, bytes: Data("<html>".utf8))
        await #expect(throws: ReadFailure("电脑转出来的不是 PDF，可以保存原文件后打开。")) {
            _ = try await RelayClient(origin: .default, transport: page).pdfPreview(device: device, app: "codex", chat: "c1", file: "f1")
        }
        let big = FileAnswerTransport(status: 200, bytes: Data("%PDF-".utf8) + Data(count: Int(RelayClient.previewLimit)))
        await #expect(throws: ReadFailure("转成的 PDF 超过 20MB，页面里不显示；可以保存原文件后打开。")) {
            _ = try await RelayClient(origin: .default, transport: big).pdfPreview(device: device, app: "codex", chat: "c1", file: "f1")
        }
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
