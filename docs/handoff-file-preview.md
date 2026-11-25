# 答案里的文件：一次做全的预览

交接设计，2026-11-25，Claude 写，DeepSeek 分四条线实现。分支 `file-preview`，从 `dev54` 的 527ebb2（dev.54 版本号那一次提交）切出，工作树 `D:/Personal/agent_remote_lanes/fprev`。这个分支只有这份文档，没有推送。电脑和网页的实现，等 dev54 合进 `agent-registry` 以后从那里开分支。

## 0. 结论

起因：用户投诉。安卓 1.0.10 上有一条回答，智能体用 R 画了一张图。图在消息里只显示成一行字「[图片：<图名> · 可在当前文件中查看已授权资源]」；同一条回答里 PNG、SVG、R 源码三个文件的链接，后面都写着「（链接未开放）」。

原因有三个，互不相干，只修一个不够：

1. **路径认得太窄。** 电脑、网页、安卓、iOS 四处用的是同一条规则：链接地址解码后，必须以「盘符 + 斜杠」开头（`D:\…` 或 `D:/…`）。写成 `/D:/…`、`file:///D:/…`、相对路径（`fig/a.png`）、`~/…` 的都不算。电脑因此不把这个文件列进对话的文件，手机就写「（链接未开放）」，图片就成了那行字。Codex 桌面版自己的格式说明，示范的正是 `[app.py](/abs/path/app.py:12)` 这种斜杠开头的写法。
2. **手机从不在消息里画图。** 安卓和 iOS 把回答里每张 Markdown 图片都换成一行字。路径认出来了，也只是一行能点的「[图片：…]」。只有网页会把图画出来。
3. **类型不全。** 电脑只把 png、jpg、jpeg、webp 算图片，只把 20 种后缀算文本。SVG、R 源码、日志、gif 都算「只能下载」，手机点开只说「手机上看不了这类文件」。

做法：认文件、判断能不能给手机、判断是什么类型、做缩略图，全部挪到电脑上**做一次**，结果跟着消息发给手机。手机和网页照着显示，不再各自猜路径。电脑还会把认出的文件链接改写成统一的 `<D:/…>`。所以**已经发布的安卓 1.0.10、iOS 0.9.0 不用更新，电脑一升级，这些链接就能点开**。图片直接画在消息里、看图缩放、SVG、代码高亮、音视频这些，要等新版 App。

分四条线交给 DeepSeek：电脑（5 段）、网页、安卓 1.0.11、iOS 0.9.1（等 0.9.0 发出后再开）。

## 1. 证据

### 1.1 截图说明了什么

安卓 1.0.10（分支 `android-push-caps`，cfef820）的 `Markdown.kt`：

- 链接（140 行起）：`localPath()`（116 行）认出电脑上的文件，就变成能点的文件链接；`safeWebLink()`（55 行）认出 http/https，就打开网页；两样都不是，就在文字后面加「（链接未开放）」（146 行）。
- 图片（149 行起）：`localPath()` 认出，就是一行能点的「[图片：名字]」（150 行）；认不出，就是「[图片：名字 · 可在当前文件中查看已授权资源]」（152 行），不能点。两种都不画图。
- `localPath()`：%-解码后要匹配 `^[A-Za-z]:[\\/]`。

所以截图说明：那张图和三个文件链接的地址都**没通过** `^[A-Za-z]:[\\/]`；那个网页链接是 https，所以能开。

截图标题下的来源名以 C 开头，是 Codex 或 Claude。这条对话不在这台电脑上（11-25 查过本机这两个助手最近两天的记录，没有这条回答），所以具体是哪种写法看不到。但不管是 `/D:/…`、`file://`、相对路径还是 `~`，都卡在同一处。智能体自己在下一步也说了，上一条用的是「电脑本地文件链接」。

就算路径认出来了：PNG 能在文件页里看；SVG 和 R 源码电脑都归为 `download`（`chat_history.py` 493 行），安卓文件页写「手机上看不了这类文件」（`WorkspaceUi.kt` 505 行），iOS 没有页内显示，网页只给下载。

### 1.2 这台电脑上的真实回答（30 天，只数数量）

脚本只打印数量，不读出文字、路径或标题。主要的那个存在 `%APPDATA%\Claude\side-session-notes\local_11ed7929-21cc-46ad-a1d2-d00e531dda08\file-preview-link-stats.py`，用法 `python -I file-preview-link-stats.py <有 message_files.py 的仓库> [天数]`。

| 助手 | 写法 | 数量 | 现在的结果 |
|---|---|---|---|
| Codex（745 条带链接的回答） | `D:\…` 或 `D:/…` | 930（其中图片 3 个） | 列出，能点；61 个文件已经不在 |
| | `/D:/…` | 18（14 个文件还在） | 没列，「（链接未开放）」 |
| | 相对路径 | 10（文件都在） | 没列，「（链接未开放）」：电脑只替 Claude 转相对路径 |
| Claude（388 条） | 电脑转好的 `D:/…` | 183 | 列出 |
| | `文件名.后缀:行号`，文件就在对话文件夹里 | 16 | 没转：`message_files.py` 28 行把 `remote.py:905` 的 `remote.py:` 当成了网址开头 |
| | 相对路径，在对话文件夹找不到 | 104 | 没列：25 个在对话文件夹下别的子文件夹里有同名文件，79 个哪里都没有 |
| | `#…` 页内链接 | 152（145 个是 Claude 桌面版的会话链接 `#local_…`，3 个终端链接） | 「（链接未开放）」，其实只该显示文字 |
| Claude「把文件发给用户」工具（SendUserFile） | 39 次，85 个文件，82 个是图片 | — | 电脑一个都没列，手机完全看不到 |

Codex 文件链接指向的类型（30 天）：代码和文本 570，Markdown 161，Office 88，HTML 41，压缩包 23，PDF 14，表格 9，图片 9。

### 1.3 现在每种文件在各处的样子

