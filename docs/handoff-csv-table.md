# 交接：安卓预览 CSV 时显示成表格（2026-11-16）

写给接手的 DeepSeek Harness 会话，由 Claude 监督。原因已经查清：你照第 3 节改安卓代码、补测试、本地提交，在第 9 节记结果。行号按 main 的 `0f333cf` 写，可能前后差几行。

---

## 0. 结论

用户转来安卓用户的投诉：在手机上预览一个 CSV 文件（`去重问题清单.csv`），看到的是一整段原文，又长又乱，希望像 Excel 那样显示成表格。

安卓应用里**已经有**表格显示页：`assets/office/sheet.html` + `sheet.js`，用 SheetJS 画 Excel 文件（1.0.5 起）。CSV 没用上它，因为电脑端把 1MB 以下的 CSV 标成 `kind: "text"`，手机只对 `kind: "download"` 的文件用表格页，所以小 CSV 走了原文显示（`CodePanel`）。

改法：手机认出 `.csv` 和 `.tsv`，不管电脑标的是 `text` 还是 `download`，都取文件本身，在手机上认出编码，交给表格页显示；表格页对 CSV 换一套适合长文字的样式；「…」菜单里能切回原文。只改安卓。

| 编号 | 现在 | 要改成 |
|---|---|---|
| 表-1 | 1MB 以下的 CSV 显示成原文 | 默认显示成表格 |
| 表-2 | TSV 不认 | 和 CSV 一样显示成表格 |
| 表-3 | 只认 UTF-8 / UTF-16；电脑上中文 Excel 存的 CSV 多是 GBK，文本预览直接报错 | 手机自己认编码：UTF-8、UTF-16、GB18030 |
| 表-4 | 表格页每格不换行（`white-space: nowrap`），长文字把一列拉得极宽 | CSV 的长格子限宽、在格子里换行，表头停在顶上 |
| 表-5 | 只有一种显示 | 「…」菜单里「查看原文 / 表格视图」来回切，原文可以复制 |

---

## 1. 用户看到的（安卓，文件页）

- 页面标题 `去重问题清单.csv`，下面是原文显示框，框头有「原始行」「复制」。
- 文件第一行是表头：`编号,问题,依据_影响_最小修改_分析确认_优先级_确定性`。
- 每一行：编号（`01`、`02`）、一个短标题、一个**用双引号包起来的很长的格子**，里面有好几段换行，每段是 Markdown 列表，比如 `- **位置/依据**：Methods P20允许…`，格子里还有逗号。
- 原文显示把这些全挤在一起，看不出哪一格是哪一格。

用户没有给原文件，**不要去电脑上找它**（可能是用户工作里的资料）。测试用你自己照上面的结构造的样例。

---

## 2. 现在的代码怎么走

**电脑端（只读，不改）**

- `chat_history.py` 约 338 行：对话里的成果文件，`.csv`、`.tsv` 等在 1MB 以内标 `kind: "text"`，更大的标 `download`。
- `remote.py` 860–866 行 `/api/file/text`：只认 UTF-16（有 BOM）和 UTF-8（可带 BOM），别的回错误「无法按 UTF-8 或 UTF-16 预览，请下载原文件」。所以 GBK 的 CSV 现在在手机上连原文都看不了。
- 文件本身由 `/api/file` 给（手机上是 `service.download(device, chat, id)`）。

**安卓**

- `WorkspaceController.kt` 675–702 行 `file()`：先取 `file/meta`。`kind == "text"` 时取 `file/text` 放进 `result`；`phone`（手机自己画）只在 `kind == "download"`、`phoneOffice(名字) != null`、大小不超过 `PreviewLimit`（20MB）时成立，这时下载文件本身放进 `preview`，`data` 里写 `"preview": "phone"`。
- `WorkspaceController.kt` 714–721 行 `officeFailed()`：表格页画不出来时，有电脑的 PDF 就转 PDF，没有就显示「手机上显示不了这个文件…」。
- `WorkspaceUi.kt` 约 410–470 行（文件页）：`preview == "phone"` 且有字节时用 `OfficePreview(...)` 占满；否则有文字时，Markdown 可切「阅读视图 / 查看源码」（`rendered`，菜单在约 433 行），其余用 `CodePanel(name, s.result, "复制文件内容")`。
- `PreviewUi.kt` 135–139 行 `phoneOffice()`：`csv` 已经算 `"sheet"`，`tsv` 不算。149–201 行 `OfficePreview()`：WebView 只从 `assets/office` 取页面，`/file` 给文件字节；深色时网址加 `?dark=1`；页面标题变成 `teleply:failed` 时调 `failed`。
- `assets/office/sheet.js`：`XLSX.read(new Uint8Array(data), { type: "array", cellDates: true })`，每个工作表一张 `sheet_to_html` 的表，最多 2000 行、100 列，超了给提示。
- `assets/office/office.css` 第 28–31 行：`#grid td { white-space: nowrap; }`。
- 已有测试：`app/src/test/.../WorkspaceControllerTest.kt`（`phoneOffice` 在约 173–175 行；Word / Excel 走手机显示、转 PDF、`officeFailed` 在约 110–170 行；`file/text` 出错在约 201 行）。

**iPhone（这次不改）**：`FilePages.swift` 246–275 行同样显示原文，但「…」菜单有「用快速查看打开」，系统会显示成表格。

---

## 3. 要做成什么样

### 3.1 哪些文件

名字以 `.csv` 或 `.tsv` 结尾（不分大小写）、大小不超过 `PreviewLimit` 的文件，不管电脑标 `text` 还是 `download`。Excel、Word 的走法一点都不变。超过 20MB 的照旧不显示（保存、用其他应用打开）。

### 3.2 取内容、认编码

