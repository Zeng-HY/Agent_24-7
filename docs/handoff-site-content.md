# 网站内容丰富方案：pocketagentdesk.com

记于 2026-10-31。用户觉得网站内容太单薄，要求写一份细致的改版方案，交给 DeepSeek Harness 实施。这份文档既是方案，也是交接说明：DeepSeek 照它做，做完的人把结果补在第 15 节。

一句话目标：把现在只有一屏的首页，做成一个让陌生人一分钟内看懂遥应、敢装、知道怎么开始的个人项目网站；守住个人备案的边界；**等公安联网备案批下来再上线**。

---

## 1. 现在的网站（2026-10-31）

| 文件 | 内容 |
|---|---|
| `deploy/site/index.html` | 首页，约 2 KB：标题、一句介绍、三张文字卡片（看进度、随手回复、只连你自己的电脑）、三步开始、两个按钮（GitHub 下载页、网页版登录）、「iPhone 版即将上架 App Store」、页脚 |
| `deploy/site/support.html` | 帮助与联系，中文在上、英文在下（`#en`） |
| `deploy/site/privacy.html` | 隐私政策，中英两段，App Store 已经填了这个网址 |
| `deploy/site/site.css` | 和账号页 `relay_account.css` 同一套样式，浅色、深色跟系统，最大宽度 720px |
| 图标 | 打包时从 `static/` 带上：`favicon.svg`、`favicon-dark.svg`、`apple-touch-icon.png` |

服务器上：网站在 `/var/www/pocketagentdesk`，是 `deploy/relay/switch-domain.py` 一次性装上去的。Caddy 直接给静态文件，配置要点（`switch-domain.py` 第 69–78 行）：

- `try_files {path} {path}.html`：所以新建 `download.html`，网址就是 `/download`；新建 `en.html`，网址就是 `/en`。**不用改 Caddy。**
- 内容安全策略：`default-src 'self'; style-src 'self'; img-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'`。这意味着：
  - 不能写 `<style>` 块，也不能写 `style="…"` 属性，样式全部放在 `.css` 文件里；
  - 不能写内联 `<script>`，要脚本只能放本站的 `.js` 文件；
  - 图片只能是本站的文件，`data:` 图片和外站图片都显示不出来；
  - 直接写在 HTML 里的 `<svg>` 图形可以用（它不是图片请求）。
- `update-027.sh` 不更新网站，以后也不能再运行 `switch-domain.py`。所以上线要新做一个只更新网站的步骤（第 11 节）。

现在的问题：
1. 只有字，没有一张图，看不出 App 长什么样。
2. 没说支持哪几个 AI 助手、要什么系统。
3. 下载只有 GitHub 发布页，国内很多人打不开，也没说 Windows 会弹安全提示。
4. 没有常见问题。
5. 没有英文首页。App Store 海外区的「营销网址」就是这个首页。
6. 页面上没有备案时的网站名称「口袋工作台」。

## 2. 硬性边界（违反任何一条都不交付）

### 2.1 备案

- 个人 ICP 备案：粤ICP备2026170106号，**备案的网站名称是「口袋工作台」**。内容要保持个人、非商业：
  - 不写价格、付费、会员、试用期、赞助、打赏、收款码；
  - 不写「公司」「官方」「团队」「企业版」「旗舰」这类字样；
  - 不放广告，不接第三方统计。
- 公安联网备案 10-31 已提交，正在审核。表单里填的是：互联网交互服务「否」，网站类型「计算机应用类G」，语种中文简体和英语，无危险物品，无前置许可。所以：
  - 不加评论、留言板、论坛、反馈表单、投稿、在线客服、任何让访客提交内容的输入框。联系只用邮箱链接 `mailto:`；
  - 网站和 App 都不提供 AI 服务本身，文字里要说清楚这一点（第 4.3 节有原句）。
- 页脚保留 ICP 备案号和 `https://beian.miit.gov.cn/` 链接（新窗口打开）。页头或页脚要写出「口袋工作台」。
- 公安备案号批下来以后（形如「粤公网安备 44xxxxxxxxxxxx号」），按第 11.4 节加到页脚。没有号之前不放占位文字。

