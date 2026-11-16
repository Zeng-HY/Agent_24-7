import Testing
import TeleplyModel

/// 11-16: following changes only with the reader's actions, never with the content's height (Android ReadingFollow;
/// the rules behind the iPhone never being pulled back to the bottom while reading above).
struct ReadingFollowTests {
    @Test func aDragStopsFollowingAndNewFramesOnlyMarkUnseen() {
        let dragged = ReadingFollow().dragged()
        #expect(!dragged.following)
        #expect(dragged.arrived(newer: false, scrolling: false).unseen)
        #expect(!dragged.arrived(newer: false, scrolling: false).following)
    }

    @Test func stoppingNearTheBottomFollowsAgainAndFarFromItDoesNot() {
        let dragged = ReadingFollow().dragged()
        #expect(dragged.stopped(atBottom: true) == ReadingFollow(following: true, unseen: false))
        #expect(dragged.stopped(atBottom: false) == dragged)
        #expect(!ReadingFollow(following: false, unseen: true).stopped(atBottom: true).unseen)
    }

    @Test func openingAndSendingFollowWhileAHistoryPageDoesNot() {
        let reading = ReadingFollow(following: false, unseen: true)
        #expect(reading.opened(following: true) == ReadingFollow())
        #expect(reading.opened(following: false) == ReadingFollow(following: false, unseen: false))
        #expect(reading.sent() == ReadingFollow())
        #expect(reading.opened(following: false).arrived(newer: true, scrolling: false).unseen)
    }

    @Test func contentGrowingOrShrinkingDoesNotChangeTheHabit() {
        let above = ReadingFollow(following: false, unseen: true)
        // A frame while a finger is on the page changes nothing; nor does a fling stopping far from the bottom.
        #expect(above.arrived(newer: false, scrolling: true) == above)
        #expect(above.stopped(atBottom: false) == above)
        // Following and idle, a frame is followed: nothing to offer.
        #expect(ReadingFollow().arrived(newer: false, scrolling: false) == ReadingFollow())
    }
}
