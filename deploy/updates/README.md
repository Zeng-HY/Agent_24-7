# 更新放在阿里云

从电脑端 0.27.0-dev.25 和安卓 1.0.3 起（两个都在 2026-10-27 发布），两个应用先到阿里云看有没有新版本，阿里云连不上或者核对不过，再去 GitHub 看。国内连不上 GitHub 的人，靠阿里云也能收到更新。iOS 走 TestFlight，跟这里无关。

## 放在哪

阿里云对象存储（OSS）里的存储空间 `teleply-updates`，地域华南3（广州），读写权限「公共读」：

| 位置 | 内容 |
|---|---|
| `windows/dev/windows-update.json` 和 `.sig` | 测试版电脑端看的清单：最新的一个版本，测试版正式版都算 |
| `windows/stable/windows-update.json` 和 `.sig` | 正式版电脑端看的清单：最新的正式版（发过正式版才有） |
| `windows/AgentRemote-<版本>-Setup.exe` | 每个版本的安装包，传上去就不再改 |
| `android/android-update.json` 和 `.sig` | 安卓的清单（域名绑好以后才传） |
| `android/Teleply-<版本>-<版本号>.apk` | 安卓安装包（同上） |

网址是 `https://teleply-updates.oss-cn-guangzhou.aliyuncs.com/` 加上面的位置。阿里云不让用这个自带网址下载 APK（会报 `ApkDownloadForbidden`），所以安卓要等 `pocketagentdesk.com` 备案下来、`dl.pocketagentdesk.com` 绑到这个存储空间以后，才从阿里云下载。在那之前，安卓更新照旧只走 GitHub。

## 为什么换不了安装包

清单里写着版本、文件名、大小、SHA-256 指纹（按文件内容算出的一串字符，改一个字节就对不上）和下载地址。清单旁边的 `.sig` 是签名，用的私钥只在发版的电脑上（`%USERPROFILE%\.teleply-updates\update-signing-key.pem`），两个应用里只写公钥（`relay_updates.py` 的 `KEY`，`Updates.kt` 的 `Key`）。

应用先核对签名，对了才读清单；下载完再核对大小和指纹；安卓还核对 APK 是不是遥应自己的钥匙签的。所以拿到阿里云上传权限的人、攻进服务器的人，都换不了安装包，最多让更新暂时下不了。GitHub 上的发布也带同一份清单和签名，应用从 GitHub 读到的也要核对签名。

## 第一次要做的

2026-10-27 已经做完：存储空间 `teleply-updates`（公共读）、只能上传的用户 `teleply-release-upload` 和它的策略 `teleply-updates-upload`，AccessKey 也填好了。下面的步骤留着，换账号或重建时照着做。

在阿里云控制台（这些只能你自己做）：

1. **建存储空间。** 对象存储 OSS → Bucket 列表 → 创建 Bucket。名称 `teleply-updates`，地域「华南3（广州）」，存储类型「标准存储」，其余保持默认。创建页上「阻止公共访问」开着、关不掉，读写权限只能选「私有」，就先按私有建。建好以后进这个存储空间 → 权限控制：先把「阻止公共访问」关掉，再把「读写权限」改成「公共读」。
2. **建一个只能上传的用户。** RAM 访问控制 → 用户 → 创建用户。名字随意，比如 `teleply-release-upload`；访问方式只勾「使用永久 AccessKey 访问」（程序调用），不勾控制台登录。创建后页面会显示 AccessKey ID 和 AccessKey Secret，Secret 只显示这一次。
3. **给它最小的权限。** RAM 访问控制 → 权限策略 → 创建权限策略 → 脚本编辑，贴进下面这段，名字比如 `teleply-updates-upload`。再到刚建的用户 → 新增授权，选这条策略。它只能在 `windows/` 和 `android/` 里上传和查看文件，删不了，也碰不到别的资源。

```json
{
  "Version": "1",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["oss:PutObject", "oss:GetObject"],
      "Resource": [
        "acs:oss:*:*:teleply-updates/windows/*",
        "acs:oss:*:*:teleply-updates/android/*"
      ]
    }
  ]
}
```

4. **填 AccessKey。** 用记事本打开 `C:\Users\39011\.teleply-updates\oss-upload-key.json`，把 ID 和 Secret 分别填进两对引号里，保存。不要发到聊天、命令行或仓库里。
5. **可选：设费用提醒。** 费用中心里设一个每月提醒。存储每月几分钱；下载流量约 0.5 元/GB，一次电脑端更新 26 MB，100 人次约 1.3 元。

在发版的电脑上：