### 2.2 敏感说法

- 不出现「翻墙」「科学上网」「VPN」「代理」「梯子」这类词，也不教人怎么访问境外服务。
- 提到 Codex、Claude Code、DeepSeek 只写名字，不放它们的 logo，不链接到它们的网站，并写明遥应和它们没有关系（第 4.3 节）。
- 不写「最好」「第一」「唯一」这类绝对化用语。

### 2.3 网址

- `/`、`/privacy`、`/support` 三个网址不能变：App Store Connect 已经填了 `/privacy` 和 `/support`。
- `support.html`、`privacy.html` 里的 `#en` 锚点保留，别处有链接指向它。
- 只新增页面（`/download`、`/en`），不改旧地址，不加跳转。

### 2.4 隐私政策的内容不动

`privacy.html` 是法律文本，App Store 审核会看。这次只能换成新版式，**文字一个字都不改**。新首页里关于数据的说法必须和它一致；发现不一致，改首页，不改隐私政策；拿不准就停下来问用户。隐私政策的要点（照原文）：

- 对话内容只在你的手机和你自己的电脑之间传送，中转服务器（阿里云，中国广州）只负责转发，不保存；
- 传输全程 HTTPS 加密，**但不是端到端加密**：内容在中转服务器上解密后再转发；
- 服务器上存的是账号、邮箱、密码摘要、登录状态、绑定的电脑、流量统计、通知标识，以及进行中对话的标题和状态（停止更新一天后删除）；
- 不出售信息，不做广告追踪，不用第三方统计；
- 面向成年人，不满 14 周岁请不要注册；
- 运营者曾环宇，联系邮箱 390116927@qq.com。

### 2.5 截图

- 只用演示数据的截图（App 的自动截图用的是本地示例数据）。
- 每一张都要人工看一遍：不能出现真实的对话内容、客户或同事的名字、真实电脑名、邮箱、文件路径、手机号。看到可疑的，换一张或不用。
- 不放苹果的手机外壳图片。手机外框用 CSS 画一个圆角框。

### 2.6 技术

- 纯静态 HTML 和 CSS。能不用 JavaScript 就不用；真要用（比如截图左右滑动），放本站的 `.js` 文件，关掉 JavaScript 时页面照样能看。
- 不引外部字体、CDN、统计、视频、iframe。字体用系统字体（现在 `site.css` 里那串）。
- 浅色、深色都要好看（跟系统 `prefers-color-scheme`）。
- 手机 360px 宽到电脑 1440px 宽都不出现横向滚动条。
- 正文对比度至少 4.5:1；键盘能走到每个链接，焦点看得见；`prefers-reduced-motion` 时不做动画。
- 首页第一次打开的总大小不超过 1 MB；单张图不超过 200 KB。

## 3. 网站结构

| 网址 | 文件 | 说明 |
|---|---|---|
| `/` | `index.html` | 中文首页，重做（第 4 节） |
| `/en` | `en.html` | 英文首页，和中文首页一一对应（第 7 节） |
| `/download` | `download.html` | 下载页，新增，中英两段（第 5 节） |
| `/support` | `support.html` | 帮助页，扩充，中英两段（第 6 节） |
| `/privacy` | `privacy.html` | 隐私政策，只换版式（第 2.4 节） |
| — | `site.css` | 全站样式，扩充 |
| — | `img/` | 截图（第 9 节） |
| — | `robots.txt`、`sitemap.xml` | 可选，见第 10.4 节 |

每页的页头都一样：左边品牌（图标 + 遥应 Teleply），右边导航「功能 · 下载 · 帮助 · English」（英文页是「Features · Download · Help · 中文」）。手机上导航排成一行，放不下时可以横向滑动；不做汉堡菜单（避免要用 JavaScript）。

每页的页脚都一样，见第 4.10 节。

## 4. 中文首页逐段内容

下面的文案是草稿，可以在不改意思的前提下顺一顺。写法要求：一句话说一件事；用口语词；不用「赋能」「闭环」「一站式」「极致」这类词。

