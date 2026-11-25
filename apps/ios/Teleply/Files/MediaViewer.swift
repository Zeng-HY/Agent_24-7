import AVFoundation
import AVKit
import SwiftUI
import TeleplyModel
import TeleplyState

/// Audio and video (§6.2): the system player streams the file route itself with the app's sign-in cookie, so nothing is
/// downloaded whole first. A file the player turns down becomes a file card with 用其他应用打开.
struct MediaViewer: View {
    let model: AppModel
    let file: FileRef
    let onOpenOther: () -> Void
    @State private var source: MediaSource?
    @State private var failed = false
    @State private var started = false

    private var video: Bool { file.view == "video" }

    var body: some View {
        Group {
            if failed || (started && source == nil) {
                VStack(spacing: 12) {
                    Image(systemName: video ? "video.slash" : "speaker.slash")
                        .font(.system(size: 44))
                        .foregroundStyle(Palette.muted)
                    Text(video ? "这个视频放不了，可以保存后用其他应用打开。" : "这个音频放不了，可以保存后用其他应用打开。")
                        .noteFont()
                        .foregroundStyle(Palette.muted)
                        .multilineTextAlignment(.center)
                    Button("用其他应用打开", systemImage: "square.and.arrow.up", action: onOpenOther)
                        .buttonStyle(PillStyle(kind: .primary))
                }
                .frame(maxWidth: .infinity)
                .padding(.top, 72)
            } else if let source {
                PlayerView(source: source) { failed = true }
                    .background(Color.black)
            } else {
                ProgressView()
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(Palette.page)
        .task(id: file.id + "\u{1F}" + file.version) {
            source = await model.workspace.mediaSource(file)
            started = true
            if source == nil { failed = true }
        }
    }
}

/// The system player, with its own play, pause and seek controls. The sign-in goes as an HTTP cookie, the only way
/// AVFoundation lets a player carry one (`AVURLAssetHTTPCookiesKey`); no private header key is used.
private struct PlayerView: UIViewRepresentable {
    let source: MediaSource
    let onFailed: () -> Void

    func makeCoordinator() -> Coordinator { Coordinator(onFailed: onFailed) }

    func makeUIView(context: Context) -> AVPlayerViewController {
        let controller = AVPlayerViewController()
        let options: [String: Any] = [AVURLAssetHTTPCookiesKey: source.cookies]
        let asset = AVURLAsset(url: source.url, options: options)
        let item = AVPlayerItem(asset: asset)
        let player = AVPlayer(playerItem: item)
        controller.player = player
        controller.showsPlaybackControls = true
        controller.videoGravity = .resizeAspect
        player.play()
        context.coordinator.watch(item, player: player)
        return controller
    }

    func updateUIView(_ controller: AVPlayerViewController, context: Context) {}

    static func dismantleUIView(_ controller: AVPlayerViewController, coordinator: Coordinator) {
        coordinator.stop()
        controller.player?.pause()
        controller.player = nil
    }

    final class Coordinator {
        private let onFailed: () -> Void
        private var watch: Task<Void, Never>?

        init(onFailed: @escaping () -> Void) {
            self.onFailed = onFailed
        }

        func watch(_ item: AVPlayerItem, player: AVPlayer) {
            watch = Task { @MainActor [weak self] in
                while !Task.isCancelled {
                    switch item.status {
                    case .failed:
                        self?.onFailed()
                        return
                    case .readyToPlay:
                        player.play()
                    default:
                        break
                    }
                    try? await Task.sleep(for: .milliseconds(400))
                }
            }
        }

        func stop() {
            watch?.cancel()
            watch = nil
        }
    }
}
