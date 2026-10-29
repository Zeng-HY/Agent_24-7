import XCTest

/// Walks the app on the local demo and keeps one screenshot per page and variant (plan: 云端检查): 登录 when the
/// service is down, the demo's 登录, 我的电脑, the list, the sidebar, a conversation with Markdown and code, 会话状态,
/// sending, Claude's cards; from 0.4.0 the question and approval cards, 新建对话 and its job, 对话文件, a file, 本轮差异,
/// ＋, 左滑归档; 设置 with 已归档对话, and 开发者选项; from 0.4.1 the sidebar swiped out and back, a file picked from the
/// computer, DeepSeek's result file in Quick Look; from 0.4.2 the list's red [草稿]. Each picture is a test attachment;
/// with TEST_RUNNER_SHOTS_DIR on the xcodebuild line it is also written there.
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

    /// 0.6.2's 灵动岛样子 only, in both lights: the lock-screen card is white on light and dark on dark, so the two
    /// screenshots are what the user looks at. The whole tour takes minutes; this is the one page.
    @MainActor func testIslandLight() throws { try islandPreview(variant: "light", appearance: "light") }
    @MainActor func testIslandDark() throws { try islandPreview(variant: "dark", appearance: "dark") }

    @MainActor private func islandPreview(variant: String, appearance: String) throws {
        continueAfterFailure = true
        let app = launch(appearance: appearance, extra: ["-TeleplyDemo"])
        let enter = app.buttons["进入示例"]
        XCTAssertTrue(enter.waitForExistence(timeout: 20), "the demo's 登录 never showed")
        enter.tap()
        XCTAssertTrue(app.staticTexts["我的电脑"].waitForExistence(timeout: 10), "我的电脑 never showed")
        let connect = app.buttons["连接测试电脑 A"]
        if connect.waitForExistence(timeout: 5) { connect.tap() }
        let menu = app.buttons["打开导航"]
        XCTAssertTrue(menu.waitForExistence(timeout: 15), "the list never showed")
        menu.tap()
        let gear = app.buttons["设置"].firstMatch
        XCTAssertTrue(gear.waitForExistence(timeout: 10), "设置 was not in the sidebar")
        gear.tap()
        XCTAssertTrue(app.navigationBars["设置"].waitForExistence(timeout: 10), "设置 never opened")
        app.swipeUp()
        let developer = app.buttons["开发者选项"].firstMatch
        for _ in 0..<3 where !developer.isHittable { app.swipeUp() }
        XCTAssertTrue(developer.isHittable, "开发者选项 could not be reached")
        developer.tap()
        XCTAssertTrue(app.navigationBars["开发者选项"].waitForExistence(timeout: 10), "开发者选项 never opened")
        let island = app.buttons["灵动岛样子"].firstMatch
        for _ in 0..<3 where !island.isHittable { app.swipeUp() }
        XCTAssertTrue(island.isHittable, "灵动岛样子 could not be reached")
        island.tap()
        XCTAssertTrue(app.navigationBars["灵动岛样子"].waitForExistence(timeout: 10), "灵动岛样子 never opened")
        // 0.6.2: the lock-screen card in both lights first, then the fixed-width compact island.
        snap(app, page: "27-island-lock-light", variant: variant)
        for (title, page) in [("锁屏卡片 · 深色", "27-island-lock-dark"), ("紧凑（灵动岛）", "27-island-compact")] {
            let header = app.staticTexts[title].firstMatch
            XCTAssertTrue(header.waitForExistence(timeout: 5), "\(title) was not on the page")
            _ = reach(app, header)
            scrollSlowly(app)  // reach stops when the header is only just on screen; its content is under it
            snap(app, page: page, variant: variant)
        }
        app.terminate()
    }

    /// 0.6.4: the list's running row and the conversation page's 正在思考 line, from the demo's fixed running turn.
    @MainActor func testRunningLight() throws { try runningShots(variant: "light", appearance: "light") }

    @MainActor private func runningShots(variant: String, appearance: String) throws {
        continueAfterFailure = true
        let app = launch(appearance: appearance, extra: ["-TeleplyDemo"])
        let enter = app.buttons["进入示例"]
        XCTAssertTrue(enter.waitForExistence(timeout: 20), "the demo's 登录 never showed")
        enter.tap()
        XCTAssertTrue(app.staticTexts["我的电脑"].waitForExistence(timeout: 10), "我的电脑 never showed")
        let connect = app.buttons["连接测试电脑 A"]
        if connect.waitForExistence(timeout: 5) { connect.tap() }
        let running = app.buttons.containing(NSPredicate(format: "label CONTAINS %@", "运行中示例")).firstMatch
        XCTAssertTrue(running.waitForExistence(timeout: 10), "the running row never showed")
        snap(app, page: "27-running-list", variant: variant)
        running.tap()
        XCTAssertTrue(app.navigationBars["运行中示例"].waitForExistence(timeout: 10), "the running conversation never opened")
        snap(app, page: "27-running-chat", variant: variant)
        app.terminate()
    }

    /// One short, slow drag up (about a quarter of the screen), for bringing what is just under the bottom edge into
    /// view without the fling a normal swipe adds.
    @MainActor private func scrollSlowly(_ app: XCUIApplication) {
        let start = app.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.72))
        let end = app.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.46))
        start.press(forDuration: 0.3, thenDragTo: end, withVelocity: .slow, thenHoldForDuration: 0.1)
        sleep(1)
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

        // 0.4.1: a swipe right from the middle of the list pulls the sidebar out; a swipe left anywhere takes it back.
        sleep(1)
        first.swipeRight()
        XCTAssertTrue(app.staticTexts["电脑遥控"].waitForExistence(timeout: 5), "a swipe right on the list did not open the sidebar")
        if app.staticTexts["电脑遥控"].exists {
            snap(app, page: "27-drawer-swipe", variant: variant)
            app.swipeLeft()
            XCTAssertTrue(app.staticTexts["电脑遥控"].waitForNonExistence(timeout: 5), "a swipe left did not close the sidebar")
            if app.staticTexts["电脑遥控"].exists { app.buttons["关闭导航"].firstMatch.tap() }
        }
        // The swipe started on this row and must not have opened it (0.4.1 tour): no message box. The row's own title
        // reads as static text too, so the title is no sign of the conversation.
        XCTAssertFalse(composer(app).exists, "a swipe on a row opened its conversation")
        sleep(1)

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
            sleep(1)  // the popover closes before the next tap lands
        }

        // Sending on the demo (0.3.0): a send starts a turn (停止这一轮 shows), the next one queues. Typing waits for
        // the box to hold the keyboard focus (build 6adede40: a tap while the popover closed was swallowed).
        let field = composer(app)
        if field.waitForExistence(timeout: 5), focus(field) {
            field.typeText("hello")
            skipKeyboardTip(app)
            app.buttons["发送"].firstMatch.tap()
            if app.buttons["停止这一轮"].waitForExistence(timeout: 5) {
                snap(app, page: "08-sent", variant: variant)
            }
            let queue = app.buttons["发送并排队"].firstMatch
            if focus(field), queue.waitForExistence(timeout: 5) {
                field.typeText("one more")
                queue.tap()
                let promote = app.buttons.containing(NSPredicate(format: "label BEGINSWITH %@", "立即补充")).firstMatch
                if promote.waitForExistence(timeout: 5) {
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

        // 本轮差异 and ＋ in the same conversation (0.4.0); the conversation files from its ⋯.
        let process = app.buttons.containing(NSPredicate(format: "label CONTAINS %@", "处理过程")).firstMatch
        if process.waitForExistence(timeout: 5), reach(app, process, up: false) {
            process.tap()
            let diff = app.buttons.containing(NSPredicate(format: "label CONTAINS %@", "本轮差异")).firstMatch
            if diff.waitForExistence(timeout: 5), reach(app, diff) {
                diff.tap()
                if app.navigationBars["本轮差异"].waitForExistence(timeout: 10) {
                    sleep(1)
                    snap(app, page: "14-diff", variant: variant)
                }
                back(app)
            }
        }
        let plus = app.buttons["添加附件或引用"].firstMatch
        if plus.waitForExistence(timeout: 5), plus.isHittable {
            plus.tap()
            sleep(1)
            snap(app, page: "15-plus", variant: variant)
            app.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.2)).tap()
            sleep(1)
        }
        let more = app.buttons["对话菜单"].firstMatch
        if more.waitForExistence(timeout: 5) {
            more.tap()
            let files = app.buttons["对话文件"].firstMatch
            if files.waitForExistence(timeout: 5) {
                files.tap()
                let note = app.buttons.containing(NSPredicate(format: "label CONTAINS %@", "说明.md")).firstMatch
                if note.waitForExistence(timeout: 10) {
                    snap(app, page: "16-files", variant: variant)
                    note.tap()
                    if app.navigationBars["说明.md"].waitForExistence(timeout: 10) {
                        sleep(1)
                        snap(app, page: "17-file", variant: variant)
                    }
                    back(app)
                }
            }
        }

        // 0.4.1: ＋ → 从电脑选择文件 → a folder → a file's page; 0.5.6: its ⋯ holds save, Quick Look and 添加到消息.
        if plus.waitForExistence(timeout: 5), plus.isHittable {
            plus.tap()
            let pick = app.buttons["从电脑选择文件"].firstMatch
            if pick.waitForExistence(timeout: 5) {
                pick.tap()
                let place = app.buttons.containing(NSPredicate(format: "label CONTAINS %@", "固定目录")).firstMatch
                if place.waitForExistence(timeout: 10) {
                    place.tap()
                    let file = app.buttons.containing(NSPredicate(format: "label CONTAINS %@", "遥应下载测试.txt")).firstMatch
                    if file.waitForExistence(timeout: 10) {
                        snap(app, page: "28-computer-folder", variant: variant)
                        file.tap()
                        let menu = app.buttons["文件菜单"].firstMatch
                        XCTAssertTrue(menu.waitForExistence(timeout: 10), "a computer file did not open its page")
                        if menu.exists {
                            snap(app, page: "29-computer-file", variant: variant)
                            menu.tap()
                            let add = app.buttons["添加到消息"].firstMatch
                            XCTAssertTrue(add.waitForExistence(timeout: 5), "the file's ⋯ had no 添加到消息")
                            if add.exists {
                                snap(app, page: "29b-file-menu", variant: variant)
                                add.tap()
                            }
                        }
                    }
                }
            }
        }

        // 0.4.2: words left in the box show on the list after a red [草稿].
        let box = composer(app)
        if box.waitForExistence(timeout: 5), focus(box) {
            box.typeText("还没发出去的话")
        }
        back(app)
        let marked = app.buttons.containing(NSPredicate(format: "label CONTAINS %@", "草稿：还没发出去的话")).firstMatch
        XCTAssertTrue(marked.waitForExistence(timeout: 5), "the list showed no 草稿 for a box left with words")
        if marked.exists { snap(app, page: "34-draft", variant: variant) }
        let cards = app.buttons.containing(NSPredicate(format: "label CONTAINS %@", "Claude 下一步示例")).firstMatch
        if cards.waitForExistence(timeout: 10) {
            cards.tap()
            if app.staticTexts["Claude 下一步示例"].waitForExistence(timeout: 10) {
                app.swipeUp()
                snap(app, page: "11-cards", variant: variant)
            }
            back(app)
        }

        // Answering in the timeline (0.4.0): a Codex question chosen, then answered and folded; DeepSeek's approval;
        // Claude's desktop question.
        let question = app.buttons.containing(NSPredicate(format: "label CONTAINS %@", "只读问题记录")).firstMatch
        if question.waitForExistence(timeout: 10) {
            question.tap()
            let option = app.buttons["方案A，固定选项"].firstMatch
            if option.waitForExistence(timeout: 10) {
                option.tap()
                app.swipeUp()
                snap(app, page: "18-question", variant: variant)
                let submit = app.buttons["提交回答"].firstMatch
                if submit.waitForExistence(timeout: 5) {
                    submit.tap()
                    if app.buttons["修改答案"].waitForExistence(timeout: 10) {
                        snap(app, page: "19-answered", variant: variant)
                    }
                }
            }
            back(app)
        }
        let approval = app.buttons.containing(NSPredicate(format: "label CONTAINS %@", "DeepSeek 批准示例")).firstMatch
        if approval.waitForExistence(timeout: 10) {
            approval.tap()
            if app.buttons["仅允许本次"].waitForExistence(timeout: 10) {
                app.swipeUp()
                snap(app, page: "20-approval", variant: variant)
            }
            // 0.4.1: DeepSeek's result file: 查看成果文件 under its message, the Word file's page. 0.5.5: the Word file
            // fills the page as the phone shows it, with no Quick Look button.
            let result = app.buttons["查看成果文件"].firstMatch
            if result.waitForExistence(timeout: 5), reach(app, result, up: false) {
                result.tap()
                let word = app.buttons.containing(NSPredicate(format: "label CONTAINS %@", "翻译稿.docx")).firstMatch
                XCTAssertTrue(word.waitForExistence(timeout: 10), "查看成果文件 did not list the Word file")
                if word.exists {
                    snap(app, page: "30-deliverables", variant: variant)
                    word.tap()
                    if app.navigationBars["翻译稿.docx"].waitForExistence(timeout: 10) {
                        sleep(5)
                        snap(app, page: "31-word-file", variant: variant)
                        XCTAssertFalse(app.buttons["用快速查看打开"].exists, "the Word file's page still offers Quick Look")
                        back(app)
                    }
                }
            }
            back(app)
        }
        let prompt = app.buttons.containing(NSPredicate(format: "label CONTAINS %@", "Claude 选项示例")).firstMatch
        if prompt.waitForExistence(timeout: 10) {
            prompt.tap()
            if app.buttons.containing(NSPredicate(format: "label CONTAINS %@", "简洁要点")).firstMatch.waitForExistence(timeout: 10) {
                app.swipeUp()
                snap(app, page: "21-claude-question", variant: variant)
            }
            back(app)
        }

        // 新建对话 (0.4.0): the sheet, then the first message's page.
        let pencil = app.buttons["新建对话"].firstMatch
        if pencil.waitForExistence(timeout: 5) {
            pencil.tap()
            let first = textBox(app, "首条消息")
            if first.waitForExistence(timeout: 10) {
                sleep(1)
                snap(app, page: "22-new-chat", variant: variant)
                if focus(first) {
                    first.typeText("写一个测试")
                    skipKeyboardTip(app)
                    let create = app.buttons["创建并发送"].firstMatch
                    if create.waitForExistence(timeout: 5) {
                        create.tap()
                        if app.staticTexts["写一个测试"].firstMatch.waitForExistence(timeout: 10) {
                            snap(app, page: "23-new-job", variant: variant)
                        }
                        back(app)
                    }
                }
            }
        }

        // 左滑归档 and 撤销: a row on screen, slid left, stops on 归档 (0.4.1: never archived by the slide alone); a tap
        // archives.
        let row = app.buttons.containing(NSPredicate(format: "label CONTAINS %@", "只读问题记录")).firstMatch
        if row.waitForExistence(timeout: 10), reach(app, row) {
            row.swipeLeft()
            let archive = app.buttons["归档"].firstMatch
            _ = archive.waitForExistence(timeout: 3)
            snap(app, page: "33-swipe-archive", variant: variant)
            if archive.exists, archive.isHittable { archive.tap() }
            if app.buttons["撤销"].waitForExistence(timeout: 5) {
                snap(app, page: "24-undo", variant: variant)
            }
        }

        if menu.waitForExistence(timeout: 5) {
            menu.tap()
            let gear = app.buttons["设置"].firstMatch
            if gear.waitForExistence(timeout: 5) {
                gear.tap()
                if app.navigationBars["设置"].waitForExistence(timeout: 5) {
                    snap(app, page: "12-settings", variant: variant)
                    let archived = app.buttons["已归档对话"].firstMatch
                    if archived.waitForExistence(timeout: 5) {
                        archived.tap()
                        if app.navigationBars["已归档对话"].waitForExistence(timeout: 5) {
                            sleep(1)
                            snap(app, page: "25-archived", variant: variant)
                        }
                        back(app)
                    }
                    app.swipeUp()
                    snap(app, page: "26-settings-more", variant: variant)
                    let developer = app.buttons["开发者选项"].firstMatch
                    if developer.waitForExistence(timeout: 5), reach(app, developer) {
                        developer.tap()
                        if app.navigationBars["开发者选项"].waitForExistence(timeout: 5) {
                            snap(app, page: "13-developer", variant: variant)
                            let island = app.buttons["灵动岛样子"].firstMatch
                            if island.waitForExistence(timeout: 5), reach(app, island) {
                                island.tap()
                                if app.navigationBars["灵动岛样子"].waitForExistence(timeout: 5) {
                                    sleep(1)
                                    snap(app, page: "27-island", variant: variant)
                                }
                            }
                        }
                    }
                }
            }
        }
        app.terminate()
    }

    /// Scrolls the page (three times at most) until [element] can be tapped: up to reach what is below, down for
    /// what went under the title bar. A tap on an element that cannot be hit ends the whole test.
    @MainActor private func reach(_ app: XCUIApplication, _ element: XCUIElement, up: Bool = true) -> Bool {
        for _ in 0..<3 where !element.isHittable {
            if up { app.swipeUp() } else { app.swipeDown() }
        }
        return element.isHittable
    }

    /// The simulator's first keyboard shows a tip over the keys (QuickPath, "Continue"); it goes.
    @MainActor private func skipKeyboardTip(_ app: XCUIApplication) {
        let tip = app.buttons["Continue"].firstMatch
        if tip.exists, tip.isHittable { tip.tap() }
    }

    /// Taps [field] until it holds the keyboard focus (twice at most); typing without it fails the whole test.
    @MainActor private func focus(_ field: XCUIElement) -> Bool {
        for _ in 0..<2 {
            field.tap()
            sleep(1)
            if (field.value(forKey: "hasKeyboardFocus") as? Bool) == true { return true }
        }
        return false
    }

    /// The composer's text box: a growing text field is a text view to XCUITest.
    @MainActor private func composer(_ app: XCUIApplication) -> XCUIElement {
        textBox(app, "输入消息")
    }

    /// A text box by its label, a text view or a text field.
    @MainActor private func textBox(_ app: XCUIApplication, _ label: String) -> XCUIElement {
        let kinds = NSPredicate(format: "label == %@ AND (elementType == %d OR elementType == %d)", label,
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
