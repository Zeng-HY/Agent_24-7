# 交接：电脑端记下和中转的断开、连回；本机服务没回应时自己恢复（2026-11-17）

写给接手的 DeepSeek Harness 会话，由 Claude 监督。原因已经查清，你照第 3 节改电脑端代码、补测试、本地提交，在第 9 节记结果。行号按 main 的 `17f0b5d` 写，可能前后差几行。

---

## 0. 结论

手机上几次看到「电脑已离线」，事后都查不出原因：电脑端和中转之间那条连接什么时候断、为什么断、什么时候连回，电脑上一个字都不记。这次让电脑端把这些写进当天日志；顺带修一个会让手机长时间看到离线的地方。

| 编号 | 现在 | 要改成 |
|---|---|---|
| 记-1 | 连上、断开、连回，日志里都没有 | 当天日志里各写一行；断开那行写原因 |
| 记-2 | 长时间连不上，没有任何痕迹 | 第一次失败写一行；之后每 10 分钟写一行「还没连上」；连回时写一行「断了多久、重连几次」 |
| 恢复-1 | 电脑端每秒查一次本机服务，**只要一次** 3 秒没回应，就停掉和中转的连接，之后**不会自己连回**，要在电脑上点「重试」或重启程序，期间手机一直看到离线 | 连续 3 次没回应才停；停了以后自己等一会儿，重启本机服务、重新连中转；每一步写一行日志 |

