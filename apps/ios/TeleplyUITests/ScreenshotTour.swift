import XCTest

/// Walks the app on the local demo and keeps one screenshot per page and variant (plan: 云端检查). Each
/// picture is a test attachment; with TEST_RUNNER_SHOTS_DIR on the xcodebuild line it is also written there.
final class ScreenshotTour: XCTestCase {
    @MainActor func testLight() throws {
        try tour(variant: "light", appearance: "light")
    }

    @MainActor func testDark() throws {
        try tour(variant: "dark", appearance: "dark")
    }

    @MainActor func testLargestText() throws {
        try tour(variant: "xxxl", appearance: "light",
                 extra: ["-UIPreferredContentSizeCategoryName", "UICTContentSizeCategoryAccessibilityXXXL"])
    }

    @MainActor private func tour(variant: String, appearance: String, extra: [String] = []) throws {
        continueAfterFailure = true

        let app = launch(appearance: appearance, extra: extra)
        XCTAssertTrue(app.staticTexts["服务 fixture"].waitForExistence(timeout: 20), "the launch page never showed the demo service")
        snap(app, page: "01-launch", variant: variant)
        app.terminate()

        let offline = launch(appearance: appearance, extra: extra + ["-TeleplyDemoUnreachable"])
        XCTAssertTrue(offline.buttons["重试"].waitForExistence(timeout: 20), "the launch page never offered 重试")
        snap(offline, page: "02-unreachable", variant: variant)
        offline.terminate()
    }

    @MainActor private func launch(appearance: String, extra: [String]) -> XCUIApplication {
        let app = XCUIApplication()
        app.launchArguments = ["-TeleplyDemo", "-TeleplyAppearance", appearance,
                               "-AppleLanguages", "(zh-Hans)", "-AppleLocale", "zh_CN"] + extra
        app.launch()
        return app
    }

    @MainActor private func snap(_ app: XCUIApplication, page: String, variant: String) {
        sleep(1)  // let the page finish rising into place (0.7 s, spec 5)
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
