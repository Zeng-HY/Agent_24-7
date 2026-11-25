import Foundation
import Testing
@testable import TeleplyModel

/// 用量 (11-17): the words the phone shows for what the computer read (usage_limits.py; Android UsageTest). Pure
/// functions only: no screen, no network, and the clock is always the test's own.
struct UsageTests {
    private let zone = TimeZone(identifier: "Asia/Shanghai")!

    /// 10:22 on 11-17 (Beijing), the moment the hand-off's example read the computer at.
    private func moment(_ month: Int, _ day: Int, _ hour: Int, _ minute: Int, _ second: Int = 0) -> Int64 {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = zone
        let parts = DateComponents(year: 2026, month: month, day: day, hour: hour, minute: minute, second: second)
        return Int64(((calendar.date(from: parts)?.timeIntervalSince1970 ?? 0) * 1000).rounded())
    }

    private func seconds(_ month: Int, _ day: Int, _ hour: Int, _ minute: Int) -> Int64 {
        moment(month, day, hour, minute) / 1000
    }

    private var now: Int64 { moment(11, 17, 10, 22) }

    private func weekly(_ resetsAt: Int64?, used: Int = 84) -> UsageWindow {
        UsageWindow(kind: "weekly", name: "每周", usedPercent: used, resetsAt: resetsAt)
    }

    // MARK: What the computer sent

