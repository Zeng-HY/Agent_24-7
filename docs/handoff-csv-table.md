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

- 新增 `apps/android/app/src/main/java/com/pocketagentdesk/teleply/CsvText.kt`：`decodeCsvText(bytes)`，按 BOM 认 UTF-8 / UTF-16 LE / UTF-16 BE，整段合法 UTF-8 就是 UTF-8，否则按 GB18030（含 GBK）解；GB18030 也解不了时抛出，交给页面显示「手机上显示不了这个文件…」。
- `WorkspaceController.kt`：`file()` 先按文件名认出 `.csv` / `.tsv`（不分大小写），这类文件不管 `file/meta` 说 `text` 还是 `download`，都直接 `service.download` 文件本身，在手机上解码成文字放进 `result`，再把同一段文字按 UTF-8 放进 `preview`，`data` 里写 `"preview": "phone"` 和 `"sheet": "csv" / "tsv"`；不再为它们调 `file/text`，也不会去要电脑的 PDF。超过 `PreviewLimit` 的不下载、不显示。`officeFailed()` 对这类文件改成回到原文，并写「表格显示不了，下面是原文」，不再走 PDF。
- `WorkspaceUi.kt`：文件页认出 CSV / TSV，默认显示表格；「…」菜单多一行「查看原文 / 表格视图」；表格画不出来时在原文上方显示那行小字。原文仍是原来的 `CodePanel`，复制照旧。
- `PreviewUi.kt`：`phoneOffice()` 增加 `tsv`；新增 `sheetKind()`；`OfficePreview()` 的网址带上 `sheet=csv|tsv`，让表格页知道分隔符和新样式。
- `assets/office/sheet.js`：CSV / TSV 当 UTF-8 文字读（`TextDecoder`），用 `XLSX.read(text, { type: "string", raw: true, FS })`；第一行转成 `<thead><th>`，长格子包一层限宽盒子；Excel 的读法不变。
- `assets/office/office.css`：只对 `body.csv` 加表头吸顶、长格子限宽换行、浅色 / 深色表头底色。
- `WorkspaceControllerTest.kt`：扩展 `phoneOffice` 的断言，新增 3 项 CSV 测试；新增 `CsvTextTest.kt`（5 项）。

`sheet.html` 没改：网址参数和 `body` class 已经够用，不必再加标记。`assets/office/lib/` 没动。

### 9.2 新测试的名字，和在旧代码上的结果

新增 / 扩展的测试：

- `CsvTextTest`：`aUtf8FileWithoutAMarkIsReadAsUtf8`、`aUtf8FileWithAMarkIsReadAsUtf8WithoutTheMark`、`aUtf16FileWithAMarkIsReadAsUtf16`、`aGbkFileIsReadAsGb18030`、`anEmptyFileIsEmptyText`。
- `WorkspaceControllerTest`：`csvShowsAsATableFromTheFileItselfWhicheverKindTheComputerGives`、`aGbkCsvIsReadOnThePhone`、`aCsvTheTableCannotDrawFallsBackToTheSourceNotToTheComputersPdf`；并把 `wordAndExcelAreTheFilesThePhoneDraws` 补上 `数据.tsv`、`数据.TSV`、`数据.CSV`。

