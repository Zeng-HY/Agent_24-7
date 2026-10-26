import SwiftUI
import TeleplyDemo
import TeleplyModel

/// Launch switches for the screenshot tour (plan: 云端检查). Only debug builds read them; a TestFlight build
/// always talks to the real service and follows the system appearance.
enum LaunchOptions {
    /// -TeleplyDemo: start on the local demo instead of the service.
    static var usesDemo: Bool {
        #if DEBUG
        return ProcessInfo.processInfo.arguments.contains("-TeleplyDemo")
        #else
        return false
        #endif
    }

    static func transport() -> any RelayTransport {
        if usesDemo { return DemoTransport() }
        return URLSessionTransport()
    }

    /// -TeleplyAppearance light|dark; otherwise the system's (the 外观 setting arrives in phase 1).
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

enum AppVersion {
    /// "0.1.0（1）": the version and the build number TestFlight shows.
    static var display: String {
        let info = Bundle.main.infoDictionary ?? [:]
        let version = info["CFBundleShortVersionString"] as? String ?? "?"
        let build = info["CFBundleVersion"] as? String ?? "?"
        return "\(version)（\(build)）"
    }
}