| 类型 | 电脑归类（`kind`） | 网页 | 安卓 1.0.10 | iOS 0.9.0 |
|---|---|---|---|---|
| 回答里的图片 | — | 认出的画出来（取原图） | 一行字 | 一行字 |
| png jpg jpeg webp | image | 文件页显示 | 铺满，不能缩放 | 铺满，点一下用快速查看放大 |
| gif bmp tif heic | download | 下载 | 看不了 | 页内显示 |
| svg | download | 下载 | 看不了 | 看不了 |
| pdf | pdf | 沙盒框里显示 | 一页页往下，不能缩放 | 能缩放 |
| docx xlsx | download，电脑转 PDF | 电脑转的 PDF | 手机上直接画 | 快速查看 |
| pptx doc ppt | download，电脑转 PDF | 电脑转的 PDF | 电脑转的 PDF | 快速查看 |
| csv tsv | text（≤1 MB） | 原文 | 表格 | 原文 |
| md | text | 阅读视图 / 源码 | 阅读视图 / 源码 | 阅读视图 / 源码 |
| html | text | 静态页面，不跑脚本 | 页面，跑脚本、能联网 | 页面，跑脚本、能联网 |
| py js json 等 20 种 | text（≤1 MB） | 原文，没有高亮 | 原文，没有高亮 | 原文，没有高亮 |
| R、log、xml、kt、swift 等 | download | xml、log、c、go 等网页自己当文本；R 只能下载 | 看不了 | 看不了 |
| 音频、视频 | download | 下载 | 看不了 | 先整个下载（≤20 MB）再播放 |
| 压缩包 | download | 下载 | 看不了 | 看不了 |
| 预览上限 | `/api/file` 不限，支持分段下载 | 16 MB，文本 1 MB | 20 MB，整个读进内存 | 20 MB |

### 1.4 代码位置

- 电脑（`dev54`）：`message_files.py`（`references` 12 行只认盘符；`_resolve` 25–31 行；`absolute_links` 33 行，只给 Claude 用，见 `chat_history.py` 129 行）；`chat_history.py` 的 `list_files` 464 行（类型在 493 行）、`file` 503 行；`remote.py` 的 `_reading_get` 922 行、`_serve_result_file` 957 行；`chats.py` 的 `codex_answer`（Codex 引用转链接）；`agents/base.py` 278 行 `presented_files`，只有 `agents/deepseek.py` 实现。
- 网页：`static/markdown-ui.js` 4 行（`local`）、34–45 行（链接、图片）；`static/reading-ui.js` 290–306 行（按序号找文件、懒加载图片）；`static/artifact-preview.js`（文件页）。
- 安卓（`android-push-caps`）：`Markdown.kt` 55、116、140–153 行；`WorkspaceController.kt` 的 `PreviewLimit` 37 行、`openLinkedFile` 636 行、`file` 693 行；`WorkspaceUi.kt` 的 `FilePage` 427 行、`PdfPages` 553 行、`PicturePreview` 582 行；`PreviewUi.kt`（HTML、Office）；`AnswerLinksTest.kt`。
- iOS（`ios-agents`）：`TeleplyCore/Sources/TeleplyModel/MarkdownReader.swift` 114–120、192–209 行；`Teleply/Files/FilePages.swift`、`DocumentPreview.swift`、`HtmlPreview.swift`、`PDFPreview.swift`；`TeleplyState/WorkspaceModel+Panes.swift` 的 `openLinkedFile` 66 行、`showsInPage` 236 行。
- 中转：分段下载能过（`relay_transport.py` 18–20 行放行 `Range`、`If-Range`、`Content-Range`、`Accept-Ranges`、`ETag`、`Content-Disposition`），回答是流式转发的。**`If-None-Match` 和 `Cache-Control` 不放行**；文件这类流式回答也不加 `nosniff`（`relay_service.py` 148–151 行只管还没开始发送的回答）。本设计不依赖改中转。

## 2. 总则

1. **电脑说了算。** 认文件、授权、类型、尺寸、缩略图都在电脑上做一次，跟着消息发给手机。手机和网页不再自己猜路径；只有连着老电脑时，才退回现在的做法。
2. **线上只有一种写法。** 电脑把认出的文件链接改写成 `<D:/…>`，老 App 也认得。
3. **能在 App 里看的就在 App 里看。** 看不了的说清原因，并给「保存到手机」「分享」「用其他应用打开」。
4. **不加「按路径读文件」的接口。** 手机只拿电脑发的文件编号；每次读都重新检查。

## 3. 电脑：认出回答里的文件

新模块 `answer_files.py`。`message_files.py` 留作兼容的薄包装（`references`、`absolute_links` 改为调新模块）。

输入：一条回答的全文（截断前）、这条消息所在那一轮的工作文件夹、对话文件夹、助手模块给的「展示的文件」。输出：`(改写后的文字, files, file_notes)`。

### 3.1 从哪里认（`via`）

| via | 是什么 | 现在 |
|---|---|---|
| `image` | Markdown 图片 `![…](…)`，以及 HTML `<img src>` | 只认盘符写法 |
| `link` | Markdown 链接 `[…](…)`，以及 HTML `<a href>` | 只认盘符写法 |
| `citation` | Codex 的 `:codex-file-citation{path=…}` | 已有（`chats.codex_answer` 转成链接） |
| `presented` | 助手明说「给用户看」的文件：Claude 的 SendUserFile 工具调用（`input.files`，都是绝对路径），DeepSeek 的成果清单 | 只有 DeepSeek |
| `tool` | 写文件的工具做完后的当前文件（`current_file`） | 已有 |
| `code` | 行内代码里**只有**一个路径（可以带行号），如 `` `D:\a\b.R` ``、`` `src/app.ts:42` `` | 新增 |
| `path` | 正文里的绝对路径（盘符开头；有空格的，要在引号或「」里） | 新增 |

整段代码块（``` 围起来的、缩进的）里的路径一律不算：那里多是命令和例子。

Claude 的 SendUserFile 是工具调用，不是回答文字。它的文件挂在它后面的第一条回答下面（同一轮里）；后面还没有回答时，先挂在那个工具行上。

### 3.2 认哪些写法

先去掉尖括号，%-解码（解出来不是合法 UTF-8 就按原样），NFC 规范化，再按下表处理：

| 写法 | 例子 | 结果 |
|---|---|---|
| 盘符 | `D:\a\b.png`、`D:/a/b.png` | 原样 |
| 斜杠加盘符 | `/D:/a/b.png`、`\D:\a\b.png` | 去掉开头的斜杠 |
| file 网址 | `file:///D:/a/b.png`、`file://localhost/D:/…`、`file:/D:/…`、`file://D:/…` | 取出路径 |
| 长路径前缀 | `\\?\D:\a\b.png` | 去掉前缀 |
| WSL 挂载 | `/mnt/d/a/b.png` | `D:/a/b.png` |
| 家目录 | `~/a/b.png`、`~\a\b.png` | 用户目录下 |
| 相对路径 | `fig/b.png`、`./b.png`、`../out/b.png`、`b.R:12` | 依次接在「这一轮的工作文件夹」「对话文件夹」「助手模块给的其他目录」后面试；**文件真的在才算**；不按名字到别处去搜 |
| 行号 | `:12`、`:12:5`、`:12-20`、`#L12`、`#L12C5`、`#L12-L20` | 去掉，记进 `line`（取第一行） |
| 网络位置 | `\\server\share\…`、`\\wsl$\…`、`file://server/…` | 不给，原因 `not_local` |
| 别的系统的绝对路径 | `/home/…`、`/Users/…`、`/tmp/…` | 不给，原因 `not_local` |
| 网页 | `http(s)://…` | 不是文件；`localhost`、`127.0.0.1`、`[::1]` 标成本机网址 |
| 页内、邮件、别的协议 | `#…`、`mailto:`、`vscode:` 等 | 不是文件，只显示文字 |

