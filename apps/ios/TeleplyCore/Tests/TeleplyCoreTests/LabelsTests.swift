import Foundation
import Testing
@testable import TeleplyModel

struct LabelsTests {
    var calendar: Calendar {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = TimeZone(identifier: "Asia/Shanghai")!
        return calendar
    }

    @Test func agoReadsLikeTheWeb() {
        let now = Date(timeIntervalSince1970: 1_792_843_200)  // 2026-10-24 20:00 in Shanghai
        let ms = { (seconds: Double) in Int64((now.timeIntervalSince1970 - seconds) * 1000) }
        #expect(Labels.ago(0, now: now, calendar: calendar) == "")
        #expect(Labels.ago(ms(30), now: now, calendar: calendar) == "刚刚")
        #expect(Labels.ago(ms(600), now: now, calendar: calendar) == "10 分钟前")
        #expect(Labels.ago(ms(3 * 3_600), now: now, calendar: calendar) == "今天 17:00")
        #expect(Labels.ago(ms(24 * 3_600), now: now, calendar: calendar) == "昨天 20:00")
        #expect(Labels.ago(ms(3 * 86_400), now: now, calendar: calendar) == "10-21 20:00")
    }

    @Test func tenThousandsAndStates() {
        #expect(Labels.wan(9_999) == "9999")
        #expect(Labels.wan(169_000) == "16.9万")
        #expect(Labels.wan(260_000) == "26万")
        #expect(Labels.status("running") == "● 运行中")
        #expect(Labels.status("") == "状态不明")
        #expect(Labels.sourceName("deepseek") == "DeepSeek")
    }
}