### 4.1 页头

品牌和导航，见第 3 节。

### 4.2 首屏

- 标题：**在手机上接着用电脑上的 AI 编程助手**
- 副标题：电脑上的 Codex、Claude Code 和 DeepSeek 做到了哪一步，手机上都看得到。它问你选哪个方案、要不要执行，你在手机上点一下就行。
- 主按钮：「下载电脑端」→ `/download`
- 次按钮：「看看怎么开始」→ `#start`
- 按钮下面一行小字：免费。电脑端支持 Windows，手机支持 iPhone 和安卓。
- 配图：一张手机截图（对话里回答提问的那张）。电脑宽度时文字在左、手机在右；手机宽度时手机图放在文字下面。

### 4.3 能连哪些 AI 助手

一行三个名字，每个配一句话：

- **Codex**：OpenAI 的 Codex 桌面版。
- **Claude Code**：Claude 桌面版里的 Code。
- **DeepSeek Harness**：DeepSeek 的桌面版。

下面一行小字（必须有）：

> 遥应不提供 AI 服务，和上面这些产品的公司也没有关系。它只在你的手机和你自己的电脑之间传话；电脑上装哪个助手、怎么用，由你自己决定，并遵守它们各自的条款。

### 4.4 能做什么

八张卡片。电脑宽度两列，手机宽度一列。每张：一个小图标（直接写在 HTML 里的 SVG，24×24，1.8 描边，圆线帽，和 App 一致）、一个短标题、两三句话。其中 4 张配截图，卡片和截图交错排（图左字右、图右字左），其余 4 张只有字。

1. **一眼看进度**（配图：对话列表）
   哪些对话在跑、哪个在等你、哪个已经做完，都在列表里。每个对话写着跑了多久、正在做什么：跑命令、改文件还是查资料。
2. **在手机上回答提问**（配图：批准或提问卡片）
   助手问你选哪个方案、要不要执行一条命令，卡片直接出现在对话里。点一下就答完，不用回到电脑前。
3. **随时发新指令**
   文字、照片、语音都能发。助手正在忙时，可以排在后面，也可以马上补充给它。
4. **灵动岛和锁屏**（配图：锁屏卡片）
   iPhone 的灵动岛和锁屏上，能看到几个对话在工作、哪个在等你。做完了会提醒你，不会每换一步就弹一次。
5. **看文件和改动**（配图：文件列表或 Word 文件）
   助手改了哪些文件、改了哪几行，手机上都看得到。Word、Excel、PDF 和网页也能直接打开。
6. **在手机上开新对话**
   选好电脑、项目和模型，写下第一句话，电脑上就开始干活。
7. **换模型和模式**
   模型、推理强度、计划模式，和电脑上一样能选。
8. **几台电脑都能连**
   一个账号目前最多绑 3 台电脑，在「我的电脑」里切换。

上线前核对（必须做）：每一条都要在**已经公开发布**的版本里有（Windows 公开版、安卓公开版；iPhone 以 App Store 上架的版本为准）。写的时候是 10-31：输入 `/` 调出命令、`/compact` 压缩上下文这些 0.6.6 的新功能还没公开发布，**先不写进去**；等它们随 Windows 正式发布后再加一句「输入 / 能调出常用命令，比如 /compact 压缩上下文」。

### 4.5 它是怎么连起来的

一张简图，用写在 HTML 里的 SVG 画：手机 ⇄ 中转服务器 ⇄ 你的电脑，三个圆角方块两条双向箭头，图下三句话：

- 你电脑上的遥应电脑端主动连到中转服务器，手机也连到这里，中转把两边的话传过去。不用在路由器上开端口，电脑和手机也不用在同一个网络。
- 对话内容只经过中转，不在服务器上保存。传输用 HTTPS 加密，但不是端到端加密：内容在中转服务器上解密后再转发。服务器上存了什么，见[隐私政策](/privacy)。
- 电脑要开着，遥应电脑端要在运行，手机才连得上它。

### 4.6 三步开始（锚点 `id="start"`）

