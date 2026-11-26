# 11-26 一批修正：问题清单和分工

这份文件是五路 DeepSeek 同时开工的共同依据。第 1 节是问题清单，第 2 节是分工，第 3 到 7 节分别写给五路，第 8 节是手机和电脑之间新增的约定，第 9 节是共同规矩，第 10 节由各路填写结果。

版本由合并的人统一改，各路都不改版本号。下一版计划：iOS 0.9.2（36），安卓 1.0.12（23），Windows dev.58。

## 1 问题清单

| 编号 | 现象 | 原因 | 归哪一路 |
|---|---|---|---|
| P1 | iPhone：一条消息一直挂着「送达状态待确认」。点「核对」没有任何变化，也撤不掉。安卓的代码一样。 | 已查明：这条消息根本没到电脑，电脑的送达记录里没有它。手机核对时，电脑回答「不知道」（`state: unknown`），手机就照旧显示待确认，什么也不说。待确认状态下没有「重发」，也没有「移除」；「撤回」只对电脑上排队的消息有用。 | 线一（iPhone）、线三（安卓）、线五（电脑明确回答「没收到」） |
| P2 | 插话（Claude 正在干活时补充）带的图片，和发给 Codex 的图片，在自己的气泡里都不显示缩略图。iPhone 和安卓都这样。 | 已查明：电脑已经把图片放在这条消息自己的 `images` 字段里，图片也取得到（编号就是手机上传时的编号，`/api/codex/image?id=…` 能取）。两边手机只认电脑另记的发送记录（状态里的 `images`），靠请求编号或「[图片]」标记去配对。插话和 Codex 新通道的消息两样都没有，所以配不上。 | 线一、线三 |
| P3 | iPhone：点开一份很大的 Word（四百多页、几百张表、几十个图表和嵌入对象，解开后正文约 24 MB），整页只有一行系统错误「未能完成操作。（OfficeImportErrorDomain 错误 912。）」，下面是「(null)」。 | 已查明：iPhone 版用 `WKWebView` 打开 Word，实际是苹果系统自带的转换器在转。转换器处理不了这份文件，系统就自己生成了这一页错误。我们的程序没发现失败，也没给别的办法。文件本身是好的：压缩包完整，不是 Strict 格式，电脑上的 Word 能打开。同一条回答里其实还有同名 PDF。 | 线二 |
| P4 | iPhone 和安卓：回答下面的文件条里，PDF、Word、Excel、SVG 等都是同一个空白文件图标或图片图标，只有图片有缩略图，分不出是什么文件。 | 设计缺口：没有按文件类型区分的图标。 | 线二（iPhone）、线四（安卓） |
| P5 | 安卓（另一位用户报告）：Word 第一次能打开，第二次打开时整个软件闪退。 | 推测，待复现：安卓版在程序里的网页视图中，用 docx-preview 画 Word，整份文件读进内存（`OfficePreview(bytes: ByteArray…)`）。大文件会让网页视图的渲染进程内存不够，被系统结束。整个安卓程序的网页视图都没处理「渲染进程没了」（`onRenderProcessGone` 一处都没有）。按安卓的规矩，没处理这件事，整个程序会跟着被结束，表现就是闪退。 | 线四 |
| P6 | 电脑：Claude 空闲时，手机发给它的带图消息发不出去。手机显示「第 1 张图片核验未通过（输入区识别到 0 张）」，重发一次又显示「识别到 2 张」。 | 部分查明（日志）：第一次贴图后等了 6 秒，输入框里一直数到 0 张；重发那次贴完数到 2 个「Remove …」按钮，而用户远程看到框里只有 1 张图。同一条路当天下午还成功发过带 1 张图的消息。可能有两种情况：一是 Claude 显示贴进去的图变慢了，超过 6 秒；二是 Claude 输入框的图片卡片改了样子，一张卡片带两个「Remove」按钮。现在的数法是数按钮，第二种情况会数成两张。另外，两次失败后，送达记录都停在 `dispatching`，没有改成未接收。 | 线五 |
| P7 | iPad：宽窗口里左边的对话列表收不起来。想像网页版 ChatGPT、Claude 那样，点一个按钮把列表收起来，对话占满整个窗口，再点一下展开。（用户 11-27 新加的功能） | 设计缺口：宽窗口是自己画的两栏（`RootView.swift` 的 `WorkspaceView.columns`：左边 `ChatListView` 固定 320–380pt，右边对话），没有收起开关。安卓没有平板两栏布局，不涉及。 | 线六 |

暂不安排：
- iPad 截图测试 `testIPadTour` 失败。从 0.8.0 起就这样，只影响截图测试，不影响使用。
- 中转服务器推给灵动岛的新助手（Antigravity 等）没有名字和颜色。改它要部署中转服务器，等用户安排。

## 2 分工（五路同时做）

| 路 | 做什么 | 分支 / 工作树 | 起点 |
|---|---|---|---|
| 线一 iPhone「发送」 | P1、P2 的 iPhone 部分 | `ios-send` / `D:\Personal\agent_remote_lanes\ios-send` | ipad-adapt 49c8239（0.9.1） |
| 线二 iPhone「文件」 | P3、P4 的 iPhone 部分 | `ios-files` / `D:\Personal\agent_remote_lanes\ios-files` | ipad-adapt 49c8239 |
| 线三 安卓「发送」 | P1、P2 的安卓部分 | `and-send` / `D:\Personal\agent_remote_lanes\and-send` | fp-android c12fa99（1.0.11） |
| 线四 安卓「文件」 | P5、P4 的安卓部分 | `and-files` / `D:\Personal\agent_remote_lanes\and-files` | fp-android c12fa99 |
| 线五 电脑 | P6，P1 的电脑部分 | `pc58` / `D:\Personal\agent_remote_lanes\pc58` | agent-registry dedb2b6（dev.57） |

两条 iPhone 线、两条安卓线会改同一个程序，合并由审核的人来做。为了少冲突，每路只改自己那几节列出的文件。实在要动别的文件，改动尽量小，并在结果里写明。演示数据各自新建文件（Swift 用 `extension`，Kotlin 用新文件），在原有演示文件里最多加一行把它接上。

## 3 线一 iPhone「发送」

### 3.1 P1：待确认要能核对出结果、能重发、能移除

现在的代码：
- `TeleplyCore/Sources/TeleplyState/ChatModel.swift`：`dispatch` 的 catch 块（失败但没有 `not_submitted` 就记成「送达状态待确认」）；`check` → `reconcile` → `client.receipt(...)`；`dismiss`。
- `TeleplyModel/ChatCore.swift`：`receiptLabel`、`agentReceiptLabel`。`unknown` 会落到默认的「送达状态待确认」。
- `Teleply/Composer/ComposerView.swift`：InputArea 里，待确认时只有「上一条送达状态待确认」和「核对待发送消息」；QueueTray（撤回）；RejectedBar（未接收：恢复草稿、移除）。
- `Teleply/Chat/ChatSheets.swift`：PendingSheet，只有「核对状态」和「恢复提交快照」。
- `TeleplyModel/Outbox.swift`：`outboxSends`。发出 10 分钟后，只要后面有新消息，这条副本就不再显示。
- `submit` 里有一条规矩：同样的字还在「提交中」或「待确认」时，拒绝再发。

