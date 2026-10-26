/// One event of a text/event-stream (live_events.py writes `id:`, `event: update`, one `data:` line of JSON).
public struct ServerSentEvent: Sendable, Equatable {
    public var id: String?
    public var event: String?
    public var data: String

    public init(id: String? = nil, event: String? = nil, data: String) {
        self.id = id
        self.event = event
        self.data = data
    }
}

/// Splits a byte stream into events, on CR, LF or CRLF only. The system's line reader also splits on U+2028
/// and U+2029, which the computer sends unescaped inside the JSON (json.dumps(ensure_ascii=False)), so a message
/// with one of them would never parse and the stream would reconnect forever.
public struct ServerSentEventParser: Sendable {
    /// Android drops an event whose data is over 8 MB.
    public static let dataLimit = 8 * 1024 * 1024

    private var line: [UInt8] = []
    private var data: [UInt8] = []
    private var hasData = false
    private var id: String?
    private var event: String?
    private var afterCarriageReturn = false

    public init() {}

    public mutating func feed(_ bytes: some Sequence<UInt8>) throws -> [ServerSentEvent] {
        var events: [ServerSentEvent] = []
        for byte in bytes {
            if afterCarriageReturn {
                afterCarriageReturn = false
                if byte == 0x0A { continue }  // the LF of a CRLF split across chunks
            }
            switch byte {
            case 0x0D:
                afterCarriageReturn = true
                if let event = try endLine() { events.append(event) }
            case 0x0A:
                if let event = try endLine() { events.append(event) }
            default:
                line.append(byte)
                if line.count > Self.dataLimit { throw ReadFailure("实时内容过大") }
            }
        }
        return events
    }

    private mutating func endLine() throws -> ServerSentEvent? {
        defer { line.removeAll(keepingCapacity: true) }
        if line.isEmpty { return dispatch() }
        if line.first == 0x3A { return nil }  // ":" a comment, e.g. the 8 s heartbeat
        let colon = line.firstIndex(of: 0x3A) ?? line.endIndex
        let field = String(decoding: line[..<colon], as: UTF8.self)
        var value = colon < line.endIndex ? Array(line[line.index(after: colon)...]) : []
        if value.first == 0x20 { value.removeFirst() }
        switch field {
        case "data":
            if hasData { data.append(0x0A) }
            data.append(contentsOf: value)
            hasData = true
            if data.count > Self.dataLimit { throw ReadFailure("实时内容过大") }
        case "id":
            id = String(decoding: value, as: UTF8.self)
        case "event":
            event = String(decoding: value, as: UTF8.self)
        default:
            break
        }
        return nil
    }

    private mutating func dispatch() -> ServerSentEvent? {
        defer {
            data.removeAll(keepingCapacity: true)
            hasData = false
            event = nil
        }
        guard hasData else { return nil }
        return ServerSentEvent(id: id, event: event, data: String(decoding: data, as: UTF8.self))
    }
}
