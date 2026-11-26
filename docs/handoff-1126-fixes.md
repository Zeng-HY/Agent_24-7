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

（待填）

### 10.2 线二 iPhone「文件」

（待填）

### 10.3 线三 安卓「发送」

已完成 P1、P2 的安卓部分，行为和文字按第 3.1、3.2 节。

**P1 待确认能核对出结果、能重发、能移除**
- 回执 `missing`：`receiptLabel` 增加 `missing`；`state` 是 `unknown` 且 `missing` 时标成「电脑没收到」。只有 `unknown` 的仍是「送达状态待确认」，并把「电脑查不到这条的记录，可能没收到。」记在本地副本的一个下划线字段里，不发给电脑。
- 输入框上方：电脑没收到那条显示「电脑没收到这条消息，可以重发。」，按钮依次是「重发」「恢复草稿」「移除」；待确认显示「核对待发送消息」「移除」，老电脑（`unknown` 但没有 `missing`）多一行说明和「恢复草稿」。在待确认上点「移除」先弹确认：「只从手机上去掉这条。如果电脑其实收到了，它仍会出现在对话里。」
- 重发用原来的 `request_id` 和原来的请求内容（去掉只给手机看的那些下划线字段），草稿不动；标签先回「提交中」，电脑回答「这次请求已提交过，结果尚未确认」时把这句话原样显示，标签回到「送达状态待确认」。
- 恢复草稿把字放回输入框，同时把这副本标成「已移除」，之后再发是一条新请求。
- 每次核对都有反馈：按钮显示「核对中…」，完成后输入卡状态栏显示一句结果，4 秒后消失；失败照旧显示「核对失败，原提交仍保留；不会自动重发。」
- 复核后这一行改成按回执原文生成：`unknown` 且有 `missing` 是「已核对：电脑没收到」；`unknown` 没有 `missing` 是「已核对：电脑查不到这条的记录」；`dispatching` 是「已核对：电脑收到了，还在处理」；其他是「已核对：<标签>」。Claude 按它的记录说「已核对：已送达」「已核对：已排队」或「已核对：Claude 的记录里还没看到这条」。
- Claude 的发送核对先问一次回执；回执说 `unknown` 且有 `missing` 时同样标成「电脑没收到」、可以重发；其他情况或回执读不到时，照旧问 Claude 的记录，不因此报核对失败。
- 恢复草稿在输入框有字时不再消失：按钮一直显示但灰掉，下面写「输入框里有字，先清空才能恢复」；PendingSheet 同样。
- 「同样的字还在待确认时拒绝再发」这条没有改，所以「电脑没收到」的记录不受限制。
- PendingSheet 加入「电脑没收到」；待确认和电脑没收到两种记录也给出同样的按钮。

**P2 气泡里画出消息自带的图片**
- `Message` 新增 `images`；`parseMessage` 读电脑放在消息上的 `images`，电脑没有 `files` 时也读。
- `sentPictures` 先放按发送记录配到的图，再放消息自带、按 `id` 还没出现过的图；只画 `url` 以 `/api/codex/image` 开头且 `id` 合规的项，只有 `path` 的项跳过。下载、缓存、看大图继续用原来的 `sentPicture`。
- 演示世界新增「发送状态示例」：一条电脑没收到（可点重发、恢复草稿、移除），一条带图插话（图只在消息自己的 `images` 里）。

**改了哪些文件**
- 代码：`ChatController.kt`、`ChatCore.kt`、`SentPictures.kt`、`Models.kt`、`ChatUi.kt`（只改用户气泡的发送状态颜色和待核对面板）、`ComposerUi.kt`（只改发送状态栏、状态行和移除确认）、`FixtureApi.kt`（接上演示数据）；新建 `FixtureSendStory.kt`。
- 测试：新建 `SendFixesTest.kt`；`SentPicturesTest.kt` 加两条；`ReaderUiScenarios.kt` 里演示列表的两处期望条数从 12 改成 13、13 改成 14（演示世界多了一条对话）。
- `RelayApi.kt` 只加了一句注释，行为没变：统一回执本来就问 `/api/agents/<app>/receipt`，老电脑没有这条路时本地答 unknown，Claude 再回落到自己的记录。
- 没有改版本号，没有开模拟器，没有连手机或安装 APK，没有碰别的工作树。

**测试数字**
- 开工前基线：在 `c12fa99` 的干净副本上跑 `gradlew.bat --offline testDebugUnitTest`，345 个测试全部通过（31 个结果文件，0 失败）。
- 做完：`gradlew.bat --offline testDebugUnitTest` 358 个测试全部通过（32 个结果文件，0 失败，新增 13 个）；`gradlew.bat --offline assembleDebug` 通过。

### 10.4 线四 安卓「文件」

（待填）

### 10.5 线五 电脑

（待填）
