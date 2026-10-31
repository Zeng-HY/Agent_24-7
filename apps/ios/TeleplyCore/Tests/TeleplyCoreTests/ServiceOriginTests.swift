import Foundation
import Testing
@testable import TeleplyModel

struct ServiceOriginTests {
    @Test func acceptsHTTPSRootsTheWayOkHttpWritesThem() throws {
        let origin = try ServiceOrigin("  https://8.166.15.235/ ")
        #expect(origin.header == "https://8.166.15.235")
        #expect(origin.key == "https://8.166.15.235/")
        #expect(try ServiceOrigin("https://Example.COM:443").header == "https://example.com")
        #expect(try ServiceOrigin("https://example.com:8443").header == "https://example.com:8443")
        #expect(try ServiceOrigin("https://APP.PocketAgentDesk.com/").header == "https://app.pocketagentdesk.com")
    }

    /// The default service is on its domain; its former address, the IP, is still a valid one to set by hand.
    @Test func theDefaultIsTheDomainAndTheIPIsItsFormerAddress() throws {
        #expect(ServiceOrigin.defaultAddress == "https://app.pocketagentdesk.com")
        #expect(ServiceOrigin.default.header == "https://app.pocketagentdesk.com")
        #expect(ServiceOrigin.default.key == "https://app.pocketagentdesk.com/")
        #expect(ServiceOrigin.formerDefault.header == "https://8.166.15.235")
        #expect(ServiceOrigin.formerDefault.key == "https://8.166.15.235/")
        #expect(try ServiceOrigin("https://8.166.15.235") == .formerDefault)
        #expect(ServiceOrigin.formerDefault != .default)
    }

    @Test(arguments: [
        "http://8.166.15.235", "https://user@example.com", "https://user:pw@example.com", "https://example.com/path",
        "https://example.com/?q=1", "https://example.com/#top", "example.com", "https://", "",
        "http://app.pocketagentdesk.com",
    ])
    func rejectsAnythingButAnHTTPSRoot(_ text: String) {
        #expect(throws: ServiceOriginError.invalid) { try ServiceOrigin(text) }
    }

    @Test func encodesQueryValuesLikeOkHttp() {
        let url = ServiceOrigin.default.url("/d/x/api/chats", query: [("query", "a+b c&d=中"), ("cursor", nil), ("app", "all")])
        #expect(url.absoluteString == "https://app.pocketagentdesk.com/d/x/api/chats?query=a%2Bb%20c%26d%3D%E4%B8%AD&app=all")
        let former = ServiceOrigin.formerDefault.url("/d/x/api/chats", query: [("query", "a+b c&d=中")])
        #expect(former.absoluteString == "https://8.166.15.235/d/x/api/chats?query=a%2Bb%20c%26d%3D%E4%B8%AD")
    }
}