三个带序号的步骤，电脑宽度横排，手机宽度竖排：

1. **在 Windows 电脑上装遥应电脑端**
   在[下载页](/download)下载安装包，双击安装。装好会自动打开一个小窗口。
2. **在手机上装遥应，注册并登录**
   用邮箱注册，把收到的验证码填进去就行。
3. **在电脑端点「绑定」**
   用同一个账号登录并确认。之后手机上的「我的电脑」里就有这台电脑了，点进去就能看到它上面的对话。

### 4.7 下载（摘要）

三个平台各一行，整行链接到 `/download`：

- **Windows 电脑端**：Windows 10 或 11（64 位）。
- **安卓**：Android 8.0 及以上。
- **iPhone**：iOS 26 及以上，正在准备上架 App Store。

### 4.8 常见问题（首页放 5 条，全部的在帮助页）

用 `<details>` 和 `<summary>` 做折叠（不用 JavaScript）：

1. **要钱吗？**
   不要。遥应是个人做的免费工具，没有付费功能，也没有广告。
2. **电脑要一直开着吗？**
   要。手机连的是你的电脑：电脑关机、睡眠或断网时，手机上会显示离线。
3. **支持 Mac 吗？**
   电脑端目前只有 Windows 版。
4. **我的对话安全吗？**
   对话内容只经过中转、不保存，传输用 HTTPS 加密，但不是端到端加密。中转服务器在阿里云广州。详见[隐私政策](/privacy)。
5. **收不到通知或灵动岛？**
   在遥应里打开 设置 → 手机通知，看通知和灵动岛是否开着；再到 iPhone 的 设置 → 遥应 → 通知，允许通知。

### 4.9 底部的行动按钮

一行大字「现在就试试」，下面两个按钮：「下载电脑端」→ `/download`，「网页版登录」→ `https://app.pocketagentdesk.com/account`。

### 4.10 页脚（全站一样）

```
口袋工作台 · 个人网站
隐私政策 · 帮助与联系 · English · 粤ICP备2026170106号 ·（公安备案号，批下来后加）
联系：390116927@qq.com
```

英文页的页脚：`Pocket Agent Desk (口袋工作台) · a personal site`，其余对应换成英文，备案号照写中文。

## 5. 下载页 `/download`

标题：下载遥应。中文在上，英文在下（`#en`），和帮助页一样的排法。

### 5.1 Windows 电脑端

- 系统要求：Windows 10 或 11，64 位。电脑上没有微软 WebView2 时，安装包会顺带装上。
- 下载：GitHub 发布页 `https://github.com/Zeng-HY/Agent_24-7/releases`，下载最新版里名为 `AgentRemote-版本号-Setup.exe` 的文件。
- 第一次运行时 Windows 可能提示「Windows 已保护你的电脑」：点「更多信息」，再点「仍要运行」。这是因为安装包没有花钱买微软的代码签名证书，不是病毒。
- 装好以后，电脑端会自己检查更新，新版本从阿里云下载，国内也快。
- GitHub 打不开：写信到 390116927@qq.com 要国内下载链接。

### 5.2 安卓

- 系统要求：Android 8.0 及以上。
- 下载：同一个 GitHub 发布页，文件名形如 `Teleply-版本号-编号.apk`。
- 安装时手机会问是否允许安装未知来源的应用，选允许。装好以后 App 会自己检查更新，新版本从阿里云下载。
- 还没上各家安卓应用商店。

### 5.3 iPhone

- 系统要求：iOS 26 及以上。
- 正在准备上架 App Store，上架后这里放下载链接。

### 5.4 不写死版本号

版本号会经常变，页面上**不写具体版本号**，只写「最新版」。第二期（第 13 节）再做固定的国内下载链接。

## 6. 帮助页 `/support`

保留现有各节和 `#en` 锚点，补成下面这些（中文和英文各一份，内容对应）：