顺手修掉现在的毛病：`b.R:12` 这种「文件名.后缀:行号」不能当成网址开头（`message_files.py` 28 行）。

### 3.3 改写文字（给老 App 用）

- 认出的 `link`、`image`、`citation`：地址改写成 `<D:/a/b.png>`。用正斜杠，加尖括号；有行号就保留 `:12`，`:12:5` 改成 `:12`。正斜杠还避开了 Markdown 把 `\.` 当转义吃掉的老问题（安卓的 `looseFilePath` 就是为它打的补丁）。
- 绝对路径但文件已经不在：也改写。老 App 点开会说「文件已移动或删除」，不再说「未开放」。
- 相对路径找不到：不改，记进 `file_notes`。
- `code`、`path`：文字不改。新 App 让那段文字能点；老 App 在「答案里的文件」列表里能找到。
- 代码块、行内代码里的文字一个字不动（照 `absolute_links` 现在的遮罩做法）。
- 改写要幂等：改过的文字再跑一遍，结果不变。
- 消息的 `length`、`truncated` 按改写后的文字算。复制出去的也是改写后的文字（`/D:/` 变成 `D:/`，没有坏处）。
- 四个助手都走这一步（现在只有 Claude 打开了 `relative_links`）。

### 3.4 在哪里做，要多快

