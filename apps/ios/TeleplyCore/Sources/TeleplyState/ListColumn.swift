import Foundation

/// 11-27 (design §11): the conversation list's left column in a wide iPad window, and the button that folds it away.
/// Three answers only — whether the list is on screen, whether the title bar's button is there, and whether the list
/// is folded — from the window, the kept setting and the page. The view draws with these; the rules live here so that
/// every combination (wide or not, kept or not, each page) can be tested without a screen.
public struct ListColumnLayout: Equatable, Sendable {
    /// The list is on screen: the page itself on a phone, or the left column beside the conversation in a wide
    /// window. When it is folded it is still in the view tree (its scroll position and search stay), just slid away.
    public let listShown: Bool
    /// 收起对话列表 / 展开对话列表 is in the conversation's title bar. Only a wide window with a conversation open has
    /// it; a phone, a narrow window and the list page itself have no button, so the window never ends up one empty
    /// page with no way back.
    public let buttonShown: Bool
    /// The list is folded away and the conversation has the window. False on the list page itself even when the
    /// setting is on, so closing a conversation always brings the list back.
    public let collapsed: Bool

    public init(listShown: Bool, buttonShown: Bool, collapsed: Bool) {
        self.listShown = listShown
        self.buttonShown = buttonShown
        self.collapsed = collapsed
    }
}

/// Where the list and its button stand (design §11.1): [wide] is an iPad window wide enough for both columns,
/// [setting] is 对话列表收起 as the phone keeps it, [screen] is the page shown. Folding needs all three: a wide
/// window, a conversation open, and the setting on.
public func listColumnLayout(wide: Bool, setting: Bool, screen: AppModel.Screen) -> ListColumnLayout {
    let reading = screen == .reading
    let folded = wide && reading && setting
    return ListColumnLayout(listShown: wide ? (screen == .chats || (reading && !folded)) : screen == .chats,
                            buttonShown: wide && reading,
                            collapsed: folded)
}