要做的：
1. 读电脑新给的 `missing`（第 8.1 节）。核对结果是 `state == "unknown"` 且 `missing == true` 时，标成新标签「电脑没收到」。
2. 「电脑没收到」那条显示一行说明：「电脑没收到这条消息，可以重发。」按钮依次是「重发」「恢复草稿」「移除」。
   - **重发**：用**原来的请求编号**和**原来的内容**再发一次。电脑按请求编号去重（`codex_control._begin`：同一个编号、同样内容，已有结果就直接返回那个结果），所以原消息就算晚到，也不会重复。重发时标签回到「提交中」，以后照正常流程走。电脑回答「这次请求已提交过，结果尚未确认」时，原样显示这句话，标签回到待确认。
   - **恢复草稿**：和未接收的「恢复草稿」一样，把字和附件放回输入框，同时去掉这条副本。之后再发就是一条新请求。
   - **移除**：去掉这条副本。
3. 电脑回答 `unknown` 但没有 `missing`（老电脑，或电脑那边读不了送达记录）时，标签不变，加一行说明：「电脑查不到这条的记录，可能没收到。」再给「恢复草稿」「移除」两个按钮。
4. 「送达状态待确认」本身也加「移除」。点了先弹确认：「只从手机上去掉这条。如果电脑其实收到了，它仍会出现在对话里。」
5. 每次点「核对」都要有看得见的反馈：核对中显示进度；核对完显示一句结果，例如「已核对：电脑没收到」「已核对：已送达」，几秒后消失。核对失败照旧显示「核对失败，原提交仍保留；不会自动重发。」
6. PendingSheet 里的待确认、电脑没收到两种记录，也给出同样的按钮。
7. 「同样的字还在待确认时拒绝再发」这条规矩里，排除「电脑没收到」的记录。
8. 不自动重发。手机从不自己重发，只在用户点「重发」时发。

### 3.2 P2：气泡里画出消息自己带的图片

现在的代码：`TeleplyModel/SentPictures.swift` 的 `sentPictures(messages:records:)` 只看状态里的 `images` 记录。`Teleply/Chat/Timeline.swift` 第 141 行附近算出 `pictures`，第 400 行附近用 `SentPictureGrid` 画。图片下载走 `model.workspace.sentPicture(_:whole:)`。

要做的：
1. 用户消息自己带 `images`（数组，每项至少有 `id`、`name`，见第 8.2 节）时，把这些图加进这条消息的图片里。`id` 照现有规矩校验（不超过 64 个字符，只有字母、数字、`-`）。
2. 合并顺序：先放按发送记录配对到的图，再放消息自己带、按 `id` 还没出现过的图。同一个 `id` 只画一次。
3. 下载、缓存、点开看大图，都用现有的 `sentPicture` 这一套。不新开接口，所有助手都一样。
4. 「[图片]」标记和 DeepSeek 的「[N 张图片]」照现在的规矩从文字里去掉。消息没有字只有图时，气泡里只画图。

### 3.3 线一可以改的文件

`TeleplyState/ChatModel*.swift`、`TeleplyModel/ChatCore.swift`、`TeleplyModel/Outbox.swift`、`TeleplyModel/SentPictures.swift`、`TeleplyModel/Relay.swift`（只为 receipt 解析）、`Teleply/Composer/ComposerView.swift`、`Teleply/Chat/ChatSheets.swift`、`Teleply/Chat/Timeline.swift`（只改用户气泡里的图片部分）、演示和测试文件。

### 3.4 线一的测试

在 TeleplyCoreTests 里加测试：
- `missing` 的解析，三种回答对应的标签：有 `missing`、只有 unknown、其他状态；
- 重发用的是同一个请求编号和同样的内容；
- 恢复草稿以后，这条副本就没了；
- 消息自带图片和发送记录合并、去重；
- 没有 `images` 时，结果和现在一样。

演示世界里加一条「电脑没收到」的消息和一条带图的插话，放在调试开关后面，现有截图组不变。

## 4 线二 iPhone「文件」

### 4.1 P3：系统打不开 Word 时，给人话和别的办法

现在的代码：`Teleply/Files/DocumentPreview.swift` 用 `WKWebView.loadFileURL` 打开 Office 文件，`Coordinator` 只实现了 `decidePolicyFor`。`Teleply/Files/FilePages.swift` 的 `FilePage` 在 `kind == "download"` 时用它，⋯ 菜单里有「保存到文件」「分享」「用快速查看打开」「添加到消息」。

要做的：
1. 认出失败。需要同时处理两种情况：
   - 失败回调：`webView(_:didFail:withError:)` 和 `webView(_:didFailProvisionalNavigation:withError:)`；
   - 系统自己生成错误页：`didFinish` 以后，用 JS 读页面正文的前 400 个字。正文很短（少于 400 字），并且包含 `ErrorDomain`，或者能匹配 `(错误|error)\s*\d{2,}`（不分大小写），就算失败。
   这段判断写成一个纯函数，放进 TeleplyCore，方便测试。
2. 失败后，换成我们自己的页面：
   - 上面是第 4.2 节的大号文件类型图标和文件名；
   - 标题：「iPhone 自带的预览打不开这份文件」；
   - 说明：「文件本身没有问题。它太大或太复杂（比如几百页、几百张表），苹果系统自带的转换器处理不了。」
   - 按钮依次是：「看 PDF 版」（只在下一条成立时出现）、「用其他应用打开」（系统分享面板，可以选 Word、WPS）、「保存到文件」。
3. 「看 PDF 版」：这条文件来自某条回答，回答的 `files` 里有一个 `.pdf`，它的文件名去掉扩展名后和这份文件相同（不分大小写），就显示这个按钮，点了打开那个 PDF 的文件页。从电脑文件浏览打开的文件，暂时不找同名 PDF。要把回答里的其他文件带给文件页，尽量不改 `Timeline.swift`；实在要改，改动最小化，并在结果里写明。
4. 正在转换时，显示转圈和「正在打开…」，直到 `didFinish` 或失败为止。大文件可能要转十几秒。
5. Excel、PowerPoint 也走这一套。

### 4.2 P4：按文件类型画图标（和安卓共用第 4.3 节的表）

1. 新建一个 SwiftUI 视图 `FileTypeIcon(name: String, size: CGFloat)`，按扩展名选第 4.3 节表里的颜色和字。
2. 图形用代码画，不放图片素材，不用任何公司的商标图形：一页纸，右上角折起一角（颜色稍浅），纸面是表里的颜色，中间是白色粗体短字。深色模式用同样的颜色。
3. 用的地方：
   - 回答文件条（`Teleply/Chat/AnswerPictures.swift` 的 `AnswerFileStrip` / `FileStripCard`）：不是图片的文件，和没有缩略图的图片；
   - 文件页「不直接显示」那一屏（`FilePage.unshown`），代替现在的 `doc` 图标；
   - 第 4.1 节的失败页；
   - 输入框里附上的非图片文件（`Teleply/Composer/Attachments.swift`），只换图标；
   - 「对话文件」和「电脑文件」列表里，文件那一行的图标。文件夹照旧用文件夹图标。