- 在 `History` 生成公开消息的地方做（`public_message` 一带），按（消息编号、文字摘要）缓存。四个助手的回答都要经过这里；动手前先核对 DeepSeek、Antigravity 的消息确实从这里出去，不是的话在它们出口各接一次。
- 先粗筛：文字里没有 `](`、`:\`、`:/`、`file:`、`<img`、`~/`，就跳过。
- 每条消息最多认 50 个文件。
- 查文件在不在用 `os.stat`，同一路径 5 秒内只查一次。
- 要求：这台电脑上最长的 Codex 对话和 Claude 对话，打开时间比 dev.54 慢不超过 5%（用 `claude-open-speed` 那套办法量）。

## 4. 电脑：哪些文件可以给手机

一个文件能给手机，要同时满足：

1. 是这个对话里某条回答按第 3 节认出来的（或完成的写文件工具、或助手明说展示的）；
2. 是普通文件，不是文件夹、设备；
3. 在这台电脑自己的磁盘上（和「电脑上的文件」同一条规则：固定盘、U 盘，不要网络盘）；
4. 实际位置就是写出来的位置：不跟着快捷方式、符号链接、目录联接走（现在就这样）；
5. 路径里没有备用数据流（盘符后面又出现 `:`）、没有 NUL，也不是 `CON`、`NUL`、`COM1` 这类保留名；
6. 不在「不给手机」清单里（新模块 `file_policy.py`）：
   - 遥应自己的：数据文件夹（`app_paths.DATA`）、任何 `remote_config.json`、`~\.teleply-updates`、`~\.android\teleply-signing`；
   - 各助手和工具的登录：`~\.codex\auth.json`、`~\.claude\.credentials.json`、`~\.dsh\.credentials.yaml`、`~\.gemini` 下的登录文件、`~\.ssh`、`~\.gnupg`、`~\.aws`、`~\.kube\config`、`~\.docker\config.json`、`~\.git-credentials`、`~\.npmrc`、`~\.pypirc`、`~\.config\gh`；
   - 按名字：`*.pem`、`*.key`、`*.p12`、`*.pfx`、`*.jks`、`*.keystore`、`*.kdbx`、`id_rsa*`、`id_ed25519*`、`.env` 和 `.env.*`（`.env.example`、`.env.sample` 除外）；
   - Windows：`System32\config`、`AppData` 下的 `Microsoft\Credentials` 和 `Microsoft\Protect`、浏览器资料文件夹里的 `Login Data`、`Cookies`、`Local State`。

每次读（列表、文件信息、原文件、缩略图、文本）都重新检查一遍，和现在一样；打开文件以后，再比一次大小和修改时间。

**为什么这样安全：**

- 没有任何接口按手机给的路径读文件。手机只拿电脑算的编号（用电脑的密钥做 HMAC，和现在一样），伪造不了。
- 只给这个对话里点了名的文件；网络位置、登录和密钥文件一律不给。
- 手机本身要先过中转的账号和设备登录。
- 实话说：「电脑上的文件」那张表（10-20 用户定的）本来就能翻遍本地磁盘、下载不隐藏的文件。所以这一层规则主要管两件事：结果**可以预期**，以及**密钥文件不会被顺手预览出去**。第 12 节建议把同一份清单也用到那张表上（另做）。

**Markdown 和 HTML 文件的附属资源**（同文件夹的图片、样式表）：现在只有对话里也点了名的才显示，所以报告里的图多半出不来。新规则：一个已经授权的 `.md` 或 `.html` 文件，它自己文字里用相对路径引用的文件也可以给。限制：

- 必须出现在这个文件的文字里（电脑自己解析，不信手机给的路径）；
- 在这个文件所在的文件夹或它的子文件夹里，不能用 `..` 走出去；
- 只限图片、CSS、字体（HTML 还可以有 JS）；每个 ≤8 MB，一个页面合计 ≤32 MB、最多 64 个；
- 同样过上面第 2–6 条检查（第 1 条换成「被已授权的文件引用」）。

## 5. 电脑：接口

这一节是四条线之间的约定。谁要改，先告诉主会话改这份文档。

### 5.1 消息里的 `files`

电脑支持本设计以后，每条回答的公开消息**都带** `files`（可以是空列表）。手机看到这个字段，就知道电脑是新的；没有这个字段，就是老电脑，手机退回现在的做法。

```json
"files": [
  {
    "id": "3f0c…",
    "index": 0,
    "name": "chart.png",
    "path": "D:\\work\\out\\chart.png",
    "kind": "image",
    "view": "image",
    "ext": "png",
    "mime": "image/png",
    "size": 183422,
    "modified": 1764031000000,
    "state": "current",
    "v": "9f2c41d0",
    "w": 2400,
    "h": 1500,
    "thumb": true,
    "line": null,
    "lang": null,
    "via": ["image", "link"]
  }
],
"file_notes": [
  {"href": "out/old.png", "reason": "not_found", "text": "电脑上没找到这个文件"}
]
```

- `id`：和现在一样，按（助手、对话、消息、序号、路径）算 HMAC；`/api/file*` 都用它。
- `index`：给还没换掉的旧网页用。Markdown 链接和图片（包括 Codex 引用转成的链接）来的文件，按它们在改写后文字里的先后编号，和旧网页 `markdown-ui.js` 的数法一致（每遇到一个本地链接或图片加一）；HTML 标签和别的来源从 1000 起编。同一条消息里同一个文件被链接两次，两个序号都要能找到（现在第二个找不到，顺手修掉）。
- `texts`：只有 `code`、`path` 来的文件才有，是它在文字里的原样（行内代码的内容、正文里那段路径）。手机按原样在文字里找到它，让那段字能点。
- `path`：Windows 写法。手机按「斜杠统一、不分大小写」和文字里的 `<D:/…>` 对上（安卓、iOS 的 `normalizePath` 已经这么做）。
- `kind`：**只用老的四种**（`image`、`pdf`、`text`、`download`；Office 另带 `"preview": "pdf"`），老 App 照它走：
  - `image` 扩到 png、jpg、jpeg、webp、bmp、heic、heif、tif、tiff。老 App 解不开的会说「无法原生预览」，不会比现在差。gif 对老 App 还是 `download`：iOS 0.9.0 现在用网页视图放 gif，会动，改成 `image` 反而只剩第一帧；
  - `text` 改成「能当文本读、≤2 MB」（见 5.5），R、日志、xml 等老 App 也能看文字了；
  - SVG 对老 App 还是 `download`（给老 App 看 SVG 的源码没有用）。
- `view`：新 App 按它选怎么显示：`image`、`svg`、`pdf`、`office`、`table`、`markdown`、`html`、`code`、`text`、`audio`、`video`、`archive`、`none`。
- `v`：文件版本，用大小和修改时间算出的短摘要；文件一变它就变。缩略图、原文件的地址都带上它，手机按地址缓存。
- `w`、`h`：图片和 SVG 的像素尺寸（只读文件头），读不到就不给。手机先按这个比例占好位置，图来了页面不跳。
- `thumb`：`/api/file/thumb` 对这个文件有回答。
- `line`：回答指向的那一行，代码页打开时跳过去。
- `lang`：代码语言，按后缀：`r`、`python`、`javascript`、`typescript`、`json`、`yaml`、`xml`、`sql`、`bash`、`powershell`、`kotlin`、`swift`、`java`、`c`、`cpp`、`csharp`、`go`、`rust`、`css`、`markdown`、`ini`、`diff`、`latex` 等。
- `state`：`current`、`updated`、`missing`。
- 同一条消息里同一个文件只出现一次，`via` 合并；顺序按第一次出现。
- `file_notes`：看着像文件、但给不了的。`href` 是文字里写的原样，手机按「%-解码后相等」找到那个链接。`reason` 见 6.4。

`/api/chat/files`（整个对话的文件）每一项也加上 `view`、`ext`、`mime`、`v`、`w`、`h`、`thumb`、`line`、`lang`、`via`；老字段不变。

### 5.2 `/api/file`（原文件）

- 照旧支持 `Range`、`If-Range`。
- `Content-Type` 用电脑自带的一张固定表，不用 `mimetypes`（它读注册表，每台电脑不一样）：
  - 图片：png `image/png`，jpg/jpeg `image/jpeg`，webp `image/webp`，gif `image/gif`，bmp `image/bmp`，tif/tiff `image/tiff`，heic/heif `image/heic`；
  - pdf `application/pdf`；
  - 音频：mp3 `audio/mpeg`，m4a `audio/mp4`，aac `audio/aac`，wav `audio/wav`，flac `audio/flac`，ogg `audio/ogg`；
  - 视频：mp4 `video/mp4`，m4v `video/x-m4v`，mov `video/quicktime`，webm `video/webm`，mkv `video/x-matroska`；
  - 文本（不会执行的）：`text/plain; charset=utf-8`；
  - 其余：`application/octet-stream`。
- 会执行的类型（`html`、`htm`、`xhtml`、`svg`、`xml`、`js`、`mjs`）**一律** `application/octet-stream` 加 `Content-Disposition: attachment`，不管请求怎么写。理由：中转不给流式回答加 `nosniff`，而网页和中转同源。
- 图片、PDF、音频、视频用 `inline` 和真实类型，好让播放器边下边播。
- 地址可以带 `v=`。`v` 和当前文件对不上时回 409「文件已变化」，手机重新取列表。
- 不靠 `If-None-Match` / 304（中转不放行），缓存靠地址里的 `v`。

### 5.3 `/api/file/thumb`（新）

- 参数：`app`、`id`、`file`、`w`、`v`。`w` 只接受 320、640、1280、2048；SVG 另外接受 4096。
- 只给 `view` 是 `image`、`svg` 的文件。PDF 首页缩略图要加 `pypdfium2`，也算新组件，这一版不做。
- 输出 WebP（质量 82，保留透明），长边不超过 `w`；按 EXIF 摆正；GIF 取第一帧；HEIC 用已经装着的 `pillow_heif`。
- SVG 转 PNG 用 resvg（见第 12 节）。转不了时 `thumb` 为 false，SVG 显示成文件卡。
- 防止超大图拖垮电脑：源图 ≤100 MB、≤1 亿像素（Pillow 的 `MAX_IMAGE_PIXELS`），一次最多做 15 秒，同时最多做 2 张，同一张图同时只做一次。
- 电脑缓存在 `DATA\cache\thumbs\`。文件名用（路径、大小、修改时间、宽度、算法版本）的摘要；总量超过 300 MB，删最久没用的。

SVG 的看图页就用 `w=2048` 或 `w=4096` 的 PNG，不另开接口。原 SVG 照样从 `/api/file` 保存、分享。

### 5.4 `/api/file/text`（扩展）

- 判断能不能当文本，不只看后缀：开头 8 KB 没有 NUL，并且能按 UTF-8（带不带 BOM）、UTF-16、GB18030 之一解开，就算文本。中文 Windows 上的 R 脚本和 CSV 常是 GBK。
- 超过 2 MB 的文本：给开头 2 MB（在行尾截断），带 `truncated: true` 和 `total_size`。
- 回答加字段：`encoding`、`truncated`、`total_size`、`lines`、`lang`、`line`。老字段 `text`、`name` 不变。

### 5.5 `kind: text` 的新判定

列表里的 `kind`：后缀在老的 20 种里、或者按 5.4 能当文本读，并且 ≤2 MB，就是 `text`。SVG、HTML 例外：SVG 照旧 `download`；HTML 照旧 `text`（老 App 有页面视图）。`view` 不受 2 MB 限制：更大的文本文件 `view` 仍是 `code` 或 `text`，新 App 显示开头 2 MB 并说明。

### 5.6 `/api/file/resource`（新：Markdown、HTML 的附属资源）

参数：`app`、`id`、`file`（那个 md 或 html 的编号）、`path`（它文字里写的相对路径）。按第 4 节的规则检查后给原文件。网页和安卓现在「到对话文件列表里按路径找」的做法，换成用它。

### 5.7 `/api/file/zip`（新）

只读 zip 的目录：`{entries: [{name, size, packed, modified, dir}], total, truncated}`，最多 2000 项。名字没有标 UTF-8 时先试 GBK（中文 Windows 打的包），不行再用 cp437。7z、rar 不读。

### 5.8 大小上限

| 用途 | 上限 | 超过时 |
|---|---|---|
| 原文件：下载、保存、分享 | 不限（分段下载，能续传） | — |
| 看图页取原图 | 30 MB | 用 2048 的缩略图看 |
| 做缩略图的源图 | 100 MB、1 亿像素 | 文件卡 +「图太大，保存后再看」 |
| SVG 源文件 | 10 MB | 文件卡 |
| 文本、代码 | 2 MB | 显示开头 2 MB，并说明 |
| 表格（CSV、TSV） | 5 MB、前 5000 行 | 显示前 5000 行，并说明 |
| PDF 在 App 里看 | 100 MB（先存进手机缓存，不整个放进内存） | 保存后用其他应用打开 |
| Office 在手机上画 | 30 MB | 照现在：电脑转 PDF，或者保存 |
| 音频、视频 | 不限（边下边播） | — |
| 一条消息认出的文件 | 50 个 | 多的不列 |

### 5.9 电脑上的缓存

- 文件信息（stat、图片尺寸、能不能当文本）：按路径缓存 5 秒。
- 每条消息的认文件结果：按（消息编号、文字摘要）缓存，跟对话记录一起丢掉。
- 缩略图：磁盘上 300 MB（5.3）。
- 文本解码结果不缓存。

## 6. 手机和网页：怎么显示

三端照同一份规格做。下面说的都是新版：网页跟着 dev.55，安卓 1.0.11，iOS 0.9.1。

### 6.1 消息里

- **图片画在原处。** 回答里的 `![…](…)` 和 `<img>`，在原来的位置画缩略图：宽度占满气泡，最高约 360 dp，先按 `w`/`h` 占好位置；没加载好时灰底加文件名；失败时一行原因加「重试」。点开进看图页。
- **文件条。** 每条回答下面一排文件卡，列出这条消息里**没有画在原处**的文件（来自 `link`、`citation`、`presented`、`tool`，按 `id` 去重）。图片和 SVG 显示小缩略图，其他显示类型图标；再加名字和大小，`updated`、`missing` 有标记。最多 8 个，多了显示「还有 N 个」，点开是这条消息的文件列表。Claude 用 SendUserFile 发的图就出现在这里。
- **文字里的链接。** 按 `files` 找到编号，点了直接进文件页（不再先拉整个对话的文件列表）。
- **`code`、`path` 来的文件。** 那段文字本身变得能点；不加文件卡，免得代码回答下面挂一长排。
- **给不了的。** 链接文字照常显示，后面跟一个灰色短说明，比如「（文件已删除）」「（找不到文件）」「（网络位置）」「（不开放）」；点一下弹出完整原因（6.4）。
- **不是文件的链接。** `#…`、Claude 桌面版的会话和终端链接、`mailto:` 等，只显示文字，不再加「（链接未开放）」。`localhost` 网址后面加「（电脑本机网址，手机打不开）」。
- **老电脑**（消息里没有 `files`）：照现在的做法，功能一样不少。

