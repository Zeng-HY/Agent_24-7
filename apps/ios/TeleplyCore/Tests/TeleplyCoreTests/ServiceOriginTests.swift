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
        #expect(ServiceOrigin.default.header == "https://8.166.15.235")
    }

    @Test(arguments: [
        "http://8.166.15.235", "https://user@example.com", "https://user:pw@example.com", "https://example.com/path",
        "https://example.com/?q=1", "https://example.com/#top", "example.com", "https://", "",
    ])
    func rejectsAnythingButAnHTTPSRoot(_ text: String) {
        #expect(throws: ServiceOriginError.invalid) { try ServiceOrigin(text) }
    }

    @Test func encodesQueryValuesLikeOkHttp() {
        let url = ServiceOrigin.default.url("/d/x/api/chats", query: [("query", "a+b c&d=中"), ("cursor", nil), ("app", "all")])
        #expect(url.absoluteString == "https://8.166.15.235/d/x/api/chats?query=a%2Bb%20c%26d%3D%E4%B8%AD&app=all")
    }
}
