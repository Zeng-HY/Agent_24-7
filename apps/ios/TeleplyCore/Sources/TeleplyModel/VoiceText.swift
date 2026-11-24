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

/// Stretches of talk one after another (voice_local.py _join): a space between English words and after English
/// punctuation ("failed. Then"), nothing between Chinese ones.
public func joinStretches(_ parts: [String]) -> String {
    var out = ""
    for part in parts {
        let part = part.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !part.isEmpty else { continue }
        if let last = out.last, let first = part.first, last.isASCII, first.isASCII,
           last.isLetter || last.isNumber || ".,!?;:'\")]".contains(last), first.isLetter || first.isNumber {
            out += " "
        }
        out += part
    }
    return out
}

/// What iOS's own recogniser has heard so far, stretch by stretch (used when the computer's voice is off). Each of
/// its answers (SFSpeechRecognitionResult) should hold everything said so far, but with on-device recognition it
/// starts afresh after a pause of about two seconds, and its next answers hold only the words after the pause (Apple
/// developer forums threads 731761, 762952, 765609; reported from iOS 17 to 26). Taking each answer as the whole text
/// lost everything said before a pause (11-24, on an iPad). Here an answer replaces only the stretch it belongs to.
///
/// New words begin a new stretch when they no longer hold most of the current one and either the recogniser closed
/// that one (an answer with metadata, or one with no words), or they start after it ended (segment times), or they
/// are at most half as many (a log on the forum: 105 segments, then 1). An answer that holds earlier stretches again (all
/// of it once more at the end, or a revision first taken for new words) takes them back, so nothing is written twice.
public struct HeardStretches: Equatable, Sendable {
    /// The stretches the recogniser has let go of.
    public private(set) var earlier: [String] = []
    /// Its latest words for the stretch still going.
    public private(set) var current = ""
    /// Where the current stretch's last word ends, in seconds from the start of the recording; 0 when not known.
    private var currentEnd = 0.0
    /// The recogniser closed the current stretch: words that do not carry it on are a new one.
    private var closed = false
    /// The current stretch had an answer without the closing mark (a mark on every answer would mean nothing).
    private var plain = false

    public init() {}

    /// Everything heard so far.
    public var text: String { joinStretches(earlier + [current]) }
    /// The stretches let go of: [text] carries on from these with the current one.
    public var settled: String { joinStretches(earlier) }

    /// One answer: its words, whether it closes a stretch (it carries speechRecognitionMetadata), and when its first
    /// word starts and its last ends (segment timestamps, 0 when not known).
    public mutating func take(_ answer: String, closes: Bool = false, start: Double = 0, end: Double = 0) {
        let words = answer.trimmingCharacters(in: .whitespacesAndNewlines)
        let next = comparable(words)
        // An answer without words never wipes what was heard; one comes when the recogniser lets a stretch go.
        guard !next.isEmpty else {
            if !current.isEmpty { closed = true }
            return
        }
        let unchanged = next == comparable(current)
        if let back = stride(from: earlier.count, through: 1, by: -1).first(where: { holdsAgain(earlier.suffix($0), by: next) }) {
            earlier.removeLast(back)  // the same words heard again: they belong to this answer now
        } else if !current.isEmpty && startsAfresh(next, start: start) {
            earlier.append(current)
            plain = false
        }
        current = words
        currentEnd = end
        // The closing mark counts on a stretch that also had answers without it, and lasts while the words do.
        closed = (closes && plain) || (unchanged && closed)
        if !closes { plain = true }
    }

    private func startsAfresh(_ next: [Character], start: Double) -> Bool {
        let now = comparable(current)
        if heldAgain(now, by: next) { return false }
        return closed || (start > 0 && currentEnd > 0 && start > currentEnd) || next.count * 2 <= now.count
    }
}

/// Letters and digits only, in lower case: punctuation and spaces the recogniser adds or moves do not count.
private func comparable(_ text: String) -> [Character] {
    Array(text.lowercased().filter { $0.isLetter || $0.isNumber })
}

/// Whether [next] begins with at least four fifths of [earlier], in order (only its first 60 characters compared):
/// the same words heard again, perhaps revised or carried on.
private func heldAgain(_ earlier: [Character], by next: [Character]) -> Bool {
    let words = Array(earlier.prefix(60))
    let start = Array(next.prefix(words.count + words.count / 4 + 1))
    return inOrder(words, start) * 5 >= words.count * 4
}

/// Whether [next] holds the [stretches] again, one after another from its start, each of them mostly (heldAgain).
/// Fewer than two characters in all are never taken for words heard again.
private func holdsAgain(_ stretches: ArraySlice<String>, by next: [Character]) -> Bool {
    var at = 0
    for stretch in stretches {
        let words = comparable(stretch)
        let from = max(0, at - words.count / 4)
        guard from < next.count, heldAgain(words, by: Array(next[from...])) else { return false }
        at += words.count
    }
    return at >= 2
}

/// How many characters [a] and [b] have in common in the same order (the longest common subsequence).
private func inOrder(_ a: [Character], _ b: [Character]) -> Int {
    guard !a.isEmpty, !b.isEmpty else { return 0 }
    var row = [Int](repeating: 0, count: b.count + 1)
    for x in a {
        var diagonal = 0
        for j in 0..<b.count {
            let above = row[j + 1]
            row[j + 1] = x == b[j] ? diagonal + 1 : max(above, row[j])
            diagonal = above
        }
    }
    return row[b.count]
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
