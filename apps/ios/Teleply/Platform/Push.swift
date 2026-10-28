import TeleplyModel
import TeleplyState
import UIKit
import UserNotifications

/// The system's side of 遥应通知 (TeleplyState PushPlatform; plan "Teleply - iOS 原生推送方案"): the permission, the
/// system's question, the push token, and whether this phone wants them (a setting on the phone).
struct SystemPush: PushPlatform {
    private static let wantedKey = "teleply.push.wanted"

    func permission() async -> PushPermission {
        await Self.read()
    }

    func ask() async -> Bool {
        (try? await UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .sound])) ?? false
    }

    func register() {
        UIApplication.shared.registerForRemoteNotifications()
    }

    var environment: String {
        #if DEBUG
        return "development"
        #else
        return "production"  // the App Store profile, which TestFlight builds are signed with
        #endif
    }

    var label: String { UIDevice.current.model }
    var version: String { AppVersion.short }

    func wanted() -> Bool { UserDefaults.standard.bool(forKey: Self.wantedKey) }
    func setWanted(_ on: Bool) { UserDefaults.standard.set(on, forKey: Self.wantedKey) }

    /// UNNotificationSettings is not Sendable: it stays in here, and only what it says goes on.
    nonisolated private static func read() async -> PushPermission {
        switch await UNUserNotificationCenter.current().notificationSettings().authorizationStatus {
        case .authorized, .provisional, .ephemeral: return .allowed
        case .denied: return .denied
        default: return .notAsked
        }
    }
}

/// Between iOS's push callbacks and the app model. The model is made in TeleplyApp's init; anything that comes
/// before it is attached waits here.
final class PushBridge {
    static let shared = PushBridge()
    private var model: AppModel?
    private var token: String?
    private var failure: String?
    private var target: PushTarget?

    func attach(_ model: AppModel) {
        self.model = model
        if let token { model.pushToken(token) }
        if let failure { model.pushTokenFailed(failure) }
        if let target { model.openNotification(target) }
        token = nil
        failure = nil
        target = nil
    }

    func token(_ hex: String) {
        if let model { model.pushToken(hex) } else { token = hex }
    }

    func failed(_ text: String) {
        if let model { model.pushTokenFailed(text) } else { failure = text }
    }

    func tapped(_ target: PushTarget) {
        if let model { model.openNotification(target) } else { self.target = target }
    }

    /// While 遥应 shows this very conversation, its notification is not shown again.
    func showing(_ target: PushTarget?) -> Bool {
        guard let target, let model else { return false }
        return model.isShowing(target)
    }
}

/// iOS's launch and push-token callbacks (UIApplicationDelegateAdaptor in TeleplyApp). The token is asked for at
/// each launch while 遥应通知 is wanted, as Apple asks: it changes after a restore, on a new phone, after a reinstall.
final class AppDelegate: NSObject, UIApplicationDelegate {
    func application(_ application: UIApplication, didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]? = nil) -> Bool {
        UNUserNotificationCenter.current().delegate = NotificationDelegate.shared
        Self.registerCategories()
        if SystemPush().wanted() { application.registerForRemoteNotifications() }
        return true
    }

    /// The relay's notices all arrive in one category, so the lock screen groups one computer's notices in one stack
    /// and its summary reads 还有 N 个对话 (PushNotice.summaryFormat; user 10-28). Registered at every launch: the
    /// system keeps categories per app, but a phone restored from a backup has none.
    private static func registerCategories() {
        let category = UNNotificationCategory(identifier: PushNotice.category, actions: [], intentIdentifiers: [],
                                             hiddenPreviewsBodyPlaceholder: nil,
                                             categorySummaryFormat: PushNotice.summaryFormat, options: [])
        UNUserNotificationCenter.current().setNotificationCategories([category])
    }

    func application(_ application: UIApplication, didRegisterForRemoteNotificationsWithDeviceToken deviceToken: Data) {
        PushBridge.shared.token(deviceToken.map { String(format: "%02x", $0) }.joined())
    }

    func application(_ application: UIApplication, didFailToRegisterForRemoteNotificationsWithError error: any Error) {
        PushBridge.shared.failed(error.localizedDescription)
    }
}

/// What iOS asks about a notification of 遥应's: whether to show it while 遥应 is in front (a banner without a sound,
/// and nothing at all while it shows that very conversation; user 10-28), and what a tap opens. The SDK calls these
/// off the main actor; they hop there. The completion-handler forms on purpose: Xcode 27.1 crashes compiling the
/// async forms of Objective-C delegate methods.
nonisolated final class NotificationDelegate: NSObject, UNUserNotificationCenterDelegate, Sendable {
    static let shared = NotificationDelegate()

    func userNotificationCenter(_ center: UNUserNotificationCenter, willPresent notification: UNNotification,
                                withCompletionHandler completionHandler: @escaping @Sendable (UNNotificationPresentationOptions) -> Void) {
        let target = PushTarget(userInfo: notification.request.content.userInfo)
        let passive = notification.request.content.interruptionLevel == .passive
        Task { @MainActor in
            switch PushNotice.foreground(showing: PushBridge.shared.showing(target), passive: passive) {
            case .none: completionHandler([])
            case .list: completionHandler([.list])  // a silent one only joins the notification centre
            case .banner: completionHandler([.banner, .list])  // no .sound: the app is open, so it stays quiet
            }
        }
    }

    func userNotificationCenter(_ center: UNUserNotificationCenter, didReceive response: UNNotificationResponse,
                                withCompletionHandler completionHandler: @escaping @Sendable () -> Void) {
        let target = response.actionIdentifier == UNNotificationDefaultActionIdentifier
            ? PushTarget(userInfo: response.notification.request.content.userInfo) : nil
        Task { @MainActor in
            if let target { PushBridge.shared.tapped(target) }
            completionHandler()
        }
    }
}
