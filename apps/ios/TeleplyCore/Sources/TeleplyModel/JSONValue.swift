import Foundation

/// A JSON document read the way the Android app reads it with org.json: a missing key or a null reads as the
/// default, so one field more or less from the computer never makes a whole page unreadable.
public enum JSONValue: Sendable, Equatable {
    case null
    case bool(Bool)
    case number(Double)
    case string(String)
    case array([JSONValue])
    case object([String: JSONValue])

    public static func parse(_ data: Data) throws -> JSONValue {
        try JSONDecoder().decode(JSONValue.self, from: data)
    }

    public func encoded() throws -> Data {
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.withoutEscapingSlashes]
        return try encoder.encode(self)
    }

    public subscript(key: String) -> JSONValue {
        if case .object(let fields) = self { return fields[key] ?? .null }
        return .null
    }

    public subscript(index: Int) -> JSONValue {
        if case .array(let items) = self, items.indices.contains(index) { return items[index] }
        return .null
    }

    public var isNull: Bool { self == .null }

    /// An object, empty or not (org.json optJSONObject() != null).
    public var isObject: Bool {
        if case .object = self { return true }
        return false
    }

    /// The key is there and is not null (org.json has() && !isNull()).
    public func has(_ key: String) -> Bool { !self[key].isNull }

    public var array: [JSONValue] {
        if case .array(let items) = self { return items }
        return []
    }

    public var object: [String: JSONValue] {
        if case .object(let fields) = self { return fields }
        return [:]
    }

    /// org.json optString: text as it is, numbers and booleans written out, anything else the fallback.
    public func string(or fallback: String = "") -> String {
        switch self {
        case .string(let text): return text
        case .number(let value): return Self.write(value)
        case .bool(let value): return value ? "true" : "false"
        default: return fallback
        }
    }

    /// org.json optBoolean: true/false, or the text "true"/"false" in any case.
    public func bool(or fallback: Bool = false) -> Bool {
        switch self {
        case .bool(let value): return value
        case .string(let text):
            switch text.lowercased() {
            case "true": return true
            case "false": return false
            default: return fallback
            }
        default: return fallback
        }
    }

    /// org.json optDouble: numbers, or text that reads as a number.
    public func double(or fallback: Double = 0) -> Double {
        switch self {
        case .number(let value): return value
        case .string(let text): return Double(text.trimmingCharacters(in: .whitespaces)) ?? fallback
        default: return fallback
        }
    }

    /// org.json optInt / optLong: the number cut toward zero.
    public func int(or fallback: Int = 0) -> Int {
        let value = double(or: .nan)
        guard value.isFinite, value >= Double(Int.min), value <= Double(Int.max) else { return fallback }
        return Int(value)
    }

    public func int64(or fallback: Int64 = 0) -> Int64 {
        let value = double(or: .nan)
        guard value.isFinite, value >= -9.2e18, value <= 9.2e18 else { return fallback }
        return Int64(value)
    }

    /// Whole numbers without ".0", the way org.json writes integers.
    static func write(_ value: Double) -> String {
        if value.isFinite, value == value.rounded(.towardZero), abs(value) < 1e15 { return String(Int64(value)) }
        return String(value)
    }
}

extension JSONValue: Codable {
    public init(from decoder: any Decoder) throws {
        let container = try decoder.singleValueContainer()
        if container.decodeNil() {
            self = .null
        } else if let value = try? container.decode(Bool.self) {
            // Booleans first: a number is never read as a boolean.
            self = .bool(value)
        } else if let value = try? container.decode(Double.self) {
            self = .number(value)
        } else if let value = try? container.decode(String.self) {
            self = .string(value)
        } else if let value = try? container.decode([JSONValue].self) {
            self = .array(value)
        } else {
            self = .object(try container.decode([String: JSONValue].self))
        }
    }

    public func encode(to encoder: any Encoder) throws {
        var container = encoder.singleValueContainer()
        switch self {
        case .null: try container.encodeNil()
        case .bool(let value): try container.encode(value)
        case .number(let value):
            // Whole numbers go out as integers: the computer checks some fields (answer_revision) as int.
            if value.isFinite, value == value.rounded(.towardZero), abs(value) < 9.0e15 { try container.encode(Int64(value)) }
            else { try container.encode(value) }
        case .string(let value): try container.encode(value)
        case .array(let value): try container.encode(value)
        case .object(let value): try container.encode(value)
        }
    }
}

extension JSONValue: ExpressibleByNilLiteral, ExpressibleByBooleanLiteral, ExpressibleByIntegerLiteral,
    ExpressibleByFloatLiteral, ExpressibleByStringLiteral, ExpressibleByArrayLiteral, ExpressibleByDictionaryLiteral {
    public init(nilLiteral: ()) { self = .null }
    public init(booleanLiteral value: Bool) { self = .bool(value) }
    public init(integerLiteral value: Int) { self = .number(Double(value)) }
    public init(floatLiteral value: Double) { self = .number(value) }
    public init(stringLiteral value: String) { self = .string(value) }
    public init(arrayLiteral elements: JSONValue...) { self = .array(elements) }
    public init(dictionaryLiteral elements: (String, JSONValue)...) {
        self = .object(Dictionary(elements, uniquingKeysWith: { _, last in last }))
    }
}
