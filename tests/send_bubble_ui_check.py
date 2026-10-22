"""A message sent from the phone is the blue bubble at once, for Codex, Claude and DeepSeek alike (10-22).

The user: a sent message showed a red frame on its way, or nothing for a while until the PC had it. Now it is the solid
blue bubble from the tap on, with a small line under it: 发送中…, then 电脑已接收 (or 已排队…); the line moves onto the
conversation's own copy when that comes, so there is never a frame without the message or with it twice. Checked every
frame with the requests held open; also a page reloaded mid-send (确认中…, no red frame), one long unconfirmed and one
turned away (still blue, a red ! beside it, what can be done inside).

    .venv\\Scripts\\python.exe tests\\send_bubble_ui_check.py
"""
import json
import sys
import time
from urllib.parse import parse_qs, urlsplit

from playwright.sync_api import sync_playwright

from motion_check import HERE, ORIGIN, handle

INIT = """
window.sources = [];
window.EventSource = class extends EventTarget {
  constructor(url) { super(); this.url = url; this.closed = false; this.seq = 0; window.sources.push(this); }
  close() { this.closed = true; }
};
window.deliver = v => {
  const s = window.sources.findLast(x => !x.closed); if (!s) return false;
  s.seq++; s.dispatchEvent(new MessageEvent('update', {data: JSON.stringify({protocol: 1, type: 'update', streaming_ids: [], seq: s.seq, ...v})}));
  return true;
};
// every frame: the user bubbles holding these words, how they look and what the line under them says
window.watch = words => {
  window.frames = []; window.watching = true;
  const loop = () => { if (!window.watching) return;
    window.frames.push([...document.querySelectorAll('#cvMsgs .bub.user')].filter(n => n.textContent.includes(words)).map(n => {
      const s = getComputedStyle(n);
      return {key: n.dataset.key, problem: n.classList.contains('problem'), line: n.querySelector('.send-receipt')?.textContent || '',
              bg: s.backgroundColor, opacity: s.opacity, popping: n.getAnimations().length > 0};
    }));
    requestAnimationFrame(loop); };
  requestAnimationFrame(loop);
};
"""
BLUE = "rgb(37, 99, 235)"