4. SVG：文件条里 `thumb` 为真的 SVG 要显示缩略图（核对现在是否已经这样）；没有缩略图时用 SVG 图标。

### 4.3 文件类型图标表（iPhone 和安卓必须一致）

| 扩展名 | 字 | 颜色 |
|---|---|---|
| pdf | PDF | #E5483B |
| doc docx docm dotx rtf odt pages | W | #2F6FDE |
| xls xlsx xlsm xlsb ods numbers | X | #1E8E4F |
| csv tsv | CSV | #2E9E6B |
| ppt pptx pptm odp key | P | #E46A2C |
| zip rar 7z tar gz tgz bz2 xz | ZIP | #B7862C |
| txt log | TXT | #7A8594 |
| md markdown | MD | #5F6B7A |
| py r js ts tsx jsx kt kts swift java c h cpp hpp cs go rs rb php sh ps1 bat sql json yaml yml toml xml html htm css ipynb | </> | #7A55D6 |
| png jpg jpeg gif webp heic heif bmp tif tiff | IMG | #12A3A3 |
| svg | SVG | #0E8F8F |
| mp3 wav m4a aac flac ogg | ♪ | #D24C8E |
| mp4 mov m4v avi mkv webm | ▶ | #5B5BD6 |
| apk | APK | #3DA35D |
| exe msi | EXE | #4B5563 |
| 其他 | 扩展名大写，最多 4 个字符；没有扩展名就空着 | #8B95A1 |

字多于 3 个字符时字号自动缩小，保证放得下。

### 4.4 线二可以改的文件

`Teleply/Files/*`、`Teleply/Chat/AnswerPictures.swift`、`Teleply/Composer/Attachments.swift`（只改图标）、列表里画文件行的视图（只改图标）、新建的图标文件、`TeleplyCore` 里新加的纯函数、演示和测试文件。

### 4.5 线二的测试

TeleplyCoreTests 里加：
- 失败判断函数：系统错误页正文判为失败；正常的长正文、空页面判为没失败；
- 扩展名到图标的对应，表里每一行至少一个例子；
- 同名 PDF 的查找：大小写、多个点的文件名、没有同名 PDF。

演示世界里加一个打不开的 Office 文件，用来看失败页：可以放一个内容不是 Word 的 `.docx`，系统会报错。放在调试开关后面。

## 5 线三 安卓「发送」

和线一做同样的两件事，行为和文字都一致（第 3.1、3.2 节）。

现在的代码：
- `ChatController.kt`：`Unsettled`；第 301 行（失败记成待确认）；`check` / `reconcile`；第 224 行（同样的字拒绝再发）；
- `ChatCore.kt`：第 48 行附近的标签映射；
- `RelayApi.kt`：`receipt`；
- `SentPictures.kt`：`sentPictures` 只看状态记录；
- `ChatUi.kt`：`TimelineItem`、`SentPictureGrid`、`SentPictureTile`；
- 待确认那一栏和未接收那一栏在 `ChatUi.kt` / `ComposerUi.kt` 里，自己找到具体位置。

可以改的文件：上面这些（`ChatUi.kt`、`ComposerUi.kt` 只改发送状态栏和用户气泡的图片部分）、`Models.kt`（只加字段）、`FixtureApi.kt` 和新建的演示文件、测试文件。

测试：`testDebugUnitTest`，内容和第 3.4 节对应；`assembleDebug` 要能通过。**这一路不要开模拟器**，模拟器给线四用。

## 6 线四 安卓「文件」

### 6.1 P5：Word 第二次打开闪退

1. **先复现，再改。**在模拟器（AVD `AgentRemoteFresh`）上，用演示数据（`FixtureApi` / 演示世界）放一个大 Word。用脚本自己生成：几百张表，`word/document.xml` 解开后十几到二十几 MB，内容全部编造，不用真实文件，也不下载任何东西。连续打开、返回，重复几次。用 `adb logcat` 看是不是渲染进程被结束（`Render process … gone`、`OOM`），以及程序是怎么退出的。把复现过程和日志要点写进结果。
2. 修改：
   - 程序里**每一个**网页视图的 `WebViewClient` 都实现 `onRenderProcessGone`，返回 `true`；销毁这个网页视图；当前页面换成失败页。至少包括 `PreviewUi.kt` 里的两处、`CodeViewer.kt`，以及其他所有地方。
   - Word 失败页：上面是第 4.3 节的大号图标和文件名；标题「手机上显示不了这份文件」；说明「文件太大或太复杂，手机里画不出来。文件本身没有问题。」按钮是「看 PDF 版」（规则同第 4.1 节第 3 条）、「用其他应用打开」、「保存到文件」。docx-preview 自己报失败时（现在用标题 `teleply:failed` 通知 `officeFailed`），也用这个失败页。
   - 不再把整份文件当 `ByteArray` 放在界面状态里。`shouldInterceptRequest` 从手机上缓存的文件流式读出。
   - 大小门槛：打开前只读压缩包目录，不解压正文。`word/document.xml` 解开后超过 8 MB，或者文件本身超过 15 MB，就不在程序里画，直接显示失败页，说明改成「文件太大，手机里不直接显示。」Excel 照同样的思路：工作表 XML 合计超过 8 MB 就不画。
   - 离开页面时确实销毁网页视图（现在有，核对一遍）。
3. 验证：在模拟器上，大文件连续打开 5 次不闪退，每次都显示失败页；小的 Word、Excel 照常显示。

### 6.2 P4：文件类型图标

和第 4.2、4.3 节一样，用 Compose 新建 `FileTypeIcon(name: String, size: Dp)`。用的地方：
- `ChatUi.kt` 的 `AnswerFileStrip` 和文件块，第 822、840 行附近现在用 `TeleplyIcons.File` / `TeleplyIcons.Image`；
- 文件页「不直接显示」的那一屏；
- 第 6.1 节的失败页；
- `ComposerUi.kt` 第 813 行附近，附上的非图片文件；
- `WorkspaceUi.kt` 第 409 行附近，电脑文件列表里的文件行。

SVG 的规则同第 4.2 节第 4 条。

### 6.3 线四可以改的文件

`PreviewUi.kt`、`WorkspaceUi.kt`、`WorkspaceController.kt`、`CodeViewer.kt`、`PictureViewer.kt`、`MediaAndZipUi.kt`、`ChatUi.kt`（只改文件条和文件块）、`ComposerUi.kt`（只改附件图标）、新建的图标文件、`FixtureApi.kt` 和新建的演示文件、测试文件。

测试：`testDebugUnitTest`，覆盖图标表和大小门槛判断；`assembleDebug`；第 6.1 节的模拟器验证，附截图。

## 7 线五 电脑

### 7.1 P6：Claude 贴图核对

现在的代码在 `chats.py`：
- `_claude_image_count`：数「Remove image/attachment/file」按钮；
- `_paste_claude_image`：贴完最多等 6 秒，数不对就报「第 N 张图片核验未通过」，并写一行 `Claude attachment probe`；
- `_send_claude_now`：贴图前先确认框里没有附件。

