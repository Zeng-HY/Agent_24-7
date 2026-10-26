import SwiftUI
import TeleplyState

/// Spec 4.8's opening: the Teleply mark and name centred on the page colour, rising into place like the web
/// account page (`.rise`, spec 5). In 0.1.0 it also shows the app version and the service version read once
/// from the default service, which proves the certificate and network settings on a real phone.
struct LaunchView: View {
    let model: LaunchModel

    // The web brand row (relay_account.css .brand): 30 px mark, 17 px semibold name, 10 px apart.
    @ScaledMetric(relativeTo: .headline) private var markSize: CGFloat = 30
    @ScaledMetric(relativeTo: .headline) private var nameSize: CGFloat = 17
    @ScaledMetric(relativeTo: .footnote) private var noteSize: CGFloat = 13
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var risen = false

    var body: some View {
        ZStack {
            Palette.page.ignoresSafeArea()
            VStack(spacing: 20) {
                brand
                VStack(spacing: 6) {
                    Text(verbatim: "版本 \(AppVersion.display)")
                    status
                }
                .font(.system(size: noteSize))
                .foregroundStyle(Palette.muted)
                .multilineTextAlignment(.center)
            }
            .padding(.horizontal, 24)
            .opacity(risen ? 1 : 0)
            .offset(y: risen || reduceMotion ? 0 : 14)
            .blur(radius: risen || reduceMotion ? 0 : 6)
        }
        .task {
            withAnimation(reduceMotion ? .easeOut(duration: 0.08) : .timingCurve(0.2, 0.8, 0.2, 1, duration: 0.7)) {
                risen = true
            }
            await model.check()
        }
    }

    private var brand: some View {
        HStack(spacing: 10) {
            Image("TeleplyMark")
                .renderingMode(.template)
                .resizable()
                .scaledToFit()
                .frame(width: markSize, height: markSize)
            Text(verbatim: "Teleply")
                .font(.system(size: nameSize, weight: .semibold))
        }
        .foregroundStyle(Palette.brandInk)
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(Text(verbatim: "Teleply"))
        .accessibilityAddTraits(.isHeader)
    }

    @ViewBuilder
    private var status: some View {
        switch model.phase {
        case .checking:
            Text("正在连接服务…")
        case .reachable(let version):
            Text(verbatim: "服务 \(version)")
        case .unreachable(let message):
            Text(message)
            Button("重试") {
                Task { await model.check() }
            }
            .buttonStyle(PrimaryCapsuleStyle())
            .padding(.top, 8)
        }
    }
}