- 取文件本身（`service.download`），**不要**再为这类文件取 `file/text`（它不认 GBK）。
- 在手机上认编码，写成一个小的 Kotlin 函数，配 JVM 测试：有 UTF-8 BOM → UTF-8；有 UTF-16 LE/BE BOM → UTF-16；整段是合法 UTF-8 → UTF-8；否则 → GB18030（包含 GBK，中文 Excel「CSV」默认存成它）。
- 认出来的文字放进 `result`，「查看原文」就显示它（复制也是它）。

### 3.3 表格页怎么读

- 把认好的文字交给表格页，不要让 SheetJS 自己猜编码。两种做法任选一种，在第 9 节写理由：交 UTF-8 加 BOM 的字节；或者网址上告诉页面这是 CSV/TSV，页面按 UTF-8 解成文字再 `XLSX.read(文字, { type: "string", ... })`。
- TSV 用 Tab 分列；CSV 用逗号。
- **照原样显示文字**：不把 `01` 变成 `1`，不把像日期的字变成日期（SheetJS 读纯文本时有 `raw: true` 一类的选项，查清楚 `lib/xlsx.full.min.js` 这一版怎么用）。
- 双引号里的逗号、换行留在同一格里（用户的文件就是这样）。

### 3.4 样子（只对 CSV/TSV；Excel 的样子不变）

- 第一行当表头，往下翻时停在顶上，底色和正文区分开。
- 长文字的格子：列宽有上限（大约 18–20 个字宽，你定），在格子里换行，格子里原有的换行保留；短格子不被撑宽。
- 左右滑动、双指缩放照旧能用；浅色、深色都要看得清。
- 页面要知道这是 CSV/TSV（比如网址加参数、`body` 加 class），只在这时用新样式。

### 3.5 原文还在

文件页「…」菜单加一行，和 Markdown 的写法一样：表格时显示「查看原文」，原文时显示「表格视图」。默认是表格。原文就是现在的 `CodePanel`，复制按钮照旧。

### 3.6 画不出来时

表格页标题变成 `teleply:failed` 时，CSV/TSV **不要**去要电脑的 PDF（没有），改成显示原文，上面一行小字说明「表格显示不了，下面是原文」。认编码本身失败（几乎不会）时，照现在的写法显示「手机上显示不了这个文件，可保存后使用系统应用打开。」。

### 3.7 很大的表

沿用 `sheet.js` 现有的上限（2000 行、100 列）和提示，不改数字。

---

## 4. 边界

- **只改**：`apps/android/app/src/main/java/com/pocketagentdesk/teleply/` 下的 `WorkspaceController.kt`、`WorkspaceUi.kt`、`PreviewUi.kt`（认编码的函数可以放这里，或者新建一个小文件）；`apps/android/app/src/main/assets/office/` 下的 `sheet.js`、`sheet.html`、`office.css`；`apps/android/app/src/test/` 下的测试；本文件第 9 节。
- **不要碰**：电脑端的任何 `.py`、iOS、网页（`remote.html`、`static/`）、`apps/android/app/build.gradle.kts`（不改版本号）、发版脚本、`apps/android/README.md`（发版时由 Claude 写）、`deploy/site/`、`pocketagentdesk.com.png`、`tests/test_activity_records.py`（都是别人的，没提交）。
- `assets/office/lib/` 里的 SheetJS、docx-preview、jszip 不换版本、不改内容。
- 不装软件、不下载浏览器、不启动或重启任何程序（包括 `G:\AgentRemote` 的遥应电脑端）。

---

## 5. 验证

### 5.1 JVM 测试（先在旧代码上跑，确认该失败的失败，原样输出存到工作区子文件夹）

1. 认编码：UTF-8 带 BOM、不带 BOM、UTF-16 LE 带 BOM、GBK 字节（比如「编号,问题」）都认对。
2. `phoneOffice("数据.tsv") == "sheet"`，`phoneOffice("数据.CSV") == "sheet"`。
3. `WorkspaceController`：一个 `kind: "text"` 的 CSV → 下载了文件本身、没调 `file/text`、`preview == "phone"`、`result` 是认好的文字；一个 GBK 的 CSV 同样能显示；CSV 的 `officeFailed()` → 显示原文，不去要 PDF。
4. Word、Excel、PDF、图片、Markdown 的已有测试照旧全过。

### 5.2 表格页读样例

在工作区子文件夹里照第 1 节的结构造样例：中文表头；`01`、`02` 编号；带逗号、带多段换行和 `**` 的长格子；一份 GBK 编码的；一份 TSV。先看 `node --version`：有 Node 就用仓库里的 `lib/xlsx.full.min.js` 和你定的读法读这些样例，把每格读出来的文字存到子文件夹，核对：编号还是 `01`、长格子没被拆开、中文没乱码、TSV 列对。没有 Node 就在第 9 节写明没核对，不要装。

### 5.3 构建

在 `apps/android` 运行 `./scripts/build.ps1`（开发版 APK、全部 JVM 测试、lint、设备测试 APK）。全部通过，记下测试数。

### 5.4 这台电脑做不了的

真手机上看（滑动、缩放、深色、表头停住）：打包后由 Claude 和用户做。

---

## 6. 发布（不是你的事）

本地提交以后停下。不打包、不改版本号、不 push、不发版。Claude 审完再问用户要不要发安卓 1.0.8（这也是第一次经阿里云推送安卓更新）。

---

## 9. 结果记录（接手的会话填）

### 9.1 改了哪些文件

### 9.2 新测试的名字，和在旧代码上的结果

### 9.3 全部测试（`build.ps1` 的结果）

### 9.4 样例读出来的样子（5.2）

### 9.5 选了哪种读法（3.3），为什么

### 9.6 没做的

### 9.7 提交
