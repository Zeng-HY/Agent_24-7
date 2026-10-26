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
    /// Where the drawer's left edge is while a finger moves it: from -width (shut) to 0 (open).
    @State private var drag: CGFloat?

    var body: some View {
        GeometryReader { geometry in
            let width = min(320, geometry.size.width * 0.88)
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
                if enabled && !chrome.drawer && drag == nil {
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

    private func close() {
        chrome.closeDrawer()
    }

    /// From the list's left edge: the drawer follows the finger; past half way (or flung) it stays open.
    private func openingDrag(_ width: CGFloat) -> some Gesture {
        DragGesture(minimumDistance: 10)
            .onChanged { value in
                drag = min(0, max(-width, value.translation.width - width))
            }
            .onEnded { value in
                let open = value.predictedEndTranslation.width > width / 2
                if open {
                    chrome.openDrawer()
                    withAnimation(.drawer()) { drag = 0 } completion: { drag = nil }
                } else {
                    withAnimation(.drawer()) { drag = -width } completion: { drag = nil }
                }
            }
    }

    /// On the open drawer: a swipe left takes it away with the finger; a short one springs back.
    private func closingDrag(_ width: CGFloat) -> some Gesture {
        DragGesture(minimumDistance: 12)
            .onChanged { value in
                guard chrome.drawer else { return }
                drag = min(0, value.translation.width)
            }
            .onEnded { value in
                guard chrome.drawer else { return }
                if value.predictedEndTranslation.width < -width / 3 {
                    withAnimation(.drawer()) { drag = -width } completion: {
                        chrome.closeDrawer()
                        drag = nil
                    }
                } else {
                    withAnimation(.drawer()) { drag = 0 } completion: { drag = nil }
                }
            }
    }
}
