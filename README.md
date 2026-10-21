# Agent Remote

在手机上查看、继续电脑上 **Codex**、**Claude**、**DeepSeek Harness** 桌面版里的对话。

电脑上跑一个小服务，手机经 [Tailscale](https://tailscale.com) 打开一个网页就能用：不需要公网服务器，不装 App，对话内容不经过任何第三方。

适合这样的时候：人不在电脑前，想看看 AI 做到哪一步了，回答它的提问，补一句话，或者新开一个任务。

## 功能

- **三家桌面版一个列表**：Codex、Claude、DeepSeek Harness 的对话放在一起，按最近活动排序，可以搜索；侧边栏按项目分组，和桌面版的分法一致。
- **只显示装了的软件**：这台电脑没装的桌面版，不会出现在列表、筛选条、新建面板和侧边栏里。每次打开页面都会重新检查一遍，新装的软件刷新页面就会出现。
- **实时看进度**：回答、思考摘要、工具步骤、进度清单都会实时更新；长回答可以展开，回答和代码可以复制。
- **继续对话**：用手机输入法打字，可以发文字和图片，也可以引用别的对话或技能。AI 正在运行时，可以「立即补充」给这一轮，也可以排队稍后发送；还可以停止这一轮。
- **附文件**：「＋」里可以翻电脑上的文件夹，选任意文件，或者整个文件夹一起选；也可以把手机里的文件传上去，存进电脑的「下载\手机传来的文件\日期」。消息里只写文件在电脑上的位置，由 Codex、Claude、DeepSeek 自己打开，所以 Word、Excel、PDF、压缩包都能附；图片照旧按图片发。手机上只看得到文件名、大小和时间，看不到文件内容。
- **左滑归档**：在对话列表里把一个对话往左滑，会先停在「归档」按钮上，点按钮就归档；一直滑过一半再松手，就直接归档。在「设置 → 已归档对话」里可以恢复，Codex 的还可以勾选后批量删除。Claude 通过桌面搜索的会话 ID 定位，等索引确认后才显示「对话已归档」和「撤销」；需要电脑解锁，运行中、状态不明或带工作副本的会话会拒绝归档。Claude 和 DeepSeek 暂不支持从手机删除。升级后需重启服务，旧服务不会开放 Claude 归档入口。
- **回答提问和批准**：Codex 的计划提问，Claude 的选项和「下一步」框，DeepSeek 的提问和工具批准，都会在手机底部弹出面板来回答。
- **新建对话**：三家都在同一个面板里新建：选软件、项目文件夹（DeepSeek 选它自己的工作区）、模型和推理强度，写好第一句话（可以带图片、文件、引用别的对话）一次发出。网络断了点「继续发送」，也不会建出两个对话。Codex 和 Claude 还能新建不属于任何项目的对话。
- **改设置**：Claude 的模型、推理强度、权限模式；DeepSeek 的模型和权限预设。
- **多台电脑**：每台电脑各装一份，页面上点电脑名就能切换。服务会自动找出同一 Tailscale 账号下装了本服务的其他电脑。
- **做完推送**（可选）：对话一轮结束时推到手机，点通知直接打开那个对话。iPhone 用 [Bark](https://bark.day.app)；安卓用 [ntfy](https://ntfy.sh) App，由本服务自己发给它，经 Tailscale 直接到手机，不经过别人的服务器。你正看着这个对话，或者刚在电脑上操作过，就不推。
- **语音输入**（可选）：边说边识别，需要另外准备本地语音模型。
- **手机上顺手**：侧滑返回、底部面板、轻触震动、主屏幕图标，按 iPhone Safari 调过。安卓上，系统返回键会在页面里一层层往回退。

## 工作原理

```
手机浏览器 ──Tailscale（加密）──▶ 电脑：tailscale serve（https）──▶ 本服务 127.0.0.1:8765
                                                                     ├─ Codex：桌面版的本机通道
                                                                     ├─ Claude：桌面版的记录文件 + 桌面窗口操作
                                                                     └─ DeepSeek Harness：桌面版的本机接口
```

- 对话内容直接读各家桌面版自己的记录文件，不靠截屏。
- 发消息：Codex 走桌面版自己的本机通道；Claude 往桌面窗口的输入框里填字、再点发送（Windows UI Automation）；DeepSeek 调用它的本机接口。
- 服务只监听本机，由 `tailscale serve` 放到这台电脑的 Tailscale https 地址上；手机要连着 Tailscale 才能打开。

## 谁能打开

- 经 Tailscale 进来的请求会带上访问者的 Tailscale 账号。只有**这台电脑登录的账号**，以及 `remote_config.json` 里 `allowed_logins` 列出的账号能用；其他账号一律拒绝，带着口令也不行。
- 不经 Tailscale 打开时要带口令：比如在电脑上直接开 `http://127.0.0.1:8765/?t=口令`，或者把服务改成在局域网里监听。口令每台电脑各自生成，只保存在本机的 `remote_config.json` 里，手机链接和二维码里都没有它。
- 安装脚本不会覆盖 443 端口上已有的服务（会改用 8443），也不会把网页放到开着 Funnel（公开到整个互联网）的端口上。

## 环境要求

| 项目 | 要求 |
|---|---|
| 电脑 | Windows 10 / 11，保持开机、登录；Claude 需要屏幕不锁 |
| Python | 3.11 或更新，推荐 3.12 |
| Tailscale | 电脑和手机登录同一个账号；在 Tailscale 后台的 DNS 页打开 HTTPS Certificates |
| 桌面版 | Codex、Claude、DeepSeek Harness 至少装一个 |
| 手机 | iPhone + Safari，或安卓 + Chrome。安卓版还没在真手机上测过；其他浏览器没有专门测过 |

## 安装

1. 电脑上装好 Tailscale（登录你的账号）、Python 3.12（安装第一页勾上 Add python.exe to PATH）和 Git。
2. 下载代码：

   ```
   git clone https://github.com/Zeng-HY/Agent_24-7.git
   ```

3. 双击 `安装.cmd`。它会依次：建 Python 环境并安装依赖（装不上会自动换国内镜像）→ 问这台电脑在手机上叫什么 → 生成本机口令 → 把网页放到 Tailscale 的 https 地址上 → 设成登录 Windows 后自动启动 → 启动服务 → 在浏览器里打开一张二维码页。
4. 手机上装 Tailscale App，登录同一个账号并连上，再扫电脑上的二维码打开网页：
   - iPhone：用相机扫，在 Safari 里打开。
   - 安卓：Tailscale 可以从 Google Play 装；手机上没有 Google Play 的，到 [Tailscale 的下载页](https://pkgs.tailscale.com/stable/#android) 下载安卓安装包（要 Android 8 或更新）。用相机或「扫一扫」扫码，在 Chrome 里打开；手机自动用别的浏览器打开时，把网址复制到 Chrome 里。
5. 想放到主屏幕：
   - iPhone：点分享 →「添加到主屏幕」。建议关掉「作为网页 App 打开」，否则用第三方键盘语音输入时，跳回来可能黑屏。
   - 安卓：在 Chrome 里点右上角 ⋮ →「添加到主屏幕」（有的版本叫「安装应用」）。国产手机上点了没反应的，到手机设置里给 Chrome 打开「桌面快捷方式」权限。

以后想再看二维码，双击 `手机链接.cmd`。更新到新版，双击 `更新.cmd`：它会先 `git pull`，再重新安装依赖并重启服务。

### Tailscale 的几个建议设置

- 在 Tailscale 后台给这台电脑关掉 Key expiry，免得密钥过期后掉线。
- 在 Windows 托盘菜单里勾上 Run unattended，这样不开 Tailscale 窗口也能保持连接。
- 手机和电脑打不通直连时，Tailscale 会走中转服务器，每次操作要慢半秒以上。用 `tailscale status` 能看出走的是直连还是中转（relay）。

### 做完推送（可选）

在网页的「设置 → 手机通知」里打开，iPhone 和安卓各用各的：

- **iPhone**：装 Bark，在它首页复制 `https://api.day.app/` 开头的地址，贴到设置里，点「保存并试推一条」。
- **安卓**：装 ntfy App（Google Play、F-Droid 都有，也可以从 [ntfy 的 GitHub 发布页](https://github.com/binwiederhier/ntfy-android/releases) 下载 `fdroid-release.apk`）。在 ntfy 里点 ＋ 订阅主题：主题名称填 `agent-remote`，勾上「使用其他服务器」，地址填你打开网页的那个 https 地址（设置里都写着，点一下就能复制）。再回到网页的设置里点「打开并试推一条」。
  - 推送由本服务自己发出，经 Tailscale 到手机，所以手机上的 Tailscale 要一直连着，ntfy 也要能在后台运行：它提示关掉电量优化时照着关，国产手机还要像 Tailscale 一样允许后台运行。
  - ntfy 会一直挂着一条「正在监听通知」的通知，这是它在保持连接，正常。
  - 手机没连着时做完的对话，连上后会补推（12 小时内的；电脑上的服务重启过就没有了）。

## 配置

配置文件是程序目录下的 `remote_config.json`，安装时自动生成，只在本机，不进 git：

| 键 | 作用 | 默认 |
|---|---|---|
| `name` | 手机上显示的电脑名 | 安装时填写 |
| `port` | 本机监听端口 | `8765` |
| `bind` | 监听地址；不是 `127.0.0.1` 时只认口令 | `127.0.0.1` |
| `token` | 本机口令，不经 Tailscale 打开时用 | 自动生成 |
| `allowed_logins` | 额外放行的 Tailscale 账号，例如 `["someone@example.com"]` | `[]` |
| `roots` | 手机上能打开的文件所在的文件夹（对话自己的工作文件夹总是可以） | 下载文件夹 |
| `phone_files` | 从手机传上来的文件存在哪个文件夹（下面按日期分） | 下载\手机传来的文件 |
| `apps` | 手动指定有哪些桌面版，例如 `["codex"]` | 自动识别（每次打开页面重新检查） |
| `voice` | 设成 `false` 关闭语音；没有语音模型时安装会自动关掉 | 自动 |
| `bark` | iPhone 的 Bark 推送地址，在网页的设置里填写 | 无 |
| `ntfy` | `true`：安卓手机的 ntfy App 收推送，在网页的设置里打开 | 无 |

改完要重启服务：重新运行一次 `安装.cmd` 就会重启。

## 常见问题

**手机打开后显示「只让它自己登录的 Tailscale 账号用」**
手机和电脑登录的不是同一个 Tailscale 账号。换成同一个账号；或者把页面上显示的那个账号写进 `allowed_logins`，再重启服务。

**页面打不开**
先确认手机上 Tailscale 是连着的；再在电脑上运行 `tailscale serve status`，看网页是不是放在了 https 地址上。

**安卓手机上 Tailscale 连着，页面却打不开**
看看手机设置里的「私人 DNS」（在设置里搜「DNS」就能找到）。如果填了某个服务商的地址，手机会绕过 Tailscale 去查网址，`.ts.net` 结尾的地址就查不到。改成「自动」或「关闭」。

**安卓手机锁屏一阵后，页面打不开了**
国产安卓系统常在锁屏后停掉后台的 App，Tailscale 一停，手机就连不上电脑。到手机设置里找到 Tailscale，允许它在后台运行（各家叫法不同，比如「自启动」「允许后台活动」），再在耗电或省电设置里把它改成「无限制」。

**安卓手机收不到推送**
先看网页的「设置 → 手机通知」里是不是写着「手机连着」。没连着的话：看手机上的 Tailscale 连着没有（安卓上同一时间只能开一个 VPN 类的软件，开了别的代理软件，Tailscale 就会断开）；ntfy 和 Tailscale 有没有被省电设置停掉；ntfy 里订阅的地址是不是和打开网页的地址一样。

**页面上没有某个软件**
说明这台电脑上没认出它。装好后刷新页面即可。DeepSeek Harness 要装桌面版，只装了命令行版不算。也可以在 `remote_config.json` 里用 `apps` 手动指定。

**发给 Claude 的消息没反应**
Claude 是通过操作桌面窗口来发送的，所以电脑要登录着、屏幕不能锁。

**左滑归档时说「电脑上的 Codex 正开着这个对话」**
电脑上的 Codex 打开过的对话，它会占着这段记录几分钟，这期间从外面归档不了。过几分钟再滑一次，或者直接在电脑上归档。正在运行的对话也不能归档，先停止这一轮。

**附的文件，AI 先问能不能读**
附文件时消息里写的是文件在电脑上的位置。文件不在对话的工作文件夹里时，Claude 在手动批准模式下、DeepSeek 在「仅可查看」等权限下可能先问一次，在手机上点允许就行。

**从手机传上来的文件在哪**
在电脑的「下载\手机传来的文件」里，按日期分文件夹（`phone_files` 可以改位置）。选了又去掉、或者一周都没发出去的会自动删掉；跟着消息发出去的会一直留着。

**微信里的文件选不到**
iPhone 上微信收到的文件不在「文件」App 里。先在微信里打开文件，点右上角「…」→「用其他应用打开」→「存储到文件」，再从遥控页里选。

**没有话筒按钮**
语音输入需要本地语音模型，没装模型时会自动关闭。

**操作很慢**
多半是 Tailscale 在走中转，见上面的 Tailscale 建议设置。

## 开发

运行测试：

```
.venv\Scripts\python.exe -m unittest discover -s tests
```

页面检查（`tests/*_check.py`）会用真实的 `remote.html` 加假接口，在无头浏览器里跑，需要先装 `requirements-dev.txt`（Playwright）。

主要文件：

| 文件 | 内容 |
|---|---|
| `remote.py` | 服务入口：接口、放行规则、配置 |
| `remote.html`、`static/` | 手机网页 |
| `chats.py`、`chat_history.py`、`chat_projects.py` | 读对话列表和记录，按项目分组 |
| `pc_files.py`、`composer_references.py` | 附文件：列电脑上的文件夹、收手机传来的文件；把文件位置和引用写进消息 |
| `archives.py` | 左滑归档：Codex、DeepSeek 和 Claude 的归档、恢复，Codex 已归档对话的删除 |
| `claude_archive.py` | Claude 按会话 ID 搜索定位、原生归档和恢复、索引回读确认 |
| `codex_control.py`、`new_conversations.py` | Codex：本机通道、新建对话 |
| `claude_control.py` | Claude：桌面窗口里的菜单、提问和设置 |
| `deepseek_control.py`、`deepseek_stream.py` | DeepSeek Harness：本机接口、实时事件 |
| `machines.py` | Tailscale 状态、本机账号、其他电脑 |
| `setup_machine.py`、`安装.cmd` | 一键安装 |
| `notify.py` | 做完推送：找出刚做完的对话，发给 Bark 和 ntfy |
| `ntfy_feed.py` | 安卓的 ntfy App 从本服务订阅推送（按 ntfy 服务器的方式回应） |
| `voice.py`、`voice_local.py`、`voice_terms.py` | 语音输入（可选） |

## 限制

- 只支持 Windows 电脑。
- 依赖各家桌面版的本机通道和界面结构，桌面版大改之后可能要跟着更新。
- 语音模型需要自己准备，目前没有一键下载。

## 许可证

[MIT](LICENSE)
