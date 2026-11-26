import SwiftUI
import TeleplyModel

/// A file's type, drawn here rather than taken from a picture (design 4.2): one sheet of paper, its top-right corner
/// folded over a little lighter, the sheet in the type's own colour and the type's short mark on it in white. The same
/// colours in light and dark. No company's mark is drawn, and no picture asset is used.
///
/// [size] is the square it is laid out in; the sheet itself is narrower than that, as paper is. The mark is the table
/// of design 4.3 (`fileTypeMark`), so iPhone and Android say the same thing for the same file.
struct FileTypeIcon: View {
    let name: String
    var size: CGFloat = 44

    private var mark: FileTypeMark { fileTypeMark(for: name) }

    var body: some View {
        // The sheet: narrower than the square, and a little shorter, so the icon sits with air around it as the
        // system's own document symbols do.
        let width = size * 0.78
        let height = size * 0.94
        // Long enough to read as folded paper at 20 points, never more than a quarter of the sheet's height.
        let fold = min(width * 0.36, height * 0.26)
        let sheet = Color(.sRGB, red: Double(mark.red) / 255, green: Double(mark.green) / 255,
                          blue: Double(mark.blue) / 255, opacity: 1)
        ZStack {
            FilePageShape(fold: fold)
                .fill(sheet)
            FilePageFoldShape(fold: fold)
                .fill(Color.white.opacity(0.42))
            Text(mark.text)
                .font(.system(size: markSize(width), weight: .bold, design: .rounded))
                .foregroundStyle(.white)
                .lineLimit(1)
                .minimumScaleFactor(0.6)
                .frame(width: width * 0.8)
                // A little below the middle, clear of the folded corner.
                .offset(y: height * 0.07)
        }
        .frame(width: width, height: height)
        .frame(width: size, height: size)
        .accessibilityHidden(true)
    }

    /// The word size for the mark: three letters and more shrink so that the widest (CSV, ZIP, </>) still fits.
    private func markSize(_ width: CGFloat) -> CGFloat {
        switch mark.text.count {
        case 0: return width * 0.4
        case 1: return width * 0.46
        case 2: return width * 0.40
        case 3: return width * 0.32
        default: return width * 0.25
        }
    }
}

/// The sheet: a page with its top-right corner cut off, the three other corners rounded.
private struct FilePageShape: Shape {
    let fold: CGFloat

    func path(in rect: CGRect) -> Path {
        let radius = min(rect.width, rect.height) * 0.14
        let fold = min(self.fold, min(rect.width, rect.height) * 0.4)
        var path = Path()
        path.move(to: CGPoint(x: radius, y: rect.minY))
        path.addLine(to: CGPoint(x: rect.maxX - fold, y: rect.minY))
        path.addLine(to: CGPoint(x: rect.maxX, y: rect.minY + fold))
        path.addLine(to: CGPoint(x: rect.maxX, y: rect.maxY - radius))
        path.addQuadCurve(to: CGPoint(x: rect.maxX - radius, y: rect.maxY),
                          control: CGPoint(x: rect.maxX, y: rect.maxY))
        path.addLine(to: CGPoint(x: rect.minX + radius, y: rect.maxY))
        path.addQuadCurve(to: CGPoint(x: rect.minX, y: rect.maxY - radius),
                          control: CGPoint(x: rect.minX, y: rect.maxY))
        path.addLine(to: CGPoint(x: rect.minX, y: rect.minY + radius))
        path.addQuadCurve(to: CGPoint(x: rect.minX + radius, y: rect.minY),
                          control: CGPoint(x: rect.minX, y: rect.minY))
        path.closeSubpath()
        return path
    }
}

/// The folded corner itself: the triangle under the cut, a little lighter than the sheet.
private struct FilePageFoldShape: Shape {
    let fold: CGFloat

    func path(in rect: CGRect) -> Path {
        let fold = min(self.fold, min(rect.width, rect.height) * 0.4)
        var path = Path()
        path.move(to: CGPoint(x: rect.maxX - fold, y: rect.minY))
        path.addLine(to: CGPoint(x: rect.maxX - fold, y: rect.minY + fold))
        path.addLine(to: CGPoint(x: rect.maxX, y: rect.minY + fold))
        path.closeSubpath()
        return path
    }
}
