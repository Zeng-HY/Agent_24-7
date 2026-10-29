import Foundation

/// 0.6.5: for words chosen at run time (`device.connectable ? "在线" : "离线"`) and custom controls that take a String;
/// SwiftUI localizes a literal by itself, but a String it is handed later would stay Chinese.
func L(_ key: String) -> String {
    NSLocalizedString(key, bundle: .main, comment: "")
}
