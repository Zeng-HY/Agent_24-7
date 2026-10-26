/// GET /account/config: the relay's version and whether it sends email (sign-up and password resets open
/// in the browser only then, spec 4.8).
public struct AccountConfig: Sendable, Equatable {
    public var version: String
    public var emailEnabled: Bool

    public init(version: String, emailEnabled: Bool) {
        self.version = version
        self.emailEnabled = emailEnabled
    }

    public init(_ json: JSONValue) {
        self.init(version: json["version"].string(), emailEnabled: json["email_enabled"].bool())
    }
}
