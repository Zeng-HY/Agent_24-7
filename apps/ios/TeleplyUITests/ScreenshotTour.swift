import XCTest

/// Walks the app on the local demo and keeps one screenshot per page and variant (plan: 云端检查). Each
/// picture is a test attachment; with TEST_RUNNER_SHOTS_DIR on the xcodebuild line it is also written there.
final class ScreenshotTour: XCTestCase {
    @MainActor func testLight() throws {
        try tour(appearance: "light", variant: "light")
    }

    @MainActor func testDark() throws {
        try tour(appearance: "dark", variant: "dark")
    }

    @MainActor func testLargestText() throws {
        try tour(appearance: "light", variant: "xxxl",
                 extra: ["-UIPreferredContentSizeCategoryName", "UICTContentSizeCategoryAccessibilityXXXL"])
    }

    @MainActor private func tour(appearance: String, variant: String, extra: [String] = []) throws {
        continueAfterFailure = true
        let app = XCUIApplication()
        app.launchArguments = ["-TeleplyDemo", "-TeleplyAppearance", appearance,
                               "-AppleLanguages", "(zh-Hans)", "-AppleLocale", "zh_CN"] + extra
        app.launch()
        XCTAssertTrue(app.staticTexts["服务 fixture"].waitForExistence(timeout: 20), "the launch page never showed the demo service")
        snap(app, page: "01-launch", variant: variant)
    }

    @MainActor private func snap(_ app: XCUIApplication, page: String, variant: String) {
        let screenshot = app.screenshot()
        let system = ProcessInfo.processInfo.operatingSystemVersion
        let name = "\(page)-\(variant)-iOS\(system.majorVersion).\(system.minorVersion)"
        let attachment = XCTAttachment(screenshot: screenshot)
        attachment.name = name
        attachment.lifetime = .keepAlways
        add(attachment)
        if let folder = ProcessInfo.processInfo.environment["SHOTS_DIR"], !folder.isEmpty {
            try? screenshot.pngRepresentation.write(to: URL(fileURLWithPath: folder).appendingPathComponent(name + ".png"))
        }
    }
}