要做的：
1. **按卡片数，不按按钮数。**把「Remove …」按钮按所属卡片归并：优先用最近的、包含这张卡片预览的祖先元素去重（比较 RuntimeId）；拿不到时，用按钮的屏幕位置归并（同一张卡片的按钮横向距离很近）。一张卡片有两个「Remove」按钮时，只算 1 张。
2. **等得更久，并等数稳定。**贴完最多等 20 秒；数到期望的张数后，再保持 0.6 秒不变才算成功。等的过程中不重复按粘贴。
3. **多出来就停。**贴第 N 张后，数到的卡片比 N 多，就停下，不发送。报给手机：「电脑上 Claude 输入框里出现了 X 张图，比要发的多，尚未发送。」
4. **失败后把自己放进去的东西收回。**开始时框里没有别人的字、也没有附件（现在已经检查），所以失败时框里的东西都是这次放进去的。失败后：
   - 按卡片上的「Remove」按钮去掉这次贴进的图，再把字清空（`SetValue('')`）；
   - 等 3 秒再数一次，处理晚到的卡片；
   - 然后照常报未接收。
   日志只写数字：收回了几张、晚到了几张。这样手机上的「恢复草稿」→ 再发，能从干净的输入框开始。
5. **诊断更细。**失败时，`Claude attachment probe` 那一行加上每个「Remove」按钮的类别（image / attachment / file / other，不写文件名）、它父元素的控件类型、取整后的屏幕位置。下次再出问题，能看出是哪种情况。
6. **送达记录改对。**这条路以「没提交」失败时（`InputNotSubmitted` / `SendNotSubmitted`），把送达记录改成 `rejected`，结果里写原因。11-26 23:27:50 和 23:28:14 两条一直停在 `dispatching`。之后同一个请求编号再来，电脑应该回答 rejected，不能回答「已提交过，结果尚未确认」。
7. 不对真实运行的 Claude 桌面做任何界面测试；测试全部用假的界面树。真机核对由审核的人在用户同意后做。

### 7.2 P1 的电脑部分：回执说清楚「没收到」

所有回执实现都要加，包括：
- `codex_apptools.receipt`；
- `codex_control.receipt`；
- 其他助手（Claude、DeepSeek、Antigravity）走的回执，用 `grep -n "def receipt\|http_receipt"` 找全。

规则：送达记录文件存在、能读，并且里面**没有这个请求编号**（任何对话都没有）时，回答 `{"state": "unknown", "missing": true}`。记录文件不存在或读不了时，照旧只回答 `{"state": "unknown"}`。其他情况不变。内部用 `receipt(...)["state"] != "unknown"` 判断的地方，行为不能变。

### 7.3 线五可以改的文件

`chats.py`（只改 Claude 贴图和发送失败的部分）、`codex_apptools.py`、`codex_control.py`（只改回执和送达记录）、`agents/*.py` 里的回执、`tests/` 下相关测试。不改版本号，不改更新说明。

测试：
- 假界面树：一张卡片两个按钮算 1 张；卡片 8 秒后才出现也能成功；期望 1 张来了 2 张就停下并收回；失败后送达记录是 `rejected`；
- 回执：有记录、没记录、记录文件不存在三种情况；
- 跑相关测试文件全部通过；全量 `pytest` 跑一遍，写下通过数和失败数。已知有 3 个和这次无关的老失败。

## 8 手机和电脑之间新增的约定

### 8.1 回执的 `missing`

`GET …/receipt`（各助手原有的回执接口）在电脑确认「送达记录里没有这个请求编号」时，多给一个字段 `missing: true`，`state` 仍是 `unknown`。老手机不认这个字段，行为不变；新手机看到它，就显示「电脑没收到」。

### 8.2 消息自带的 `images`

已经存在，这次不改电脑。用户消息上的 `images` 是数组，每项形如 `{"id": "<32 位十六进制>", "name": "x.png", "url": "/api/codex/image?id=…", "thumbnail": "/api/codex/image?thumb=1&id=…"}`。另有一种只有 `id`、`name`、`path` 的项：图片不在电脑的上传目录里，`id` 是路径的摘要。这种项取不到图，手机跳过它，不报错。只有 `url` 以 `/api/codex/image` 开头的项才画。

## 9 共同规矩

- 工作区和仓库分开。笔记、草稿、试验脚本、生成的测试文件放进自己的工作区子文件夹；仓库工作树只放要提交的改动。提交前 `git status` 只能剩这些文件，用 `git add <文件>` 一个一个加，绝不用 `git add -A` 或 `git add .`。
- 别的会话也在这台电脑的同一个仓库里干活。不是你做的文件不要碰，不切换分支，不动别的工作树，不用 `git stash`。
- 提交说明用中文，最后一行写 `Co-Authored-By: DeepSeek Flash <noreply@deepseek.com>`。
- 不推送、不合并、不打包、不安装、不发布、不改版本号。
- 这些事必须停下来等用户：推送、Codemagic、TestFlight、苹果后台、中转服务器、任何密钥。不打印任何密钥或令牌。不打开 `%USERPROFILE%\.codemagic\token.txt` 和 `%LOCALAPPDATA%\AgentRemote\Data\remote_config.json`。
- 不读真实的对话记录，不调用正在运行的遥应电脑端，不操作正在运行的 Claude、Codex 桌面程序。测试只用编造的数据。不结束任何不是你自己启动的进程。
- 不下载、不安装任何软件或依赖。
- PowerShell 里不用自动变量当变量名（`$home`、`$HOME`、`$pwd`、`$args`、`$input`、`$host`、`$profile`）。不在自己建的文件夹以外递归删除。删除前先打印绝对路径。
- 仓库是公开的。代码、测试、文档里不写用户的对话标题、消息内容、文件名、电脑名、账号。
- 汇报用中文，简短：先说结论，再说做了什么、怎么核对的、没做什么、最担心的地方，一句一件事。

## 10 结果（各路只改自己那一小节）

### 10.1 线一 iPhone「发送」

**结论**：P1、P2 的 iPhone 部分按第 3.1、3.2 节做完，未编译、未跑测试（这台电脑没有 Swift），等 Codemagic 编译和跑测试。

**P1 做了什么**

- 回执的 `missing`（第 8.1 节）读出来了：`state == "unknown"` 且 `missing == true` 时标签是新的「电脑没收到」；只有 `unknown`（老电脑、或读不了送达记录）时标签不变，并给这条副本记一个 `_receipt_unknown` 备注。
- `unknown` 且没有 `missing` 时标签不变这条，也修掉了老代码把「已接收」拉回「待确认」的副作用：没有证据时保留原来的标签。
- 「电脑没收到」那条下面一行「电脑没收到这条消息，可以重发。」，按钮依次是「重发」「恢复草稿」「移除」（草稿不为空时不显示「恢复草稿」）。
- 重发：用原请求编号和原请求体（去掉手机自己记的备注）再发一次；标签先回「提交中」，之后照正常回执走。电脑答「这次请求已提交过，结果尚未确认…」时原样显示那句话并回到「待确认」。不会自动重发。
- 待确认（`unknown` 且无 `missing`）时，加一行「电脑查不到这条的记录，可能没收到。」和「恢复草稿」「移除」；「送达状态待确认」本身也有「移除」，点了先弹确认「只从手机上去掉这条。如果电脑其实收到了，它仍会出现在对话里。」
- 待确认/电脑没收到这两种副本的「恢复草稿」都会把字和附件放回输入框并把副本从列表上拿掉，之后发的是新请求（否则同字重发现在会被「同样的字还在待确认」拦住）。
- 每次点「核对」都有反馈：核对中显示进度和「正在核对…」，核完显示「已核对：电脑没收到 / 已送达 / …」几秒；失败仍显示「核对失败，原提交仍保留；不会自动重发。」
- 待核对发送记录（PendingSheet）里加进「电脑没收到」和按钮；待确认的「恢复提交快照」对这两种副本改成「恢复草稿」（会移除副本）。
- 「同样的字还在待确认时拒绝再发」这条规则仍只拦「提交中 / 待确认」，不拦「电脑没收到」。

