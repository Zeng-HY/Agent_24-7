import Foundation

/// The most common words the computer sends back, translated by their exact Chinese text (0.6.5). Everything else
/// stays as the computer wrote it; README lists what is not covered.
public enum Hints {
    /// Set once at launch from the iPhone language; tests keep Chinese.
    nonisolated(unsafe) public static var language = "zh-Hans"

    private static let english: [String: String] = [
        "已接收": "Received",
        "已送达": "Delivered",
        "已排队": "Queued",
        "未接收": "Not Received",
        "已取消排队": "Removed from Queue",
        "送达状态待确认": "Delivery Unconfirmed",
        "停止请求已接收，等待轮次确认": "Stop request received. Waiting for the turn to confirm.",
        "连接中断，正在重连": "Connection lost. Reconnecting…",
        "登录失效，请返回账号页重新登录": "Your session has expired. Go back to Account and sign in again.",
        "请求完成": "Request completed",
        "服务端未成功": "Server Failed",
        "连接失败，请检查网络和服务地址后重试。": "Couldn’t connect. Check your network and the service address, then try again.",
        "找不到这个对话（可能已归档或删掉了）": "Conversation not found. It may have been archived or deleted.",
        "对话身份不匹配": "Conversation identity doesn’t match.",
        "实时协议或会话身份不匹配": "Live protocol or session identity mismatch.",
        "实时序号不连续": "Live sequence numbers are out of order.",
        "分页位置无效，请刷新": "Invalid page position. Refresh and try again.",
        "对话已变化，请刷新": "The conversation has changed. Refresh and try again.",
        "文件引用无效或不属于当前对话": "This file reference is invalid or doesn’t belong to this conversation.",
        "电脑已离线，请等待上线后再连接": "This computer is offline. Try again when it’s back online.",
    ]

    public static func text(_ raw: String) -> String {
        guard language.hasPrefix("en") else { return raw }
        if let exact = english[raw] { return exact }
        for (zh, en) in english where !zh.isEmpty && raw.hasPrefix(zh) {
            return en + raw.dropFirst(zh.count)
        }
        return raw
    }
}