旧代码上的结果（原始输出在 `F:\Android-Dev\work\20261101-island-duplicates\20261116-csv-table\`）：

- `old-code-workspace-tests.log`：`WorkspaceControllerTest` 29 项，**4 项失败**（`wordAndExcelAreTheFilesThePhoneDraws` 的 TSV 断言、CSV 表格测试、GBK 测试、`officeFailed` 不回 PDF 的测试）。正是旧代码只把 CSV 当 `download`、把 TSV 当普通文件、不认 GBK、失败时要 PDF 的地方。
- `old-code-encoding-tests.log`：`CsvTextTest` 在旧代码上**编译失败**，5 处 `Unresolved reference 'decodeCsvText'`。旧代码没有这个函数，这是预期的失败形式。

新代码上：`WorkspaceControllerTest` 29 项、`CsvTextTest` 5 项全部通过。

### 9.3 全部测试（`build.ps1` 的结果）

在 `apps/android` 跑 `.\scripts\build.ps1`（默认 `assembleDebug`、`testDebugUnitTest`、`lintDebug`、`assembleDebugAndroidTest`）**全部通过**：

- JVM 测试 **226 项，0 失败、0 跳过**（从 `app/build/test-results/testDebugUnitTest/*.xml` 统计；原来 218 项，本次加 8 项）。
- lint 通过；开发版 APK 和设备测试 APK 都编译通过（没有安装、没有在设备上跑）。
- 日志：`build-full-2.log`；测试结果在 `app/build/test-results/testDebugUnitTest/`。

### 9.4 样例读出来的样子（5.2）

工作区里有照第 1 节结构造的 `sample-utf8.csv`、`sample-gbk.csv`、`sample-utf8.tsv`；Node（v24.14.0）用仓库里的 `lib/xlsx.full.min.js`（版本 0.20.3）按页面同样的读法解析，原始输出在 `sample-check.log`，每格内容在 `sample-*.cells.json`。核对结果：

- 编号仍是 `"01"`、`"02"`，没有变成数字 `1`、`2`。
- 长格子仍是三段，里面的 `- **位置/依据**：…`、中文逗号和多段换行都留在同一格，没有被逗号拆开。
- 引号后的 `高` / `已确认` / `中` / `待确认` 没有错位；中文表头没有乱码。
- GBK 文件按 GB18030 读出来和 UTF-8 文件逐字相同。
- TSV 表头 3 列、第一行 4 列、第二行 5 列，Tab 分列正确，长格子没被 Tab 拆开。

`node --check sheet.js` 也通过。表头吸顶、限宽换行、深色、左右滑动和缩放属于画面效果，本机没有浏览器 / DOM，没在真机或 WebView 里看过，留给 Claude 和用户按 5.4 验。

### 9.5 选了哪种读法（3.3），为什么

选了第 2 种：**网址上告诉页面这是 CSV / TSV，页面按 UTF-8 解成文字再 `XLSX.read(text, { type: "string", raw: true, FS })`**。

- 手机反正要解一次编码才能把文字放进 `result` 给「查看原文」，所以直接把解好的文字再按 UTF-8 交给页面，页面不必猜字符集；GBK 的字节不会再被 SheetJS 当别的编码读。
- 网址上的 `sheet=csv|tsv` 同时决定分隔符（逗号 / Tab）和 `body.csv` 样式；`sheet.html` 不用改。
- `raw: true` 是这一版 SheetJS（0.20.3）保留原文的选项：样例里 `01` 仍是字符串，像日期的字也不会变成日期；`FS` 指定分隔符。已用样例核对（见 9.4）。
- 没有选「交 UTF-8 加 BOM 的字节」：页面仍要判断这是 CSV 还是 TSV，BOM 只解决编码、不解决分隔符；而且 `type: "array"` 让 SheetJS 自己认格式，不如明确 `type: "string"` 可控。

### 9.6 没做的

- 没在真手机 / WebView 里看表头吸顶、长格子换行、左右滑动、双指缩放、深色；本机没有浏览器和 DOM，只核对了 SheetJS 解析和 `sheet.js` 语法。按 5.4 由 Claude 和用户验。
- 没测试真正超过 20MB 的 CSV；代码沿用原来的 `PreviewLimit` 判断，超过就不下载、不显示，但没有造 20MB 样例跑一遍。
- 没改 `sheet.html`、Excel 的读法、`assets/office/lib/`、2000 行 / 100 列的上限。
- 没去电脑上找用户的 `去重问题清单.csv`，样例是自己造的。
- 没打包 release、没改版本号、没 push、没发版；没动电脑端、iOS、网页、发版脚本、`deploy/site/`、`pocketagentdesk.com.png`、`tests/test_activity_records.py`。

### 9.7 提交

本地提交，没有 push。代码和测试的提交：

- `安卓：CSV 和 TSV 在手机上显示成表格（手机认编码，表格页换长文字样式，可切回原文）`：`5c5fbba`（8 个文件：新增 `CsvText.kt`、`CsvTextTest.kt`，改 `WorkspaceController.kt`、`WorkspaceUi.kt`、`PreviewUi.kt`、`sheet.js`、`office.css`、`WorkspaceControllerTest.kt`）。
- 本节随后单独提交，只改本文件。
