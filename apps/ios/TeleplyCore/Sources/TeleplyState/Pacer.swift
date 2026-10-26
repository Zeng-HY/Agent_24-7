/// How the state layer waits between polls and retries. The app waits for real; tests decide when time passes.
public protocol Pacer: Sendable {
    func wait(_ duration: Duration) async throws
}

public struct RealPacer: Pacer {
    public init() {}

    public func wait(_ duration: Duration) async throws {
        try await Task.sleep(for: duration)
    }
}
