import SwiftUI
import TeleplyState

/// The sidebar over the workspace (spec 4.2): from the left, the smaller of 320 pt and 88% of the width, right
/// corners 20 pt, the panel colour, opaque; the page behind dims and stays put. ☰ brings it 24 pt in with a fade
/// (web .drawer .box); a drag from the list's left edge pulls it out under the finger; a tap on the dim, a swipe
/// left or Esc closes it. While it is open, VoiceOver reads only the sidebar.
struct DrawerHost<Content: View>: View {
    let model: AppModel
    /// The left-edge pull, only on the list: the conversation page keeps the system's swipe back.
    let enabled: Bool
    @ViewBuilder let content: () -> Content

    @Environment(Chrome.self) private var chrome
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    /// Where the drawer's left edge is while a finger moves it: from -width (shut) to 0 (open). The system puts it
    /// back to nil when the drag ends or is taken away (a screenshot, Control Center, a call), so a lost drag never
    /// leaves the drawer half out with the dim catching every touch (0.3.0 on a phone, user 10-26: a strip on the
    /// left, taps did nothing, the list would not scroll).
    @GestureState private var pull: CGFloat?
    /// Where the drawer goes once a drag ends, animated; nil when it rests.
    @State private var settle: CGFloat?

    var body: some View {
        GeometryReader { geometry in
            let width = min(320, geometry.size.width * 0.88)
            let drag = pull ?? settle
            ZStack(alignment: .leading) {
                content()
                    .accessibilityHidden(chrome.drawer)
                if chrome.drawer || drag != nil {
                    Palette.scrim
                        .ignoresSafeArea()
                        .opacity(drag.map { max(0, min(1, ($0 + width) / width)) } ?? 1)
                        .contentShape(Rectangle())
                        .onTapGesture { close() }
                        .accessibilityHidden(true)
                        .transition(.opacity)
                    DrawerView(model: model, opening: chrome.drawerOpenings, close: close)
                        .frame(width: width)
                        .offset(x: drag ?? 0)
                        .gesture(closingDrag(width))
                        .accessibilityAddTraits(.isModal)
                        .transition(reduceMotion ? .opacity : .offset(x: -24).combined(with: .opacity))
                }
                // The edge stays while its own drag runs: a view that leaves takes its gesture with it, and the drag
                // would then never end (what left the drawer stuck in 0.3.0).
                if enabled && !chrome.drawer {
                    Color.clear
                        .frame(width: 16)
                        .frame(maxHeight: .infinity)
                        .contentShape(Rectangle())
                        .gesture(openingDrag(width))
                        .accessibilityHidden(true)
                }
            }
            .animation(reduceMotion ? .easeOut(duration: 0.08) : .drawer(), value: chrome.drawer)
        }
    }

    /// A tap on the dim always ends it, whatever a drag left behind.
    private func close() {
        settle = nil
        chrome.closeDrawer()
    }

    /// From the list's left edge: the drawer follows the finger; past half way (or flung) it stays open.
    private func openingDrag(_ width: CGFloat) -> some Gesture {
        DragGesture(minimumDistance: 10)
            .updating($pull) { value, pull, _ in
                pull = min(0, max(-width, value.translation.width - width))
            }
            .onEnded { value in
                let open = value.predictedEndTranslation.width > width / 2
                settle = min(0, max(-width, value.translation.width - width))
                if open { chrome.openDrawer() }
                withAnimation(.drawer()) { settle = open ? 0 : -width } completion: { settle = nil }
            }
    }

    /// On the open drawer: a swipe left takes it away with the finger; a short one springs back.
    private func closingDrag(_ width: CGFloat) -> some Gesture {
        DragGesture(minimumDistance: 12)
            .updating($pull) { value, pull, _ in
                pull = min(0, value.translation.width)
            }
            .onEnded { value in
                settle = min(0, value.translation.width)
                if value.predictedEndTranslation.width < -width / 3 {
                    withAnimation(.drawer()) { settle = -width } completion: {
                        chrome.closeDrawer()
                        settle = nil
                    }
                } else {
                    withAnimation(.drawer()) { settle = 0 } completion: { settle = nil }
                }
            }
    }
}
