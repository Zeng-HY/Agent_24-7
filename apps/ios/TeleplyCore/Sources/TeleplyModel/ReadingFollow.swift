/// 11-16: whether a conversation's page follows new output, and whether there is more below (Android ReadingFollow;
/// the same rules on both phones). It changes only with what the reader does — a drag, stopping near the bottom,
/// opening, sending, 回到最新 — never with the content growing or shrinking, which used to pin the page back down in
/// the middle of a drag.
public struct ReadingFollow: Equatable, Sendable {
    public var following: Bool
    public var unseen: Bool

    public init(following: Bool = true, unseen: Bool = false) {
        self.following = following
        self.unseen = unseen
    }

    /// A finger is on the page: reading above, wherever it stops.
    public func dragged() -> ReadingFollow {
        ReadingFollow(following: false, unseen: unseen)
    }

    /// The finger (or the fling) stopped: near the bottom it follows again, otherwise the habit stays.
    public func stopped(atBottom bottom: Bool) -> ReadingFollow {
        bottom ? ReadingFollow(following: true, unseen: false) : self
    }

    /// Opening the conversation, 回到最新 or the pill: `following` says whether it opens at the newest.
    public func opened(following: Bool) -> ReadingFollow {
        ReadingFollow(following: following, unseen: false)
    }

    /// A send of yours: the page follows the bottom again.
    public func sent() -> ReadingFollow {
        ReadingFollow(following: true, unseen: false)
    }

    /// A new frame arrived: followed while following and nothing is moving, else marked unseen.
    public func arrived(newer: Bool, scrolling: Bool) -> ReadingFollow {
        following && !newer && !scrolling ? self : ReadingFollow(following: following, unseen: true)
    }
}
