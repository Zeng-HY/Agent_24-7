import SwiftUI
import TeleplyState

/// The sidebar over the workspace (spec 4.2): from the left, the smaller of 320 pt and 88% of the width, right
/// corners 20 pt, the panel colour, opaque; the page behind dims and stays put. ☰ brings it 24 pt in with a fade
/// (web .drawer .box). On the list a swipe right from anywhere pulls it out under the finger; while it is open a
/// swipe left anywhere, on it or on the dim, takes it back (user 10-26: from the edge alone it was hard to pull out,
/// and a swipe left often did not close it). A drag that starts up or down is scrolling and is left alone, and so is
/// one on the source chips while they scroll. A tap on the dim or Esc closes it. While it is open, VoiceOver reads
/// only the sidebar.
struct DrawerHost<Content: View>: View {
    let model: AppModel
    /// Pulling it out, only on the list: the conversation page keeps the system's swipe back.
    let enabled: Bool
    @ViewBuilder let content: () -> Content

    @Environment(Chrome.self) private var chrome
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    /// What the drag under way does, and where the drawer's left edge is while it moves (-width shut, 0 open). The
    /// system puts it back to idle when the drag ends or is taken away (a screenshot, Control Center, a call), so a
    /// lost drag never leaves the drawer half out with the dim catching every touch (0.3.0 on a phone, user 10-26).
    @GestureState private var pull = Pull.idle
    /// Where the drawer goes once a drag ends, animated; nil when it rests.
    @State private var settle: CGFloat?
    /// What the drag under way decided on its first move, for when it ends. A plain box: changing it redraws nothing.
    @State private var decided = Decision()

    enum Pull: Equatable {
        case idle
        /// Up or down, or the other way: scrolling, not the drawer.
        case ignored
        case moving(CGFloat)
    }

    final class Decision {
        /// Opening (from the list) or closing (from the open drawer); nil for a drag left alone.
        var opening: Bool?
    }

    var body: some View {
        GeometryReader { geometry in
            let width = min(320, geometry.size.width * 0.88)
            let drag = offset
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
                        .accessibilityAddTraits(.isModal)
                        .transition(reduceMotion ? .opacity : .offset(x: -24).combined(with: .opacity))
                }
            }
            // On the whole workspace, beside its scrolling and taps. It sits on what stays: a view that leaves takes
            // its gesture with it, and the drag would then never end (what left the drawer stuck in 0.3.0).
            .simultaneousGesture(swipe(width), including: enabled || chrome.drawer ? .all : .subviews)
            // Ended or taken away: taps count again a moment later.
            .onChange(of: pull) {
                if pull == .idle, chrome.pulling {
                    chrome.pulling = false
                    chrome.pulledAt = Date()
                }
            }
            .animation(reduceMotion ? .easeOut(duration: 0.08) : .drawer(), value: chrome.drawer)
        }
    }

    /// The drawer's left edge while a finger or the last drag's end moves it.
    private var offset: CGFloat? {
        if case .moving(let x) = pull { return x }
        return settle
    }

    /// A tap on the dim always ends it, whatever a drag left behind.
    private func close() {
        settle = nil
        chrome.closeDrawer()
    }

    /// One swipe both ways, decided on its first move: across rather than up or down, rightwards on the list (not
    /// on scrolling source chips) or leftwards on the open drawer. Opening, past half way or flung it stays out;
    /// closing, a short one springs back.
    private func swipe(_ width: CGFloat) -> some Gesture {
        DragGesture(minimumDistance: 12, coordinateSpace: .global)
            .updating($pull) { value, pull, _ in
                let dx = value.translation.width
                if pull == .idle {
                    let across = abs(dx) > abs(value.translation.height) * 1.2
                    let opening = !chrome.drawer
                    let moving = opening ? across && dx > 0 && !chrome.noPull.contains(value.startLocation) : across && dx < 0
                    decided.opening = moving ? opening : nil
                    pull = moving ? .moving(opening ? -width : 0) : .ignored
                }
                guard case .moving = pull, let opening = decided.opening else { return }
                chrome.pulling = true
                pull = .moving(opening ? min(0, max(-width, dx - width)) : min(0, dx))
            }
            .onEnded { value in
                guard let opening = decided.opening else { return }
                decided.opening = nil
                chrome.pulledAt = Date()
                let dx = value.translation.width
                let flung = value.predictedEndTranslation.width
                if opening {
                    let open = flung > width / 2 || dx > width / 2
                    settle = min(0, max(-width, dx - width))
                    if open { chrome.openDrawer() }
                    withAnimation(.drawer()) { settle = open ? 0 : -width } completion: { settle = nil }
                } else if flung < -width / 3 {
                    settle = min(0, dx)
                    withAnimation(.drawer()) { settle = -width } completion: {
                        chrome.closeDrawer()
                        settle = nil
                    }
                } else {
                    settle = min(0, dx)
                    withAnimation(.drawer()) { settle = 0 } completion: { settle = nil }
                }
            }
    }
}