def stamp():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def main():
    errors, fails, held = [], [], []
    transcripts = {
        ("codex", "c1"): [{"id": "x1", "role": "user", "text": "前面的问题", "time": "2026-10-22T08:00:00Z"},
                          {"id": "x2", "role": "assistant", "text": "前面的回答", "time": "2026-10-22T08:00:05Z"}],
        ("claude", "c3"): [{"id": "y1", "role": "user", "text": "前面的问题", "time": "2026-10-22T08:00:00Z"}],
        ("deepseek", "d1"): [{"id": "1", "role": "user", "text": "前面的问题", "order": 1, "time": "2026-10-22T08:00:00Z"}],
    }
    claude = {"delivered": False, "queued": False, "refuse": False}

    def ok(name, cond, detail=""):
        print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail and not cond else ""), flush=True)
        if not cond: fails.append(name)

    def route(r, req):
        u = urlsplit(req.url)
        js = lambda v, status=200: r.fulfill(status=status, content_type="application/json; charset=utf-8", body=json.dumps(v, ensure_ascii=False))
        if u.path == "/":
            html = (HERE / "remote.html").read_text(encoding="utf-8").replace(
                "<!--machine-->", '<script>window.MACHINE={apps:["codex","claude","deepseek"],voice:false};</script>')
            return r.fulfill(status=200, content_type="text/html; charset=utf-8", body=html)
        if u.path == "/api/chat":
            q = parse_qs(u.query); key = (q.get("app", [""])[0], q.get("id", [""])[0])
            if key in transcripts:
                return js({"app": key[0], "id": key[1], "title": "发送测试", "status": "idle", "folder": "D:/demo", "size": 1,
                           "messages": transcripts[key], "has_more": False, "next_cursor": None, "has_newer": False})
        if u.path == "/api/codex/state":
            return js({"available": True, "running": False, "settings": {"model": "gpt-5", "effort": "high", "mode": "default", "service_tier": None},
                       "questions": [], "queued": [], "queue_available": True, "images": [], "plan": None, "catalog": {"models": []}})
        if u.path in ("/api/codex/receipt", "/api/deepseek/receipt"):
            return js({"state": "unknown"})
        if u.path == "/api/claude/state":
            return js({"settings": {}, "available": True, "on_screen": True, "actions": [], "running": True, "queued": []})
        if u.path == "/api/deepseek/state":
            return js({"available": True, "running": False, "settings": {}, "questions": [], "interactions": [], "inbox": {}, "queued": []})
        if u.path == "/api/deepseek/models":
            return js({"groups": []})
        if u.path == "/api/chat/check":
            return js({"delivered": claude["delivered"], "queued": claude["queued"], "stage": "received" if claude["delivered"] else "queued" if claude["queued"] else "unknown"})
        if u.path == "/api/chat/send" and claude["refuse"]:
            return js({"error": "电脑上 Claude 的输入框里有别的字（「e」），没有覆盖", "not_submitted": True, "code": "desktop_draft", "draft": "e"}, 400)
        if u.path in ("/api/codex/send", "/api/chat/send", "/api/deepseek/send"):
            held.append((r, u.path, json.loads(req.post_data or "{}"))); return
        return handle(r, req)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, channel="chrome")
        ctx = browser.new_context(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
        ctx.add_init_script(INIT)
        ctx.route(ORIGIN + "/**", route)
        page = ctx.new_page()
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(ORIGIN)
        page.wait_for_function("window.readingUI && window.workspaceUI && window.codexUI && window.deepseekUI")

        def open_chat(app, cid):
            page.evaluate("([app, id]) => openConv({app, id, title: '发送测试', status: 'idle'})", [app, cid])
            page.wait_for_function("document.getElementById('cvMsgs').dataset.ready && window.sources.some(x => !x.closed)")
            page.wait_for_timeout(400)

        def tap_send(words):
            page.locator("#cvText").fill(words); page.evaluate("updateSendButton()")
            page.locator("#cvBtn").click()

        def wait_held(path):
            for _ in range(100):
                if any(h[1] == path for h in held): return [h for h in held if h[1] == path][-1]
                page.wait_for_timeout(50)
            raise AssertionError("no request to " + path)

        def release(h, result, status=200):
            held.remove(h); h[0].fulfill(status=status, content_type="application/json", body=json.dumps(result, ensure_ascii=False))

        def arrive(app, cid, message):  # the conversation's own copy: in its record, and on the stream
            transcripts[(app, cid)].append(message)
            page.wait_for_function("window.sources.some(x => !x.closed)")
            page.evaluate("v => window.deliver(v)", {"app": app, "id": cid, "messages": [message], "meta": {"status": "idle"}})

        def bubbles(words):
            return page.evaluate("""w => [...document.querySelectorAll('#cvMsgs .bub.user')].filter(n => n.textContent.includes(w)).map(n => ({
                key: n.dataset.key, problem: n.classList.contains('problem'), line: n.querySelector('.send-receipt')?.textContent || '',
                bg: getComputedStyle(n).backgroundColor}))""", words)

        def every_frame(name, lines):
            frames = page.evaluate("window.watching = false, window.frames")
            frames = frames[next((i for i, f in enumerate(frames) if f), len(frames)):]  # from the tap's first frame on
            counts = sorted({len(f) for f in frames})
            ok(f"{name}: from the tap on, in every frame the message is there exactly once", counts == [1], f"bubbles per frame: {counts}, {len(frames)} frames")
            looks = {(b["bg"], b["opacity"], b["problem"]) for f in frames for b in f if not b["popping"]}  # its pop fades it in (0.25.0)
            ok(f"{name}: always the solid blue bubble, never pale or framed in red", looks == {(BLUE, "1", False)}, looks)
            said = []
            for f in frames:
                for b in f:
                    if not said or said[-1] != b["line"]: said.append(b["line"])
            ok(f"{name}: the line under it goes {' → '.join(lines)}", said == lines, said)

        # -- Codex: 发送中… → 电脑已接收, and the conversation's own copy takes over with no gap
        open_chat("codex", "c1")
        page.evaluate("watch('测试发送甲')")
        tap_send("测试发送甲")
        h = wait_held("/api/codex/send"); page.wait_for_timeout(150)
        ok("Codex: the tap empties the box into a blue bubble saying 发送中…",
           bubbles("测试发送甲") == [{"key": "outbox:" + h[2]["request_id"], "problem": False, "line": "发送中…", "bg": BLUE}]
           and page.locator("#cvText").input_value() == "", bubbles("测试发送甲"))
        release(h, {"ok": True, "accepted": True, "delivery_state": "accepted", "text": "已交给 Codex", "request_id": h[2]["request_id"]})
        page.wait_for_function("!sending"); page.wait_for_timeout(600)
        ok("Codex: accepted, the bubble stays and says 电脑已接收 until the conversation has its copy",
           [b["line"] for b in bubbles("测试发送甲")] == ["电脑已接收"], bubbles("测试发送甲"))
        arrive("codex", "c1", {"id": "x3", "role": "user", "text": "测试发送甲", "client_request_id": h[2]["request_id"], "time": stamp()})
        page.wait_for_timeout(400)
        ok("Codex: the conversation's copy takes the bubble's place, 电脑已接收 under it",
           bubbles("测试发送甲") == [{"key": "x3", "problem": False, "line": "电脑已接收", "bg": BLUE}], bubbles("测试发送甲"))
        every_frame("Codex", ["发送中…", "电脑已接收"])
        arrive("codex", "c1", {"id": "x4", "role": "assistant", "text": "收到，马上看。", "time": stamp()})
        page.wait_for_timeout(300)
        ok("the line stays under it while the reply comes", [b["line"] for b in bubbles("测试发送甲")] == ["电脑已接收"])
        tap_send("测试发送己"); h = wait_held("/api/codex/send"); page.wait_for_timeout(150)
        ok("the next message takes the line: 发送中… under it, none under the one before",
           [b["line"] for b in bubbles("测试发送甲")] == [""] and [b["line"] for b in bubbles("测试发送己")] == ["发送中…"],
           (bubbles("测试发送甲"), bubbles("测试发送己")))
        release(h, {"ok": True, "accepted": True, "delivery_state": "accepted", "text": "已交给 Codex"}); page.wait_for_function("!sending")

        # -- Codex queued while a turn runs: blue, 已排队 (it was a white box framed in red)
        page.locator("#cvText").fill("排队消息乙"); page.evaluate("void codexUI.send(null, 'queue')")
        h = wait_held("/api/codex/send")
        release(h, {"ok": True, "accepted": True, "delivery_state": "queued", "text": "已排队", "request_id": h[2]["request_id"]})
        page.wait_for_function("!sending"); page.wait_for_timeout(300)
        ok("Codex: a queued message is the blue bubble saying 已排队，这一轮结束后发出",
           bubbles("排队消息乙") == [{"key": "outbox:" + h[2]["request_id"], "problem": False, "line": "已排队，这一轮结束后发出", "bg": BLUE}], bubbles("排队消息乙"))

        # -- Claude: 发送中… while the PC types it in, 已排队 while Claude is busy, then its record's copy with 电脑已接收
        open_chat("claude", "c3")
        page.evaluate("watch('克劳德丙')")
        tap_send("克劳德丙")
        h = wait_held("/api/chat/send"); page.wait_for_timeout(150)
        ok("Claude: the tap empties the box into a blue bubble saying 发送中…", [b["line"] for b in bubbles("克劳德丙")] == ["发送中…"], bubbles("克劳德丙"))
        claude["queued"] = True
        release(h, {"ok": True, "pressed": True, "offset": 0, "running": True, "text": "已提交，等待对话记录确认"})
        page.wait_for_function("[...document.querySelectorAll('#cvMsgs .bub.user')].some(n => n.textContent.includes('已排队'))", timeout=6000)
        ok("Claude: queued behind the running turn, the bubble stays in the conversation saying so (it used to vanish)",
           [b["line"] for b in bubbles("克劳德丙")] == ["已排队，这一轮结束后发出"], bubbles("克劳德丙"))
        arrive("claude", "c3", {"id": "y2", "role": "user", "text": "克劳德丙", "time": stamp()})
        claude.update(queued=False, delivered=True)
        page.wait_for_function("!sending", timeout=8000); page.wait_for_timeout(400)
        ok("Claude: read from its queue, its record's copy takes the bubble's place with 电脑已接收",
           bubbles("克劳德丙") == [{"key": "y2", "problem": False, "line": "电脑已接收", "bg": BLUE}], bubbles("克劳德丙"))
        every_frame("Claude", ["发送中…", "已排队，这一轮结束后发出", "电脑已接收"])

        # -- Claude turned away (text in its box on the PC): still the blue bubble, a red ! beside it, what to do inside
        claude.update(refuse=True, delivered=False)
        tap_send("被拒消息庚"); page.wait_for_function("!sending"); page.wait_for_timeout(300)
        look = page.evaluate("""(() => { const n = [...document.querySelectorAll('#cvMsgs .bub.user')].find(n => n.textContent.includes('被拒消息庚'));
            return {problem: n.classList.contains('problem'), bg: getComputedStyle(n).backgroundColor, mark: getComputedStyle(n, '::before').content,
                    state: n.querySelector('.outbox-state')?.textContent}; })()""")
        ok("a message turned away keeps the blue bubble, with a red ! beside it and 没发出去 inside",
           look == {"problem": True, "bg": BLUE, "mark": '"!"', "state": "没发出去 ›"}, look)
        claude["refuse"] = False

        # -- DeepSeek: the bubble at once (it used to stay in the box till DeepSeek had it), then its copy by request number
        open_chat("deepseek", "d1")
        page.evaluate("watch('深度求索丁')")
        tap_send("深度求索丁")
        h = wait_held("/api/deepseek/send"); page.wait_for_timeout(150)
        ok("DeepSeek: the tap empties the box into a blue bubble saying 发送中…",
           [b["line"] for b in bubbles("深度求索丁")] == ["发送中…"] and page.locator("#cvText").input_value() == "", bubbles("深度求索丁"))
        ok("DeepSeek: 核对待发送消息 does not flash up while it goes", page.locator("#deepseekRun button", has_text="核对待发送消息").is_hidden())
        release(h, {"accepted": True, "text": "已交给 DeepSeek", "request_id": h[2]["request_id"]})
        page.wait_for_function("!sending"); page.wait_for_timeout(500)
        ok("DeepSeek: accepted, it says 电脑已接收 until the conversation has its copy",
           [b["line"] for b in bubbles("深度求索丁")] == ["电脑已接收"], bubbles("深度求索丁"))
        arrive("deepseek", "d1", {"id": "2", "role": "user", "text": "深度求索丁", "request_id": h[2]["request_id"], "order": 2, "time": stamp()})
        page.wait_for_timeout(400)
        ok("DeepSeek: its copy takes the bubble's place with 电脑已接收",
           bubbles("深度求索丁") == [{"key": "2", "problem": False, "line": "电脑已接收", "bg": BLUE}], bubbles("深度求索丁"))
        every_frame("DeepSeek", ["发送中…", "电脑已接收"])

        # -- the page reloads while a message is on its way (iPhone Safari does that after a while in another app)
        open_chat("codex", "c1")
        tap_send("重载消息戊"); wait_held("/api/codex/send")
        page.reload(); page.wait_for_function("window.workspaceUI && cur && cur.id === 'c1' && document.getElementById('cvMsgs').dataset.ready")
        page.wait_for_timeout(800)
        ok("reloaded mid-send: the bubble says 确认中…, no red frame",
           [(b["line"], b["problem"], b["bg"]) for b in bubbles("重载消息戊")] == [("确认中…", False, BLUE)], bubbles("重载消息戊"))
        page.evaluate("(() => { const real = Date.now; Date.now = () => real() + 180000; renderMsgs(currentMessages); })()")  # 3 minutes on
        page.wait_for_timeout(300)
        b = bubbles("重载消息戊")
        ok("unconfirmed for minutes: it says so, still the blue bubble", [(x["problem"], x["bg"]) for x in b] == [(True, BLUE)], b)
        page.locator("#cvMsgs .bub.outbox.problem .outbox-state").click(); page.wait_for_timeout(200)
        acts = page.evaluate("[...document.querySelectorAll('#cvMsgs .bub.outbox.problem .message-actions button')].map(b => b.textContent)")
        ok("tapping that offers 重新核对, 恢复草稿 and 移除", acts == ["重新核对", "恢复草稿", "移除"], acts)

        ok("no page errors", not errors, errors[:3])
        browser.close()
    print(f"send bubble ui check: {'FAILED ' + str(len(fails)) if fails else 'ok'}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
