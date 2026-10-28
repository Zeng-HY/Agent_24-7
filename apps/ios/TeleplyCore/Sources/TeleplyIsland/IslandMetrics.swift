import Foundation

/// Sizes the island pins so that Apple's self-ticking timer text cannot stretch it (0.6.2). `Text(timerInterval:)` asks
/// for the widest reading it could ever show, and with no limit the compact island grew into a bar across the whole
/// top of the screen, over the clock, signal and battery (user 10-28).
public enum IslandMetrics {
    /// The compact island's right side at the 13-point font: wide enough for "59:59"; an hour's "1:02:03" scales a
    /// little and still fits. The short states (等你 / ✓ / ! / 断开) use the same width, so the island's length does
    /// not change with its state.
    public static let compactTrailing: Double = 46
    /// A timer in the expanded list or on the lock-screen card: never wider than this, so the title keeps its room.
    public static let rowTimer: Double = 54
}