1. 遥应是做什么的（现有）。
2. **怎样开始**：现有三步，每步配一张小截图（电脑端窗口那步可以不配图）。
3. **常见问题**：首页那 5 条，再加：
   - 列表里没有我想看的对话？遥应只列电脑上 Codex、Claude Code、DeepSeek 的对话；列表每 10 秒自己读一次，新开的对话一般十几秒内出现。（聊天列表没有下拉刷新，别写「下拉刷新」；「我的电脑」页才有。）
   - 一个账号能绑几台电脑？目前最多 3 台（服务器设置 `AR_DEVICE_LIMIT=3`）。「我的电脑」里能看到全部，点一台切换过去。
   - 换手机了怎么办？在新手机上登录同一个账号，电脑不用重新绑定。
4. **出了问题怎么办**：
   - 电脑显示离线（现有）；
   - 发出去的消息一直没反应：看电脑上那个 AI 助手是否开着、那段对话是否还在；
   - 收不到通知或灵动岛：同首页第 5 条；
   - Windows 提示「已保护你的电脑」：同下载页。
5. 忘记密码（现有）。
6. 删除账号（现有，文字不改）。
7. 联系我们（现有）。

上线前核对：帮助页里说到的每个按钮和菜单名，都要在 App 和电脑端里真的叫这个名字（比如「设置 → 手机通知」「我的电脑」「绑定」）。对不上就按 App 里的写。

## 7. 英文首页 `/en`

- 和中文首页一一对应，`<html lang="en">`。
- 中文页和英文页都写 `<link rel="alternate" hreflang="zh-CN" href="https://pocketagentdesk.com/">` 和 `<link rel="alternate" hreflang="en" href="https://pocketagentdesk.com/en">`。
- 下载、帮助、隐私链接到各自的 `#en` 段。
- 截图用英文版（第 9 节）。

英文文案草稿：

- Title: **Keep using your computer's AI coding assistants from your phone**
- Subtitle: See how far Codex, Claude Code and DeepSeek have got on your computer. When one asks which option to take or whether to run a command, tap your answer on the phone.
- Buttons: Download for Windows · How to start
- Small print: Free. The computer app runs on Windows; the phone app on iPhone and Android.
- Note under the assistants: Teleply does not provide any AI service and is not affiliated with the companies behind these products. It only passes messages between your phone and your own computer; which assistant you use, and how, is up to you, under its own terms.
- Features: See progress at a glance · Answer questions on your phone · Send new instructions any time · Dynamic Island and Lock Screen · Files and changes · Start a new conversation from your phone · Switch models and modes · Connect several computers（每条的说明照中文意思翻，句子短）。
- How it connects: The Teleply computer app connects out to our relay server, and so does your phone; the relay passes messages between them. No ports to open on your router, and the two don't need to be on the same network. Conversations pass through the relay and are not stored there. Traffic is encrypted with HTTPS, but not end to end: the relay decrypts it before passing it on. See the [privacy policy](/privacy#en) for what the server keeps. Your computer has to be on, with the Teleply computer app running.
- Start in three steps: Install the Teleply computer app on a Windows PC · Install Teleply on your phone, create an account and sign in · Click "Bind" in the computer app.
- FAQ: Is it free? Yes. Teleply is a free tool made by one person, with no paid features and no ads. · Does my computer have to stay on? Yes… · Is there a Mac version? Not yet; the computer app is Windows only. · Is my data safe? … · No notifications or Dynamic Island? In Teleply, open Settings → Phone Notifications…（菜单名以 App 英文界面为准）。

## 8. 设计

照 `docs/design-language.md`（第 2 节令牌、第 3 节按钮）。和现在 `site.css` 不一致的地方，以设计规范为准。

