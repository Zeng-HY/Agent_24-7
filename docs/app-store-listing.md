# App Store 上架资料（遥应 iPhone 版）

记于 2026-10-31。这里是要填进 App Store Connect 的文字和选项，照着复制即可。首发地区：中国大陆以外（用户 10-31 定：先上外区，国区等 APP 备案）。

## 网址

- 支持网址：`https://pocketagentdesk.com/support`
- 营销网址：`https://pocketagentdesk.com`
- 隐私政策网址：`https://pocketagentdesk.com/privacy`

这三个网址在服务器换完域名（`docs/handoff-domain.md`）以后才打得开，要在提交审核前打开确认一遍。

## 名称、副标题、类别

| | 简体中文 | English |
|---|---|---|
| 名称 | 遥应 | Teleply |
| 副标题（30 字以内） | 手机上接着用电脑上的 AI 助手 | Coding agents, from your phone |

类别：主要“开发者工具”，次要“效率”。

## 描述

简体中文：

```
遥应把你电脑上 AI 编程助手的对话放到手机上。离开电脑时，也能看它做到了哪一步、回答它的提问、给它发新的要求。

· 看进度：对话在跑、在等你确认、已经做完，一眼就知道；锁屏和灵动岛上也能看到。
· 随手回复：文字、照片、语音都能发，直接进到电脑上的那段对话里。
· 回答提问：助手要你选择或批准时，在手机上直接点。
· 查看文件：打开电脑上的文档、表格和网页预览。
· 只连你自己的电脑：对话内容在手机和电脑之间转发，服务器不保存。

使用前要在 Windows 电脑上安装遥应电脑端（在 pocketagentdesk.com 下载），用同一个账号绑定。支持电脑上的 Claude Code、Codex 和 DeepSeek。
```

English:

```
Teleply puts the conversations of the AI coding assistants on your computer onto your phone. Away from your desk, see how far they got, answer their questions and send them new instructions.

• Follow progress: running, waiting for you, or done, at a glance — on the Lock Screen and in the Dynamic Island too.
• Reply on the go: text, photos and voice go straight into the conversation on your computer.
• Answer questions: when an assistant asks you to choose or approve, tap the answer on your phone.
• Open files: documents, spreadsheets and web previews from your computer.
• Only your own computer: conversations travel between your phone and your computer; our server does not keep them.

Teleply needs the Teleply computer app on a Windows PC (download at pocketagentdesk.com), bound to the same account. Works with Claude Code, Codex and DeepSeek on your computer.
```

以后加上中国大陆时，国区的描述和截图里去掉 Claude、Codex 这些名字。

## 关键词（100 字符以内，不写别家的商标）

- 简体中文：`远程,编程助手,AI,电脑,遥控,对话,开发者,代码,通知,灵动岛`
- English：`remote,coding,agent,AI,desktop,developer,code,assistant,companion,notifications`

## App 隐私（“App 隐私”页的问卷）

选“是，我们会从此 App 收集数据”，然后勾这几项。每一项都选：用于“App 功能”；与用户身份关联；不用于跟踪。

| 数据类型 | 实际是什么 |
|---|---|
| 联系信息 → 电子邮件地址 | 注册、登录、找回密码用的邮箱 |
| 标识符 → 用户 ID | 账号编号 |
| 标识符 → 设备 ID | 推送标识（苹果分配，用来发遥应通知） |
| 用户内容 → 其他用户内容 | 灵动岛和锁屏显示的对话标题与状态，最多留一天 |
| 使用数据 → 其他使用数据 | 每台电脑每天的请求次数和流量，用来防滥用 |

不勾的：照片、音频、文件（只转发，不保存）、诊断、位置、浏览记录、购买。App 里的隐私清单 `PrivacyInfo.xcprivacy` 写的是同一份。

## 年龄分级

各类内容都选“无”。“不受限制的网页访问”选“否”：App 里没有地址栏，对话里的链接交给 Safari 打开。问卷里如果问到 AI 生成的内容，照实选“有”：内容来自用户自己电脑上的 AI 助手。

## 审核信息

- 需要登录：是。提交前用一个自己能收信的邮箱，在 App 里注册一个审核专用账号，账号和密码填在这里（这个账号不绑真实电脑）。
- 联系人：你的姓名、电话、邮箱（只给审核员看）。
- 附件：录一段一两分钟的屏幕录像，手机和电脑一起出镜：电脑端绑定、手机上看对话进度、回复一条、答一个提问。上传到“附件”。
- 备注（英文，原样复制）：

```
Teleply is a companion app for the Teleply computer app on Windows. It shows and answers the conversations of AI coding assistants (Claude Code, Codex, DeepSeek) running on the user's own PC. Without a bound PC, the account shows an empty "My Computers" list.

To see every feature without a PC, use the built-in sample: on the sign-in screen tap the gear at the top right → Developer Options → Open Local Sample. It runs on fixed sample data and does not connect to any server. The attached video shows the app with a real PC.

Demo account (no PC bound): see the sign-in fields above.
Account deletion: Settings → Account → Delete Account (asks for the password).
Sign-up and password reset are inside the app (email code).
The app uses only standard HTTPS encryption (ITSAppUsesNonExemptEncryption = NO).
```

## 价格与销售范围

- 价格：免费。
- 地区：全选，再去掉“中国大陆”。
- 如果地区里有欧盟：要声明是不是“商家（trader）”。选“是”会在欧盟的商品页公开你的地址、电话和邮箱；不声明的话欧盟地区不会上架。怎么选由你决定。

## 截图

要一组 6.9 英寸 iPhone 的截图（1320 × 2868 或 1290 × 2796），3 到 10 张。iPhone 版改好后，自动截图会改用 iPhone 17 Pro Max 拍。建议顺序：我的电脑、对话列表、对话里回答提问、灵动岛、查看文件。

## 提交前核对

- 隐私政策、支持网址能打开；
- 用审核账号在 App 里登录、退出、删除账号都走一遍（删除后再注册一个新的审核账号）；
- 本地示例能打开；
- 版本号定为 1.0。