### 6.2 文件页（按 `view`）

| view | 怎么显示 | 「⋯」菜单 |
|---|---|---|
| image | 先显示 1280 的缩略图，再换原图（≤30 MB，否则用 2048）。双指缩放到 8 倍，双击放大或还原，可以拖动；GIF 会动；左右滑看同一条消息里的其他图，顶上显示「2/5」 | 保存到手机、分享、用其他应用打开 |
| svg | 显示电脑转的 PNG（2048；放大到 2 倍以上换 4096）。网页直接用 `<img>` 画矢量 | 同上；拿到的是原 SVG |
| pdf | 一页页往下，能缩放（安卓现在不能，补上：缩放停下后按新倍数重画看得见的页，最多 3 倍），显示页码 | 同上 |
| office | 照现在：安卓手机上画 docx、xlsx，ppt 等用电脑转的 PDF；iOS 快速查看；网页用电脑转的 PDF | 同上 |
| table | CSV、TSV 三端都画成表格：首行当表头、能横滑、前 5000 行。文字由 `/api/file/text` 给，编码已经解好 | 查看原文，加上面三项 |
| code | 语法高亮、行号、自动换行开关、打开时跳到 `line`、页内查找、复制全部；超过 200 KB 不高亮，只给行号 | 同上 |
| text | 和 code 一样，不高亮 | 同上 |
| markdown | 阅读视图（附属图片经 5.6 显示）/ 源码 | 同上 |
| html | 安卓、iOS 照用户 10-24、10-25 的选择：页面跑脚本、能联网，但和 App 隔开（没有 App 的 cookie，没有桥），附属资源经 5.6。网页还是静态，不跑脚本（见第 8 节） | 查看源码，加上面三项 |
| audio、video | 系统播放器边下边播（分段下载）。安卓用 `MediaPlayer` / `VideoView`，带上和接口一样的 Cookie 和协议头；iOS 用 `AVURLAsset`，Cookie 放进 `AVURLAssetHTTPCookiesKey`；网页用 `<video>`、`<audio>`。放不了的格式显示文件卡 | 同上 |
| archive | zip 列出里面的文件名和大小（5.7）；7z、rar 只显示文件卡 | 同上 |
| none | 图标、名字、大小，一句「这种文件手机上不能直接显示」，下面三个按钮 | — |

代码高亮三端用同一份东西：固定版本的 `highlight.js`（BSD-3 许可）加一个 `code.html`。网页放进 `static/`，照 `vendor-lock.json` 记下版本和摘要；安卓放进 `assets/viewer/`；iOS 放进 App 包。手机上用一个不联网、没有 App 桥的网页视图打开它，和安卓现在画 Word、Excel 的做法一样。

### 6.3 加载顺序和流量

- 消息里只取缩略图（按屏幕挑 640 或 1280），不取原图。
- 文件条只取 320 的缩略图。
- 看图页先显示已经缓存的缩略图，再取原图。
- 用移动网络时不预取后面的图；用 Wi-Fi 时预取同一条消息里的下一张。

### 6.4 原因怎么说

