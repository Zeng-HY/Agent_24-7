import SwiftUI
import TeleplyModel

/// A zip's page (§5.7): the names inside, folders first and by path, at most 2000, with sizes and local times; nothing
/// is unpacked. 7z and rar, or a listing the computer could not read, stay a file card with the reason.
struct ZipViewer: View {
    let data: JSONValue

    private var listing: ZipListing { parseZipListing(data["zip"]) }

    var body: some View {
        let parsed = listing
        VStack(alignment: .leading, spacing: 0) {
            if parsed.entries.isEmpty {
                VStack(spacing: 12) {
                    Image(systemName: "doc.zipper")
                        .font(.system(size: 44))
                        .foregroundStyle(Palette.muted)
                    Text("这个压缩包读不了，可以保存后用其他应用打开。")
                        .noteFont()
                        .foregroundStyle(Palette.muted)
                        .multilineTextAlignment(.center)
                }
                .frame(maxWidth: .infinity)
                .padding(.top, 72)
            } else {
                Text("共 \(parsed.total) 项，解压后 \(byteSize(parsed.unpackedBytes))")
                    .noteFont()
                    .foregroundStyle(Palette.muted)
                    .padding(.horizontal, 16)
                    .padding(.vertical, 8)
                if parsed.more {
                    let suffix = parsed.truncated ? "" : "，共 \(parsed.total) 项"
                    Text("只列了前 \(parsed.entries.count) 项" + suffix)
                        .noteFont()
                        .foregroundStyle(Palette.muted)
                        .padding(.horizontal, 16)
                        .padding(.bottom, 4)
                }
                Rectangle().fill(Palette.line).frame(height: 1)
                ScrollView {
                    LazyVStack(alignment: .leading, spacing: 0) {
                        ForEach(parsed.entries) { entry in
                            HStack(spacing: 10) {
                                Image(systemName: entry.dir ? "folder" : "doc")
                                    .font(.system(size: 16))
                                    .foregroundStyle(Palette.muted)
                                    .frame(width: 22)
                                Text(entry.name)
                                    .bodyFont()
                                    .foregroundStyle(Palette.ink)
                                    .lineLimit(2)
                                    .frame(maxWidth: .infinity, alignment: .leading)
                                if !entry.dir {
                                    Text(byteSize(entry.size))
                                        .captionFont()
                                        .foregroundStyle(Palette.muted)
                                    Text(Self.date(entry.modified))
                                        .captionFont()
                                        .foregroundStyle(Palette.muted)
                                        .frame(width: 110, alignment: .trailing)
                                }
                            }
                            .padding(.horizontal, 16)
                            .padding(.vertical, 8)
                            Rectangle().fill(Palette.line).frame(height: 0.5).padding(.leading, 48)
                        }
                    }
                }
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
        .background(Palette.page)
    }

    /// The entry's time on this phone's clock, or an empty line when the computer gave none.
    private static func date(_ milliseconds: Int64) -> String {
        guard milliseconds > 0 else { return "" }
        let formatter = DateFormatter()
        formatter.dateFormat = "yyyy-MM-dd HH:mm"
        formatter.timeZone = .current
        return formatter.string(from: Date(timeIntervalSince1970: Double(milliseconds) / 1000))
    }
}
