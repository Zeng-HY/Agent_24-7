import Foundation
import Testing
@testable import TeleplyModel

struct SessionCookieTests {
    let now = Date(timeIntervalSince1970: 1_792_843_200)

    @Test func keepsOnlyTheRelaysOwnSignIn() {
        let cookie = SessionCookie.fromSetCookie("__Host-ar_account=synthetic; Path=/; Secure; HttpOnly; Max-Age=3600; SameSite=Strict", now: now)
        #expect(cookie == SessionCookie(value: "synthetic", expires: now.addingTimeInterval(3600)))
        #expect(cookie?.header(at: now) == "__Host-ar_account=synthetic")
        #expect(cookie?.header(at: now.addingTimeInterval(3600)) == nil)
    }

    @Test(arguments: [
        "__Host-ar_account=x; Path=/; HttpOnly",
        "__Host-ar_account=x; Path=/; Secure",
        "__Host-ar_account=x; Path=/; Secure; HttpOnly; Domain=example.com",
        "__Host-ar_account=x; Path=/d; Secure; HttpOnly",
        "__Host-ar_account=x; Secure; HttpOnly",
        "other=x; Path=/; Secure; HttpOnly",
        "__Host-ar_account=x; Path=/; Secure; HttpOnly; Max-Age=0",
    ])
    func refusesAnythingElse(_ header: String) {
        #expect(SessionCookie.fromSetCookie(header, now: now) == nil)
    }

    @Test func findsItAmongJoinedCookiesWithCommaDates() {
        let joined = "lbr=1; Expires=Wed, 21 Oct 2026 07:28:00 GMT; Path=/, __Host-ar_account=v2; Path=/; Secure; HttpOnly"
        #expect(SessionCookie.fromSetCookie(joined, now: now)?.value == "v2")
    }

    @Test func theVaultKeepsOneEntryPerAddress() throws {
        let vault = MemoryCookieVault()
        try vault.write("https://a/", SessionCookie(value: "a", expires: nil))
        try vault.write("https://b/", SessionCookie(value: "b", expires: nil))
        try vault.write("https://a/", nil)
        #expect(try vault.read("https://a/") == nil)
        #expect(try vault.read("https://b/")?.value == "b")
    }
}