| reason | 手机上的话 |
|---|---|
| `missing` | 文件已移动或删除 |
| `changed` | 文件刚改过，重新打开就是新的 |
| `not_found` | 电脑上没找到这个文件（回答写的是相对位置，在对话文件夹里没找到） |
| `not_local` | 文件在网络位置或别的电脑上，遥应只读这台电脑自己的磁盘 |
| `denied` | 出于安全，遥应不让手机读这个文件（可能含密钥或登录信息） |
| `folder` | 这是文件夹，可以在「电脑上的文件」里看 |
| `too_large` | 文件有 N MB，超过手机上直接看的上限；可以保存或用其他应用打开 |
| `unsupported` | 这种文件手机上不能直接显示；可以保存或用其他应用打开 |
| `decode` | 读不出这个文件的文字编码；可以保存后用其他应用打开 |
| `offline` | 电脑离线，连上后再试 |
| `old_pc` | 电脑端版本较旧，更新到 dev.55 或以后才能看 |
| `local_web` | 这是电脑本机的网址，手机打不开 |

`missing`、`not_found`、`not_local`、`denied`、`folder` 由电脑给，其余由手机自己判断。

## 7. 手机上的缓存

- 缩略图：按地址（带 `v`）存在 App 的缓存目录，上限 200 MB，超了删最久没用的。地址里有 `v`，同一个地址的内容永远不变，不用再问电脑。
- 原文件（看图、PDF、代码、表格、Office）：按（电脑、文件编号、`v`）存缓存目录，上限 500 MB。「保存到手机」「分享」有缓存就直接用，不再下载第二遍。
- 列表里的 `v` 变了，旧缓存就不再用，下次清理时删掉。
- 退出登录、删掉一台电脑时，清空这台电脑的缓存。不放进公共相册或下载目录。
- 安卓照 `SentPictures` 现在的做法（先写 `.part` 再改名），解码时按屏幕尺寸缩小；iOS 用 ImageIO 按尺寸解码；网页用浏览器自己的缓存。

## 8. 安全细节

- 网页：
  - SVG 只放进 `<img>`（这里面的脚本不会执行）。**不要**在新标签页打开 SVG、HTML 的 blob 地址，也不要让用户跳过去：blob 地址和遥应同源，跳过去以后 SVG 里的脚本能拿到登录。保存一律用 `download`。
  - HTML 预览照现在：DOMPurify 清理，`sandbox` 框（不给 `allow-same-origin`，也不给 `allow-scripts`），严格的 CSP。
- 手机：
  - HTML、代码、表格用的网页视图：不给 App 的 cookie，不开文件访问，没有 JS 桥；代码和表格视图不联网。
  - 看图、PDF、播放器只用电脑发的编号地址。
- 电脑：第 4 节的清单和每次复查；5.2 的「会执行的类型一律当下载」。
- 中转（建议另做，要用户同意）：给流式回答也加 `X-Content-Type-Options: nosniff`，并放行 `Cache-Control`。本设计不依赖它。

## 9. 测试

电脑（pytest）：

- `tests/test_answer_files.py`：一张表驱动的样例集，3.2 节每种写法都有。还要有：中文文件名、空格、括号、%-转义、反斜杠转义、各种行号、相对路径的查找顺序、代码块里的路径不算、行内代码只有路径才算、正文路径后面跟中文标点、HTML `<img>`、Codex 引用、Claude SendUserFile、DeepSeek 成果、网络位置、WSL、`~`、`#`、`localhost`。
- 改写：代码不动；幂等；**把安卓的 `localPath`、iOS 的 `localPath`、网页的 `local` 三条规则照抄进测试，断言每个改写后的地址三条都认**；改写后的地址经兼容包装 `references` 也能列出。
- `tests/test_file_policy.py`：清单里的每一类、目录联接（照现有测试的做法）、备用数据流、保留名、网络盘（注入 `drives`）。
- 接口：缩略图（png、jpg、gif、heic、svg、坏图、超大图）；`v` 对不上回 409；`Range` 和 `If-Range`；会执行的类型当下载；文本编码（UTF-8、带 BOM、UTF-16、GB18030 的 R 脚本）和截断；zip 目录（含 GBK 名字）；附属资源的每一条限制；同一文件链接两次时两个 `index` 都能找到。
- 老测试：`tests/test_read_golden.py` 里凡是带非盘符文件链接的文字会变，这是有意的，在结果里逐条列出；`tests/test_action_golden.py` 不变。DeepSeek 的终端跑浏览器测试要先设 `PLAYWRIGHT_BROWSERS_PATH=D:/Personal/agent_remote_lanes/ms-playwright`；全套 pytest 最后由主会话自己跑。
- 速度：3.4 节的 5%。
- 真实数据：改完在这台电脑上重跑只数数量的脚本（1.2 节的 `file-preview-link-stats.py`，由主会话跑）。目标：还存在的文件里，除了网页链接和 `#`，「没列出」的是 0；Claude SendUserFile 的图都在列表里。

网页（Playwright）：一个「文件预览示例」测试对话，每种 `view` 一个文件。检查：消息里的图画出来、文件条、原因、看图缩放和左右滑、SVG 用 `<img>`、表格、高亮、音视频能放、HTML 是静态的。

安卓：单元测试（按 `files` 找链接、老电脑退回 `localPath`、原因文字、按 `view` 选页面）；`FixtureApi` 加同样的示例对话；浅色、深色截图。

iOS：TeleplyCore 测试和安卓一样；`DemoWorld` 加示例对话（放在调试开关后面，不改现有的截图组）；Codemagic 编译和截图。

## 10. 上线顺序

| 部分 | 版本 | 前提 | 用户能看到什么 |
|---|---|---|---|
| 电脑和网页 | Windows dev.55 | dev54 合进 `agent-registry` 以后 | 老手机：各种写法的文件链接都能点开；R、日志、xml 等能看文字；heic、bmp、tif 在安卓上也能看图；Claude 发的图出现在「答案里的文件」里；已删除的文件说「已移动或删除」。网页：第 6 节全部 |
| 安卓 | 1.0.11 | 配 dev.55 或以后；配老电脑时和 1.0.10 一样 | 第 6 节全部 |
| iOS | 0.9.1 | 0.9.0 发出后，从发 0.9.0 的分支开 | 第 6 节全部 |

打包、安装、发布、推送、TestFlight，都照老规矩先问用户。

## 11. 分给 DeepSeek 的线

DeepSeek 工作区 `F:\Android-Dev\work\20261101-island-duplicates`，每条线一个日期子文件夹；deepseek-flash，high，完全权限。每段做完提交一次，在第 14 节写结果，然后停下等审。提示词由主会话照 deepseek-harness 技能的规则写：工作区和仓库分开、`git add` 一个个加、不用 PowerShell 自带变量当名字、不在自己文件夹以外递归删除、哪些事要停下问用户。