- 签名钥匙已经生成在 `C:\Users\39011\.teleply-updates\`（2026-10-27）。把整个文件夹另外拷一份到 U 盘这类不联网的地方。丢了，以后的更新所有应用都不认，只能每个人手动重装一次；不要再运行 `new-key`，它也会拒绝覆盖。换电脑时把这个文件夹拷回去。
- 发版脚本要用装了 cryptography 的 Python（只给这个脚本用，应用不用）。在仓库目录：

```bash
python -m venv .toolchain\release-venv
```

```bash
.toolchain\release-venv\Scripts\python.exe -m pip install -r requirements-release.txt
```

## 每次发版

**电脑端**

1. 照旧改 `windows-version.json`、写 `windows-release-notes.json`，运行 `deploy/windows/build.ps1`。现在打出的 `dist/windows-update.json` 多了 `product`、`channel` 和下载地址 `urls`（阿里云在前，GitHub 在后）。
2. 运行：

```bash
.toolchain\release-venv\Scripts\python.exe deploy\updates\publish.py windows
```

它核对清单和安装包对得上，签名，然后按这个顺序上传：安装包，签名，清单。最后像应用那样从阿里云取回来核对一遍，打印阿里云的直接下载地址。阿里云上已经有更新的版本时，它不覆盖。

3. 在 GitHub 建 Release `windows-v<版本>`（测试版勾 Pre-release），附上脚本最后列出的三个文件：安装包、`windows-update.json`、`windows-update.json.sig`。旧版本只认 GitHub，所以这一步不能省；新版本在阿里云连不上时也会来这里，没有 `.sig` 的发布它不认。

**安卓**

1. 照旧改版本号，运行 `apps/android/scripts/release.ps1`，得到 `apps/android/build/Teleply-<版本>-<版本号>.apk`。
2. 把更新说明写进一个文本文件（UTF-8，和 GitHub Release 的说明用同一份，手机上显示前 500 字），然后运行：

```bash
.toolchain\release-venv\Scripts\python.exe deploy\updates\publish.py android apps\android\build\Teleply-1.0.3-14.apk --notes-file 说明.txt
```

3. 在 GitHub 建 Release `android-v<版本>`，附上 APK、`android-update.json`、`android-update.json.sig` 三个文件。

域名绑好之前，脚本只签名、只准备 GitHub 的文件，不传阿里云。

只想签名、不上传（比如阿里云还没准备好）：在命令后面加 `--sign-only`。

## 备案下来以后（安卓也走阿里云）

1. 对象存储 OSS → `teleply-updates` → 域名管理 → 绑定域名 `dl.pocketagentdesk.com`，按提示在云解析里加 CNAME 记录，再配上 HTTPS 证书（阿里云的免费证书就行）。
2. 把 `deploy/updates/publish.py` 里的 `ANDROID_FROM_ALIYUN` 改成 `True`，提交。
3. 用当前最新的 APK 再运行一次上面的安卓发版命令。脚本会把 APK 和清单传上去，并从 `dl.pocketagentdesk.com` 取回 APK 核对。装着 1.0.3 及以后版本的手机，从这时起就从阿里云下载更新，不用再装什么。

## 给还在用旧版本的人

旧版本只会问 GitHub，连不上 GitHub 就永远看不到更新，所以要手动装一次新版本。下面两段可以直接发给他们；链接里的版本号换成实际发布的那个。

**电脑端：**

> 遥应电脑端以前只从 GitHub 检查更新，国内很多网络连不上，所以一直收不到更新。从这一版起改成从阿里云更新，需要你手动装一次：
> 1. 在屏幕右下角找到遥应的图标（看不到就先点那里的小箭头），右键点「退出」。
> 2. 用浏览器打开下面的链接，下载安装包（约 26 MB）。浏览器提示文件不常下载时，选「保留」。
> https://teleply-updates.oss-cn-guangzhou.aliyuncs.com/windows/AgentRemote-0.27.0-dev.25-Setup.exe
> 3. 双击安装包。出现「Windows 已保护你的电脑」时，点「更多信息」，再点「仍要运行」。一路点「下一步」，会装在原来的位置，账号、数据和开机启动都保留。
>
> 装好以后，以后的更新在托盘菜单里点「检查更新」就能收到。

**安卓：**

> 遥应安卓版以前也只从 GitHub 检查更新。请装一次我发给你的 1.0.3 安装包：在手机上点开它，选「安装」，会直接覆盖旧版，登录和数据都保留。等我们的下载域名开通以后，之后的更新应用会自己提示，不用再找我要安装包。

安卓的安装包在域名开通前只能由你直接发，比如用微信或 QQ 发文件。开通以后可以改发链接 `https://dl.pocketagentdesk.com/android/Teleply-<版本>-<版本号>.apk`。
