import Testing
@testable import TeleplyState

/// 11-27 线六 (design §11.1, §11.3): when the iPad's conversation list shows and when its fold button does, for every
/// window, kept setting and page. Rules only: nothing is drawn and no computer is read.
@MainActor
struct ListColumnTests {
    /// Every page a window can be on, for the two windows (a wide iPad and a phone or a narrow window) and the setting
    /// either way: twenty combinations, each checked against the three rules.
    @Test func theListAndItsButtonFollowTheWindowTheSettingAndThePage() async {
        let screens: [AppModel.Screen] = [.launch, .login, .devices, .chats, .reading]
        for wide in [false, true] {
            for setting in [false, true] {
                for screen in screens {
                    let layout = listColumnLayout(wide: wide, setting: setting, screen: screen)
                    let reading = screen == .reading
                    let folded = wide && reading && setting
                    // The list is the page on a phone; in a wide window it is beside a conversation, and it goes
                    // only when that conversation and the setting fold it.
                    #expect(layout.listShown == (wide ? (screen == .chats || (reading && !folded)) : screen == .chats))
                    // The button is the wide window's, and only beside a conversation.
                    #expect(layout.buttonShown == (wide && reading))
                    // The fold is only ever a wide window's open conversation.
                    #expect(layout.collapsed == folded)
                }
            }
        }
    }

    @Test func aWideWindowWithNoConversationNeverHidesTheList() async {
        // The list page itself: the list is always there and nothing can fold it, whatever the setting says.
        for setting in [false, true] {
            let layout = listColumnLayout(wide: true, setting: setting, screen: .chats)
            #expect(layout.listShown)
            #expect(!layout.buttonShown)
            #expect(!layout.collapsed)
        }
        // The pages before the workspace show neither column.
        for screen in [AppModel.Screen.launch, .login, .devices] {
            let layout = listColumnLayout(wide: true, setting: true, screen: screen)
            #expect(!layout.listShown)
            #expect(!layout.buttonShown)
            #expect(!layout.collapsed)
        }
    }

    @Test func aKeptFoldComesBackWithTheNextConversation() async {
        // 收起 is kept while the list is back: the list shows anyway (the setting is not applied there), and the next
        // conversation opens folded, with the button saying 展开对话列表.
        let list = listColumnLayout(wide: true, setting: true, screen: .chats)
        #expect(list.listShown && !list.collapsed && !list.buttonShown)
        let opened = listColumnLayout(wide: true, setting: true, screen: .reading)
        #expect(!opened.listShown && opened.collapsed && opened.buttonShown)
        // Unfolding it is the setting gone: the list is back beside the conversation and the button stays.
        let unfolded = listColumnLayout(wide: true, setting: false, screen: .reading)
        #expect(unfolded.listShown && !unfolded.collapsed && unfolded.buttonShown)
        // And closing the conversation again brings the list back even with the setting on.
        #expect(listColumnLayout(wide: true, setting: true, screen: .chats).listShown)
    }

    @Test func aPhoneOrANarrowWindowIsNeverFolded() async {
        for setting in [false, true] {
            for screen in [AppModel.Screen.chats, .reading] {
                let layout = listColumnLayout(wide: false, setting: setting, screen: screen)
                #expect(layout.listShown == (screen == .chats))
                #expect(!layout.buttonShown)
                #expect(!layout.collapsed)
            }
        }
    }
}