**P2 做了什么**

- 用户消息自己的 `images` 也画出来：先放按发送状态记录配到的图，再放消息自带、按 id 还没出现过的图，同一个 id 只画一次；`id` 沿用原来的校验，`url` 不以 `/api/codex/image` 开头的（只有 path 的项）跳过。
- 下载、缓存、点开大图仍走原来的 `workspace.sentPicture`，没开新接口。
- 画图时文字里的 `[图片]` 前缀和 DeepSeek 的 `[N 张图片]` 后缀都去掉；只有图没有字时气泡里只画图。

**11-27 审后补三处（和安卓用同样的字）**

- Claude 的发送也能到「电脑没收到」：核对时先问一次回执（Claude 走 `/api/agents/claude/receipt`，老电脑没有这个地址就退回 Claude 记录），`unknown` 且 `missing` 标成「电脑没收到」，其他情况照原来的 `claudeCheck` 走；问回执出错不报核对失败。`resend` 不再排除 Claude，重发的回答照 `applyReply` 的 `pressed` 分支走。
- 核对那一行改成按回执原始的 `state`/`missing` 说：`unknown`+`missing` →「已核对：电脑没收到」；只有 `unknown` →「已核对：电脑查不到这条的记录」；`dispatching` →「已核对：电脑收到了，还在处理」；Claude 记录里既没送达也没排队 →「已核对：Claude 的记录里还没看到这条」；其他 →「已核对：<标签>」。这两段是 TeleplyCore 的纯函数 `checkResultText`/`claudeCheckResultText`。
- 恢复草稿在输入框有字时不再消失：按钮一直在，只是不能点，下面一行灰字「输入框里有字，先清空才能恢复」。待核对发送记录里也是这样。
- 测试加了：`checkResultText`/`claudeCheckResultText` 每一种；Claude 回执 `missing`、核对到「电脑没收到」、再用同一编号重发并走 `pressed`；`receiptLabel` 只对 send 认 `missing`（和安卓一致）。

**改了哪些文件**

- `TeleplyCore/Sources/TeleplyModel/ChatCore.swift`：`missingLabel`、`unknownReceiptLabel`，`receiptLabel`/`agentReceiptLabel` 加 `missing`（默认 false，旧调用不变），`checkResultText`/`claudeCheckResultText`。
- `TeleplyCore/Sources/TeleplyModel/Relay.swift`：Claude 的回执改问 `/api/agents/claude/receipt`（老电脑 404 时由调用方退回 Claude 记录）。
- `TeleplyCore/Sources/TeleplyModel/SentPictures.swift`：消息自带 `images` 的解析与合并、`wordsWithoutPictureMarks`。
- `TeleplyCore/Sources/TeleplyModel/Models.swift`：**不在第 3.3 节列表里，只加了一个字段名**：`messageDetails` 里加 `"images"`（`parseMessage` 是唯一能看到消息原始 JSON 的地方；不加就拿不到消息自带的图）。
- `TeleplyCore/Sources/TeleplyState/ChatModel.swift`：`checking`/`checkNotes`、核对反馈、`missing` 与「标签不变」的判断、`resend`、`restoreAndRemove`、`mayBeMissing`，把回执处理抽成 `applyReply`（首次发送和重发共用）；`save` 不让已移除的副本被晚到的回执复活。
- `TeleplyCore/Sources/TeleplyState/ChatModel+SendDemo.swift`（新建）：`-TeleplyDemoSend` 时在演示里放一条「电脑没收到」的副本。
- `TeleplyCore/Sources/TeleplyDemo/DemoSend.swift`（新建）：演示行「发送恢复示例」、一条带两张图自己的插话。
- `TeleplyCore/Sources/TeleplyDemo/DemoWorld.swift`：**三处各一行**把它接上（列表多加一行、`control` 不给这个演示对话塞固定问题卡、`messages` 用演示消息）。
- `Teleply/Composer/ComposerView.swift`：`RecoveryBar`（待确认/电脑没收到），待确认的移除确认。
- `Teleply/Chat/ChatSheets.swift`：PendingSheet 的两种副本、按钮、核对反馈和移除确认。
- `Teleply/Chat/Timeline.swift`：只改用户气泡里取文字的那一行，用 `wordsWithoutPictureMarks`。
- 测试：`TeleplyCoreTests/SendRecoveryTests.swift`（新建，7 项）、`TeleplyCoreTests/SentPicturesTests.swift`（加 2 项）。

**测试**

- `SendRecoveryTests`：三种回执标签（有 `missing`、只有 `unknown`、其他状态）；核对那一行的每一种说法；Claude 的回执 `missing` →「电脑没收到」，再用同一编号重发、走 `pressed` 分支；重发用同一请求编号、同一文字和同一 `expected_turn`，且只有一条副本；老电脑只答 `unknown` 时标签不变并记下「可能没收到」；恢复草稿后副本变成已移除、字回到输入框；电脑答「已提交过」时回到待确认并显示原话。
- `SentPicturesTests`：消息自带图和记录配对图的合并、按 id 去重、path-only / 非 `/api/codex/image` / 超长或带斜杠的 id 跳过、没有 `images` 时结果与以前一样、只有图时文字为空。
- 现有测试的调用方式没变（`receiptLabel`/`agentReceiptLabel` 的旧 3 参数调用仍可用）。

**演示**：启动参数 `-TeleplyDemoSend`（只在 DEBUG 有效，默认关）。打开「发送恢复示例」能看到一条「电脑没收到」和一条带两张图的用户消息；关掉开关时列表、消息和截图组都与原来一样。

**没做 / 没验**

- 这台电脑没有 Swift，**没编译、没跑测试、没跑截图巡览**；只按类型和可选值逐处静态核对过，并查了新加的唯一一处原始字符串（没有 `"#`）。
- 没碰别的路线的文件；没改版本号、README 更新说明。
- `ConversationView.swift` 里 ⋯ 菜单的「待核对发送记录」计数仍只算「提交中 / 待确认」（原有行为），所以一条对话只剩「电脑没收到」时该菜单入口不出现；输入区上方那条有全部按钮。这个文件不在第 3.3 节列表里，没动。
- 新标签「电脑没收到」没有英文翻译：`Hints.swift` 不在可改列表里，英文界面会显示中文；标签比较都用同一个常量，行为不受影响。新加的界面文字（「重发」「正在核对…」「已核对：…」「电脑查不到这条的记录，可能没收到。」等）也没进 `Localizable.xcstrings`（不在可改列表里），英文界面会显示中文。

