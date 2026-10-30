import SwiftUI

/// 0.6.5: for words chosen at run time (`device.connectable ? "在线" : "离线"`) and custom controls that take a String;
/// SwiftUI localizes a literal by itself, but a String it is handed later would stay Chinese.
func L(_ key: String) -> String {
    NSLocalizedString(key, bundle: .main, comment: "")
}

/// The same key as a SwiftUI key, for a `Text`/`Button` whose words are chosen at run time: `Text(LK(word))` asks
/// the String Catalog, while `Text(word)` would show the String verbatim.
func LK(_ key: String) -> LocalizedStringKey {
    LocalizedStringKey(key)
}
