import XCTest

/// Walks the app on the local demo and keeps one screenshot per page and variant (plan: 云端检查): 登录 when the
/// service is down, the demo's 登录, 我的电脑, the list, the sidebar, a conversation with Markdown and code, 会话状态,
/// Claude's cards, 设置 and 开发者选项. Each picture is a test attachment; with TEST_RUNNER_SHOTS_DIR on the
/// xcodebuild line it is also written there.
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

        let offline = launch(appearance: appearance, extra: extra + ["-TeleplyDemoUnreachable"])
        XCTAssertTrue(offline.buttons["重试"].waitForExistence(timeout: 20), "登录 never offered 重试 when the service was down")
        snap(offline, page: "01-unreachable", variant: variant)
        offline.terminate()

        let app = launch(appearance: appearance, extra: extra + ["-TeleplyDemo"])
        let enter = app.buttons["进入示例"]
        XCTAssertTrue(enter.waitForExistence(timeout: 20), "the demo's 登录 never showed")
        snap(app, page: "02-demo-login", variant: variant)

        enter.tap()
        XCTAssertTrue(app.staticTexts["我的电脑"].waitForExistence(timeout: 10), "我的电脑 never showed")
        snap(app, page: "03-devices", variant: variant)

        let connect = app.buttons["连接测试电脑 A"]
        XCTAssertTrue(connect.waitForExistence(timeout: 5), "测试电脑 A had no 连接")
        connect.tap()
        let first = app.buttons.containing(NSPredicate(format: "label CONTAINS %@", "原生阅读示例")).firstMatch
        XCTAssertTrue(first.waitForExistence(timeout: 10), "the list never showed its rows")
        snap(app, page: "04-list", variant: variant)

        let menu = app.buttons["打开导航"]
        if menu.waitForExistence(timeout: 5) {
            menu.tap()
            if app.staticTexts["电脑遥控"].waitForExistence(timeout: 5) {
                snap(app, page: "05-drawer", variant: variant)
            }
            app.buttons["关闭导航"].firstMatch.tap()
        }

        first.tap()
        XCTAssertTrue(app.staticTexts["原生阅读示例"].waitForExistence(timeout: 10), "the conversation never opened")
        sleep(1)
        snap(app, page: "06-reading", variant: variant)

        let ring = app.buttons.containing(NSPredicate(format: "label BEGINSWITH %@", "上下文已用约")).firstMatch
        if ring.waitForExistence(timeout: 5) {
            ring.tap()
            if app.staticTexts["上下文"].waitForExistence(timeout: 5) {
                snap(app, page: "07-runtime", variant: variant)
            }
            app.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.45)).tap()
        }

        // Sending on the demo (0.3.0): a send starts a turn (停止这一轮 shows), the next one queues.
        let field = composer(app)
        if field.waitForExistence(timeout: 5) {
            field.tap()
            field.typeText("hello")
            app.buttons["发送"].firstMatch.tap()
            if app.buttons["停止这一轮"].waitForExistence(timeout: 5) {
                snap(app, page: "08-sent", variant: variant)
            }
            field.tap()
            field.typeText("one more")
            let queue = app.buttons["发送并排队"].firstMatch
            if queue.waitForExistence(timeout: 5) {
                queue.tap()
                if app.buttons["立即补充"].firstMatch.waitForExistence(timeout: 5) {
                    app.swipeDown()
                    snap(app, page: "09-queued", variant: variant)
                }
            }
            let chip = app.buttons.containing(NSPredicate(format: "label BEGINSWITH %@", "模型：")).firstMatch
            if chip.waitForExistence(timeout: 5) {
                chip.tap()
                sleep(1)
                snap(app, page: "10-model-menu", variant: variant)
                app.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.2)).tap()
            }
        }

        back(app)
        let cards = app.buttons.containing(NSPredicate(format: "label CONTAINS %@", "Claude 下一步示例")).firstMatch
        if cards.waitForExistence(timeout: 10) {
            cards.tap()
            if app.staticTexts["Claude 下一步示例"].waitForExistence(timeout: 10) {
                app.swipeUp()
                snap(app, page: "11-cards", variant: variant)
            }
            back(app)
        }

        if menu.waitForExistence(timeout: 5) {
            menu.tap()
            let gear = app.buttons["设置"].firstMatch
            if gear.waitForExistence(timeout: 5) {
                gear.tap()
                if app.navigationBars["设置"].waitForExistence(timeout: 5) {
                    snap(app, page: "12-settings", variant: variant)
                    app.buttons["开发者选项"].firstMatch.tap()
                    if app.navigationBars["开发者选项"].waitForExistence(timeout: 5) {
                        snap(app, page: "13-developer", variant: variant)
                    }
                }
            }
        }
        app.terminate()
    }

    /// The composer's text box: a growing text field is a text view to XCUITest.
    @MainActor private func composer(_ app: XCUIApplication) -> XCUIElement {
        let kinds = NSPredicate(format: "label == %@ AND (elementType == %d OR elementType == %d)", "输入消息",
                                XCUIElement.ElementType.textView.rawValue, XCUIElement.ElementType.textField.rawValue)
        return app.descendants(matching: .any).matching(kinds).firstMatch
    }

    @MainActor private func back(_ app: XCUIApplication) {
        let bar = app.navigationBars.firstMatch
        let button = bar.buttons.element(boundBy: 0)
        if button.exists { button.tap() }
        sleep(1)
    }

    @MainActor private func launch(appearance: String, extra: [String]) -> XCUIApplication {
        let app = XCUIApplication()
        app.launchArguments = ["-TeleplyAppearance", appearance, "-AppleLanguages", "(zh-Hans)", "-AppleLocale", "zh_CN"] + extra
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