当天日志：`DATA / "logs" / "YYYYMMDD.log"`（安装版是 `%LOCALAPPDATA%\AgentRemote\Data\logs\`），每行 `HH:MM:SS 文字`。

---

## 1. 用户看到的

- 11-13 到 11-16 有几次、11-17 早上 07:25 一次：iPhone 上「电脑已离线，请稍后刷新电脑列表。」，DeepSeek 对话头上「连接中断，正在重连」。
- iPhone 对 HTTP 503，或 409 加 `device_offline`，显示前一句（`apps/ios/TeleplyCore/Sources/TeleplyModel/Relay.swift` 约 495 行）；对话的实时连接出任何错显示后一句（`TeleplyState/ChatModel.swift` 约 242 行）。

---

## 2. 已经查清的（不用再查，写在这里是让你知道为什么这样改）

1. **11-17 07:25 那次不是断线。** 托盘进程（`AgentRemote.exe`，PID 19800，11-16 21:51:40 启动）到中转只有一条连接，04:20:11 建立，08:30 查时还是同一条。断过的话，电脑端 1 秒左右就会重连，换成一条新的。
2. **电脑端不会在一条死掉的连接上空等，不用再加自己的心跳。** `relay_agent.py` 的两处 `ws_connect(..., heartbeat=20)`：aiohttp 3.14.5 在 20 秒没收到任何东西时发 ping，再 10 秒还是什么都没收到就断开（`.venv/Lib/site-packages/aiohttp/client_ws.py`：`_send_heartbeat`、`_pong_not_received`；收到任何字节都算，见 `_on_data_received`，`client.py` 约 1447 行接上）。ping 和 pong 在 TLS 里面，本机 Clash 的 TUN（假 IP 198.18.71.231）没法替中转回答，所以就算本机这头的 socket 还是 ESTABLISHED，死连接最多 30 秒就会被发现。中转那头也是 `heartbeat=20`（`relay_transport.py` 63 行）。
3. **日志里的「中转现在没连着，连上后会补报」不代表断线。** 它看的是中转此刻有没有在读通知流（`notify.py` 911 行的 `self.relay.listening`）。中转只在账号有手机登记通知、或者这台电脑有灵动岛时才读，而且读一会儿就停、再重读。之前（`docs/handoff-data-folder-wipe.md` 9.8）拿这句判断 dev.35「断线」，可能误判。这次**不改**这句话（另做），但你写的新日志要和它分得开。
4. 07:25 那次 503 最可能来自中转「每台电脑同时最多 16 个请求」（`relay_transport.py` 136 行，回 503 和 `Retry-After: 2`），但中转拒绝时不写日志，证实不了。这属于中转服务器，**这次不改**。
5. **会长时间离线的地方**：`relay_controller.py` 235–238 行，`connect_agent()` 在连上中转期间每秒调一次 `desktop.healthy(self.cfg)`（`relay_desktop.py` 245–250 行，GET `/api/status`，3 秒超时）。只要一次返回 False，就把状态设成「连接失败」、`break`，接着停掉中转连接，本机服务如果是托盘自己启动的（`owned`）也一起结束掉，然后 worker 线程就结束了。之后只有用户点「重试」（`dispatch('retry')` → `start_agent()`）、重新绑定或重启程序才会再连。另外 231 行的 `state()` 在 `self.state=='连接失败'` 时不再更新状态，自动恢复时要注意（见 3.6）。

---

## 3. 要做成什么样

### 3.1 哪些文件

- `relay_agent.py`：记录连上、断开、连回和原因。
- `relay_controller.py`：把记录交给 `Agent`；自己停连接时写明为什么；本机服务没回应时自动恢复。
- `relay_desktop.py`：加一个往当天日志追加一行的函数。
- `tests/` 下的测试（新建 `tests/test_relay_link_log.py`，也可以在 `tests/test_relay_controller.py`、`tests/test_relay_v2.py` 里加）。

### 3.2 日志写在哪、什么格式

- 中转连接跑在托盘进程里（`relay_controller.py` 的 `DesktopController` 和 `relay_agent.py` 的 `Agent`）。当天日志由另一个进程写：本机服务（`AgentRemote.exe --serve`，`remote.py` 204–228 行的 `Log`）。两个进程往同一个文件追加。
- 在 `relay_desktop.py` 加一个函数（比如 `day_log(text)`）：路径、格式和 `remote.py` 的 `Log.write` 一样（`DATA / "logs" / f"{now:%Y%m%d}.log"`，内容 `f"{now:%H:%M:%S} {text}\n"`，UTF-8，换行用 `\n`）。每次打开、追加、关闭；文件夹不在就建；**任何错误都吞掉，不能影响连接**。
- 两个进程同时追加，极少数情况下两行可能挤在一起；这几行很少，接受，不加锁。

### 3.3 写哪几行（原样用这些字，测试按这些字核对）

`{时长}`：60 秒以内写「N 秒」，1 小时以内写「N 分钟」，再长写「N 小时 M 分钟」（M 为 0 时只写「N 小时」）。

中转连接（`relay_agent.py`）：

1. 程序启动后第一次连上：`中转：连上了`
2. 连上以后断开：`中转：断开了（{原因}），这次连了 {时长}`
3. 程序启动后一次都还没连上就失败：`中转：连不上（{原因}）`
4. 断开以后还在重试：不每次都写；从断开那一刻起每满 10 分钟写一行 `中转：还没连上（已经断了 {时长}，重连 {n} 次；最近一次：{原因}）`
5. 断开以后连回：`中转：重新连上了（断了 {时长}，重连 {n} 次）`
6. 中转不认这台电脑的凭据（HTTP 401 / 403，现在的代码停下不再重连，这个行为不变）：`中转：不认这台电脑的凭据（HTTP {状态码}），停止重连，要在电脑上重新绑定`

`{n}` 是断开以后发起连接的次数（包括最后成功的那次）。「断了多久」从第一次断开（或第一次连不上）算到连回为止，**跨过 3.6 的自动恢复也要接着算**，所以记账的东西要由 `DesktopController` 持有一份、每次新建 `Agent` 时交给它，而不是每个 `Agent` 各记各的。

电脑端自己停连接（`relay_controller.py`）：

7. 用户退出：`中转：电脑端退出，断开连接`
8. 重新绑定：`中转：重新绑定，断开连接`
9. 本机服务连续没回应（3.6）：`本机服务：连续 3 次没回应（每次等 3 秒），先断开中转，{s} 秒后重启本机服务再连`
10. 自动恢复时本机服务起不来（`desktop.backend()` 抛 `ValueError`，比如「端口已被其他程序占用，未启动重复服务」「本机服务启动失败」）：`本机服务：没启动起来（{ValueError 的原话}），{s} 秒后再试`。同一个原因只在第一次和之后每满 10 分钟写。

### 3.4 原因怎么写

**绝不写网址、钥匙、请求头、请求或回答的内容。** 只用异常的类型名（`type(exc).__name__`）、HTTP 状态码、WebSocket 关闭代码。**不要用 `str(exc)`**：aiohttp 的出错文字里带网址（`relay_agent.py` 72 行原来就有这条规矩）。

| 情况 | 怎么认（以 aiohttp 3.14.5 源码和测试为准，别只信这张表） | 写成 |
|---|---|---|
| 心跳超时 | 连上以后循环结束，`ws.exception()` 是 `aiohttp.ServerTimeoutError`（`_pong_not_received` 放进去的） | `中转没回应心跳（心跳超时）` |
| 中转关闭 1000 | 循环结束，没有异常，`ws.close_code == 1000` | `中转正常关闭（1000）` |
| 中转关闭 1001 | `close_code == 1001` | `中转那边在关闭（1001）` |
| 中转关闭 1008 | `close_code == 1008`（`relay_transport.py` 的 `disconnect()`：同一台电脑又连了一条新的、撤销、重新绑定、删账号；中转停服务时 `relay_service.py` 的 `close()` 也用它） | `中转关掉了这条连接（1008：中转重启、同一台电脑又连了一条，或被撤销、重新绑定）` |
| 被掐断 | `close_code` 是 1006 或 None，且没有异常（网络断了、代理或 Caddy 断了 TCP；中转重启有时也是这样） | `连接被掐断，没收到关闭信号（1006）` |
| 别的关闭代码 | 其余 `close_code` | `中转关闭了连接（代码 {n}）` |
| 消息不对 | `once()` 里收到二进制消息（82 行的 `break`，不是 ERROR 的情况），或控制消息不合规矩（85 行的 `break`） | `中转发来的消息不对，主动断开` |
| 加密出错 | `aiohttp.ClientSSLError` 及其子类（它是 `ClientConnectorError` 的子类，先判断它） | `和中转的加密连接出错（{类型名}）` |
| 连不上 | `aiohttp.ClientConnectorError`（含 DNS 失败） | `连不上中转（{类型名}）` |
| 连接超时 | 连接阶段的 `asyncio.TimeoutError` / `aiohttp.ConnectionTimeoutError` 等（`sock_connect=15`） | `连中转超时（{类型名}）` |
| 握手被拒 | `aiohttp.WSServerHandshakeError`，状态码不是 401 / 403（中转没开时 Caddy 回 502） | `中转没接受连接（HTTP {状态码}）` |
| 其他 | 任何别的异常 | `{类型名}` |

### 3.5 在哪里接上

- `Agent.__init__` 多收一个记账对象（建议在 `relay_agent.py` 里写一个小类，比如 `LinkLog(write, clock=time.monotonic)`，方法如 `connected()`、`lost(reason)`、`refused(status)`；名字你定）。不传时什么都不写，测试和老调用照常能用。
- `once()`：`ws_connect` 成功、调 `self.state('online')` 的地方记「连上」；`async for` 结束以后按 3.4 判断原因，交给 `run()`。
- `run()`：捕到的异常按 3.4 变成原因；401 / 403 写第 6 行。重连间隔（1 秒起翻倍到 60 秒、连满 60 秒归 1）**不改**。
- `asyncio.CancelledError`（电脑端自己停）照旧往外抛，`Agent` 不写断开行，由 `DesktopController` 写 7–9 行。
- `DesktopController`：建一份记账对象，`write` 用 3.2 的函数；`quit()` 写第 7 行，`rebind()` 真的要停连接时写第 8 行（用户在确认框点「否」时不写）。

### 3.6 本机服务没回应时（恢复-1）

- `connect_agent()` 里数**连续**失败的次数，成功一次就归零；连续 3 次才动手。一次检查最多等 3 秒，加上间隔 1 秒，所以本机服务大约 3–12 秒都没回应才算（服务直接没了时检查立刻失败，大约 3 秒；卡住时每次等满 3 秒，大约 12 秒）。
- 动手时：写第 9 行；停掉 `Agent`；本机服务是托盘启动的（`owned`）就照现在的写法结束它；托盘状态显示「断线重连」，`detail` 写「本机服务没回应，正在重启」。
- 然后在 `start_agent()` 的 worker 里自己再来一轮：等 5 秒，再调 `connect_agent()`（它会调 `desktop.backend()`，没有健康的本机服务就启动一个），再建 `Agent` 连中转。接连恢复都不成功时，等待翻倍：5、10、20、40、60 秒封顶；一轮正常连满 10 分钟就回到 5 秒。
- `desktop.backend()` 抛 `ValueError` 时：写第 10 行，状态「连接失败」、`detail` 写原话（和现在一样），但**继续按上面的间隔重试**，不要停。
- 每一轮开始时把 `self.state` 设回「连接中」：231 行的 `state()` 在「连接失败」时不更新状态，不设回去的话，恢复以后托盘和窗口会一直显示「连接失败」。
- 这些情况**不**自动恢复，照现在的样子停下：用户退出（`self.stop`）、重新绑定（`self.agent_stop`）、中转不认凭据（`unauthorized`）。worker 还在跑时点「重试」照旧什么都不做（`start_agent()` 开头的判断），不用改。
- 所有等待都用 `cancel.wait(...)` 或 `self.stop.wait(...)`，退出时 `quit()` 里 `self.worker.join(timeout=25)` 要能很快等到 worker 结束。
- 迁移、写 `remote_config.json`、`set_startup` 这些只在 `start_agent()` 开头做一次，不要每轮都做。
- 窗口和托盘不加新按钮、新文字以外的东西；状态还是那五种：连接中 / 已连接 / 断线重连 / 连接失败 / 需要重新绑定。

---

## 4. 边界

- **只改**：`relay_agent.py`、`relay_controller.py`、`relay_desktop.py`、`tests/` 下的测试（新文件，或在已有测试文件里只加不删）、本文件第 9 节。
- **不要碰**：中转服务器的代码（`relay_transport.py`、`relay_service.py`、`relay_push.py`，改了要用户同意再上服务器）；`remote.py`、`notify.py`（「中转现在没连着」那句另做）；iOS、安卓、网页（`remote.html`、`static/`）；`deploy/`；版本号（`windows-version.json`）；用户没提交的 `deploy/site/`、`pocketagentdesk.com.png`、`tests/test_activity_records.py`。
- **不改**：两处 `heartbeat=20`、重连间隔、`once()` 里同时 32 个请求的上限、`unauthorized` 停下不重连的行为。
- 不装软件、不下载；不启动、不重启、不结束任何程序，特别是 `G:\AgentRemote` 里正在跑的遥应电脑端（它正连着中转，用户手机在用）。
- `git add` 一个文件一个文件地加。main 上有别的会话没推送的提交：不 rebase、不 amend、不 push。

---

## 5. 验证

### 5.1 新测试（先在旧代码上跑，确认该失败的失败；原样输出存到 `F:\Android-Dev\work\20261101-island-duplicates\20261117-relay-link-log\`）

1. 记账对象，用假时钟、用列表当 `write`：第一次连上 → 第 1 行；连了 2 分钟断开 → 第 2 行写「这次连了 2 分钟」；10 分钟内再失败几次 → 不写；满 10 分钟 → 第 4 行；连回 → 第 5 行，时长和次数对；时长格式 59 秒、5 分钟、1 小时、1 小时 5 分钟都对。
2. 原因：`ServerTimeoutError` → 含「心跳超时」；`WSServerHandshakeError` 状态 502 → 「HTTP 502」；关闭代码 1001、1006、1008 各对一句；`ClientSSLError` 不会被写成「连不上中转」。造一个 `str()` 里带 `https://app.example.test/tunnel/connect` 和一串假钥匙的异常，写出来的行里两样都没有。
3. 真中转加真 `Agent`（照 `tests/test_relay_v2.py` 的写法，`test_http=True`）：连上 → 第 1 行；`await service.hub.disconnect(device)` → 第 2 行，带 1008；随后自动连回 → 第 5 行。
4. 中转不认钥匙（401）→ 第 6 行，`Agent` 停下。
5. `DesktopController`（假 `healthy`、假 `backend`、假 `Agent`，不起窗口）：`healthy` 失败 1 次、2 次 → 不停；连续 3 次 → 第 9 行，`Agent` 停了，`owned` 被结束，几秒后自动重来一轮，状态回到「已连接」；`backend` 抛 `ValueError` → 第 10 行，继续重试；等待期间 `quit()` → worker 很快结束，写第 7 行。测试里把等待秒数调小，别真等 5 秒。
6. 写日志的函数：写进 `logs/YYYYMMDD.log`，格式 `HH:MM:SS 文字\n`；文件夹写不进去时不抛错。测试用临时文件夹，**不要**写到真的 `%LOCALAPPDATA%\AgentRemote\Data`。

### 5.2 全部测试

`.venv\Scripts\python.exe -m unittest discover -s tests`：改之前先跑一遍记下基线，改完再跑。不能有新的失败。已知原来就坏的：Playwright 浏览器被删（约 21 项，`C:\Users\39011\AppData\Local\ms-playwright` 不在）、`test_mobile_polish` 找「复制命令」按钮（1 项）。两次的出错清单逐行比对。改之前 `tests.test_relay_controller` 和 `tests.test_relay_v2` 共 23 项全过。

### 5.3 这台电脑做不了的

装上新版以后在真机上看（断开 Wi-Fi 一分钟再连上，看当天日志里的几行；手机上看电脑在线）：打包、安装由 Claude 问过用户以后做。

---

## 6. 发布（不是你的事）

本地提交以后停下。不打包、不改版本号、不 push、不装、不发版。Claude 审完再问用户要不要打 Windows dev.38。

---

## 9. 结果记录（接手的会话填）

### 9.1 改了哪些文件

### 9.2 新测试的名字，和在旧代码上的结果

### 9.3 全部测试

### 9.4 日志的样子（测试里写出来的几行，原样贴）

### 9.5 没做的

### 9.6 提交
