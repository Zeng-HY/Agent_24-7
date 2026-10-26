import Foundation
import Testing
@testable import TeleplyDemo
import TeleplyModel
@testable import TeleplyState

/// 新建对话 on the local demo, through the whole app (Android ReaderUiScenarios new-conversation cases).
@MainActor
struct NewConversationTests {
    func demoList(device index: Int = 0) async -> AppModel {
        let model = makeApp()
        model.openDemo()
        model.login(name: "x", password: "y")
        await model.settle()
        model.select(model.account!.devices[index])
        await model.settle()
        await model.workspace.settle()
        return model
    }

    func openSheet(_ model: AppModel, app: String? = nil, folder: String = "", projectless: Bool = false) async {
        model.startNew(app: app, folder: folder, projectless: projectless)
        for _ in 0..<1_000 where model.workspace.pane != "new" { await Task.yield() }
        await model.workspace.settle()
    }

    /// The demo computer reports in three looks; the page's own looks wait (the test pacer never ends a wait).
    func look(_ model: AppModel) async {
        if let job = model.jobs.jobs.first { model.jobs.check(job) }
        await model.jobs.settle()
        await model.settle()
    }

    @Test func aFirstMessageBecomesAJobItsPageThenTheConversation() async {
        let model = await demoList()
        await openSheet(model, app: "codex")
        #expect(model.workspace.pane == "new")
        #expect(model.workspace.newData["folders"]["items"].array.count == 3)
        #expect(!model.workspace.saved["new_id"].string().isEmpty)
        model.workspace.chooseFolder("D:/fixture", projectless: false)
        model.workspace.edit("first_message", "写一个测试")
        model.workspace.create()
        await model.workspace.settle()
        await model.settle()
        #expect(model.workspace.pane == nil)
        #expect(model.screen == .reading && isNewPage(model.chat?.id))
        #expect(model.chat?.title == "写一个测试")
        let job = model.jobs.jobs.first
        #expect(job?.label == "固定测试项目")
        #expect(job?.body["folder"].string() == "D:/fixture")
        await model.jobs.settle()
        #expect(model.jobs.jobs.first?.state == "creating")
        await look(model)
        #expect(newJobInline(model.jobs.jobs.first!) == "发送中…")
        await look(model)
        #expect(model.chat?.id == "fixture-new-1")
        #expect(model.handoff?.text == "写一个测试")
        #expect(model.jobs.jobs.isEmpty)
        #expect(model.messages.first?.text == "写一个测试")
        model.back()
        await model.settle()
        #expect(model.chats.first?.id == "fixture-new-1")
    }

    @Test func theSheetKeepsTheProjectAndPicksButNotTheWordsOrTheRequest() async {
        let model = await demoList()
        await openSheet(model, app: "codex", folder: "D:/fixture-docs")
        #expect(model.workspace.saved["folder"].string() == "D:/fixture-docs")
        let first = model.workspace.saved["new_id"].string()
        model.workspace.edit("new_model", "fixture-model")
        model.workspace.edit("first_message", "第一条")
        model.workspace.create()
        await model.workspace.settle()
        await model.settle()
        model.back()
        await model.settle()
        await openSheet(model, app: "codex")
        #expect(model.workspace.saved["folder"].string() == "D:/fixture-docs")
        #expect(model.workspace.saved["new_model"].string() == "fixture-model")
        #expect(model.workspace.saved["first_message"].string().isEmpty)
        #expect(model.workspace.saved["new_id"].string() != first)
        #expect(model.dockJobs.count == 1)
        #expect(newJobDock(model.dockJobs[0]).hasPrefix("Codex · "))
    }

    @Test func aFirstMessageThatDidNotGoOutCanComeBackToTheSheet() async {
        let model = await demoList()
        await openSheet(model, app: "codex")
        model.workspace.edit("first_message", "fail")
        model.workspace.create()
        await model.workspace.settle()
        await model.jobs.settle()
        await model.settle()
        let job = model.jobs.jobs.first!
        #expect(job.state == "failed" && job.retryable)
        #expect(newJobInline(job) == "没发出去 · 点击处理")
        model.openJob(job)
        #expect(model.jobSheet == job.request)
        model.restoreJob(job)
        for _ in 0..<1_000 where model.workspace.pane != "new" { await Task.yield() }
        await model.workspace.settle()
        #expect(model.jobSheet == nil && model.jobs.jobs.isEmpty)
        #expect(model.workspace.saved["first_message"].string() == "fail")
    }

    @Test func continuingSendsTheSameRequestWhichIsMadeOnce() async {
        let model = await demoList()
        await openSheet(model, app: "codex")
        model.workspace.edit("first_message", "fail")
        model.workspace.create()
        await model.workspace.settle()
        await model.jobs.settle()
        await model.settle()
        let job = model.jobs.jobs.first!
        model.retryJob(job)
        await model.jobs.settle()
        #expect(model.jobs.current(job.request)?.request == job.request)
        #expect(model.jobs.jobs.count == 1)
        #expect(model.jobs.current(job.request)?.state == "creating")
    }

    @Test func deepseekNeedsAWorkspaceAndAComputerWithoutClaudeStartsElsewhere() async {
        let model = await demoList()
        await openSheet(model, app: "deepseek")
        model.workspace.edit("first_message", "清理一下")
        model.workspace.create()
        await model.workspace.settle()
        #expect(model.workspace.error == "还没发出，草稿还在：DeepSeek 要选一个工作区")
        #expect(model.jobs.jobs.isEmpty)
        let other = await demoList(device: 1)
        await other.loadTreeAndSettle()
        await openSheet(other, app: "claude")
        #expect(other.workspace.key?.app == "codex")
    }
}

extension AppModel {
    /// The sidebar read that says which apps the computer has, done.
    func loadTreeAndSettle() async {
        loadTree(force: true)
        await settle()
    }
}