- **宽度**：首页内容最宽 1080px；下载、帮助、隐私这类文字页保持 720px，读起来不累。
- **字**：系统字体（现在 `site.css` 那串）。首页大标题电脑宽度 40–44px、手机 28–32px；小节标题 24px；正文 16px，行高 1.7–1.8；小字 13px。
- **颜色**：用 CSS 变量。浅色沿用现在的白底、浅灰面板；深色按规范：页面 `#000000`，面板 `#141414`，控件 `#1E1E1E`，分隔线 `#333333`，正文 `#EEEEEE`，次要 `#A8A8A8`，强调 `#8AB4FF`。
- **圆角**：卡片 16px，大面板 24px，按钮是胶囊（999px）。
- **按钮**：主操作实心胶囊，同一块区域最多一个；次操作浅底胶囊，不描边。高度至少 44px，最好 48px。按下缩到 0.97（约 100ms），减少动态效果时不缩。
- **间距**：4px 网格，常用 8、12、16、24px；小节之间 72–96px（手机 48–64px）。
- **手机截图的框**：CSS 画的圆角框，圆角约 36px，边框 8–10px，浅色模式用 `#111113`，深色模式用 `#333333`；图片 `width` 和 `height` 写死防跳动，`object-fit: cover`。
- **图标**：写在 HTML 里的 SVG，24×24 viewBox、1.8 描边、圆线帽圆转角，颜色跟文字（`currentColor`），不用 emoji。
- **深色截图**：灵动岛和锁屏有深色版截图的，用 `<picture>` 的 `media="(prefers-color-scheme: dark)"` 换深色图；其他截图深色模式下也用浅色图，加一圈分隔色描边就行。
- **动画**：最多做「滚到时淡入」，而且要用纯 CSS 写；`prefers-reduced-motion` 时完全不做。这一条可以不做。

## 9. 截图清单

截图来源（都是演示数据，仍要逐张人工检查）：

- 中文浅色：`F:\Android-Dev\work\ios-056-screens\shots\`（0.5.6 版，30 多张，文件名形如 `04-list-light-iOS26.5.png`）
- 英文和灵动岛：`F:\Android-Dev\work\20261029-island-064\shots-065\`（0.6.5 版，15 张）

| 用在哪 | 中文页 | 英文页 |
|---|---|---|
| 首屏 | `18-question-light-iOS26.5.png` | `08-chat-en-iOS26.5.png` |
| 一眼看进度 | `04-list-light-iOS26.5.png` | `27-running-list-en-iOS26.5.png` |
| 在手机上回答提问 | `20-approval-light-iOS26.5.png` | `27-running-chat-en-iOS26.5.png` |
| 灵动岛和锁屏 | `27-island-lock-light-light-iOS26.5.png`，深色用 `27-island-lock-dark-dark-iOS26.5.png` | `27-island-lock-light-en-iOS26.5.png`，深色用 `27-island-lock-dark-en-iOS26.5.png` |
| 看文件和改动 | `31-word-file-light-iOS26.5.png` 或 `16-files-light-iOS26.5.png` | 不配图 |
| 帮助页「怎样开始」 | `02-demo-login-light`、`03-devices-light` | `02-demo-login-en`、`03-devices-en` |

文件名后缀都是 `-iOS26.5.png`，表里有的省略了。先打开看一眼，觉得别的更合适可以换，但要在第 15 节写明换了哪张、为什么。

处理方法（在工作区里做，不要把原图放进仓库）：

1. 用 Python 的 Pillow（装在工作区的虚拟环境里）把图缩到宽 600px（首屏那张 720px），存成 WebP，质量 80 左右；每张控制在 200 KB 以内。
2. 不裁掉顶部状态栏（真实感）；如果状态栏上有真实信息（运营商、真实时间以外的东西），就裁掉。
3. 输出到仓库的 `deploy/site/img/`，名字用英文小写加短横：`zh-hero.webp`、`zh-list.webp`、`en-hero.webp`……
4. 每张图都写 `alt`（中文页写中文，英文页写英文）、`width`、`height`；首屏以外加 `loading="lazy"`。

0.5.6 的截图比现在的 App 旧一些（没有「正在思考」那行，灵动岛那几张除外）。要重新拍，用 `apps/ios/scripts/codemagic.ps1 -Mode shots`，这会花 Codemagic 的构建分钟，**先问用户**。

## 10. 其他细节

### 10.1 每页的 `<head>`

- `<title>`：首页「遥应 Teleply · 在手机上接着用电脑上的 AI 编程助手」，其余「下载 · 遥应 Teleply」这样。
- `<meta name="description">`：一句话，中文页中文、英文页英文。
- 分享卡片：`og:title`、`og:description`、`og:image`（用本站 `img/` 里的一张 1200×630 的图，用首屏截图加品牌名在工作区合成）、`og:url`。
- `<meta name="theme-color">` 浅色、深色各一个。
- 图标：现在那三个照旧。

### 10.2 链接

- 站内链接用 `/download` 这种不带 `.html` 的写法（Caddy 会对上）。
- 站外链接只允许这些：GitHub 发布页、`https://app.pocketagentdesk.com/account`、`https://beian.miit.gov.cn/`、公安备案查询页（批下来后）、`mailto:390116927@qq.com`。站外链接加 `rel="noopener"`；备案链接新窗口打开。

