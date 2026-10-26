import SwiftUI

/// While the app opens (spec 4.8; Android LaunchPage): only the mark and the name, where 登录 will keep them, on
/// the page colour that the system launch screen also shows, so nothing jumps when the next page arrives.
struct LaunchView: View {
    var body: some View {
        GeometryReader { geometry in
            BrandHeader()
                .frame(maxWidth: .infinity)
                .padding(.top, max(48, geometry.size.height * 0.11))
                .rise(0)
        }
        .background(AccountPalette.page.ignoresSafeArea())
    }
}