**最担心编不过的几处**

1. `ChatModel` 的新代码（`CheckOutcome`、`check`/`noteCheck` 里的 `Task`、`resend` 里捕获 `backgroundTime` 返回的闭包和 `body`/`attempt`）在 Swift 6 的 MainActor 默认隔离下能否直接编译。
2. `SentPictures.swift` 里 `compactMap(SentPicture.init(own:))` 这个带标签的初始化器引用写法。
3. SwiftUI：`.alert(_:isPresented:presenting:)` 配 `@State Submission?`，以及 `ViewThatFits` 里包一个 `@ViewBuilder` 方法。
4. 演示的两个新文件：`ChatModel+SendDemo.swift` 跨文件访问 `@ObservationIgnored var demo`；`SendDemo` 的静态属性引用 `DemoData.row`/`DemoData.message`。
5. `ChatModel.save` 把列表更新挪到写盘之前（为了让已移除不被晚到的回执复活），有没有哪个旧测试依赖原来的先后顺序。
6. Claude 的回执地址：iOS 改成问 `/api/agents/claude/receipt`，和电脑端 `agents/claude.py` 的 `http_receipt` 是不是同一条路（安卓也是先走 `/api/agents/<app>/receipt`，老电脑 404 后退回 Claude 记录）。

### 10.2 线二 iPhone「文件」

**做了什么**

- P3（第 4.1 节）：文件页换了一条路——网页视图把状态（正在转换 / 已显示 / 失败）报给页面；失败两种都认：`didFail` 和 `didFailProvisionalNavigation`（`NSURLErrorCancelled` 除外，那是页面关掉），以及 `didFinish` 后用 `evaluateJavaScript` 读正文交给纯函数 `systemPreviewFailed`。转换期间整页是转圈和「正在打开…」，`didFinish` 或失败后撤掉。
- 失败判断（11-27 收紧过一次）：正文少于 400 字，并且满足两条之一才算失败——含 `ErrorDomain`（系统错误页一定带错误域名，中文「（XxxErrorDomain 错误 N。）」、英文「(XxxErrorDomain error N.)」），或者有某一整行去掉首尾空白后正好是 `(null)`（系统把空的原因写成这一行）。不再按「错误 / error 加数字」判断：短文档里出现「Error 404 处理说明」「共发现错误 12 处」这类句子不该算失败。
- 失败页：大号文件类型图标和文件名，标题「iPhone 自带的预览打不开这份文件」，说明「文件本身没有问题。它太大或太复杂（比如几百页、几百张表），苹果系统自带的转换器处理不了。」，按钮「看 PDF 版」（有同名 PDF 时）、「用其他应用打开」（系统分享面板）、「保存到文件」。Word、Excel、PowerPoint 同一条路。
- 同名 PDF：判断是纯函数 `sameNamePDF`（去扩展名比、不分大小写、只管最后一个点、没有 id 的 PDF 不算）。文件页从当前对话的消息里找这份文件所属的回答，再用那个回答的 `files`；从「电脑文件」浏览打开的文件（页面数据里有 `reference`）不找。**没有改 `Timeline.swift`、`ConversationView.swift`、`RootView.swift`**。「看 PDF 版」就地换文件页（同一个导航层），返回回到对话，不回到失败页。
- P4（第 4.2、4.3 节）：新视图 `FileTypeIcon(name:size:)`，SwiftUI 画纸页、右上角折角（稍浅）、纸面用表里的颜色、白色粗体短字；不用图片素材、不画公司商标；深浅色同色；字多于 3 个字符缩小一档，另有 `minimumScaleFactor` 兜底。表放在 TeleplyCore（`FileTypeMark` + `fileTypeMark(for:)`），颜色用 RGB 的 0–255 数值，没有 `#E5483B` 这类原始字符串。16 行照抄；其他类型取扩展名大写前 4 个字符，没有扩展名就空着。
- 用图标的地方：回答文件条（`FileStripCard`，非图片和没缩略图的图片）、文件页「不直接显示」、失败页、输入框附件（`AttachmentTiles`，只换图标）、「对话文件」列表、「电脑文件」列表（文件夹仍用文件夹图标）。SVG 核对过：`thumb` 为真时现在就会显示缩略图，没缩略图时是 SVG 图标；这两处没动。

**改了哪些文件**

- 新建：`apps/ios/Teleply/Files/FileTypeIcon.swift`、`apps/ios/TeleplyCore/Sources/TeleplyModel/FilePreviewRules.swift`、`apps/ios/TeleplyCore/Tests/TeleplyCoreTests/FilePreviewRulesTests.swift`。
- 修改：`apps/ios/Teleply/Files/DocumentPreview.swift`、`apps/ios/Teleply/Files/FilePages.swift`、`apps/ios/Teleply/Chat/AnswerPictures.swift`、`apps/ios/Teleply/Composer/Attachments.swift`、`apps/ios/TeleplyCore/Sources/TeleplyDemo/DemoWorld.swift`、`apps/ios/TeleplyCore/Sources/TeleplyDemo/DemoTransport.swift`、`apps/ios/TeleplyCore/Tests/TeleplyCoreTests/AnswerFilesTests.swift`（只把演示文件条的期望列表加两个 id）。
- 没动版本号、README、本地化文件，也没动线一的 `Timeline.swift`、`ComposerView.swift`、`ChatModel.swift`。

**加了哪些测试**（`FilePreviewRulesTests`，6 项，TeleplyCoreTests）

- 失败判断：用户截图那句「未能完成操作。（OfficeImportErrorDomain 错误 912。）\n(null)」、只有 `ErrorDomain`、只有一行 `(null)`、`(null)` 前后带空白 → 失败；空页面、400 字以上的长正文（即使含 `ErrorDomain`）、普通短句、「错误 12」「ERROR 1024」「Error 404 处理说明」「共发现错误 12 处」、（`null`）只出现在句子里（「正文里提到 (null) 这个词」「文件已损坏。(null)」）→ 没失败。
- 同名 PDF：大小写、文件名里多个点、「带.点的.报告.docx」对「带.点的.报告.PDF」、没有同名 PDF、PDF 没有 id、扩展名不是 pdf、问的名字没有点（按整名比）。
- 图标表：16 行每行一个例子（字和 RGB 三个数）；同行其他扩展名（doc/pages/ods/tsv/key/tar.gz/log/markdown/kts/tiff/m4a/mov/msi）、大小写、未知扩展名大写取 4 个字符、没有扩展名（`Makefile`、`.gitignore`、`a.`）。
- 演示：那份打不开的 docx 能找到同名 PDF；「文件预览示例」只在 `-TeleplyDemoFiles` 下列出。
- `AnswerFilesTests` 里演示文件条的期望列表补上 `fp-heavy-docx`、`fp-heavy-pdf`。

**演示**

`-TeleplyDemoFiles` 的「文件预览示例」多了两个文件：`季度报告.docx`（内容不是 Word，系统转换会失败）和同一份的 `季度报告.pdf`；回答正文里两个都有链接，失败页上能看到「看 PDF 版」。默认截图组不用这个开关，现有截图不受影响。

**怎么核对的**

