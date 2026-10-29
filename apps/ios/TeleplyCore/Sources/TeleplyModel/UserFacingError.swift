/// An error with words for the person using the app (Android: the exception's message shown as is).
public protocol UserFacingError: Error {
    var message: String { get }
}

extension ServiceFailure: UserFacingError {}
extension ReadFailure: UserFacingError {}
extension RelayError: UserFacingError {}
extension ServiceOriginError: UserFacingError {}

/// What to show for any error: its own words, or Android's general line for a network failure.
public func describe(_ error: any Error) -> String {
    Hints.text((error as? any UserFacingError)?.message ?? "连接失败，请检查网络和服务地址后重试。")
}