    @Test func theWholeAnswerIsRead() throws {
        let json = try JSONValue.parse(Data(#"""
        {"codex":{"available":true,"source":"live","as_of":1794882122354,"plan":"pro",
          "windows":[{"kind":"weekly","minutes":10080,"used_percent":84,"resets_at":1795006481,"name":"每周"}],
          "reached":null,
          "resets":{"available":1,"items":[{"id":"credit-available","title":"Full reset",
            "description":"Thanks for using Codex!","granted_at":1794000000,"expires_at":1797000000}]},
          "ordinary_usage_allowed":true},
         "claude":{"available":true,"source":"window","as_of":1794882122354,
          "text":"Usage: 35% of 5-hour limit, Resets at 12:20 PM",
          "windows":[{"kind":"5h","label":"5-hour limit","name":"5 小时","used_percent":35,"resets_at":null,
            "resets_text":"12:20"}],"minimized":false},
         "now":1794882122354}
        """#.utf8))
        let usage = UsageReport.parse(json)
        #expect(usage.codex.windows.count == 1)
        #expect(usage.codex.windows.first?.usedPercent == 84)
        #expect(usage.codex.windows.first?.name == "每周")
        #expect(usage.codex.windows.first?.resetsAt == 1795006481)
        #expect(usage.codex.source == "live")
        #expect(usage.codex.reached == nil)
        #expect(usage.codex.resets)
        #expect(usage.codex.resetsAvailable == 1)
        #expect(usage.codex.credits?.first?.title == "Full reset")
        #expect(usage.codex.credits?.first?.expiresAt == 1797000000)
        #expect(usage.claude.windows.first?.usedPercent == 35)
        #expect(usage.claude.windows.first?.resetsText == "12:20")
        #expect(usage.claude.minimized == false)
        #expect(usage.now == 1794882122354)
    }

    @Test func theRecordsCarryNoResetCreditsAndSayWhyTheyAreOld() throws {
        let json = try JSONValue.parse(Data(#"""
        {"codex":{"available":true,"source":"records","as_of":1794882122354,"plan":"pro",
          "windows":[{"kind":"weekly","minutes":10080,"used_percent":84,"resets_at":1795006481,"name":"每周"}],
          "reached":null,"resets":null,"ordinary_usage_allowed":null,
          "live_error":"读不到 Codex 的实时用量：没找到这台电脑上的 Codex"},
         "claude":{"available":false,"reason":"这台电脑没装 Claude"},"now":1794882122354}
        """#.utf8))
        let usage = UsageReport.parse(json)
        #expect(!usage.codex.resets)
        #expect(usage.codex.resetsAvailable == nil)
        #expect(usage.codex.credits == nil)
        #expect(usage.codex.liveError == "读不到 Codex 的实时用量：没找到这台电脑上的 Codex")
        #expect(usage.codex.source == "records")
    }

    @Test func aComputerWithoutAnAppSaysSo() throws {
        let json = try JSONValue.parse(Data(#"{"codex":{"available":false,"reason":"这台电脑没装 Codex"},"claude":{"available":false,"reason":"这台电脑没装 Claude"},"now":0}"#.utf8))
        let usage = UsageReport.parse(json)
        #expect(!usage.codex.available)
        #expect(usage.codex.reason == "这台电脑没装 Codex")
        #expect(!usage.claude.available)
        #expect(usage.codex.windows.isEmpty)
    }

    @Test func claudeWordsThePhoneCannotReadAreShownWhole() throws {
        let json = try JSONValue.parse(Data(#"{"codex":{"available":false},"claude":{"available":true,"text":"Plan usage unavailable","windows":[],"minimized":true},"now":0}"#.utf8))
        let usage = UsageReport.parse(json)
        #expect(usage.claude.windows.isEmpty)
        #expect(usage.claude.text == "Plan usage unavailable")
        #expect(usage.claude.minimized)
    }

    // MARK: Other assistants (protocol 2 `agents`)

    @Test func newAssistantsCarryTheirOwnWindowsAndLabelFallback() throws {
        let json = try JSONValue.parse(Data(#"""
        {"codex":{"available":false},"claude":{"available":false},"now":1794882122354,
         "agents":{
           "gemini":{"available":true,"source":"live","as_of":1794882122000,
             "windows":[
               {"kind":"5h","label":"Gemini 模型 · 5 小时","used_percent":150,"resets_at":1795006481},
               {"kind":"weekly","label":"Gemini 模型 · 每周","used_percent":-4,"resets_at":null,"resets_text":"周五 10:00"}
             ]},
           "Bad Id":{"available":true,"windows":[{"kind":"5h","name":"不该出现"}]},
           "not usage":{"available":true}
         }}
        """#.utf8))
        let usage = UsageReport.parse(json)
        #expect(usage.agents["Bad Id"] == nil)
        #expect(usage.agents["not usage"] == nil)
        let gemini = try #require(usage.agents["gemini"])
        #expect(gemini.id == "gemini")
        #expect(gemini.available && gemini.source == "live" && gemini.asOf == 1_794_882_122_000)
        #expect(gemini.windows.map(\.name) == ["Gemini 模型 · 5 小时", "Gemini 模型 · 每周"])
        #expect(gemini.windows.map(\.usedPercent) == [100, 0])
        #expect(gemini.windows[0].resetsAt == 1_795_006_481)
        #expect(gemini.windows[1].resetsAt == nil)
        #expect(gemini.windows[1].resetsText == "周五 10:00")
    }

    @Test func newAssistantsComeInTheCatalogsOrderAndSayWhyTheyCannotBeRead() {
        let catalog = AgentCatalogSnapshot.fromServer([
            AgentInfo(id: "zeta", order: 20, legacy: false, caps: AgentCapabilities(usage: true)),
            AgentInfo(id: "alpha", order: 10, legacy: false, caps: AgentCapabilities(usage: true)),
            AgentInfo(id: "old", order: 15, legacy: true, caps: AgentCapabilities(usage: true)),
            AgentInfo(id: "quiet", order: 30, legacy: false, caps: AgentCapabilities(usage: false)),
        ])
        var report = UsageReport(now: now)
        report.agents = ["zeta": AgentUsage(id: "zeta", available: true, windows: [weekly(nil)])]
        #expect(agentUsageOrder(report, catalog: catalog) == ["alpha", "zeta"])
        #expect(agentUsageLine(AgentUsage(id: "gamma"), name: "Antigravity") == "读不到 Antigravity 的用量")
        #expect(agentUsageLine(AgentUsage(id: "gamma", reason: "Antigravity 没装"), name: "Antigravity") == "Antigravity 没装")
        #expect(agentWindowLine(weekly(nil), source: "live", nowMs: now, zone: zone) == "")
        var withText = weekly(nil)
        withText.resetsText = "周五 10:00"
        #expect(agentWindowLine(withText, source: "live", nowMs: now, zone: zone) == "周五 10:00 重置")
        #expect(agentWindowLine(weekly(seconds(11, 17, 13, 34)), source: "live", nowMs: now, zone: zone)
                == "今天 13:34 重置（还有 3 小时 12 分）")
    }

    // MARK: When it resets

    @Test func todayTomorrowAnotherDayOrAlreadyGone() {
        #expect(resetLine(weekly(seconds(11, 17, 20, 54)), source: "live", nowMs: now, zone: zone) == "今天 20:54 重置（还有 10 小时 32 分）")
        #expect(resetLine(weekly(seconds(11, 18, 20, 54)), source: "live", nowMs: now, zone: zone) == "明天 20:54 重置（还有 1 天 10 小时）")
        #expect(resetLine(weekly(seconds(11, 21, 15, 0)), source: "live", nowMs: now, zone: zone) == "11月21日 15:00 重置（还有 4 天 4 小时）")
        #expect(resetLine(weekly(seconds(11, 17, 9, 0)), source: "live", nowMs: now, zone: zone) == "已过重置时间")
        #expect(resetLine(weekly(seconds(11, 17, 9, 0)), source: "records", nowMs: now, zone: zone)
                == "已过重置时间，等电脑上 Codex 下一次回话就会更新")
    }

    @Test func theTimeLeftIsSaidInTheLongestUnitThatFits() {
        #expect(resetLine(weekly(seconds(11, 17, 13, 34)), source: "live", nowMs: now, zone: zone) == "今天 13:34 重置（还有 3 小时 12 分）")
        #expect(resetLine(weekly(seconds(11, 17, 10, 47)), source: "live", nowMs: now, zone: zone) == "今天 10:47 重置（还有 25 分钟）")
        #expect(resetLine(weekly(seconds(11, 17, 10, 23)), source: "live", nowMs: moment(11, 17, 10, 22, 30), zone: zone)
                == "今天 10:23 重置（马上）")
        #expect(resetLine(weekly(nil), source: "live", nowMs: now, zone: zone) == "")
    }

    @Test func whereTheNumbersCameFrom() {
        #expect(sourceLine(source: "live", asOf: now - 30_000, nowMs: now, zone: zone) == "刚从 Codex 读到")
        #expect(sourceLine(source: "live", asOf: now - 5 * 60_000, nowMs: now, zone: zone) == "5 分钟前从 Codex 读到")
        #expect(sourceLine(source: "records", asOf: now, nowMs: now, zone: zone)
                == "来自电脑上 Codex 最近一次回话（10:22）。之后在别处用掉的，这里还没算上。")
        #expect(sourceLine(source: "", asOf: now, nowMs: now, zone: zone) == "")
    }

    // MARK: The confirmation

    @Test func theConfirmationSaysWhatItUsesAndWarnsWhileThereIsRoom() {
        let credit = ResetCredit(id: "credit-available", title: "Full reset", expiresAt: seconds(12, 13, 6, 48))
        let expected = "会马上恢复 Codex 的用量限额。用掉就没了，不能撤回。\n"
            + "这次用：Full reset，12月13日 到期\n"
            + "现在每周还剩 16%，还没用完，现在用可能浪费。"
        #expect(confirmText(credit, windows: [weekly(nil)], zone: zone) == expected)
    }

    @Test func aLimitNearlyGoneGetsNoWarning() {
        let credit = ResetCredit(id: "c", title: "Full reset", expiresAt: nil)
        let expected = "会马上恢复 Codex 的用量限额。用掉就没了，不能撤回。\n这次用：Full reset，不会过期"
        #expect(confirmText(credit, windows: [weekly(nil, used: 95)], zone: zone) == expected)
    }

    @Test func withoutOneCreditPickedOnlyTheFirstLineAndTheWarning() {
        #expect(confirmText(nil, windows: [weekly(nil)], zone: zone)
                == "会马上恢复 Codex 的用量限额。用掉就没了，不能撤回。\n现在每周还剩 16%，还没用完，现在用可能浪费。")
        #expect(confirmText(nil, windows: [], zone: zone) == "会马上恢复 Codex 的用量限额。用掉就没了，不能撤回。")
    }

    @Test func aCreditWithoutATitleIsCalledAUsageReset() {
        #expect(confirmText(ResetCredit(), windows: [], zone: zone).contains("这次用：用量重置，不会过期"))
    }

    // MARK: The request id that keeps a retry from using a second credit

    @Test func theRequestIdStaysUntilAFinalAnswer() {
        let attempt = ResetAttempt()
        let first = attempt.id()
        #expect(attempt.id() == first)
        #expect(attempt.keepsId(ServiceFailure(status: 409, code: "reset_unconfirmed")))
        #expect(attempt.keepsId(URLError(.timedOut)))
        #expect(!attempt.keepsId(ServiceFailure(status: 409, code: "codex_refused")))
        #expect(!attempt.keepsId(ServiceFailure(status: 400, code: "not_confirmed")))
        attempt.done()
        #expect(attempt.id() != first)
    }

    /// 11-17 review: only the answers that say for certain nothing was used may drop the request id.
    @Test func onlyTheCodesThatSayNothingWasUsedDropTheId() {
        let attempt = ResetAttempt()
        // A 500 or a relay hiccup may hide a reset that did go through: the same id has to be sent again.
        #expect(attempt.keepsId(ServiceFailure(status: 500)))
        #expect(attempt.keepsId(ServiceFailure(status: 500, detail: "电脑端出错，没确认这次用成了没有，请到电脑上的 Codex 里看用量")))
        #expect(attempt.keepsId(ServiceFailure(status: 502)))
        #expect(attempt.keepsId(ServiceFailure(status: 504)))
        #expect(attempt.keepsId(ServiceFailure(status: 409, code: "device_offline")))
        #expect(attempt.keepsId(ServiceFailure(status: 409, code: "reset_unconfirmed")))
        #expect(attempt.keepsId(URLError(.networkConnectionLost)))
        // These say for certain nothing was used.
        for code in ["not_confirmed", "bad_request", "codex_unreachable", "codex_refused", "no_codex"] {
            #expect(!attempt.keepsId(ServiceFailure(status: 409, code: code)))
        }
    }
}