- 这台电脑没有 Swift，**没编译、没跑测试、没跑模拟器**。全部靠读代码加两个自查：
- 新加的代码里没有原始字符串（失败判断的正则已去掉），颜色一律 RGB 数值。
- 用一个粗写的 Swift 括号/字符串配平脚本（放在工作区子文件夹，不进仓库）把改过的 10 个文件过了一遍，0 处括号或字符串不闭合。

**最担心编不过的地方**（按担心程度）

1. `DocumentPreview` 新加的 `didFinish` / `didFail` / `didFailProvisionalNavigation` 三个可选 delegate 方法签名。`ci-testflight.sh` 见到「nearly matches optional requirement」就让构建失败；签名按 Apple 文档的 `WKNavigation!` 加 `any Error` 写，但本机没有 SDK 能核对。
2. `evaluateJavaScript` 的 completion handler 在新 SDK 里的隔离标注。为了两种都能编过，回调里只写 `let body = value as? String ?? ""` 和 `Task { @MainActor in self.finished(body) }`；若 SDK 的标注是别的形式，仍可能报隔离错误。
3. `FileTypeIcon` 里的 `Color(.sRGB, red:green:blue:opacity:)`、`Path.addQuadCurve`、`Text` 的字号 `markSize(width)`（CGFloat）——老 API，但只能靠读。
4. `PickerSheet.rows(_:label:pick:)` 的 label 从三元组改成四元组，两处调用都改了；本机 grep 只有这两处，若还有遗漏会编不过。
5. 演示里那份假 `.docx` 是不是真让系统转换器失败，以及系统错误页在 iOS 26 上能不能在 `didFinish` 后用 `innerText` 读到、是不是真的少于 400 字——只能等 Codemagic 模拟器或真机。
6. `FilePage.pdfVersion` 靠 `model.messages` 找同名 PDF：文件页打开时当前对话的消息还没读进来时按钮不出现（不报错，只是少一个按钮）。

**没做什么**

没推送、没合并、没打包、没改版本号；没跑 Codemagic、没上真机；没读真实对话记录；没动别的工作树和别的路的文件。

### 10.3 线三 安卓「发送」

（待填）

### 10.4 线四 安卓「文件」

（待填）

### 10.5 线五 电脑

（待填）

### 10.6 线六 iPad「收起对话列表」

**结论**：第 11.1 节第 1–7 条和 11.3 节都做了；这台电脑没有 Swift，**没编译、没跑测试、没跑截图**，等 Codemagic 编译和跑测试。

**做了什么**

- 开关（第 1 条）：`RootView` 加 `@AppStorage("TeleplyListCollapsed")`，默认展开；它是唯一的读写处，用 `$listCollapsed` 传给 `WorkspaceView` 和 `ConversationView`。重开 App 保持上次的样子。
- 什么时候能收（第 2 条）：新纯函数 `listColumnLayout(wide:setting:screen:)`（`TeleplyState/ListColumn.swift`）算三件事：`listShown`、`buttonShown`、`collapsed`。只有宽窗口且 `.reading` 才有按钮、才收起；`.chats` 时列表总在、按钮不出现（设置不生效），所以不会只剩一页空白；窄窗口和 iPhone 没有按钮。
- 收起的样子（第 3 条）：宽窗口的两栏从 `HStack` 改成 `ZStack(alignment: .leading)`：右边对话栈 `.padding(.leading, listShown ? columnWidth + 1 : 0)`，左边列表和 1pt 分隔线作为一个 `HStack` 整体按 `-(columnWidth + 1)` 往左移，配 `.opacity`、`.allowsHitTesting`、`.accessibilityHidden`。列表视图一直在视图树里、宽度不变（不销毁重建），滚动位置和搜索框里的字保留；`setSideBySide` 和 10 秒刷新没动，收起时照旧刷新，展开时是新的。`.animation(foldAnimation, value: column.listShown)` 是 `.easeInOut(duration: 0.25)`，减弱动态效果时 `foldAnimation` 为 `nil`（直接切换，不滑）。
- 按钮（第 4 条）：`ConversationView` 的 `.toolbar` 加 `ToolbarItem(placement: .topBarLeading)`；`Label("显示/隐藏对话列表", systemImage: "sidebar.left").labelStyle(.iconOnly)`，无障碍标签随状态「收起对话列表」/「展开对话列表」。只有传进来的 `wide` 为真时出现，收起和展开时都不挪地方。
- 键盘（第 5 条）：同一个按钮加 `.keyboardShortcut("s", modifiers: [.command, .control])`；Label 的标题是「显示/隐藏对话列表」，按住 ⌘ 的列表用它，无障碍标签另给动态的「收起对话列表」/「展开对话列表」。
- 第 6 条（窗口按钮）：见下一段。
- 第 7 条：`listShown` 只看 `screen` 和设置：关对话回到 `.chats` 时列表一定回来；再开一个对话按存着的开关收起或展开。列表的 10 秒刷新走 `AppModel.listShown`（`sideBySide && reading`），没改，所以收起时照旧。

**第 11.1 节第 6 条（窗口按钮）是怎么处理的**

没有加额外距离，原因是新按钮在**系统导航栏**里：`ToolbarItem(placement: .topBarLeading)`，不是应用自己画的标题栏。`WindowControls.swift` 已经写明 iPadOS 26 的窗口按钮由系统导航栏自己让开，只有应用自己画的栏（列表顶栏、侧栏）才要用 `WindowControls.inset` 的 72 点；再给导航栏里的按钮加同样的 72 点，会和系统的让位叠在一起。**窗口模式没验过**（模拟器和真机都没跑）；如果真被三个圆点挡住，处理是在这个按钮的内容上补 `WindowControls.inset` 的 leading padding（`WindowControls` 在应用 target 里，`ConversationView` 直接可用）。

**改了哪些文件**

- 新建 `apps/ios/TeleplyCore/Sources/TeleplyState/ListColumn.swift`：`ListColumnLayout`、`listColumnLayout(wide:setting:screen:)`。
- 新建 `apps/ios/TeleplyCore/Tests/TeleplyCoreTests/ListColumnTests.swift`：4 项。
- `apps/ios/Teleply/App/RootView.swift`：`@AppStorage`、`WorkspaceView` 的 `@Binding`、两栏改 `ZStack` 和移动/动画、`ConversationView` 的新参数。
- `apps/ios/Teleply/Chat/ConversationView.swift`：`wide` 和 `@Binding`、顶栏按钮和快捷键、`column`。
- `apps/ios/TeleplyUITests/ScreenshotTour.swift`：只在 `ScreenshotTour` 类里加 `testIPadListCollapse`（`ci-check.sh` 的 `-Only` 写死 `-only-testing:TeleplyUITests/ScreenshotTour/<名字>`，放别的类跑不到）；`testIPadTour` 没动。
- 没动 `ChatListView.swift`（不需要）、版本号、README、`Localizable.xcstrings`。

**加了哪些测试**

