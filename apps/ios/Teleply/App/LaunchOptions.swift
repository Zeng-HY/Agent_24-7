import Foundation
import SwiftUI
import Synchronization
import TeleplyDemo
import TeleplyModel

/// Launch switches for the screenshot tour (plan: 云端检查). Only debug builds read them; a TestFlight build
/// always talks to the real service and follows the 外观 setting.
enum LaunchOptions {
    private static func flag(_ name: String) -> Bool {
        #if DEBUG
        return ProcessInfo.processInfo.arguments.contains(name)
        #else
        return false
        #endif
    }

    /// -TeleplyDemo: open on the local demo's 登录 instead of the service.
    static var usesDemo: Bool { flag("-TeleplyDemo") }

    /// -TeleplyDemoUnreachable: the service cannot be reached, for the "连不上服务器" screenshots.
    static var unreachable: Bool { flag("-TeleplyDemoUnreachable") }

    /// How the app talks to the service: URLSession with every request timed into 诊断记录; for the screenshots
    /// a demo service that is down.
    static func transport() -> any RelayTransport {
        if unreachable { return DemoTransport(unreachable: true) }
        return LoggedTransport(base: URLSessionTransport(), log: .shared)
    }

    /// -TeleplyAppearance light|dark overrides 外观 for the screenshots.
    static var colorScheme: ColorScheme? {
        #if DEBUG
        switch UserDefaults.standard.string(forKey: "TeleplyAppearance") {
        case "dark": return .dark
        case "light": return .light
        default: return nil
        }
        #else
        return nil
        #endif
    }
}

/// The local demo's computer for this run of the app (开发者选项 → 本地示例): each opening starts a fresh one;
/// 示例网络 changes how it answers, also for the one in use.
nonisolated final class DemoHolder: Sendable {
    static let shared = DemoHolder()
    private let world = Mutex<DemoWorld?>(nil)
    private let chosen = Mutex(DemoNetwork.instant)

    func fresh() -> any RelayTransport {
        let next = DemoWorld()
        next.network = chosen.withLock { $0 }
        world.withLock { $0 = next }
        return DemoTransport(world: next)
    }

    var network: DemoNetwork {
        get { chosen.withLock { $0 } }
        set {
            chosen.withLock { $0 = newValue }
            world.withLock { $0?.network = newValue }
        }
    }
}

enum AppVersion {
    /// "0.2.0（3）": the version and the build number TestFlight shows.
    static var display: String {
        "\(short)（\(Bundle.main.infoDictionary?["CFBundleVersion"] as? String ?? "?")）"
    }

    /// "0.2.0".
    static var short: String {
        Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "?"
    }
}
