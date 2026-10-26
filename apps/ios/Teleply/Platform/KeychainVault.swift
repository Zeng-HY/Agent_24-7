import Foundation
import Security
import TeleplyModel

/// The sign-in in the keychain (spec 12; Android SecureCookieVault): one item per service address, readable after
/// the first unlock, on this phone only, never in iCloud. A read while the phone is locked throws, so it is not
/// taken as signed out.
nonisolated final class KeychainVault: CookieVault {
    struct Locked: UserFacingError {
        var message: String { "手机锁着，暂时读不到登录信息，解锁后再试。" }
    }

    private let service = "com.pocketagentdesk.teleply.account"

    func read(_ key: String) throws -> SessionCookie? {
        var query = base(key)
        query[kSecReturnData as String] = true
        query[kSecMatchLimit as String] = kSecMatchLimitOne
        var item: CFTypeRef?
        let status = SecItemCopyMatching(query as CFDictionary, &item)
        switch status {
        case errSecSuccess:
            guard let data = item as? Data, let cookie = try? JSONDecoder().decode(SessionCookie.self, from: data) else {
                SecItemDelete(base(key) as CFDictionary)
                return nil
            }
            return cookie
        case errSecItemNotFound:
            return nil
        case errSecInteractionNotAllowed:
            throw Locked()
        default:
            return nil
        }
    }

    func write(_ key: String, _ cookie: SessionCookie?) throws {
        SecItemDelete(base(key) as CFDictionary)
        guard let cookie else { return }
        var item = base(key)
        item[kSecValueData as String] = try JSONEncoder().encode(cookie)
        item[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
        item[kSecAttrSynchronizable as String] = false
        let status = SecItemAdd(item as CFDictionary, nil)
        if status == errSecInteractionNotAllowed { throw Locked() }
    }

    /// Keychain items outlive the app; after a reinstall the old sign-ins go (UserDefaults does not survive one).
    func forgetAfterReinstall() {
        let marker = "teleply.installed"
        guard !UserDefaults.standard.bool(forKey: marker) else { return }
        SecItemDelete([kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: service] as CFDictionary)
        UserDefaults.standard.set(true, forKey: marker)
    }

    private func base(_ key: String) -> [String: Any] {
        [kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: service, kSecAttrAccount as String: key]
    }
}

/// Where this phone's records live: Application Support/Teleply, kept out of iCloud backups (Android disables
/// backup too).
nonisolated enum StoreFolder {
    static func url() -> URL {
        let base = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
        var folder = base.appendingPathComponent("Teleply", isDirectory: true)
        try? FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        var values = URLResourceValues()
        values.isExcludedFromBackup = true
        try? folder.setResourceValues(values)
        return folder
    }
}