| 线 | 分支和工作树 | 从哪里开 | 改哪些文件 | 分段 | 依赖 |
|---|---|---|---|---|---|
| 一、电脑 | `fp-pc`，`D:\Personal\agent_remote_lanes\fp-pc` | `file-preview`；B 段前合入 dev54 合并后的 `agent-registry` | `answer_files.py`（新）、`file_policy.py`（新）、`file_renders.py`（新）、`message_files.py`、`chat_history.py`、`chats.py`、`agents/*.py`（Claude 的 SendUserFile）、`remote.py` 的文件接口、`tests/` | A 认文件和改写；B 授权、`files`、`file_notes`、列表；C 文本接口、类型表、速度、老测试；D 缩略图、SVG、`v`；E zip、附属资源 | 无 |
| 二、网页 | `fp-web`，`D:\Personal\agent_remote_lanes\fp-web` | 线一 B 段的提交 | `static/*.js`、`static/*.css`、`static/vendor-lock.json`、`highlight.js`、网页测试 | A 消息里的图、文件条、原因；B 看图页、SVG、表格、高亮；C 音视频、zip、附属资源 | 线一 B 段（A 段可以先拿 5.1 的样例 JSON 做） |
| 三、安卓 1.0.11 | `fp-android`，`D:\Personal\agent_remote_lanes\fp-android` | `android-push-caps`（cfef820，即 1.0.10） | `Markdown.kt`、`ChatUi.kt`、`WorkspaceController.kt`、`WorkspaceUi.kt`、`PreviewUi.kt`、`RelayApi.kt`、`PlatformFiles.kt`、`FixtureApi.kt`、`assets/viewer/`、测试 | A 按 `files` 找链接、消息里的图、文件条、原因；B 看图页（缩放、左右滑）、SVG、PDF 缩放、存缓存不进内存；C 代码高亮、表格改走文本接口、音视频、zip | 第 5 节的约定；联调要等线一 D 段装到这台电脑上 |
| 四、iOS 0.9.1 | `fp-ios`，`D:\Personal\agent_remote_lanes\fp-ios` | 0.9.0 发出后的分支（ipad-adapt 和 ios-agents 合并后） | `MarkdownReader.swift`、对话页、`Files/*`、`WorkspaceModel+Panes.swift`、`RelayClient`、`DemoWorld`、测试 | 和安卓一样三段；每段推送后在 Codemagic 编译 | 0.9.0 发出；第 5 节的约定 |

线一、线三 11-25 同时开工（用户：「交给 DeepSeek」）。线一的 A 段只加新文件，所以先从 `file-preview`（dev54 的 527ebb2 加这份文档）切出；B 段开始前，主会话把合了 dev54 的 `agent-registry` 合进 `fp-pc`。线三从 cfef820 切出，再拣入这份文档。线二等线一 B 段；线四等 0.9.0 发出。

各线都不做的事：版本号和更新说明（主会话做）、打包、安装、发布、推送、TestFlight、中转、Codemagic 网站、Apple 网站；不打印密钥和令牌；不打开 `remote_config.json`；不把真实对话的文字、标题写进代码、测试或文档。

## 12. 要用户决定的事

1. **SVG 转图片要加一个新组件 resvg。** 开源，Apache-2.0 或 MIT 双许可。**用户 11-25 已同意：这份设计要用的组件（resvg、highlight.js）下载时不用再问，直接用。** 仍然要：固定版本，从官方来源拿（PyPI、npm、GitHub 发布页），核对它自己的许可证文件，把版本和摘要记进 `requirements.txt` 或 `static/vendor-lock.json`。resvg 还要先确认这台电脑的 Python 版本有 Windows 安装包（`resvg_py` 新版只见到 Linux 包，可能要用旧版或官方的 `resvg.exe`）；实在没有，网页照样能画 SVG，手机上的 SVG 显示成文件卡。
2. **行内代码里的路径也算「回答点名了这个文件」。** 现在的规则是「代码里的路径一律不算」（`message_files.py` 第 1 行的说明）。新规则只放宽到「反引号里只有一个路径」；整段代码块照旧不算，另外还有第 4 节的「不给手机」清单把关。
3. 建议另做：把第 4 节的「不给手机」清单也用到「电脑上的文件」那张表上。
4. 建议另做（要改中转）：第 8 节最后一条。

## 13. 这次不做

- Mermaid 图（Codex 的格式说明鼓励用它画小图）和 Codex 的「内嵌可视化」，手机上现在显示成代码。以后可以在电脑上转成图片，走同一条缩略图的路。
- 电脑本机网址（`localhost` 上的开发服务器）通过中转给手机看。
- 别的电脑、网络盘上的文件。
- 在手机上改文件。
- 视频封面、PDF 首页缩略图（要 ffmpeg、pypdfium2）。

## 14. 结果（各线填写）

### 线一、电脑

#### 第一段（认文件和改写）

已做：新增 `answer_files.py`，入口是纯函数 `scan(text, bases, *, presented=(), stat=os.stat) -> Scan`；新增 `tests/test_answer_files.py`。这一段没有改 `chat_history.py`、`remote.py`、`message_files.py`，也没有接进消息的出口。

认哪些：§3.1 的 `image`、`link`（含 `[x][r]` 和定义行）、HTML `<img src>` / `<a href>`、`code`、`path`、`presented`；另外直接认 `:codex-file-citation{...}`，记 `via: citation`、文字不改（线上 `chats.codex_answer` 已经先把它转成链接）。`texts` 只给 `code`、`path` 来的文件。

怎么改写：§3.3 全部照做。地址从原文取（反斜杠一律当分隔符，`D:\a\.claude\f.md` 不会丢反斜杠）；%-解码失败就保留原样（`100%.txt`、`%FF`）；NFC；`:12`、`:12:5`、`:12-20` 去掉，`#L12`、`#L12C5`、`#L12-L20` 只在整串找不到文件时去掉；HTML 标签只认不改；引用式链接改定义行；代码块、行内代码一字不动；`scan(scan(t).text)` 文字不变。

`index`：按改写后的文字、markdown-it 的顺序，给所有本地 Markdown 链接和图片从 0 编号（文件夹、文件不在也占号）；HTML、`code`、`path`、`presented`、`citation` 从 1000。每个文件另有 `indexes`（旧网页的每个号），`index` 是其中最小的一个。同一个文件被链接两次时两个号都在；B 段做 `/api/chat/files` 时按 `indexes` 拆成多行，旧网页第二个链接才找得到。

审后修（11-25）：带端口的网址（`https://host:443`）和一切 `协议://` 地址不再当文件；`//cdn…` 按原文判成网页地址，只有原文以 `\\` 开头的才算网络位置；`presented`、Codex 引用、行内代码、正文路径是真实路径，不做 %-解码（只有 Markdown 链接/图片地址解码）；只有 markdown-it 真认作定义的行才算定义行；链接文字 `[…]` 里的路径不再记成 `path`；`<file:///D:/…>` 自动链接认成 `link` 但不改写，编号从 1000。每处都有测试。

几个自己定的做法，请审：