### 10.3 打印和无障碍

- 每页只有一个 `<h1>`，小节用 `<h2>`，层级不跳。
- 导航用 `<nav>`，主要内容用 `<main>`，页脚用 `<footer>`。
- 装饰用的 SVG 加 `aria-hidden="true"`。

### 10.4 robots.txt 和 sitemap.xml（可选）

- `robots.txt`：允许全部，写上 sitemap 的地址。
- `sitemap.xml`：列出 `/`、`/en`、`/download`、`/support`、`/privacy`。

## 11. 上线方式（这次只准备，不上线）

### 11.1 新增 `deploy/relay/update-site.sh`

只更新网站文件，不碰 Caddy，不动中转，不重启任何服务。要求：

1. 不是 root 就退出，提示「用 sudo 运行」。
2. 确认 `/var/www/pocketagentdesk` 存在，否则退出并说明。
3. 把旧网站整个复制到 `/var/www/pocketagentdesk-previous-<时间>`。
4. 把包里的 `site/` 复制过去：文件 `644`、目录 `755`，属主 root。包里没有的旧文件删掉（网站以包为准），但 `.well-known` 这类目录不碰。
5. 逐个检查 `/`、`/en`、`/download`、`/support`、`/privacy` 都返回 200。用 `curl --resolve pocketagentdesk.com:443:127.0.0.1 https://pocketagentdesk.com/…` 走本机的 Caddy，证书照常校验。
6. 有一个不是 200，就整个换回备份，并提示失败。
7. 成功时打印「网站已更新。旧文件在 …」。
8. 换行用 LF。参照 `deploy/relay/update-027.sh` 的写法和语气。

### 11.2 改 `deploy/relay/pack-027.py`

- `DEPLOY` 加上 `update-site.sh`。
- 现在 `SITE` 是写死的四个文件名。改成把 `deploy/site/` 下的文件（包括 `img/`）全部带上，放在包里的 `site/` 下；保留「页面里还有『待填』就拒绝打包」的检查。
- 包里的 `relay_push.py` 必须是 HEAD 那版：打包后用 `git show HEAD:relay_push.py` 换进去，再核对一次。不这样做，会把已经上线的灵动岛改动换回旧版。
- 改之前先告诉用户：`pack-027.py` 和 `deploy/site` 原本是另一个 Claude 会话（「域名备案后的应用部署」）在管，用户会转告它。

### 11.3 上线步骤（写给用户，等公安备案批下来、用户同意后再用）

在阿里云 Workbench 里：

1. 把 `D:\Personal\agent_remote\dist\agent-relay-0.27.0-dev.zip` 上传到 `/home/admin/`，覆盖旧的。
2. 运行：

```bash
python3 -m zipfile -e /home/admin/agent-relay-0.27.0-dev.zip /home/admin/agent-relay-027-new
```

```bash
sudo bash /home/admin/agent-relay-027-new/update-site.sh
```

3. 看到「网站已更新」就成了。不要运行 `switch-domain.py`，也不用运行 `update-027.sh`（这次只更新网站）。

### 11.4 公安备案号

批下来以后，用户会提供「粤公网安备 …号」和平台给的显示代码。做法：

