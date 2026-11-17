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
        // The relay's words for 创建账号, 忘记密码 and 删除账号 (relay_identity.py, relay_accounts.py).
        "请输入有效的邮箱地址": "Enter a valid email address.",
        "密码须为 12 至 256 个字符": "Passwords must be 12 to 256 characters.",
        "验证码不对": "That code isn’t right.",
        "验证码已失效，请重新发送": "This code has expired. Send a new one.",
        "邮箱已关联账号，请登录": "This email already has an account. Sign in instead.",
        "当前注册名额已满": "Sign-up is full for now.",
        "邮箱服务暂未启用": "Email isn’t available on this service yet.",
        "当前密码错误": "The current password is wrong.",
        "密码已变化，请重新登录": "The password has changed. Sign in again.",
        // Codex's and Claude's usage (usage_limits.py, 11-17): the fixed sentences the computer sends.
        "已用掉 1 次重置，Codex 用量恢复了": "Used 1 reset. Codex’s limits are back.",
        "现在没有能重置的限额，这次没用掉": "There’s nothing to reset right now, so nothing was used.",
        "没有可用的重置次数，这次没用掉": "There are no reset credits, so nothing was used.",
        "这次之前已经用成了，没有再用掉一次": "This reset had already gone through, so nothing more was used.",
        "没确认这次用成了没有。再点一次会用同一个编号重试，不会多用掉一次。":
            "Couldn’t confirm whether this went through. Trying again uses the same request, so no second credit is used.",
        "没确认这次用成了没有。": "Couldn’t confirm whether this went through.",
        "要先在手机上确认": "Confirm it on the phone first.",
        "请求编号不对": "That request id isn’t valid.",
        "重置编号不对": "That reset id isn’t valid.",
        "这台电脑没装 Codex": "Codex isn’t installed on this computer.",
        "这台电脑没装 Claude": "Claude isn’t installed on this computer.",
        "电脑上 Claude 没开": "Claude isn’t open on this computer.",
        "Claude 窗口上没有用量（要开着一个 Code 对话）": "Claude’s window shows no usage. Open a Code conversation there.",
        "这会儿读不到 Claude 窗口，请稍后再试": "Can’t read Claude’s window right now. Try again in a moment.",
        "电脑上还没有 Codex 的用量记录（用一次 Codex 就会有）": "No Codex usage on this computer yet. One Codex reply will bring it.",
        "读不到 Codex 的实时用量：": "Couldn’t read Codex’s live usage: ",
        "Codex 没给用量：": "Codex didn’t give its usage: ",
        "Codex 没让用：": "Codex wouldn’t let it be used: ",
        "没用掉：连不上电脑上的 Codex（": "Not used: couldn’t reach Codex on this computer (",
    ]

    public static func text(_ raw: String) -> String {
        guard language.hasPrefix("en") else { return raw }
        if let exact = english[raw] { return exact }
        if let seconds = wait(raw) { return seconds == 1 ? "Try again in 1 second." : "Try again in \(seconds) seconds." }
        for (zh, en) in english where !zh.isEmpty && raw.hasPrefix(zh) {
            return en + raw.dropFirst(zh.count)
        }
        return raw
    }

    /// The seconds in the relay's "请在 N 秒后重试" (a request it limits, 429).
    static func wait(_ raw: String) -> Int? {
        guard raw.hasPrefix("请在 "), raw.hasSuffix(" 秒后重试") else { return nil }
        return Int(raw.dropFirst("请在 ".count).dropLast(" 秒后重试".count))
    }
}
