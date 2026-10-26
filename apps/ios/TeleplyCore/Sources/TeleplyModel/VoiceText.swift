import Foundation

/// Where voice put its words in the draft (Android VoicePlacement): [at] (in characters) and the [text] there now,
/// the words as heard ([raw]), and the new draft.
public struct VoicePlacement: Equatable, Sendable {
    public var at: Int
    public var text: String
    public var raw: String
    public var draft: String

    public init(at: Int, text: String, raw: String, draft: String) {
        self.at = at
        self.text = text
        self.raw = raw
        self.draft = draft
    }
}

/// Puts recognised words where the cursor was, replacing a selection (web voice-ui.js insert): a space before them
/// after Latin text, nothing after Chinese, a line break when the words hold one. Positions are in characters.
public func placeDictation(_ existing: String, _ text: String, start: Int, end: Int? = nil) -> VoicePlacement {
    let characters = Array(existing)
    let s = min(max(0, start), characters.count)
    let e = min(max(s, end ?? s), characters.count)
    let before = String(characters[..<s])
    let after = String(characters[e...])
    let separator: String
    if let last = before.last, !last.isWhitespace {
        if text.contains("\n") {
            separator = "\n"
        } else if let scalar = last.unicodeScalars.first, (0x3000...0x9FFF).contains(scalar.value) || (0xFF00...0xFFEF).contains(scalar.value) {
            separator = ""
        } else {
            separator = " "
        }
    } else {
        separator = ""
    }
    return VoicePlacement(at: before.count + separator.count, text: text, raw: text, draft: before + separator + text + after)
}

/// Swaps the words voice put in for others (整理, or its 撤销), only while they are still there as they were.
public func swapDictation(_ draft: String, _ placed: VoicePlacement, with text: String) -> VoicePlacement? {
    let characters = Array(draft)
    let count = placed.text.count
    guard placed.at >= 0, placed.at + count <= characters.count, String(characters[placed.at..<(placed.at + count)]) == placed.text else { return nil }
    let next = String(characters[..<placed.at]) + text + String(characters[(placed.at + count)...])
    return VoicePlacement(at: placed.at, text: text, raw: placed.raw, draft: next)
}

/// The rate the computer's recogniser takes: 16 kHz mono, 16-bit.
public let voiceRate = 16_000

/// 16-bit little-endian mono PCM, as the computer's recogniser takes it.
public func pcmBytes(_ samples: [Int16]) -> Data {
    var data = Data(capacity: samples.count * 2)
    for sample in samples {
        let value = UInt16(bitPattern: sample)
        data.append(UInt8(value & 0xFF))
        data.append(UInt8(value >> 8))
    }
    return data
}

/// A WAV file of 16 kHz mono PCM (web wav()), for the computer's cloud recogniser.
public func wavBytes(_ samples: [Int16], rate: Int = voiceRate) -> Data {
    func word(_ value: UInt32) -> [UInt8] { [UInt8(value & 0xFF), UInt8((value >> 8) & 0xFF), UInt8((value >> 16) & 0xFF), UInt8(value >> 24)] }
    func half(_ value: UInt16) -> [UInt8] { [UInt8(value & 0xFF), UInt8(value >> 8)] }
    let size = UInt32(samples.count * 2)
    var data = Data()
    data.append(contentsOf: Array("RIFF".utf8) + word(36 + size) + Array("WAVE".utf8) + Array("fmt ".utf8))
    data.append(contentsOf: word(16) + half(1) + half(1) + word(UInt32(rate)) + word(UInt32(rate * 2)) + half(2) + half(16))
    data.append(contentsOf: Array("data".utf8) + word(size))
    data.append(pcmBytes(samples))
    return data
}

/// Loudness 0…1 of a piece of audio (web pushLevel: dB of every fourth sample, −55 to −15).
public func voiceLevel(_ samples: [Int16]) -> Float {
    var sum = 0.0
    var count = 0
    var index = 0
    while index < samples.count {
        let value = Double(samples[index]) / 32_768
        sum += value * value
        count += 1
        index += 4
    }
    let decibels = 10 * log10(sum / Double(max(1, count)) + 1e-9)
    return Float(min(1, max(0, (decibels + 55) / 40)))
}