- 公安平台给的警徽小图标，存成本站文件 `img/gongan.png`（内容安全策略不允许用外站图片）；
- 页脚加：图标 + 「粤公网安备 …号」，链接到公安平台给的查询地址（形如 `https://beian.mps.gov.cn/#/query/webSearch?code=…`），新窗口打开；
- 全站页脚都加，然后按 11.3 上线。按规定，批下来后 30 天内要挂上。

## 12. 工作顺序

1. **阶段一：页面和样式。** 按第 3–10 节做出全部页面，只在本地看。本地预览：在工作区里起一个静态服务器，比如 `python -m http.server`，把 `deploy/site` 当网站根目录；注意 `/download` 这种不带后缀的地址要另外处理（可以写一个几行的小服务器脚本，放在工作区，模拟 `try_files {path} {path}.html`）。
2. **给用户看。** 每页截四张图：手机宽度（390px）浅色、深色，电脑宽度（1280px）浅色、深色。用 Edge 或 Playwright 截都行，截图放工作区。把截图路径和一段说明发给用户，等用户点头。
3. **阶段二：提交。** 用户同意后，提交到 main 并推送（网站文件提交不用问用户）。只加你改的文件。
4. **阶段三：上线准备。** 做第 11.1、11.2 节，打包，核对包里的文件，写好第 11.3 节的步骤发给用户。**不上线**。
5. **阶段四（以后）：** 用户说公安备案批下来了，再做 11.4，然后请用户按 11.3 上线。

## 13. 第二期（这次不做，先记下）

- **国内固定下载链接**：在 `dl.pocketagentdesk.com`（绑到阿里云 OSS 以后）放「最新版」的固定文件名，下载页直接用。要改发布脚本 `deploy/updates/publish.py`，先问用户。
- **更新记录页** `/changelog`：从 `windows-release-notes.json` 和安卓、iPhone 的说明里整理，每版两三句大白话。
- **重新拍一套截图**：用最新的 App（0.7.0 以后），中英文、浅色深色各一套。
- **App Store 上架以后**：下载页和首页放 App Store 链接和苹果官方的下载徽章（徽章按苹果的使用规范，下载到本站）。
- **账号数量上限（提醒用户，不归网站做）**：中转服务器默认最多 20 个账号（`AR_ACCOUNT_LIMIT=20`，`relay_service.py`），满了以后新用户注册不了。网站改版或 App Store 上架、真有人来注册之前，要不要调大由用户决定，改的是服务器设置（见 `deploy/relay/README-027.md`「默认 AR_ACCOUNT_LIMIT」一段）。

## 14. 验收清单

交付前逐条核对，在第 15 节写结果：

- [ ] 第 2 节的边界全部守住：没有评论或表单、没有商业字样、没有敏感说法、没有第三方 logo；「口袋工作台」和 ICP 备案号在每页页脚。
- [ ] `/privacy` 文字和原来逐字一致（只换了版式）：去掉标签后和旧文件比对，没有差异。
- [ ] `/`、`/en`、`/download`、`/support`、`/privacy` 本地都能打开，所有站内链接和锚点都对。
- [ ] 全站搜一遍 `http://` 和 `https://`：只出现第 10.2 节允许的地址。
- [ ] 没有 `style="`、没有 `<style>`、没有内联 `<script>`、没有 `data:` 图片。
- [ ] 360px、390px、768px、1280px、1440px 宽度都没有横向滚动条；浅色、深色都看过。
- [ ] 首页第一次打开总大小不超过 1 MB；每张图不超过 200 KB；图片都有 `alt`、`width`、`height`。
- [ ] 每张截图都人工看过，没有真实信息。
- [ ] 第 4.4 节的每个功能都在已公开发布的版本里；帮助页的菜单名和 App 一致。
- [ ] 页面用 HTML 校验工具查过没有结构错误（比如工作区里用 `html5validator` 或 W3C 的 Nu checker 本地版）。
- [ ] 包里的 `relay_push.py` 和 `git show HEAD:relay_push.py` 一致；包里有 `update-site.sh` 和全部网站文件。

## 15. 结果记录

（实施的人在这里补：做了什么、截图在哪、哪些没做、用户确认了什么、提交编号。）