- `ListColumnTests`（TeleplyCoreTests，4 项）：20 种组合（够宽/不够宽 × 开关 × `launch`/`login`/`devices`/`chats`/`reading`）逐条对 `listShown`/`buttonShown`/`collapsed`；宽窗口没有对话时列表总在且没有按钮；存着的收起在列表页不生效、再开对话又收起、展开后还在；窄窗口和 iPhone 一律不收起。
- `testIPadListCollapse`（iPad 才跑，iPhone 跳过）：演示数据 → 进示例 → 连 测试电脑 A → 开「原生阅读示例」→ 如果上一次留下收起就先点「展开对话列表」→ 截图 `55-ipad-list-open` → 点「收起对话列表」→ 断言按钮变成「展开对话列表」、列表的「打开导航」不可点 → 截图 `56-ipad-list-folded` → 点「展开对话列表」→ 断言列表回来 → 截图 `57-ipad-list-open-again`。开头不依赖上一个测试留下的状态（看按钮自己的文字反过来展开），结尾是展开的。
  - 没有用 `-TeleplyListCollapsed NO` 清状态：启动参数落在 `NSArgumentDomain`，读 `UserDefaults` 时优先级高于 `@AppStorage` 自己写进去的值，按钮会看起来怎么点都不变。用按钮反过来展开更稳。
  - `ci-check.sh` 默认那张 iPad 四个用例的列表没动（不在第 11.2 节的可改文件里），所以它要按第 11.3 节的 `-Only "testIPadListCollapse"` 单独跑。

**怎么核对的**

- 没有 Swift，**没编译、没跑测试、没跑模拟器/真机、没跑 Codemagic**。
- 5 个改动/新文件过了括号和字符串配平的脚本（放在工作区子文件夹，不进仓库）：0 处不闭合；新代码里没有原始字符串（没有一处 `#"`）。
- `ConversationView` 只有 `RootView` 一个调用处，`WorkspaceView` 只有 `RootView.content` 一个调用处，都跟着改了。
- 纯函数的三条规则在单元测试里重新算一遍（不照抄实现），20 种组合都在。

**没做 / 没验**

- 没验证台前调度窗口模式下系统导航栏会不会自己让开三个圆点；只按 `WindowControls.swift` 里 0.8.0 的结论（系统导航栏自己让开）。
- 没验证按住 ⌘ 的快捷键列表显示的是 Label 标题「显示/隐藏对话列表」还是动态的无障碍标签；代码里两者分开写，只能等真机按 ⌘ 看。
- 新文字（「收起对话列表」「展开对话列表」「显示/隐藏对话列表」）没进 `Localizable.xcstrings`（不在可改列表），英文界面会显示中文。
- 没推送、没合并、没改版本号、没动别的工作树和别的路的文件。

**最担心编不过的几处**

1. `ConversationView` 新加 `@Binding` 后，成员初始化器从 `ConversationView(model:)` 变成 `ConversationView(model:wide:listCollapsed:)`，调用处在另一个文件；`@State` 都是私有的——现有 `RootView(model:)` 也是同一种写法，应该没问题，但这是最容易漏的。
2. `ZStack` + `NavigationStack` 的 `.padding(.leading)`：编译应该没问题，但系统导航栏、`safeAreaBar` 和列表的 72 点让位在运行时是否和原来的 `HStack` 一样，只能看截图。
3. `Animation?` 的 `foldAnimation` 配 `.animation(_:value:)`；`.keyboardShortcut("s", modifiers: [.command, .control])` 的 `EventModifiers` 数组字面量。
4. `Label(...).labelStyle(.iconOnly)` 放进 `ToolbarItem(placement: .topBarLeading)`，和现有 `.toolbarRole(.editor)` + `.principal` 标题的排布：按钮应该在最左、标题往右让一点，没有 SDK 能核对。
5. `ListColumnLayout: Sendable` 在 `TeleplyState`（默认 `MainActor` 隔离）里，测试用 `@MainActor`；现有 `NewTarget`/`NewHandoff` 也是这个写法。


## 11 线六 iPad「收起对话列表」（11-27 加）

分支 `ios-sidebar`，工作树 `D:\Personalgent_remote_lanes\ios-sidebar`，起点 `ios-092`（de53eec，线一、线二已合并）。

### 11.1 要做的

1. **开关的状态**：新增一个持久的开关「对话列表收起」，用 `@AppStorage`（键名 `TeleplyListCollapsed`），默认展开。重开 App 后保持上次的样子。
2. **哪种时候能收**：只在 iPad 宽窗口（`WorkspaceView` 走 `columns` 的时候）并且正打开着一个对话（`model.screen == .reading`）时才能收起。没打开对话时（`.chats`），列表总是显示，开关按钮也不出现，所以永远不会只剩一个空白页。窄窗口（`single`）和 iPhone 完全不变，不出现按钮。
3. **收起的样子**：左边列表和那条 1pt 分隔线一起滑出去（从左边缘移走，`.easeInOut` 约 0.25 秒；系统开了「减弱动态效果」时不滑，直接切换），对话占满整个窗口。对话正文已有最大宽度 820pt 并居中，不用改。列表视图不要销毁重建（滚动位置、搜索框里的字要保留），用宽度和透明度把它藏起来，或者用别的能保留状态的办法。
4. **按钮**：只有一个按钮，位置固定在对话顶栏最左边（`ConversationView` 的 `.toolbar` 加 `ToolbarItem(placement: .topBarLeading)`，只在宽窗口出现）。图标用系统符号 `sidebar.left`，按钮在展开时叫「收起对话列表」，收起时叫「展开对话列表」（无障碍标签同名）。这和 iPad 自带 App 的边栏按钮是同一个位置，收起和展开时按钮不挪地方。
5. **键盘**：外接键盘按 ⌃⌘S 也能切换（`.keyboardShortcut("s", modifiers: [.command, .control])`），按住 ⌘ 时出现在快捷键列表里，名字「显示/隐藏对话列表」。
6. **台前调度的窗口按钮**：iPadOS 26 小窗口时左上角有窗口按钮（`WindowControls.inset`）。现在由列表那一栏让开；收起后最左边是对话顶栏，要确认顶栏的新按钮没被窗口按钮挡住（系统导航栏一般会自己让开，如果没有，就加上这段距离）。
7. **别的**：收起时左边列表每 10 秒的刷新照旧（`setSideBySide` 不改），展开时内容是新的。关闭对话回到列表时，列表自动出现（因为第 2 条）；再打开一个对话，按开关原来的状态收起或展开。

### 11.2 可以改的文件

`Teleply/App/RootView.swift`、`Teleply/Chat/ConversationView.swift`（只加顶栏按钮）、`Teleply/List/ChatListView.swift`（只在必要时）、新建的文件、`TeleplyUITests` 下新加的测试。不改版本号、README。

### 11.3 测试和验证

- 把「什么时候显示列表、什么时候显示按钮」写成 TeleplyCore 里的纯函数（输入：宽不宽、开关、`screen`），单元测试覆盖每种组合。
- 在 `TeleplyUITests` 加一个新的界面测试 `testIPadListCollapse`（不要改现有的 `testIPadTour`，它从 0.8.0 起就失败，和这次无关）：演示数据打开一个对话 → 截图 → 点「收起对话列表」→ 截图（列表不见、对话占满）→ 点「展开对话列表」→ 截图。只在 iPad 上跑，iPhone 上跳过。审核的人会用 Codemagic 的 `-Mode shots -Device "iPad mini" -Only "testIPadListCollapse"` 跑它看截图。
