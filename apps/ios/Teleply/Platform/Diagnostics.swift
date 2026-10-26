import CoreTransferable
import Foundation
import MetricKit
import Synchronization
import TeleplyModel
import UIKit
import UniformTypeIdentifiers

/// 诊断记录 (spec 4.6, iOS only): the last requests (method, path, status, time, error; never a body, a query or
/// the sign-in), the app's own lines, and the crash reports the system collected, shared as one text file. The
/// app is built on Windows, where nothing on the iPhone can be seen otherwise.
nonisolated final class DiagnosticsLog: Sendable {
    static let shared = DiagnosticsLog()
    private let lines = Mutex<[String]>([])

    // DateFormatter formats safely from any thread.
    nonisolated(unsafe) private static let clock: DateFormatter = {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.dateFormat = "MM-dd HH:mm:ss.SSS"
        return formatter
    }()

    func note(_ text: String) {
        let line = Self.clock.string(from: Date()) + " " + text
        lines.withLock { lines in
            lines.append(line)
            if lines.count > 400 { lines.removeFirst(lines.count - 400) }
        }
    }

    func request(_ request: RelayRequest, status: Int?, seconds: Double, error: String?) {
        // The path only: queries carry search words and conversation ids.
        let outcome = status.map { String($0) } ?? ("失败：" + (error ?? ""))
        note("\(request.method.rawValue) \(request.url.path) \(outcome) \(String(format: "%.2f", seconds))s")
    }

    var recent: [String] { lines.withLock { $0 } }

    /// The whole record as a text file in the temporary folder, for the share sheet.
    func writeFile() throws -> URL {
        let info = Bundle.main.infoDictionary ?? [:]
        var text = "遥应诊断记录\n"
        text += "版本 \(info["CFBundleShortVersionString"] as? String ?? "?")（\(info["CFBundleVersion"] as? String ?? "?")）\n"
        text += "系统 iOS \(ProcessInfo.processInfo.operatingSystemVersionString)\n"
        text += "导出 \(Self.clock.string(from: Date()))\n\n"
        text += "最近的请求和记录\n" + recent.joined(separator: "\n") + "\n"
        let reports = CrashReports.saved()
        text += "\n系统收集的崩溃报告（\(reports.count) 份）\n"
        for report in reports { text += "\n" + report + "\n" }
        let stamp = Self.clock.string(from: Date()).replacingOccurrences(of: ":", with: "").replacingOccurrences(of: " ", with: "-")
        let url = FileManager.default.temporaryDirectory.appendingPathComponent("teleply-diagnostics-\(stamp).txt")
        try Data(text.utf8).write(to: url, options: .atomic)
        return url
    }
}

/// The file 导出诊断记录 hands to the share sheet, written when it is shared.
nonisolated struct DiagnosticsExport: Transferable {
    static var transferRepresentation: some TransferRepresentation {
        FileRepresentation(exportedContentType: .plainText) { _ in
            SentTransferredFile(try DiagnosticsLog.shared.writeFile())
        }
    }
}

/// The phone's own requests, timed into 诊断记录. Only the real service is logged; the demo is not.
nonisolated struct LoggedTransport: RelayStreamingTransport, RelayFileTransport {
    let base: any RelayStreamingTransport
    let log: DiagnosticsLog

    func send(_ request: RelayRequest) async throws -> RelayResponse {
        let start = ContinuousClock.now
        do {
            let response = try await base.send(request)
            log.request(request, status: response.status, seconds: Self.seconds(since: start), error: nil)
            return response
        } catch {
            log.request(request, status: nil, seconds: Self.seconds(since: start), error: describe(error))
            throw error
        }
    }

    func download(_ request: RelayRequest, limit: Int64, progress: (@Sendable (Int64, Int64) -> Void)?) async throws -> RelayDownload {
        guard let files = base as? any RelayFileTransport else { throw ReadFailure("当前服务不支持下载文件") }
        let start = ContinuousClock.now
        do {
            let answer = try await files.download(request, limit: limit, progress: progress)
            log.request(request, status: answer.status, seconds: Self.seconds(since: start), error: nil)
            return answer
        } catch {
            log.request(request, status: nil, seconds: Self.seconds(since: start), error: describe(error))
            throw error
        }
    }

    func stream(_ request: RelayRequest) async throws -> RelayStream {
        let start = ContinuousClock.now
        do {
            let stream = try await base.stream(request)
            log.request(request, status: stream.status, seconds: Self.seconds(since: start), error: nil)
            return stream
        } catch {
            log.request(request, status: nil, seconds: Self.seconds(since: start), error: describe(error))
            throw error
        }
    }

    private static func seconds(since start: ContinuousClock.Instant) -> Double {
        let elapsed = ContinuousClock.now - start
        return Double(elapsed.components.seconds) + Double(elapsed.components.attoseconds) / 1e18
    }
}

/// Crash and hang reports MetricKit delivers (usually on the next launch), kept as JSON in the app's folder; the
/// last five go into 诊断记录.
nonisolated final class CrashReports: NSObject, MXMetricManagerSubscriber, @unchecked Sendable {
    static let shared = CrashReports()

    func start() {
        MXMetricManager.shared.add(self)
    }

    func didReceive(_ payloads: [MXDiagnosticPayload]) {
        for payload in payloads { Self.save(payload.jsonRepresentation()) }
    }

    private static var folder: URL {
        StoreFolder.url().appendingPathComponent("diagnostics", isDirectory: true)
    }

    private static func save(_ json: Data) {
        let folder = folder
        try? FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        let name = "crash-\(Int(Date().timeIntervalSince1970 * 1000)).json"
        try? json.write(to: folder.appendingPathComponent(name), options: .atomic)
        let files = ((try? FileManager.default.contentsOfDirectory(at: folder, includingPropertiesForKeys: nil)) ?? [])
            .filter { $0.lastPathComponent.hasPrefix("crash-") }
            .sorted { $0.lastPathComponent < $1.lastPathComponent }
        for old in files.dropLast(5) { try? FileManager.default.removeItem(at: old) }
    }

    static func saved() -> [String] {
        let files = ((try? FileManager.default.contentsOfDirectory(at: folder, includingPropertiesForKeys: nil)) ?? [])
            .filter { $0.lastPathComponent.hasPrefix("crash-") }
            .sorted { $0.lastPathComponent < $1.lastPathComponent }
        return files.compactMap { try? String(contentsOf: $0, encoding: .utf8) }
    }
}