- 改写后的地址把 `%` 写成 `%25`（`100%.txt` → `100%25.txt`），否则旧网页的 `decodeURIComponent` 遇到 `100%` 会抛错；三端规则解码后仍是原路径。
- 相对路径找不到只给 `file_notes`（`not_found`），并且只认「像文件」的相对路径（有 `/`、有扩展名或有行号）；`#…`、`mailto:`、`vscode:`、网页、`localhost` 都不记 note。
- 网络位置和别的系统的绝对路径在查文件之前就判 `not_local`，不会调用 `stat`（测试里用会抛错的 `stat` 验证过）。

测试：`tests/test_answer_files.py` 80 个（表驱动，§3.2 每种写法、三端 `localPath` 契约、幂等、代码不动、重复 index、50 个上限、网络不 stat，以及上面六处审后修），加 `tests/test_relative_links.py`、`tests/test_artifact_files.py` 共 90 个通过。速度：本机 10,000 条编造消息（各约 2 KB，5,000 条带链接），总 8.3–8.7 秒，约 0.86 ms/条；带链接的约 1.7 ms/条。量速脚本在 DeepSeek 工作区，没有提交。

没做：B 段的 `file_policy.py`、消息里的 `files` / `file_notes`、`/api/chat/files`；没有改版本号、没有推送。

#### 第二段（授权、接进电脑、发给手机）

已做：

- 新增 `file_policy.py`：§4 第 2–6 条和「不给手机」清单，`check()` / `inspect()` 只返回 `missing`、`folder`、`not_local`、`denied` 或 `None`；盘符列表、家目录、数据文件夹、`stat` 都可注入。网络位置、别的盘、别的系统的绝对路径在 stat 之前就拒绝；符号链接/目录联接、备用数据流、保留名、登录/密钥/浏览器资料和 `remote_config.json` 都拒绝。
- `History` 按需处理：读记录时只存原文，出公开消息、列文件时才调 `answer_files.scan`，结果按（文字摘要、bases、presented）缓存到消息上；`length`、`truncated` 按改写后的文字算。
- 三个出口都带 `files`（没有文件是 `[]`），有原因时带 `file_notes`：`chat_history.py` 的 `conversation()`（一页）、`message()`（整条）、`live_events.py` 的 `merge_live_messages()`（实时）。DeepSeek、Antigravity 的 `read()` 页也在 `History.conversation()` 里补上，所以四个助手都走同一套。
- `bases` 依次是消息/这一轮的 `cwd`（有的话）、对话文件夹；`presented` 用助手自己的 `presented_files()`。
- Claude 的 SendUserFile：`chats.parse_claude` 把 `input.files` 记在工具行上；`ClaudeAgent.attach_presented()` 把它移到同一轮后面的第一条回答，后面还没有回答时留在工具行。DeepSeek 成果清单照旧。
- `files` 字段按 §5.1：`id`、`index`、`name`、`path`、`kind`（老四种）、`view`、`ext`、`mime`、`size`、`modified`、`state`、`v`、`line`、`lang`、`via`，`code`/`path` 加 `texts`；`thumb` 一律 false，没有 `w`/`h`。Office 带 `preview: "pdf"`。策略拒绝的不进 `files`，进 `file_notes`；`missing` 留在 `files`，`state` 是 `missing`。
- `/api/chat/files` 用同一套结果；老字段都在，新字段照 §5.1；`message=` 时同一个文件的每个 `index` 各一行（各自的 `id`），整个对话按路径去重。`History.file()` 仍每次重新走 `list_files()` 的策略复查。
- `message_files.references`、`absolute_links` 改成 `answer_files` 的薄包装。

审后修（11-25）：`~/.gemini` 只放开 `antigravity/brain` 和 `antigravity-cli/brain`，其余照旧不给；盘符列表缓存 30 秒，`file_policy.inspect` 的路径结果缓存 5 秒（时钟可注入，`History.file()` 用 `fresh=True` 绕过读缓存、仍每次重新检查）；`updated` 恢复成一旦发现就一直保持；同样文字的消息共用一次 `answer_files.scan`（`History` 里最多 256 条），所以一万条编造对话第一次列文件从 **4.8 秒降到约 0.10 秒**。

测试：`tests/test_file_policy.py` 52 个通过、1 个符号链接用例跳过（Windows 不许建链接）；`tests/test_answer_files_history.py` 13 个通过（三个出口、空 `files`、`file_notes`、SendUserFile 两种位置、DeepSeek 成果、缓存、同文共用、刷新后仍能称重、updated 保持）；`tests/test_answer_files.py` 80 个、第一段两个旧文件测试也通过。

完整 pytest（第二段当时，工作区 `full-pytest-final.log`）：**1523 passed，7 skipped，3 failed**。

速度（本机，编造 10,000 条各约 2 KB、5,000 条带链接的对话，只有两个不同文件）：修前第一次出一页 **0.085 秒**、第一次列整个对话文件 **4.78 秒**；修后 **0.026 秒**和 **0.105 秒**，缓存后再列 0.09 秒、再出页 0.018 秒。脚本在 DeepSeek 工作区，没有提交。

旧测试的有意改动：

- `tests/test_relative_links.py`：Claude 读记录不再改写原文，改写后的文字从公开消息看；`absolute_links` 现在也把绝对链接统一成 `<D:/…>`；`references` 去重。
- `tests/test_artifact_files.py`：行内代码里只有一个路径现在算引用（§12 的决定），`references('`C:/secret.html`')` 从 `[]` 变为 `['C:/secret.html']`；`plain filename.html` 仍然不算。
- `tests/test_read_golden.py`、`tests/test_action_golden.py` 没变：它们的固定数据只存记录解析和旧版实时合并的原始字段，没有经过公开消息的 `files`，也没有带链接的例子。

没做：第三段的内容判文本、类型细表；第四段的缩略图、`w`/`h`、附件资源、zip；没有推送、合并、打包、改版本号。

要审：

- `files` 只加在回答（和还没有回答的 SendUserFile 工具行）上；用户消息没有 `files`。
- `file_policy` 把 `~/.aws`、`~/.ssh` 等整个目录都算不给；`~/.gemini` 只放开 `antigravity/brain` 和 `antigravity-cli/brain`，其余不给。浏览器文件只在路径带 Chrome/Edge/Firefox/User Data 等标记时按文件名拒绝。
- HTML 的 `<img src>` / `<a href>` 仍按网址做 %-解码；审后修里「不做 %-解码」只指 presented、Codex 引用、行内代码、正文路径。
- 整个对话第一次列文件在 10,000 条时约 0.10 秒（同文共用一次 scan；不同文字的长对话仍是逐条认）。

### 线二、网页

（待填）

### 线三、安卓 1.0.11

（待填）

### 线四、iOS 0.9.1

（待填）
