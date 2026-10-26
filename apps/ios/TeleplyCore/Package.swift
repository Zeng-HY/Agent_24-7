// swift-tools-version: 6.2
import PackageDescription

// The part of Teleply that never touches the screen, so it builds and tests on Windows as well as on the Mac.
// TeleplyModel: data and logic that may run off the main thread. TeleplyState: screen state, on the main
// thread. TeleplyDemo: the local demo (spec 4.6 本地示例).
let package = Package(
    name: "TeleplyCore",
    platforms: [.iOS(.v26), .macOS(.v15)],
    products: [
        .library(name: "TeleplyModel", targets: ["TeleplyModel"]),
        .library(name: "TeleplyState", targets: ["TeleplyState"]),
        .library(name: "TeleplyDemo", targets: ["TeleplyDemo"]),
    ],
    dependencies: [
        // Exact commits of the 0.9.0 tags. swift-cmark is listed only to pin what swift-markdown pulls in.
        .package(url: "https://github.com/swiftlang/swift-markdown.git", revision: "25cb61d3482054b09ae76ca4f281b1bfe7fe5a43"),
        .package(url: "https://github.com/swiftlang/swift-cmark.git", revision: "08ddb528923cc1a6527e02b7a1aee9e516ca749a"),
    ],
    targets: [
        .target(name: "TeleplyModel", dependencies: [.product(name: "Markdown", package: "swift-markdown")]),
        .target(name: "TeleplyState", dependencies: ["TeleplyModel"], swiftSettings: [.defaultIsolation(MainActor.self)]),
        .target(name: "TeleplyDemo", dependencies: ["TeleplyModel"]),
        .testTarget(name: "TeleplyCoreTests", dependencies: ["TeleplyModel", "TeleplyState", "TeleplyDemo"]),
    ]
)
