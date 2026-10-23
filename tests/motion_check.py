"""Motion and haptics check for the phone page (manual; not collected by unittest discovery).

Loads the real remote.html and static/*.js in headless Chrome at phone size with a touch screen, answers every
/api/* request with small fake data (no token, no running service), drives real touch input through the
DevTools protocol, and records every frame: where the page, the drawer, the chat and the top sheet are.

Run from this folder (Playwright is in its .venv, see requirements.txt):
    .venv\\Scripts\\python.exe tests\\motion_check.py [--shots DIR]
Exit code 0 when every check passes.
"""
import argparse
import json
import sys
import time
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent.parent
ORIGIN = "https://lbr.test"
W, H = 390, 844
N = round(min(320, W * 0.74))  # drawer width, as navigation-ui.js computes it

INIT = r"""
(() => {
  // Let Chrome take the iPhone path of haptic() (a click on the hidden <input switch> label) and count it.
  Object.defineProperty(HTMLInputElement.prototype, 'switch', {configurable: true,
    get() { return this.hasAttribute('switch'); }, set(v) { this.toggleAttribute('switch', !!v); }});
  // Count every tick: navigator.vibrate calls (what haptic() uses) and clicks on the test sheet's scripted switches.
  window.__haptics = 0;
  const vib = navigator.vibrate ? navigator.vibrate.bind(navigator) : null;
  Object.defineProperty(navigator, 'vibrate', {configurable: true, value: (...a) => { window.__haptics++; return vib ? vib(...a) : true; }});
  const click = HTMLLabelElement.prototype.click;
  HTMLLabelElement.prototype.click = function () { if (this.dataset && this.dataset.haptic) window.__haptics++; return click.call(this); };
  const matrix = el => { const t = el && getComputedStyle(el).transform; return !t || t === 'none' ? null : new DOMMatrixReadOnly(t); };
  const m41 = el => el ? (matrix(el)?.m41 ?? 0) : null, m42 = el => el ? (matrix(el)?.m42 ?? 0) : null;
  window.__rec = {frames: [], on: false,
    start() { this.frames = []; this.on = true; const loop = () => { if (!this.on) return;
      const d = document, view = d.getElementById('convView'), drawer = d.getElementById('navSheet'), box = drawer.querySelector('.box'),
        header = d.querySelector('body>header'), shield = d.getElementById('chatBackdrop'), top = overlays.at(-1), sheet = top && d.getElementById(top.id);
      this.frames.push({t: Math.round(performance.now()), header: m41(header), box: m41(box), kid: m41(box.firstElementChild),
        view: view.style.display === 'none' ? null : m41(view), shield: +getComputedStyle(shield).opacity, drawer: drawer.style.display,
        sheet: sheet && sheet !== drawer ? m42(sheet.querySelector('.box')) : null, sheetH: sheet && sheet !== drawer ? sheet.querySelector('.box').offsetHeight : null,
        nodes: [...d.querySelectorAll('body>header,body>section')].filter(n => getComputedStyle(n).display !== 'none').map(m41),
        cls: d.body.className, sy: Math.round(scrollY), sx: Math.round(scrollX), iw: innerWidth});
      requestAnimationFrame(loop); }; requestAnimationFrame(loop); },
    stop() { this.on = false; return this.frames; }};
})();
"""

STATE = """() => ({overlays: overlays.map(o => o.id), cur: cur ? cur.id : null, drawer: document.getElementById('navSheet').style.display,
  header: document.querySelector('body>header').style.transform, view: document.getElementById('convView').style.display,
  viewT: document.getElementById('convView').style.transform, cls: document.body.className,
  headerVis: getComputedStyle(document.querySelector('body>header')).visibility, sx: scrollX, sy: scrollY,
  active: document.activeElement && (document.activeElement.id || document.activeElement.tagName), haptics: window.__haptics})"""


def fake_chats(n=30):
    now = int(time.time() * 1000)
    return [{"app": "claude" if i % 2 else "codex", "id": f"c{i}", "title": f"测试对话 {i}", "status": "idle",
             "updated": now - i * 600_000, "folder": "D:/demo", "preview": "一段预览文字，用来占位。"} for i in range(1, n + 1)]


def fake_chat(app, cid):
    msgs = []
    for i in range(1, 13):
        msgs.append({"id": f"{cid}-u{i}", "role": "user", "text": f"第 {i} 个问题：这里是一段用户消息。"})
        msgs.append({"id": f"{cid}-a{i}", "role": "assistant", "text": f"第 {i} 个回答。" + "这是一段比较长的回复文字，用来撑出滚动。" * 3})
    return {"app": app, "id": cid, "title": f"测试对话 {cid[1:]}", "status": "idle", "folder": "D:/demo", "size": 1000,
            "messages": msgs, "note": "", "has_more": False, "next_cursor": None}


ASK_NAMES = ["Dismiss question", "选项 A 说明 A 1", "选项 B 说明 B 2", "选项 C 说明 C 3", "Other 4", "Skip", "Next"]
CLAUDE_ASK = {  # what the service reports while Claude asks a two-question AskUserQuestion (shape of claude_control._read)
    "settings": {}, "available": True, "on_screen": True, "action_revision": "r1",
    "actions": [{"type": "ButtonControl", "name": n, "token": f"t{i}"} for i, n in enumerate(ASK_NAMES)],
    "prompt": {"title": "手机上用哪种方式出现比较顺手？", "progress": "1 / 2",
               "choices": [{"name": ASK_NAMES[i], "label": f"选项 {c}", "description": f"说明 {c}", "pressed": None, "token": f"t{i}"} for i, c in ((1, "A"), (2, "B"), (3, "C"))],
               "nav": [{"name": "Dismiss question", "label": "不回答", "token": "t0"}, {"name": "Skip", "label": "跳过", "token": "t5"}, {"name": "Next", "label": "下一题", "token": "t6"}],
               "other": {"name": "Other 4", "token": "t4"}}}
CHOSEN = {"tokens": []}
# Codex asking through request_user_input (shape of codex_control.native_questions): c2 asks two questions, c4 one
CODEX_ASKS = {
    "c2": {"id": "native:t1:7", "request_id": 7, "kind": "native", "turn_id": "t1", "status": "pending", "questions": [
        {"id": "q1", "header": "方案", "question": "先做哪一个？", "options": [{"label": "选项 A", "description": "说明 A"}, {"label": "选项 B", "description": "说明 B"}]},
        {"id": "q2", "header": "范围", "question": "改到哪里为止？", "options": [{"label": "只改手机页", "description": ""}]}]},
    "c4": {"id": "native:t2:8", "request_id": 8, "kind": "native", "turn_id": "t2", "status": "pending", "questions": [
        {"id": "only", "question": "要现在执行吗？", "options": [{"label": "执行", "description": "马上开始"}, {"label": "先不", "description": ""}]}]}}
ANSWERS = []


def fake_project_items(prefix, app, count, start=0):
    now = int(time.time() * 1000)
    return [{"app": app, "id": f"{prefix}{i}", "title": f"{prefix} 对话 {i}", "folder": "demo", "cwd": "D:/demo",
             "updated": now - i * 3_600_000, "status": "running" if (prefix, i) == ("lq", 1) else "idle"} for i in range(start + 1, start + count + 1)]


def fake_tree():
    """What /api/chat/projects answers (chat_projects.tree): 示例项目 has 25 conversations, 10 sent at first."""
    now = int(time.time() * 1000)
    other = fake_project_items("ot", "codex", 2)
    other[1]["place"] = "codex_BYOK_software"
    return {"now": now, "apps": [
        {"app": "codex", "name": "Codex", "count": 30, "projects": [
            {"key": "p-lq", "name": "示例项目", "count": 25, "updated": now, "folder": "D:/Projects/示例项目", "projectless": False,
             "items": fake_project_items("lq", "codex", 10)},
            {"key": "p-qt", "name": "quant", "count": 3, "updated": now - 1, "folder": "D:/Projects/quant", "projectless": False,
             "items": fake_project_items("qt", "codex", 3)},
            {"key": "other", "name": "其他对话", "count": 2, "updated": now - 2, "folder": "", "projectless": True, "items": other}]},
        {"app": "claude", "name": "Claude", "count": 5, "projects": [
            {"key": "f:notes_app", "name": "notes_app", "count": 5, "updated": now,
             "folder": "D:/Projects/notes_app", "projectless": False, "items": fake_project_items("cs", "claude", 5)},
            {"key": "other", "name": "其他对话", "count": 0, "updated": None, "folder": "", "projectless": True, "items": []}]}]}


def handle(route, request):
    u = urlsplit(request.url)
    path, q = u.path, parse_qs(u.query)
    js = lambda obj, status=200: route.fulfill(status=status, content_type="application/json; charset=utf-8", body=json.dumps(obj, ensure_ascii=False))
    if path == "/api/claude/state":
        asking = q.get("id", [""])[0] == "c1" and not CHOSEN["tokens"]
        return js(CLAUDE_ASK if asking else {"settings": {}, "available": True, "actions": []})
    if path == "/api/claude/choose":
        CHOSEN["tokens"].append((json.loads(request.post_data or "{}")).get("token"))
        time.sleep(0.7)  # the PC takes a moment to click and read back
        return js({"ok": True, "text": "已操作", "state": {"settings": {}, "available": True, "actions": []}})
    if path == "/api/codex/state":
        cid = q.get("id", [""])[0]
        card = CODEX_ASKS.get(cid)
        asking = [card] if card and not any(a["question_id"] == card["id"] for a in ANSWERS) else []
        return js({"available": True, "running": bool(asking), "settings": {"model": "gpt-5", "effort": "high", "mode": "default", "service_tier": None},
                   "questions": asking, "plan": None, "catalog": {"models": []}, "images": []})
    if path == "/api/codex/answer":
        ANSWERS.append(json.loads(request.post_data or "{}"))
        time.sleep(0.5)  # the desktop takes the answer
        return js({"ok": True, "text": "答案已提交给 Codex", "request_id": ANSWERS[-1].get("request_id")})
    if path == "/":
        return route.fulfill(status=200, content_type="text/html; charset=utf-8", body=(HERE / "remote.html").read_text(encoding="utf-8"))
    if path == "/api/chats":
        items = fake_chats()
        return js({"items": items, "total": len(items), "has_more": False, "next_cursor": None})
    if path == "/api/chat":
        return js(fake_chat(q.get("app", ["claude"])[0], q.get("id", ["c1"])[0]))
    if path == "/api/chat/folders":
        items = [{"path": "D:/Projects/示例项目", "name": "示例项目", "sources": ["Codex 项目"]}]
        return js({"folders": [v["path"] for v in items], "items": items})
    if path == "/api/chat/projects":
        if q.get("key"):  # 显示更多
            offset, limit = int(q.get("offset", ["0"])[0]), int(q.get("limit", ["30"])[0])
            return js({"count": 25, "items": fake_project_items("lq", "codex", max(0, min(limit, 25 - offset)), offset)})
        return js(fake_tree())
    if path == "/api/events":
        return js({}, 404)
    if path.startswith("/api/"):
        return js({})
    file = HERE / "static" / path.lstrip("/")
    if path != "/" and file.is_file():
        ctype = {".js": "application/javascript; charset=utf-8", ".png": "image/png"}.get(file.suffix, "application/octet-stream")
        return route.fulfill(status=200, content_type=ctype, body=file.read_bytes())
    return route.fulfill(status=404, body="")


class Finger:
    def __init__(self, page, cdp):
        self.page, self.cdp = page, cdp

    def _send(self, kind, pts):
        self.cdp.send("Input.dispatchTouchEvent", {"type": kind, "touchPoints": [{"x": x, "y": y, "id": 1} for x, y in pts]})

    def drag(self, pts, step=16, hold=None, shot=None):
        """Touch down at pts[0], move through the rest every `step` ms, lift. `hold` = (index, ms, callback)."""
        self._send("touchStart", [pts[0]])
        for i, p in enumerate(pts[1:], 1):
            self.page.wait_for_timeout(step)
            self._send("touchMove", [p])
            if hold and hold[0] == i:
                self.page.wait_for_timeout(hold[1])
                hold[2]()
        self.page.wait_for_timeout(step)
        self._send("touchEnd", [])

    def tap(self, x, y):
        self._send("touchStart", [(x, y)])
        self.page.wait_for_timeout(40)
        self._send("touchEnd", [])


class Checks:
    def __init__(self):
        self.rows = []

    def __call__(self, name, ok, detail=""):
        self.rows.append((name, bool(ok), detail))
        print(("PASS " if ok else "FAIL ") + name + (f"  [{detail}]" if detail else ""), flush=True)

    @property
    def failed(self):
        return [r for r in self.rows if not r[1]]


def center(page, selector):
    b = page.locator(selector).first.bounding_box()
    return b["x"] + b["width"] / 2, b["y"] + b["height"] / 2


def run(shots_dir=None, reduced=False, check=None):
    ok = check
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True,
                                    args=["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream"])
        ctx = browser.new_context(viewport={"width": W, "height": H}, device_scale_factor=3, is_mobile=True, has_touch=True,
                                  reduced_motion="reduce" if reduced else "no-preference")
        ctx.grant_permissions(["microphone"], origin=ORIGIN)
        ctx.route(f"{ORIGIN}/**", handle)
        ctx.add_init_script(INIT)
        page = ctx.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(f"{e.message} @ {(e.stack or '').splitlines()[1:2]}"))
        page.goto(ORIGIN + "/")
        page.wait_for_function("window.navigationUI && document.querySelectorAll('.conv').length >= 10", timeout=20000)
        cdp = ctx.new_cdp_session(page)
        finger = Finger(page, cdp)
        state = lambda: page.evaluate(STATE)
        rec = lambda: page.evaluate("__rec.start()")
        frames = lambda: page.evaluate("__rec.stop()")
        wait = page.wait_for_timeout
        shot = (lambda name: page.screenshot(path=str(Path(shots_dir) / name))) if shots_dir else (lambda name: None)
        tag = "[reduced] " if reduced else ""

        finger.tap(W / 2, 22)  # a first touch, so the page counts as used (navigator.userActivation)
        wait(300)
        menu = center(page, 'button[aria-label="打开导航"]')

        # -- drawer: menu button, then a tap on the strip of the card that stays visible
        page.evaluate("""window.__entered = false; const nb = document.querySelector('#navSheet .box');
            new MutationObserver(() => { if (nb.classList.contains('lbr-entering')) window.__entered = true; }).observe(nb, {attributes: true, attributeFilter: ['class']});""")
        h0 = state()["haptics"]; rec(); finger.tap(*menu); wait(700); f = frames(); s = state()
        ok(tag + "drawer opens from the menu button", "navSheet" in s["overlays"] and s["drawer"] == "block", s["overlays"])
        ok(tag + "drawer: one tick on opening", s["haptics"] - h0 == 1, s["haptics"] - h0)
        entering = page.evaluate("window.__entered")
        ok(tag + ("opened with a tap: its contents arrive one after another" if not reduced else "no arriving one after another with Reduce Motion"), entering == (not reduced), entering)
        ok(tag + "the contents have arrived by the time the drawer stops (10-14)",
           not page.evaluate("document.querySelector('#navSheet .box').classList.contains('lbr-entering')"))
        shown = [r for r in f if r["drawer"] == "block"]
        worst = max((abs(r["header"] - (r["box"] + N)) for r in shown), default=0)
        ok(tag + "drawer: the page (card) moves with the drawer edge every frame", worst < 1, f"worst {worst:.2f}px over {len(shown)} frames")
        worst = max((abs(r["kid"] + r["box"]) for r in shown), default=0)
        ok(tag + "drawer: its contents stay still while revealed", worst < 1, f"worst {worst:.2f}px")
        mid = [r for r in shown if 5 < r["header"] < N - 5]
        ok(tag + "drawer: slides (frames in between)" if not reduced else tag + "drawer: no slide with Reduce Motion",
           (len(mid) >= 3) if not reduced else (len(mid) == 0), f"{len(mid)} in-between frames")
        if shots_dir and not reduced:
            shot("drawer_open.png")
        h0 = state()["haptics"]; rec(); finger.tap(W - 20, 420); wait(800); f = frames(); s = state()
        ok(tag + "drawer closes on a tap on the visible strip", "navSheet" not in s["overlays"] and s["drawer"] == "none" and not s["header"],
           (s["overlays"], s["drawer"], s["header"]))
        ok(tag + "drawer: one tick on closing", s["haptics"] - h0 == 1, s["haptics"] - h0)
        shown = [r for r in f if r["drawer"] == "block"]
        worst = max((abs(r["header"] - (r["box"] + N)) for r in shown), default=0)
        bad = [(i, r["t"] - f[0]["t"], round(r["header"], 1), round(r["box"], 1), r["cls"]) for i, r in enumerate(f) if r["drawer"] == "block" and abs(r["header"] - (r["box"] + N)) >= 1]
        ok(tag + "drawer: card and drawer stay together while closing", worst < 1, f"worst {worst:.2f}px; frames (i, ms, header, box, body): {bad[:6]}")
        widths = sorted({r["iw"] for r in f})
        ok(tag + "drawer: the page never widens or zooms out while closing", widths == [W], widths)
        ok(tag + "drawer: no sideways scroll left behind", s["sx"] == 0, s["sx"])

        if not reduced:
            # -- edge pull, held halfway for a picture; then pushed shut from inside the drawer
            h0 = state()["haptics"]
            finger.drag([(4, 420), (40, 420), (90, 420), (150, 420), (210, 420)], hold=(3, 150, lambda: shot("drawer_halfway.png")))
            wait(700); s = state()
            ok("edge pull opens the drawer", "navSheet" in s["overlays"], s["overlays"])
            ok("edge pull: one tick", s["haptics"] - h0 == 1, s["haptics"] - h0)
            ok("pulled open: no arriving one after another (the rows were on show under the finger)", not page.evaluate("document.querySelector('#navSheet .box').classList.contains('lbr-entering')"))
            h0 = s["haptics"]
            finger.drag([(230, 420), (200, 420), (150, 420), (90, 420), (40, 420)])
            wait(700); s = state()
            ok("pushing the drawer left closes it", "navSheet" not in s["overlays"] and s["drawer"] == "none", (s["overlays"], s["drawer"]))
            ok("push close: one tick", s["haptics"] - h0 == 1, s["haptics"] - h0)
            # -- a short, slow edge pull springs back
            h0 = s["haptics"]
            finger.drag([(4, 420), (18, 420), (30, 420), (38, 420)], step=70)
            wait(700); s = state()
            ok("a short pull springs back closed", "navSheet" not in s["overlays"] and s["drawer"] == "none" and not s["header"], (s["drawer"], s["header"]))
            ok("short pull: no tick", s["haptics"] - h0 == 0, s["haptics"] - h0)
            # -- swipe right from the middle of the list; close with X
            h0 = s["haptics"]
            finger.drag([(160, 520), (172, 521), (205, 523), (255, 525), (320, 527)])
            wait(700); s = state()
            ok("a rightward swipe on the list opens the drawer", "navSheet" in s["overlays"], s["overlays"])
            finger.tap(*center(page, "#navSheet .sh-head button")); wait(700); s = state()
            ok("the X closes it", "navSheet" not in s["overlays"] and s["drawer"] == "none", (s["overlays"], s["drawer"]))
            ok("swipe open + X close: two ticks", s["haptics"] - h0 == 2, s["haptics"] - h0)
            # -- on a scrolled list: the sticky header stays at the top and the scroll position is kept
            page.evaluate("window.scrollTo(0, 900)"); wait(300)
            finger.tap(*menu); wait(700)
            s1 = page.evaluate("({sy: scrollY, top: Math.round(document.querySelector('body>header').getBoundingClientRect().top), html: document.documentElement.style.overflow, body: document.body.style.overflow})")
            ok("drawer over a scrolled list: the header stays stuck to the top, scroll kept", s1["top"] == 0 and s1["sy"] == 900, s1)
            finger.tap(W - 20, 420); wait(800)
            s2 = page.evaluate("({sy: scrollY, html: document.documentElement.style.overflow, body: document.body.style.overflow})")
            ok("drawer closed: scroll position kept and the page unlocked", s2["sy"] == 900 and s2["html"] == "" and s2["body"] == "", s2)
            # -- the drawer's tree: Codex and Claude, under each its projects, under each project its conversations
            finger.tap(*menu); wait(900)  # opening the drawer reads /api/chat/projects
            rows = lambda: page.evaluate("""[...document.querySelectorAll('#navSheet .tree-row')].filter(r => !r.closest('.tree-group:not(.open) > .tree-kids')).map(r => [r.classList[1],
              r.querySelector('.tree-name')?.firstChild?.textContent || '', r.getAttribute('aria-expanded')])""")
            t = rows()
            ok("the drawer lists Codex and Claude, each with its projects, folded", t == [
                ["tree-app", "Codex", "true"], ["tree-proj", "示例项目", "false"], ["tree-proj", "quant", "false"], ["tree-proj", "其他对话", "false"],
                ["tree-app", "Claude", "true"], ["tree-proj", "notes_app", "false"], ["tree-proj", "其他对话", "false"]], t)
            before = page.evaluate("document.getElementById('lbrTapSource').checked")
            finger.tap(*center(page, "#navSheet .tree-proj >> nth=0")); wait(400); t = rows()
            ok("tapping a project unfolds it: its 10 newest conversations, then 显示更多",
               t[1] == ["tree-proj", "示例项目", "true"] and [r[0] for r in t[2:13]] == ["tree-item"] * 10 + ["tree-more"]
               and t[12][1] == "显示更多（还有 15 个）", t[:14])
            ok("the tap reaches the shared switch (the iPhone's tick)", page.evaluate("document.getElementById('lbrTapSource').checked") != before)
            running = page.evaluate("[...document.querySelectorAll('#navSheet .tree-item')].filter(r => r.querySelector('.tree-dot')).map(r => r.querySelector('.tree-name').firstChild.textContent)")
            ok("a running conversation has the green dot", running == ["lq 对话 1"], running)
            page.evaluate("document.querySelector('#navSheet .tree-more').scrollIntoView({block: 'center'})"); wait(200)
            finger.tap(*center(page, "#navSheet .tree-more")); wait(600); t = rows()
            ok("显示更多 adds the rest of the project", sum(r[0] == "tree-item" for r in t) == 25 and not any(r[0] == "tree-more" for r in t),
               sum(r[0] == "tree-item" for r in t))
            page.evaluate("document.querySelector('#navSheet .nav-links').scrollTop = 0"); wait(200)
            finger.tap(*center(page, "#navSheet .tree-app >> nth=0")); wait(400); t = rows()
            ok("tapping Codex folds all of Codex", t == [["tree-app", "Codex", "false"], ["tree-app", "Claude", "true"], ["tree-proj", "notes_app", "false"],
                                                    ["tree-proj", "其他对话", "false"]], t)
            finger.tap(*center(page, "#navSheet .tree-app >> nth=0")); wait(400); t = rows()
            ok("and unfolds it with 示例项目 still open", t[1] == ["tree-proj", "示例项目", "true"] and sum(r[0] == "tree-item" for r in t) == 25, t[:3])
            kept = page.evaluate("JSON.parse(localStorage.getItem('lbr_sidebar_folds'))")
            ok("the folds are kept on this phone", kept == {"p:codex|p-lq": True, "app:codex": True}, kept)
            # -- a project's ＋: 新建对话 with that app and project filled in; 其他对话's ＋: a conversation in no project
            pluses = page.evaluate("[...document.querySelectorAll('#navSheet .tree-proj')].map(r => [r.querySelector('.tree-name').textContent, !!r.querySelector('.tree-add')])")
            ok("every project has a ＋, 其他对话 too", len(pluses) == 5 and all(has for _, has in pluses), pluses)
            before = page.evaluate("document.getElementById('lbrTapSource').checked")
            folds = page.evaluate("localStorage.getItem('lbr_sidebar_folds')")
            finger.tap(*center(page, "#navSheet .tree-proj >> nth=0 >> .tree-add")); wait(700); s = state()
            sheet = page.evaluate("""({app: document.getElementById('newCodex').getAttribute('aria-checked'), name: document.getElementById('newFolderName').textContent,
              path: document.getElementById('newFolderPath').textContent})""")
            ok("示例项目's ＋ opens 新建对话 over the drawer, Codex and 示例项目 filled in", s["overlays"] == ["navSheet", "newSheet"]
               and sheet == {"app": "true", "name": "示例项目", "path": "D:/Projects/示例项目"}, (s["overlays"], sheet))
            back = page.evaluate("""[...document.querySelectorAll('body>header, #navSheet .box')].map(n => [n.classList.contains('lbr-receded'), getComputedStyle(n).scale])""")
            ok("the sheet steps the drawer and the page behind it back", back == [[True, "0.94"], [True, "0.94"]], back)
            ok("the ＋ leaves the fold alone and its tap reaches the tick switch",
               page.evaluate("localStorage.getItem('lbr_sidebar_folds')") == folds and page.evaluate("document.getElementById('lbrTapSource').checked") != before)
            page.evaluate("closeSheet('newSheet')"); wait(500)
            page.evaluate("document.querySelectorAll('#navSheet .tree-proj')[4].scrollIntoView({block: 'center'})"); wait(200)
            finger.tap(*center(page, "#navSheet .tree-proj >> nth=4 >> .tree-add")); wait(700)
            sheet = page.evaluate("({claude: document.getElementById('newClaude').getAttribute('aria-checked'), name: document.getElementById('newFolderName').textContent})")
            ok("Claude's 其他对话 ＋ starts one in no project", sheet == {"claude": "true", "name": "无项目"}, sheet)
            page.evaluate("document.getElementById('newFolderChoice').click()"); wait(600)
            first = page.evaluate("document.querySelector('#newPickerResults .new-pick-row')?.firstChild?.textContent")
            ok("the project list in 新建对话 starts with 无项目", first == "无项目", first)
            page.evaluate("closeSheet('newPicker'); closeSheet('newSheet')"); wait(600)
            back = page.evaluate("""[...document.querySelectorAll('body>header, #navSheet .box')].map(n => [n.classList.contains('lbr-receded'), getComputedStyle(n).scale])""")
            ok("and they come forward again when it goes", back == [[False, "none"], [False, "none"]], back)
            # -- a project opens by growing, its folder lifting its front; the icons have depth and colour
            looks = page.evaluate("""({marks: [...document.querySelectorAll('#navSheet .tree-app .mark')].length, folders: [...document.querySelectorAll('#navSheet .tree-proj .fd:not(.loose) .face')].map(f => getComputedStyle(f).fill),
              loose: document.querySelectorAll('#navSheet .tree-proj .fd.loose').length})""")
            ok("each app has its mark, each project a grey layered folder (all the same grey), 其他对话 its bubbles",
               looks["marks"] == 2 and len(looks["folders"]) == 3 and len(set(looks["folders"])) == 1 and looks["loose"] == 2, looks)
            kids = "document.querySelectorAll('#navSheet .tree-proj')[1].parentElement.querySelector(':scope>.tree-kids').offsetHeight"
            finger.tap(*center(page, "#navSheet .tree-proj >> nth=1"))
            mid = page.evaluate("new Promise(r => setTimeout(() => r(" + kids + "), 100))"); wait(700); end = page.evaluate(kids)
            lid = page.evaluate("getComputedStyle(document.querySelectorAll('#navSheet .tree-proj')[1].querySelector('.fd .front')).transform")
            ok("a project opens by growing, not in one jump", 0 < mid < end, (mid, end))
            ok("and its folder lifts its front", lid not in ("none", ""), lid)
            finger.tap(*center(page, "#navSheet .tree-proj >> nth=1")); wait(600)
            page.evaluate("document.querySelector('#navSheet .nav-links').scrollTop = 0"); wait(200)
            page.evaluate("document.querySelectorAll('#navSheet .tree-item')[1].scrollIntoView({block: 'center'})"); wait(200)
            rec(); finger.tap(*center(page, "#navSheet .tree-item >> nth=1")); wait(900); f = frames(); s = state()
            ok("tapping a conversation opens it", s["cur"] == "lq2" and s["view"] == "flex" and "navSheet" not in s["overlays"], (s["cur"], s["view"], s["overlays"]))
            shown = [r for r in f if r["view"] is not None]
            ok("the chat is in place at once, not slid in from the right", bool(shown) and all(abs(r["view"]) < 1 for r in shown), [r["view"] for r in shown][:6])
            sliding = [r for r in shown if r["drawer"] == "block" and -N + 5 < r["box"] < -5]
            ok("and the drawer slides away over it", len(sliding) >= 3 and s["drawer"] == "none", f"{len(sliding)} in-between frames, drawer {s['drawer']}")
            shot("tree_open_chat.png")
            finger.tap(*center(page, ".cv-top .back")); wait(900)
            ok("back to the list", state()["cur"] is None and page.evaluate("mode") == "chat", state()["cur"])
            # -- 设置: the gear at the foot of the drawer; 录音后自动整理 is a real switch; 语音词典 opens over it
            gone = page.evaluate("""({nav: [...document.querySelectorAll('#navSheet [data-nav]')].map(b => b.dataset.nav),
              parts: document.querySelectorAll('[data-mode~="browser"], [data-mode~="win"], [data-mode~="tasks"], .task-shortcut, #winSel, #elList, #picker').length,
              tidyInBar: !!document.querySelector('.rec-tidy'), menuTerms: document.getElementById('convMenu').textContent.includes('语音词典')})""")
            ok("the drawer's one page is 对话 (no 任务, browser or window parts); no 整理 in the recording bar, no 语音词典 in the chat menu",
               gone == {"nav": ["chat"], "parts": 0, "tidyInBar": False, "menuTerms": False}, gone)
            page.evaluate("localStorage.removeItem('lbr_setting_voice_tidy')")
            finger.tap(*menu); wait(700)
            gear = page.evaluate("""(() => { const b = document.getElementById('settingsBtn').getBoundingClientRect(), d = document.querySelector('#navSheet .box').getBoundingClientRect();
              return {right: Math.round(d.right - b.right), bottom: Math.round(d.bottom - b.bottom), tick: !!document.querySelector('#settingsBtn > input.tap-tick[switch]')}; })()""")
            ok("the gear sits at the drawer's bottom right, with a switch over it for the tick", gear["right"] <= 24 and gear["bottom"] <= 40 and gear["tick"], gear)
            finger.tap(*center(page, "#settingsBtn")); wait(700); s = state()
            ok("the gear opens 设置 over the drawer", s["overlays"] == ["navSheet", "settingsSheet"], s["overlays"])
            sw = page.evaluate("(() => { const s = document.getElementById('voiceTidySwitch'); return {real: s.type === 'checkbox' && s.hasAttribute('switch'), on: s.checked, label: s.closest('label').textContent.trim()}; })()")
            ok("录音后自动整理 is a real switch, on unless turned off before", sw == {"real": True, "on": True, "label": "录音后自动整理"}, sw)
            h0 = state()["haptics"]; finger.tap(*center(page, "#voiceTidySwitch")); wait(300)
            after = page.evaluate("({on: document.getElementById('voiceTidySwitch').checked, saved: localStorage.getItem('lbr_setting_voice_tidy')})")
            ok("a finger on the switch turns 整理 off and it is remembered", after == {"on": False, "saved": "0"}, after)
            ok("the switch ticks (Android: vibrate; on the iPhone the switch itself ticks)", state()["haptics"] - h0 == 1, state()["haptics"] - h0)
            finger.tap(*center(page, "#settingsBody label.setting-row > span")); wait(300)
            ok("a tap on the row's words turns it back on", page.evaluate("localStorage.getItem('lbr_setting_voice_tidy')") == "1")
            finger.tap(*center(page, "#settingsBody button.setting-row:has-text('语音词典')")); wait(700); s = state()  # 已归档对话 is first (10-20)
            ok("语音词典 opens over 设置", s["overlays"] == ["navSheet", "settingsSheet", "voiceTermsSheet"], s["overlays"])
            page.evaluate("closeSheet('voiceTermsSheet')"); wait(500)
            shot("settings.png")
            finger.tap(*center(page, "#settingsSheet .sh-head button")); wait(600); s = state()
            ok("closing 设置 goes back to the drawer", s["overlays"] == ["navSheet"], s["overlays"])
            finger.tap(W - 20, 420); wait(800)
            ok("and the drawer closes as before", state()["drawer"] == "none", state()["drawer"])
            # -- a vertical swipe stays a scroll
            sy0 = s["sy"]
            finger.drag([(200, 720), (202, 640), (204, 520), (205, 380), (206, 260)])
            wait(600); s = state()
            ok("a vertical swipe does not open the drawer", "navSheet" not in s["overlays"] and s["drawer"] == "none", s["drawer"])
            ok("a vertical swipe scrolls the list", s["sy"] != sy0, f"scrollY {sy0} -> {s['sy']}")
            wait(1500)  # let the fling stop: a tap during momentum scrolling only stops it
            page.evaluate("window.scrollTo(0, 0)"); wait(300)

        # -- tap a row: the chat is pushed in over the list
        row = center(page, ".conv >> nth=2")
        page.evaluate("(() => { const open = window.openConv; window.__opens = 0; window.openConv = (...a) => { window.__opens++; return open(...a); }; window.__tapBefore = document.getElementById('lbrTapSource').checked; })()")
        rec(); finger.tap(*row); wait(800); f = frames(); s = state()
        ok(tag + "tapping a row opens the chat", s["cur"] is not None and s["view"] == "flex", s["cur"])
        taps = page.evaluate("({opens: window.__opens, flipped: document.getElementById('lbrTapSource').checked !== window.__tapBefore})")
        ok(tag + "the row's label passes the tap on to the shared switch (the iPhone's tick) and the chat opens once", taps == {"opens": 1, "flipped": True}, taps)
        ok(tag + "chat open: back at rest (list hidden, no motion classes, no inline transform)",
           "chat-open" in s["cls"] and "chat-motion" not in s["cls"] and s["headerVis"] == "hidden" and not s["viewT"], (s["cls"], s["headerVis"], s["viewT"]))
        moving = [r for r in f if r["view"] is not None and 1 < r["view"] < W - 1]
        ok(tag + "chat open: slides in" if not reduced else tag + "chat open: no slide with Reduce Motion",
           (len(moving) >= 3) if not reduced else (len(moving) == 0), f"{len(moving)} in-between frames")
        worst = max((abs(r["header"] - (-0.3 * (W - r["view"]))) for r in moving), default=0)
        ok(tag + "chat open: the list moves 30% behind it (parallax)", worst < 2, f"worst {worst:.2f}px")
        worst = max((abs(r["shield"] - 0.1 * (1 - r["view"] / W)) for r in moving), default=0)
        ok(tag + "chat open: the list dims with it", worst < 0.02, f"worst {worst:.3f}")

        # -- the back button: the chat slides out the way it came
        back = center(page, 'button[aria-label="返回对话列表"]')
        rec(); finger.tap(*back); wait(800); f = frames(); s = state()
        ok(tag + "back button closes the chat", s["cur"] is None and s["view"] == "none" and "chat-motion" not in s["cls"] and s["headerVis"] == "visible",
           (s["cur"], s["view"], s["cls"]))
        moving = [r for r in f if r["view"] is not None and 1 < r["view"] < W - 1]
        ok(tag + "back button: slides out" if not reduced else tag + "back button: no slide with Reduce Motion",
           (len(moving) >= 3) if not reduced else (len(moving) == 0), f"{len(moving)} in-between frames")
        worst = max((abs(r["header"] - (-0.3 * (W - r["view"]))) for r in moving), default=0)
        ok(tag + "back button: list parallax", worst < 2, f"worst {worst:.2f}px")
        ok(tag + "after closing: no leftover transform on the list", not page.evaluate("[...document.querySelectorAll('body>header,body>section')].some(n => n.style.transform)"))

        if not reduced:
            # -- back drag committed: one tick, and the chat never comes back on screen (no flash)
            finger.tap(*row); wait(800)
            page.evaluate("document.getElementById('cvText').focus()"); wait(100)
            page.evaluate("navigationUI.haptic()")
            ok("a tick keeps the text box focused (the keyboard would stay)", state()["active"] == "cvText", state()["active"])
            page.evaluate("document.activeElement.blur()")
            h0 = state()["haptics"]; rec()
            finger.drag([(4, 420), (50, 420), (120, 420), (200, 420), (280, 420)], hold=(3, 150, lambda: shot("chat_back_halfway.png")))
            wait(1000); f = frames(); s = state()
            ok("back drag closes the chat", s["cur"] is None and s["view"] == "none", (s["cur"], s["view"]))
            ok("back drag: one tick", s["haptics"] - h0 == 1, s["haptics"] - h0)
            out, flash = False, 0
            for r in f:
                if r["view"] is not None and r["view"] > 0.9 * W:
                    out = True
                if out and r["view"] is not None and r["view"] < 0.9 * W:
                    flash += 1
            ok("back drag: the chat never comes back after leaving (no flash)", flash == 0, f"{flash} frames")
            # -- back drag too short: springs back, stays open
            finger.tap(*row); wait(800); h0 = state()["haptics"]
            finger.drag([(4, 420), (20, 420), (34, 420), (44, 420)], step=70)
            wait(800); s = state()
            ok("a short back drag springs back", s["cur"] is not None and "chat-motion" not in s["cls"] and not s["viewT"], (s["cur"], s["cls"], s["viewT"]))
            ok("short back drag: no tick", s["haptics"] - h0 == 0, s["haptics"] - h0)
            # -- the send button ticks once
            h0 = s["haptics"]
            page.evaluate("document.getElementById('cvText').value='测试'; updateSendButton()")
            finger.tap(*center(page, "#cvBtn")); wait(300)
            ok("the send button ticks once", state()["haptics"] - h0 == 1, state()["haptics"] - h0)
            # -- the microphone: one tick on press, one on the ✓
            h0 = state()["haptics"]
            mic = center(page, ".mic-btn")
            finger.tap(*mic); wait(1200)
            t1 = state()["haptics"] - h0
            mic = center(page, ".mic-btn")  # while recording the button moves right and becomes the ✓
            finger.tap(*mic); wait(600)
            t2 = state()["haptics"] - h0
            ok("microphone: a tick when recording starts and when it finishes", (t1, t2) == (1, 2), f"after press {t1}, after ✓ {t2}")
            finger.tap(*back); wait(800)

        if not reduced:
            # -- iPhone ticks: a see-through switch over each key button; a tap lands on it, then the button acts
            page.evaluate("window.scrollTo(0, 0)"); wait(100)
            missing = page.evaluate("""['#cvBtn', '#newBtn', 'header button[aria-label="打开导航"]', '#navSheet .sh-head button', '#settingsBtn', '.mic-btn', '.cv-top .back', '.stop-turn',
                '#addImageBtn', '#claudeReferenceAdd', '#newAdd', '#modelChoice', '#modeChoice', '#claudeComposerTools .composer-chip']
                .filter(s => !document.querySelector(s + ' > input.tap-tick[switch]'))""")
            ok("a see-through switch sits over send, new-chat send, menu, drawer close, settings, microphone, back, stop, both +'s and the model/mode chips", not missing, missing)
            chips = page.evaluate("[...document.querySelectorAll('.composer-tools button')].filter(c => !c.querySelector(':scope > .tap-tick')).map(c => c.id || c.textContent)")
            ok("every button in both input-box toolbars (+, model, mode) has its switch", not chips, chips)
            rows = page.evaluate("""(() => { const rows = [...document.querySelectorAll('#convList .conv')];
                return {switches: document.querySelectorAll('#convList input').length, unlabelled: rows.filter(r => r.querySelector(':scope > label.tap-label')?.htmlFor !== 'lbrTapSource').length,
                        source: (s => s && s.parentNode === document.documentElement && getComputedStyle(s).pointerEvents === 'none')(document.getElementById('lbrTapSource'))}; })()""")
            ok("list rows: no switch under the finger (it took every swipe on the iPhone); a label on each row points at the one switch outside <body>",
               rows == {"switches": 0, "unlabelled": 0, "source": True}, rows)
            menu_switch = "document.querySelector('header button[aria-label=\"打开导航\"] > .tap-tick').checked"
            before = page.evaluate(menu_switch)
            finger.tap(*menu); wait(700)
            ok("tapping the menu button lands on its switch and still opens the drawer", page.evaluate(menu_switch) != before and "navSheet" in state()["overlays"])
            ok("the visible strip of the card is a switch too", page.evaluate("!!document.querySelector('#navSheet > input.nav-strip[switch]')"))
            finger.tap(*center(page, "#navSheet .sh-head button")); wait(800)
            ok("the drawer's close button (with its switch) closes it", state()["overlays"] == [] and state()["drawer"] == "none", state()["overlays"])
            # -- menus that pop up (the + menu) tick on their items too
            page.evaluate("openSheet('attachmentMenu', document.getElementById('addImageBtn'))"); wait(500)
            rows = page.evaluate("[...document.querySelectorAll('#attachmentMenu .menu-row')].map(b => [b.textContent, !!b.querySelector(':scope > .tap-tick')])")
            ok("the + menu's items (拍照 / 从相册选择) have switches", rows and all(r[1] for r in rows), rows)
            page.evaluate("closeSheet('attachmentMenu')"); wait(400)

            # -- Claude asks: a one-line strip above the message box; a sheet with the question and each choice
            page.wait_for_function("!document.querySelector('.voice-pill.show')", timeout=15000)  # the microphone test's 没听清 sits there up to 7 s
            finger.tap(*center(page, ".conv >> nth=0")); wait(1500)  # c1 is a Claude conversation that is asking
            pill = page.evaluate("document.querySelector('#cvOpts .ask-pill')?.textContent || ''")
            ok("a Claude question shows as a one-line strip above the message box", "手机上用哪种方式出现比较顺手" in pill and "1/2" in pill, pill)
            height = page.evaluate("document.getElementById('cvOpts').getBoundingClientRect().height")
            ok("the strip does not crowd the conversation (one line)", height < 70, height)
            px, py = center(page, "#cvOpts .ask-pill")
            hit = page.evaluate(f"(() => {{ const e = document.elementFromPoint({px}, {py}); if (!e) return null; const host = e.closest('[id]'); return (e.className || e.tagName) + ' in #' + (host && host.id) + ': ' + (e.closest('button,div') || e).outerHTML.slice(0, 140).replace(/'/g, ''); }})()")
            finger.tap(px, py); wait(700)
            sheet = page.evaluate("""(() => { const s = document.getElementById('claudeAskSheet');
                return {hit: '""" + str(hit) + """', overlays: overlays.map(o => o.id), top: overlays.at(-1)?.id, title: s.querySelector('.ask-title')?.textContent, progress: s.querySelector('.ask-progress').textContent,
                        choices: [...s.querySelectorAll('.ask-choice')].map(b => [b.querySelector('b').textContent, b.querySelector('small')?.textContent || '', !!b.querySelector(':scope > .tap-tick')]),
                        nav: [...s.querySelectorAll('.ask-nav button')].map(b => b.textContent)}; })()""")
            ok("tapping the strip opens the sheet with the question and progress",
               sheet["top"] == "claudeAskSheet" and sheet["title"] == "手机上用哪种方式出现比较顺手？" and sheet["progress"] == "1/2", sheet)
            ok("each choice shows its label and description, with a switch for the tick",
               sheet["choices"] == [["选项 A", "说明 A", True], ["选项 B", "说明 B", True], ["选项 C", "说明 C", True]], sheet["choices"])
            ok("navigation reads 不回答 / 跳过 / 下一题", sheet["nav"] == ["不回答", "跳过", "下一题"], sheet["nav"])
            page.evaluate("window.__askStatusSeen = false; new MutationObserver(() => { if (document.querySelector('.ask-choice.is-choosing .ask-status')) window.__askStatusSeen = true; })"
                          ".observe(document.body, {subtree: true, childList: true})")
            h0 = state()["haptics"]
            finger.tap(*center(page, "#claudeAskSheet .ask-choice >> nth=1")); wait(1800)
            ok("the tapped choice says 正在电脑上点选… while the PC clicks", page.evaluate("window.__askStatusSeen"))
            ok("the choice sent is the one tapped", CHOSEN["tokens"] == ["t2"], CHOSEN["tokens"])
            gone = page.evaluate("({sheet: overlays.some(o => o.id === 'claudeAskSheet'), pill: !!document.querySelector('#cvOpts .ask-pill'), toast: document.getElementById('toast').textContent})")
            ok("when the PC is done the sheet closes and the strip goes", not gone["sheet"] and not gone["pill"] and "已选：选项 B" in gone["toast"], gone)
            ok("Android vibrates on that tap too (the iPhone ticks from the switch)", state()["haptics"] - h0 == 1, state()["haptics"] - h0)
            finger.tap(*back); wait(900)

            # -- Codex asks the same way (10-12): the strip above the message box, the sheet one question at a time
            finger.tap(*center(page, ".conv >> nth=1")); wait(1500)  # c2 is a Codex conversation asking two questions
            looks = page.evaluate("""({pill: document.querySelector('#cvOpts .codex-ask')?.textContent || '', form: !!document.querySelector('#cvMsgs .codex-card fieldset, #cvMsgs .question-block'),
                bar: document.getElementById('cvPending').hidden ? '' : document.getElementById('cvPending').textContent})""")
            ok("a Codex question shows as the strip above the message box, not as a form in the conversation",
               "方案" in looks["pill"] and "2 个问题" in looks["pill"] and not looks["form"], looks)
            ok("the bar under the title says Codex is waiting", looks["bar"] == "Codex 有待处理操作 · 查看", looks["bar"])
            finger.tap(*center(page, "#cvOpts .codex-ask")); wait(700)
            sheet = lambda: page.evaluate("""(() => { const s = document.getElementById('codexAskSheet');
                return {top: overlays.at(-1)?.id, progress: s.querySelector('.ask-progress').textContent, head: s.querySelector('.ask-head')?.textContent || '',
                        title: s.querySelector('.ask-title')?.textContent, review: [...s.querySelectorAll('.ask-review button')].map(b => [b.querySelector('small').textContent, b.querySelector('b').textContent]),
                        choices: [...s.querySelectorAll('.ask-choice')].map(b => [b.querySelector('b').textContent, b.querySelector('small')?.textContent || '', b.getAttribute('aria-checked'), !!b.querySelector(':scope > .tap-tick')]),
                        next: s.querySelector('.ask-nav button.big')?.textContent || '', nextOff: !!s.querySelector('.ask-nav button.big')?.disabled}; })()""")
            s1 = sheet()
            ok("tapping the strip opens the sheet on the first question, 1/2", s1["top"] == "codexAskSheet" and s1["progress"] == "1/2" and s1["head"] == "方案" and s1["title"] == "先做哪一个？", s1)
            ok("each choice shows its label and description with a switch for the tick, then 自行填写",
               s1["choices"] == [["选项 A", "说明 A", "false", True], ["选项 B", "说明 B", "false", True], ["自行填写", "", "false", True]], s1["choices"])
            finger.tap(*center(page, "#codexAskSheet .ask-choice >> nth=1")); wait(300)
            ok("choice alone does not submit or advance", not ANSWERS and sheet()["progress"] == "1/2")
            finger.tap(*center(page, "#codexAskSheet .ask-nav button.big")); wait(500); s2 = sheet()
            ok("a tap on a choice answers that question and moves on to the next, 2/2", s2["progress"] == "2/2" and s2["title"] == "改到哪里为止？" and not ANSWERS, (s2["progress"], s2["title"], ANSWERS))
            finger.tap(*center(page, "#codexAskSheet .ask-choice >> nth=1")); wait(400); s3 = sheet()
            typed = page.evaluate("document.activeElement?.classList.contains('ask-other')")
            ok("自行填写 opens a text box with the keyboard; 完成 waits for some text", typed and s3["next"] == "完成" and s3["nextOff"], (typed, s3["next"], s3["nextOff"]))
            page.locator("#codexAskSheet .ask-other").fill("改完测试为止"); wait(200)
            finger.tap(*center(page, "#codexAskSheet .ask-nav button.big")); wait(500); s4 = sheet()
            ok("完成 lists both answers to check before sending", s4["progress"] == "核对" and s4["review"] == [["1. 方案", "选项 B"], ["2. 范围", "改完测试为止"]] and s4["next"] == "提交答案", s4)
            finger.tap(*center(page, "#codexAskSheet .ask-nav button.big")); wait(1800)
            sent = ANSWERS[-1] if ANSWERS else {}
            ok("提交 sends both answers once, for this question card", len(ANSWERS) == 1 and sent.get("id") == "c2" and sent.get("question_id") == "native:t1:7"
               and sent.get("answers") == {"q1": ["选项 B"], "q2": ["改完测试为止"]}, ANSWERS)
            gone = page.evaluate("({sheet: overlays.some(o => o.id === 'codexAskSheet'), pill: !!document.querySelector('#cvOpts .codex-ask'), toast: document.getElementById('toast').textContent, bar: document.getElementById('cvPending').hidden})")
            ok("then the sheet closes, the strip and the bar go", not gone["sheet"] and not gone["pill"] and gone["bar"] and "答案已提交给 Codex" in gone["toast"], gone)
            finger.tap(*back); wait(900)
            finger.tap(*center(page, ".conv >> nth=3")); wait(1500)  # c4 asks one question
            finger.tap(*center(page, "#cvOpts .codex-ask")); wait(700)
            one = sheet()
            ok("one question: no progress, no 提交 button", one["progress"] == "" and one["next"] == "提交答案" and one["nextOff"] and one["title"] == "要现在执行吗？", one)
            finger.tap(*center(page, "#codexAskSheet .ask-choice >> nth=0")); wait(300)
            ok("single choice is only a draft", len(ANSWERS) == 1)
            finger.tap(*center(page, "#codexAskSheet .ask-nav button.big")); wait(1500)
            ok("one question: explicit submit sends the answer", len(ANSWERS) == 2 and ANSWERS[-1].get("answers") == {"only": ["执行"]}, ANSWERS[-1:])
            ok("and the sheet closes with 已选：执行", not page.evaluate("overlays.some(o => o.id === 'codexAskSheet')") and "已选：执行" in page.evaluate("document.getElementById('toast').textContent"))
            finger.tap(*back); wait(900)

        # -- a bottom sheet slides up and can be dragged down
        page.evaluate("window.scrollTo(0, 0)"); wait(100)
        rec(); finger.tap(*center(page, 'button[aria-label="新建对话"]')); wait(800); f = frames()
        top = page.evaluate("overlays.at(-1)?.id")
        ok(tag + "the new-chat sheet opens", bool(top), top)
        mid = [r for r in f if r["sheet"] is not None and 5 < r["sheet"] < r["sheetH"] - 5]  # strictly between open (0) and closed (its height)
        ok(tag + "sheet slides up (the opening animation is no longer skipped)" if not reduced else tag + "sheet: no slide with Reduce Motion",
           (len(mid) >= 3) if not reduced else (len(mid) == 0), f"{len(mid)} in-between frames")
        if not reduced:
            hx, hy = center(page, f"#{top} .sh-head")
            finger.drag([(hx, hy), (hx, hy + 40), (hx, hy + 120), (hx, hy + 240), (hx, hy + 380)], hold=(2, 120, lambda: shot("sheet_halfway.png")))
            wait(800)
            gone = page.evaluate(f"!overlays.some(o => o.id === '{top}') && document.getElementById('{top}').style.display === 'none'")
            ok("dragging the sheet's title row down closes it", gone)
        else:
            page.evaluate(f"closeSheet('{top}')"); wait(200)

        nav_errors = [e for e in errors if "navigation-ui" in e]
        ok(tag + "no page errors from navigation-ui.js", not nav_errors, nav_errors[:3])
        if errors:
            print(f"   ({len(errors)} page error(s) elsewhere, from the fake data: {errors[:2]})")
        browser.close()


FAKE_VV = r"""
(() => {  // a visual viewport the test moves by hand, like Safari's when the keyboard comes up
  const fake = new EventTarget(); let vh = null, vo = 0;
  const props = {height: () => vh ?? innerHeight, width: () => innerWidth, offsetTop: () => vo, offsetLeft: () => 0, pageTop: () => scrollY + vo, pageLeft: () => scrollX, scale: () => 1};
  for (const [k, get] of Object.entries(props)) Object.defineProperty(fake, k, {get});
  Object.defineProperty(window, 'visualViewport', {configurable: true, get: () => fake});
  window.__vv = {set(h, o) { vh = h; vo = o; fake.dispatchEvent(new Event('resize')); fake.dispatchEvent(new Event('scroll')); }};
})();
"""
def modes(current):  # the desktop's mode menu as read on 10-12; Auto gets a "Recommended" while another mode is on
    auto = "Auto Claude handles permission decisions" if current == "Auto" else "Auto Recommended Claude handles permission decisions"
    return [{"name": n, "type": "RadioButtonControl"} for n in (auto, "Manual Always ask before making changes", "Plan Create a plan before making changes")]
MODES = modes("Auto")


def run_fixes(check):
    """10-11 fixes: a page file that fails to load, a keyboard Safari does not move the view for, the mode list at once."""
    ok = check
    seen = {"page": 0, "claude_ui": 0, "fail_claude_ui": "once", "debug": [], "menu": 0, "setting": [], "modes": True}
    mode = {"label": "Auto"}

    def handle_fixes(route, request):
        u = urlsplit(request.url)
        js = lambda obj, status=200: route.fulfill(status=status, content_type="application/json; charset=utf-8", body=json.dumps(obj, ensure_ascii=False))
        state = lambda: ({"settings": {"model": "claude-opus-5-5", "effort": "max", "mode": "auto"}, "available": False, "on_screen": False,
                          "recorded_label": "Opus 5.5", "actions": [], "mode_options": MODES} if seen.get("away") else
                         {"settings": {"mode": "plan" if mode["label"] == "Plan" else "auto"}, "available": True, "actions": [], "mode_label": mode["label"],
                          **({"mode_options": modes(mode["label"])} if seen["modes"] else {})})
        if u.path == "/":
            seen["page"] += 1
        if u.path == "/claude-ui.js":
            seen["claude_ui"] += 1
            if seen["fail_claude_ui"] == "always" or (seen["fail_claude_ui"] == "once" and seen["claude_ui"] == 1):
                return route.fulfill(status=502, body="")  # what Tailscale answered when the service turned a connection away
        if u.path == "/api/debug/client":
            seen["debug"].append(json.loads(request.post_data or "{}"))
            return js({"ok": True})
        if u.path == "/api/claude/state":
            return js(state())
        if u.path == "/api/chat/open":
            seen["opened"] = seen.get("opened", 0) + 1
            return js({"ok": True, "text": "电脑上已打开"})
        if u.path == "/api/claude/menu":
            seen["menu"] += 1
            return js({"items": [{**m, "selected": False, "token": f"m{i}"} for i, m in enumerate(MODES)], "notice": ""})
        if u.path == "/api/claude/setting":
            seen["setting"].append(json.loads(request.post_data or "{}"))
            time.sleep(0.5)  # the PC opens its menu, clicks, reads back
            mode["label"] = seen["setting"][-1]["name"].split()[0]  # the mode button by the box then reads Plan, Auto…
            return js({"ok": True, "state": state()})
        if u.path == "/api/chat/send":  # an "e" sits in Claude's box on the PC (10-12): turned away unless named
            seen.setdefault("sends", []).append(json.loads(request.post_data or "{}"))
            if seen["sends"][-1].get("replace_draft") != "e":
                return js({"ok": False, "error": "电脑上 Claude 的输入框里有别的字（「e」），没有覆盖；可以在这里换掉它再发，或者先到电脑上处理",
                           "not_submitted": True, "code": "desktop_draft", "draft": "e"}, 400)
            return js({"ok": True, "pressed": True, "offset": 0, "running": False, "text": "已提交，等待对话记录确认"})
        if u.path == "/api/chat/check":
            return js({"delivered": bool(seen.get("sends")) and seen["sends"][-1].get("replace_draft") == "e", "stage": "received"})
        return handle(route, request)

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        ctx = browser.new_context(viewport={"width": W, "height": H}, device_scale_factor=3, is_mobile=True, has_touch=True)
        ctx.route(f"{ORIGIN}/**", handle_fixes)
        ctx.add_init_script(INIT)
        ctx.add_init_script(FAKE_VV)
        page = ctx.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(e.message))

        # -- a page file lost on the way: the page reloads itself once and is whole
        page.goto(ORIGIN + "/")
        page.wait_for_function("window.claudeUI && window.referencesUI && window.voiceUI && document.querySelectorAll('.conv').length >= 10", timeout=20000)
        page.wait_for_timeout(500)
        ok("a page file that failed to load: the page reloads once and then has every part", seen["page"] == 2 and seen["claude_ui"] == 2, (seen["page"], seen["claude_ui"]))
        report = [e for d in seen["debug"] for e in d.get("events", []) if e.get("e") == "parts-missing"]
        ok("after that reload the PC is told what was missing", bool(report) and "claude-ui" in report[0]["before"] and report[0]["now"] == "", report)

        cdp = ctx.new_cdp_session(page)
        finger = Finger(page, cdp)
        finger.tap(W / 2, 22); page.wait_for_timeout(300)

        # -- the mode list shows at once from what the PC last read; the PC is asked only to apply the pick
        finger.tap(*center(page, ".conv >> nth=2")); page.wait_for_timeout(1200)  # c3, a Claude conversation
        chip = 'button[aria-label="选择 Claude 模式"]'
        ok("Claude in Auto: the mode chip reads Auto (it read 普通执行, the same as Manual)", page.inner_text(chip).strip() == "Auto", page.inner_text(chip))
        t0 = time.time(); finger.tap(*center(page, chip))
        page.wait_for_function("document.querySelectorAll('#claudeSettingSheet .mode-choice').length === 3", timeout=3000)
        shown = time.time() - t0
        rows = """(() => [...document.querySelectorAll('#claudeSettingSheet .mode-choice')].map(r => [r.querySelector('.ask-caption b').textContent,
            r.querySelector('.ask-caption small:not(.ask-status)')?.textContent || '', r.getAttribute('aria-checked')]))()"""
        sheet = page.evaluate(rows)
        ok("tapping the mode chip lists the modes at once, without reading the PC's menu", seen["menu"] == 0 and shown < 0.6, f"{shown:.2f}s, menu reads {seen['menu']}")
        ok("the list shows Auto, Manual and Plan, each word in bold with what it does below, Auto current", sheet == [
           ["Auto", "Claude handles permission decisions", "true"], ["Manual", "Always ask before making changes", "false"], ["Plan", "Create a plan before making changes", "false"]], sheet)
        page.evaluate("window.__modeBusySeen = false; new MutationObserver(() => { if (document.querySelector('.mode-choice.is-choosing .ask-status')) window.__modeBusySeen = true; })"
                      ".observe(document.body, {subtree: true, childList: true})")
        page.wait_for_timeout(600)  # the sheet is still sliding up
        finger.tap(*center(page, "#claudeSettingSheet .mode-choice >> nth=2")); page.wait_for_timeout(1300)
        ok("the tapped mode says 正在电脑上切换… while the PC applies it", page.evaluate("window.__modeBusySeen"))
        ok("only the picked mode's name goes to the PC", seen["setting"] == [{"id": "c3", "kind": "mode", "name": "Plan Create a plan before making changes"}], seen["setting"])
        after = page.evaluate(f"({{chip: document.querySelector('{chip}').textContent, open: overlays.some(o => o.id === 'claudeSettingSheet')}})")
        ok("when the PC has switched, the sheet closes and the chip reads 计划模式", after == {"chip": "计划模式", "open": False}, after)
        # -- and back to Auto from the phone (10-12: a pick of Plan there could not be undone)
        page.wait_for_timeout(500); finger.tap(*center(page, chip)); page.wait_for_timeout(700)
        sheet = page.evaluate(rows)
        ok("in Plan, Auto still reads Auto with what it does (the desktop's Recommended left out), Plan current",
           sheet[0] == ["Auto", "Claude handles permission decisions", "false"] and sheet[2][2] == "true", sheet)
        finger.tap(*center(page, "#claudeSettingSheet .mode-choice >> nth=0")); page.wait_for_timeout(1300)
        after = page.evaluate(f"({{chip: document.querySelector('{chip}').textContent, open: overlays.some(o => o.id === 'claudeSettingSheet')}})")
        ok("Auto can be picked to go back: its name goes to the PC and the chip reads Auto",
           seen["setting"][-1:] == [{"id": "c3", "kind": "mode", "name": "Auto Recommended Claude handles permission decisions"}] and after == {"chip": "Auto", "open": False},
           (seen["setting"][-1:], after))
        page.evaluate("localStorage.removeItem('lbr_claude_modes2')"); seen["modes"] = False
        page.evaluate("claudeUI.refresh(cur, true)"); page.wait_for_timeout(500)
        finger.tap(*center(page, chip)); page.wait_for_timeout(800)
        ok("with no list remembered yet, the PC's menu is read as before", seen["menu"] == 1, seen["menu"])
        page.evaluate("closeSheet('claudeSettingSheet')"); page.wait_for_timeout(500)

        # -- the PC shows another conversation: the chips still read this one's model, effort and mode from its record,
        #    and the list opens at once (10-12: the chip said 电脑上打开 and took a second tap after opening it)
        seen["away"] = True; page.evaluate("claudeUI.refresh(cur, true)"); page.wait_for_timeout(600)
        model_chip = 'button[aria-label="选择 Claude 模型"]'
        chips = page.evaluate(f"({{model: document.querySelector('{model_chip}').textContent, mode: document.querySelector('{chip}').textContent,"
                              f" modeShown: !document.querySelector('{chip}').hidden}})")
        ok("PC on another conversation: the chips read this one's model, effort and mode", chips == {"model": "Opus 5.5 · 最高", "mode": "Auto", "modeShown": True}, chips)
        finger.tap(*center(page, chip)); page.wait_for_timeout(800)
        away = page.evaluate("""(() => { const s = document.getElementById('claudeSettingSheet');
            return {open: overlays.some(o => o.id === 'claudeSettingSheet'), rows: s.querySelectorAll('.mode-choice').length,
                    hints: [...s.querySelectorAll('.sh-body .hint')].map(h => h.textContent).join(' ')}; })()""")
        ok("tapping the mode chip lists the modes at once, says the PC switches first, opens nothing on the PC",
           away["open"] and away["rows"] == 3 and "先切到这个对话" in away["hints"] and not seen.get("opened"), (away, seen.get("opened")))
        page.evaluate("closeSheet('claudeSettingSheet')"); page.wait_for_timeout(500); seen["away"] = False

        # -- text found in Claude's box on the PC turns a send away (10-12: an "e"); the card says why and can send the
        #    same message again replacing just that text
        page.evaluate("document.getElementById('cvText').value = '替换测试消息'; updateSendButton()")
        finger.tap(*center(page, "#cvBtn")); page.wait_for_timeout(1200)
        card = ".bub.outbox.problem"
        page.evaluate(f"document.querySelector('{card}')?.scrollIntoView({{block: 'center'}})"); page.wait_for_timeout(200)
        first = page.evaluate(f"({{card: !!document.querySelector('{card}'), state: document.querySelector('{card} .outbox-state')?.textContent}})")
        ok("a send turned away by text in Claude's box shows as 没发出去", first == {"card": True, "state": "没发出去 ›"}, first)
        finger.tap(*center(page, f"{card} .outbox-state")); page.wait_for_timeout(300)
        opened = page.evaluate(f"""(() => {{ const a = document.querySelector('{card} .message-actions');
            return {{why: a.querySelector('.outbox-why')?.textContent || '', buttons: [...a.querySelectorAll('button')].map(b => b.textContent)}}; }})()""")
        ok("tapping it says why and offers to replace that text and send again", "「e」" in opened["why"] and opened["buttons"][0] == "换掉电脑上的「e」再发", opened)
        page.evaluate(f"document.querySelector('{card} .outbox-replace').scrollIntoView({{block: 'center'}})"); page.wait_for_timeout(200)  # opened, it reaches under the box
        finger.tap(*center(page, f"{card} .outbox-replace")); page.wait_for_timeout(2500)
        last = seen["sends"][-1]
        done = page.evaluate(f"({{left: document.querySelectorAll('{card}').length, box: document.getElementById('cvText').value}})")
        ok("the same message goes again naming the text to replace; the card goes and the box is empty",
           len(seen["sends"]) == 2 and last.get("replace_draft") == "e" and last.get("text") == "替换测试消息" and done == {"left": 0, "box": ""}, (seen["sends"], done))

        # -- the keyboard: when Safari leaves the view where it was, the chat is cut to what can be seen
        view = "document.getElementById('convView').style.height"
        page.evaluate("const m = document.getElementById('cvMsgs'); m.scrollTop = m.scrollHeight")
        page.evaluate("document.getElementById('cvText').focus()")
        page.evaluate("__vv.set(-29, 0)"); page.wait_for_timeout(30); page.evaluate("__vv.set(427, 0)"); page.wait_for_timeout(250)
        cut = page.evaluate(f"""({{height: {view}, box: Math.round(document.querySelector('.cv-row').getBoundingClientRect().bottom),
            title: Math.round(document.querySelector('.cv-top').getBoundingClientRect().top),
            fromEnd: (m => Math.round(m.scrollHeight - m.scrollTop - m.clientHeight))(document.getElementById('cvMsgs'))}})""")
        ok("keyboard up, Safari did not move the view: the chat is cut to the visible height", cut["height"] == "427px" and cut["box"] <= 427 and cut["title"] == 0, cut)
        ok("and the newest messages stay right above the box", cut["fromEnd"] <= 2, cut["fromEnd"])
        page.evaluate("__vv.set(427, 368)"); page.wait_for_timeout(50)
        ok("when Safari does move the view, the chat fills the window again at once", page.evaluate(view) == f"{H}px", page.evaluate(view))
        page.evaluate("__vv.set(427, 0)"); page.wait_for_timeout(250); page.evaluate("document.activeElement.blur()"); page.wait_for_timeout(50)
        ok("when the keyboard goes (the box loses focus), the chat fills the window at once", page.evaluate(view) == f"{H}px", page.evaluate(view))
        page.evaluate("__vv.set(%d, 0)" % H); page.wait_for_timeout(100)
        page.evaluate("window.__heights = []; new MutationObserver(() => __heights.push(document.getElementById('convView').style.height)).observe(document.getElementById('convView'), {attributes: true, attributeFilter: ['style']})")
        page.evaluate("document.getElementById('cvText').focus()")
        for h_, o_ in [(427, 368), (199, 368), (199, 370), (427, 368)]:  # the usual sequence: Safari moves the view, numbers in flux
            page.evaluate(f"__vv.set({h_}, {o_})"); page.wait_for_timeout(17)
        page.wait_for_timeout(250)
        heights = page.evaluate("[...new Set(__heights)]")
        ok("the usual keyboard (Safari moves the view) leaves the chat alone, even while the numbers are in flux", all(h_ == f"{H}px" for h_ in heights), heights)
        page.evaluate("document.activeElement.blur()"); page.evaluate("__vv.set(%d, 0)" % H); page.wait_for_timeout(100)

        # -- a part that keeps failing: one reload only, then a note to reload by hand
        seen.update(fail_claude_ui="always", page=0)
        page2 = ctx.new_page()
        page2.goto(ORIGIN + "/")
        page2.wait_for_timeout(4000)
        note = page2.evaluate("document.querySelector('.parts-missing')?.textContent || ''")
        ok("a part that keeps failing: one reload, then a note asks to reload (no loop)", seen["page"] == 2 and "claude-ui" in note, (seen["page"], note))

        mine = [e for e in errors if "claude-ui" in e or "remote" in e or "keyboard" in e]
        ok("no page errors from these fixes", not mine, mine[:3])
        browser.close()


def run_computers(check):
    """10-13: a computer with only Codex and no voice, named 公司电脑; the switch to the other computer."""
    ok = check
    machine = {"name": "公司电脑", "apps": ["codex"], "voice": False}
    asked = {"computers": 0}

    def handle_computers(route, request):
        u = urlsplit(request.url)
        if u.netloc == "home.test":
            return route.fulfill(status=200, content_type="text/html; charset=utf-8", body="<title>家里电脑</title>home")
        if u.path == "/":  # what remote.py does: the computer's facts go into the page before its scripts run
            page = (HERE / "remote.html").read_text(encoding="utf-8")
            page = page.replace("<!--machine-->", "<script>window.MACHINE=" + json.dumps(machine, ensure_ascii=False) + ";</script>", 1)
            return route.fulfill(status=200, content_type="text/html; charset=utf-8", body=page)
        if u.path == "/api/computers":
            asked["computers"] += 1
            body = {"self": {"name": "公司电脑", "url": ORIGIN + "/"}, "others": [{"name": "家里电脑", "url": "https://home.test/", "reachable": True}]}
            return route.fulfill(status=200, content_type="application/json; charset=utf-8", body=json.dumps(body, ensure_ascii=False))
        return handle(route, request)

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        ctx = browser.new_context(viewport={"width": W, "height": H}, device_scale_factor=3, is_mobile=True, has_touch=True)
        ctx.route(f"{ORIGIN}/**", handle_computers)
        ctx.route("https://home.test/**", handle_computers)
        ctx.add_init_script(INIT)
        page = ctx.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(e.message))
        page.goto(ORIGIN + "/")
        page.wait_for_function("window.voiceUI && window.newChatUI && document.querySelectorAll('.conv').length >= 10", timeout=20000)
        page.wait_for_timeout(500)
        top = page.evaluate("""({sub: document.getElementById('appSubtitle').textContent, can: !document.getElementById('appSubtitle').disabled,
            title: document.title, chips: getComputedStyle(document.querySelector('.conversation-home .chips')).display,
            mic: !!document.querySelector('.mic-btn'), gear: getComputedStyle(document.getElementById('settingsBtn')).display,
            missing: !!document.querySelector('.parts-missing'), status: document.getElementById('serviceStatus').textContent})""")
        ok("the page names its computer under the title, and the name can be tapped", top["sub"] == "公司电脑" and top["can"] and "公司电脑" in top["title"], top)
        ok("only Codex here: no 全部 / Codex / Claude chips", top["chips"] == "none", top["chips"])
        settings = page.evaluate("[...document.querySelectorAll('#settingsBody .setting-title')].map(n => n.textContent)")
        ok("no voice here: no microphone, the gear has 对话 (已归档对话), 手机通知 and 诊断测速 last, and no part reported missing",
           not top["mic"] and top["gear"] != "none" and settings == ["对话", "手机通知", "诊断测速"] and not top["missing"], (top, settings))
        page.evaluate("openNewSheet()"); page.wait_for_timeout(600)
        ok("the new-chat panel offers no Claude", page.evaluate("document.querySelector('#newSheet .new-apps').hidden"))
        page.evaluate("closeSheet('newSheet')"); page.wait_for_timeout(500)
        cdp = ctx.new_cdp_session(page)
        finger = Finger(page, cdp)
        finger.tap(*center(page, "#appSubtitle")); page.wait_for_timeout(700)
        rows = page.evaluate("[...document.querySelectorAll('#computerList .menu-row')].map(r => r.textContent)")
        ok("tapping the name lists this computer first, then the other one", rows == ["✓ 公司电脑（现在这台）", "家里电脑"] and asked["computers"] == 1, rows)
        finger.tap(*center(page, "#computerList button.menu-row")); page.wait_for_timeout(1200)
        ok("tapping the other computer opens its own page", page.url == "https://home.test/", page.url)
        ok("no page errors on a computer with only Codex", not errors, errors[:3])
        browser.close()


def run_notify(check):
    """10-14 (0.19): a notification's link opens its conversation; 设置 → 手机通知 takes Bark's address."""
    ok = check
    told = {"configured": False, "server": "", "recent": []}
    posts = []

    def handle_notify(route, request):
        u = urlsplit(request.url)
        js = lambda obj, status=200: route.fulfill(status=status, content_type="application/json; charset=utf-8", body=json.dumps(obj, ensure_ascii=False))
        if u.path == "/api/notify" and request.method == "GET":
            return js(told)
        if u.path in ("/api/notify", "/api/notify/test"):
            posts.append((u.path, json.loads(request.post_data or "{}")))
            if u.path == "/api/notify" and "day.app" not in posts[-1][1].get("address", ""):
                return js({"error": "没认出 Bark 的推送地址"}, 400)
            told.update(configured=True, server="api.day.app", recent=[{"time": "10:42", "text": "Codex「测试对话 3」好了 · 已推到手机"}])
            time.sleep(0.3)  # the PC sends the first one before it answers
            return js({"ok": True, "configured": True, "text": "已保存，刚推了一条，看看手机"})
        return handle(route, request)

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        ctx = browser.new_context(viewport={"width": W, "height": H}, device_scale_factor=3, is_mobile=True, has_touch=True)
        ctx.route(f"{ORIGIN}/**", handle_notify)
        ctx.add_init_script(INIT)
        page = ctx.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(e.message))
        page.goto(ORIGIN + "/?open=codex:c3")
        page.wait_for_function("window.voiceUI && typeof cur !== 'undefined' && cur && cur.id === 'c3'", timeout=20000)
        page.wait_for_timeout(500)
        opened = page.evaluate("({app: cur.app, id: cur.id, search: location.search, title: document.getElementById('cvTitle').textContent})")
        ok("the link in a notification opens that conversation, and leaves the address bar clean",
           opened == {"app": "codex", "id": "c3", "search": "", "title": "测试对话 3"}, opened)
        page.evaluate("closeConv(true); openSheet('settingsSheet')"); page.wait_for_timeout(600)
        rows = page.evaluate("[...document.querySelectorAll('#settingsBody .setting-title')].map(n => n.textContent)")
        ok("the settings have 对话 (已归档对话), 语音输入, 手机通知 and 诊断测速 last", rows == ["对话", "语音输入", "手机通知", "诊断测速"], rows)
        box = "#settingsBody input[aria-label='Bark 的推送地址']"
        page.fill(box, "随便几个字")
        page.click("#settingsBody .menu-row:has-text('保存并试推一条')"); page.wait_for_timeout(500)
        ok("an address that is not Bark's is refused, and what was typed stays",
           posts[-1] == ("/api/notify", {"address": "随便几个字"}) and page.input_value(box) == "随便几个字", posts[-1:])
        page.fill(box, "https://api.day.app/AbCdEf1234567890xyZQ/这里改成你自己的推送内容")
        page.click("#settingsBody .menu-row:has-text('保存并试推一条')"); page.wait_for_timeout(900)
        # 手机通知's part of 设置: from its title to the next one (诊断测速 comes after it)
        shown = page.evaluate("""(() => { const t = [...document.querySelectorAll('#settingsBody .setting-title')].find(n => n.textContent === '手机通知'), part = [];
            for (let n = t.nextElementSibling; n && !n.classList.contains('setting-title'); n = n.nextElementSibling) part.push(n, ...n.querySelectorAll('*'));
            return {rows: part.filter(n => n.classList.contains('setting-group')).at(-1).innerText.split('\\n').filter(Boolean),
              note: part.filter(n => n.classList.contains('setting-note')).at(-1).textContent, toast: document.getElementById('toast').textContent}; })()""")
        ok("a Bark address is kept: 已开 with the server, 试推一条 and 关掉, and the last outcome",
           shown["rows"][:2] == ["已开", "api.day.app"] and "试推一条" in shown["rows"] and "关掉" in shown["rows"]
           and "已推到手机" in shown["note"] and "看看手机" in shown["toast"], shown)
        ok("no page errors around notifications", not errors, errors[:3])
        browser.close()


def run_update(check):
    """10-14: the service restarted with new code. Nothing is pinned over the page: the drawer offers a reload, and the
    page only reloads when the user explicitly selects the update action."""
    ok = check
    served = {"version": "0.19.0"}  # what the service says now; the page was given 0.19.0 when it loaded

    def handle_update(route, request):
        u = urlsplit(request.url)
        if u.path == "/":
            page = (HERE / "remote.html").read_text(encoding="utf-8")
            machine = {"name": "家里电脑", "apps": ["codex", "claude"], "voice": True, "version": served["version"]}  # as remote.py puts it in
            page = page.replace("<!--machine-->", "<script>window.MACHINE=" + json.dumps(machine, ensure_ascii=False) + ";</script>", 1)
            return route.fulfill(status=200, content_type="text/html; charset=utf-8", body=page)
        if u.path == "/api/status":
            return route.fulfill(status=200, content_type="application/json", body=json.dumps({"ok": True, "ui_version": served["version"], "chat": {"available": True}}))
        return handle(route, request)

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        ctx = browser.new_context(viewport={"width": W, "height": H}, device_scale_factor=3, is_mobile=True, has_touch=True)
        ctx.route(f"{ORIGIN}/**", handle_update)
        ctx.add_init_script(INIT)
        page = ctx.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(e.message))
        page.goto(ORIGIN + "/")
        page.wait_for_function("window.voiceUI && document.querySelectorAll('.conv').length >= 10", timeout=20000)
        page.wait_for_timeout(2500)
        ok("same version: the drawer just says 已连接", page.evaluate("document.getElementById('serviceStatus').textContent") == "已连接家里电脑")
        served["version"] = "0.19.1"
        page.wait_for_timeout(2500)  # the status check runs every 2 s
        seen = page.evaluate("""({status: document.getElementById('serviceStatus').textContent, pinned: !!document.getElementById('pageUpdate'),
            fixed: [...document.querySelectorAll('body > button')].filter(b => getComputedStyle(b).position === 'fixed').length})""")
        ok("after an update nothing is pinned over the page; the drawer's status line offers the reload",
           seen["status"] == "已连接家里电脑 · 有新版，点此刷新" and not seen["pinned"] and seen["fixed"] == 0, seen)
        page.evaluate("window.__same = 1; openConv(convItems[0]); document.getElementById('cvText').focus(); document.dispatchEvent(new Event('visibilitychange'))")
        page.wait_for_timeout(1200)
        ok("back on screen while typing: no reload", page.evaluate("window.__same") == 1)
        page.evaluate("document.activeElement.blur(); closeConv(true)")
        page.evaluate("document.dispatchEvent(new Event('visibilitychange'))")
        page.wait_for_timeout(1200)
        ok("returning to an idle page also preserves it", page.evaluate("window.__same") == 1)
        page.evaluate("openSheet('navSheet')")
        with page.expect_navigation(timeout=8000):
            page.get_by_role('button',name='有新版，点此刷新',exact=True).click()
        page.wait_for_function("window.voiceUI", timeout=20000)
        page.wait_for_timeout(900)
        after = page.evaluate("({same: window.__same ?? null, toast: document.getElementById('toast').textContent})")
        ok("explicit update action reloads the page and says so", after == {"same": None, "toast": "页面已更新到新版"}, after)
        ok("no page errors around the update", not errors, errors[:3])
        browser.close()


def run_sidebar_quiet(check):
    """10-14: the sidebar's tree is not rebuilt while the drawer opens (the PC answers after it has stopped, and the
    rebuild played the rows' entrance a second time); the same answer again, only the PC's clock moved, is not redrawn."""
    ok = check
    tree = {"value": fake_tree(), "delay": 0.0}

    def handle_tree(route, request):
        u = urlsplit(request.url)
        if u.path == "/api/chat/projects" and not parse_qs(u.query).get("key"):
            time.sleep(tree["delay"])
            body = {**tree["value"], "now": int(time.time() * 1000)}
            return route.fulfill(status=200, content_type="application/json; charset=utf-8", body=json.dumps(body, ensure_ascii=False))
        return handle(route, request)

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        ctx = browser.new_context(viewport={"width": W, "height": H}, device_scale_factor=3, is_mobile=True, has_touch=True)
        ctx.route(f"{ORIGIN}/**", handle_tree)
        ctx.add_init_script(INIT)
        page = ctx.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(e.message))
        page.goto(ORIGIN + "/")
        page.wait_for_function("window.sidebarUI && document.querySelectorAll('.conv').length >= 10", timeout=20000)
        page.wait_for_timeout(2500)  # the first read, 1.5 s after the page loads, is drawn
        page.evaluate("""window.__marks = [];
            new MutationObserver(() => __marks.push(['tree', performance.now()])).observe(document.querySelector('.nav-tree'), {childList: true});
            const box = document.querySelector('#navSheet .box');
            new MutationObserver(() => __marks.push([box.classList.contains('lbr-entering') ? 'on' : 'off', performance.now()])).observe(box, {attributes: true, attributeFilter: ['class']});""")
        page.evaluate("sidebarUI.load(true)"); page.wait_for_timeout(600)
        ok("the same tree again (only the PC's clock moved) is not redrawn", page.evaluate("__marks") == [], page.evaluate("__marks"))
        changed = json.loads(json.dumps(fake_tree())); changed["apps"][0]["projects"][0]["name"] = "改过名字的项目"
        tree.update(value=changed, delay=0.15)
        cdp = ctx.new_cdp_session(page)
        Finger(page, cdp).tap(*center(page, 'header button[aria-label="打开导航"]'))
        page.evaluate("sidebarUI.load(true)")  # its answer comes while the drawer is still opening
        page.wait_for_timeout(1500)
        marks = page.evaluate("__marks")
        names = [m[0] for m in marks]
        off = next((t for n, t in marks if n == "off"), None)
        drawn = [t for n, t in marks if n == "tree"]
        ok("a changed tree that arrives while the drawer opens is drawn once, after the drawer stands still",
           "on" in names and off is not None and len(drawn) == 1 and drawn[0] >= off
           and page.evaluate("document.querySelector('.nav-tree').textContent.includes('改过名字的项目')"), marks)
        ok("no page errors around the sidebar", not errors, errors[:3])
        browser.close()


NEW_OPTIONS = {
    "claude": {"models": [{"id": "Opus 5.5", "label": "Opus 5.5", "efforts": [{"id": v, "label": n} for v, n in enumerate(["Low", "Medium (Recommended)", "High", "Extra", "Max", "Ultracode"])]},
                          {"id": "Sonnet 5.5", "label": "Sonnet 5.5", "efforts": [{"id": v, "label": n} for v, n in enumerate(["Low", "Medium (Recommended)", "High", "Extra", "Max", "Ultracode"])]}], "note": ""},
    "codex": {"models": [{"id": "gpt-5.5", "label": "GPT-5.5", "efforts": [{"id": "low", "label": "low"}, {"id": "high", "label": "high"}], "default_effort": "low"}], "note": ""},
}


def run_new_model(check, shots=None):
    """10-14: the new-conversation sheet picks a model and effort, kept for each app, and sends them with the first message."""
    ok = check
    posted = []

    def handle_new(route, request):
        u = urlsplit(request.url)
        js = lambda obj: route.fulfill(status=200, content_type="application/json; charset=utf-8", body=json.dumps(obj, ensure_ascii=False))
        if u.path == "/api/chat/new/options":
            return js(NEW_OPTIONS[parse_qs(u.query).get("app", ["codex"])[0]])
        if u.path == "/api/chat/new/draft":
            return js({"request_id": "b" * 32})
        if u.path == "/api/chat/new":
            posted.append(json.loads(request.post_data or "{}"))
            return js({"request_id": "b" * 32, "state": "creating", "message": "正在创建对话…"})
        if u.path == "/api/chat/new/state":
            return js({"request_id": "b" * 32, "state": "creating", "app": "claude", "message": "正在创建对话…"})
        return handle(route, request)

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        ctx = browser.new_context(viewport={"width": W, "height": H}, device_scale_factor=3, is_mobile=True, has_touch=True)
        ctx.route(f"{ORIGIN}/**", handle_new)
        ctx.add_init_script(INIT)
        page = ctx.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(e.message))
        page.goto(ORIGIN + "/")
        page.wait_for_function("window.newChatUI && document.querySelectorAll('.conv').length >= 10", timeout=20000)
        page.evaluate("openNewSheet({app: 'claude', projectless: true})"); page.wait_for_timeout(600)
        ok("the new-conversation sheet offers a model, the desktop's own at first", page.inner_text("#newModelName") == "默认模型", page.inner_text("#newModelName"))
        page.click("#newModelChoice"); page.wait_for_function("document.querySelectorAll('#newModelRows .model-list-row').length === 3")
        page.click("#newModelRows .model-list-row:has-text('Sonnet 5.5')"); page.wait_for_timeout(200)
        chips = page.evaluate("[...document.querySelectorAll('#newEffortRows button')].map(b => b.textContent)")
        ok("picking a model shows its effort steps", chips == ["Low", "Medium (Recommended)", "High", "Extra", "Max", "Ultracode"], chips)
        page.click("#newEffortRows button:has-text('High')"); page.wait_for_timeout(200)
        if shots:
            page.screenshot(path=str(Path(shots) / "new_model_sheet.png"))
        page.click("#newModelDone"); page.wait_for_timeout(500)
        ok("the sheet names the pick", page.inner_text("#newModelName") == "Sonnet 5.5 · High", page.inner_text("#newModelName"))
        page.click("#newCodex"); page.wait_for_timeout(200)
        ok("each app keeps its own pick (Codex: still the default)", page.inner_text("#newModelName") == "默认模型", page.inner_text("#newModelName"))
        page.click("#newModelChoice"); page.wait_for_function("document.querySelectorAll('#newModelRows .model-list-row').length === 2")
        page.click("#newModelRows .model-list-row:has-text('GPT-5.5')"); page.wait_for_timeout(200)
        codex_chips = page.evaluate("[...document.querySelectorAll('#newEffortRows button')].map(b => b.textContent)")
        ok("Codex's effort steps are named as in its own sheet", codex_chips == ["低", "高"], codex_chips)
        page.click("#newModelDone"); page.wait_for_timeout(400)
        page.click("#newClaude"); page.wait_for_timeout(200)
        if shots:
            page.screenshot(path=str(Path(shots) / "new_sheet.png"))
        page.fill("#newText", "手机遥控测试：模型选择"); page.click("#newBtn"); page.wait_for_timeout(800)
        sent = posted[-1] if posted else {}
        ok("the first message goes with the picked model and effort", sent.get("app") == "claude" and sent.get("settings") == {"model": "Sonnet 5.5", "effort": 2}, sent.get("settings"))
        ok("no page errors around picking a model", not errors, errors[:3])
        browser.close()


def run_claude_progress(check, shots=None):
    """10-15: a Claude run that writes its progress only as thinking lines and keeps a checklist (update_plan)."""
    ok = check
    plan = lambda a, b: {"role": "plan", "items": [{"text": "读记录，摸清格式", "status": a}, {"text": "核对运行目录里的完整记录", "status": b},
                                                   {"text": "汇总并核对覆盖", "status": "pending"}], "text": "计划"}
    rows = [{"role": "user", "text": "请只读审查这份笔记。"},
            {"role": "tool", "text": "Read：笔记.md"}, {"role": "tool", "text": "Bash：dir"},
            {"role": "assistant", "phase": "commentary", "thinking": True, "text": "找到笔记文件了，确认区有 7.4 万行。我先看运行目录里的结构化数据。"},
            {"role": "tool", "text": "Bash：python check.py"}, plan("in_progress", "pending"), {"role": "tool", "text": "Bash：python more.py"},
            plan("completed", "in_progress"),
            {"role": "assistant", "phase": "commentary", "thinking": True, "text": "这一段想得比较长。" * 60}]
    messages = [{**m, "id": f"p{i}", "time": f"2026-10-15T00:00:{i:02d}Z"} for i, m in enumerate(rows)]

    def handle_chat(route, request):
        u = urlsplit(request.url)
        if u.path == "/api/chat" and parse_qs(u.query).get("id", [""])[0] == "c1":
            body = {"app": "claude", "id": "c1", "title": "联合审查", "status": "running", "folder": "D:/demo", "size": 1000,
                    "messages": messages, "note": "", "has_more": False, "next_cursor": None}
            return route.fulfill(status=200, content_type="application/json; charset=utf-8", body=json.dumps(body, ensure_ascii=False))
        return handle(route, request)

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        ctx = browser.new_context(viewport={"width": W, "height": H}, device_scale_factor=3, is_mobile=True, has_touch=True)
        ctx.route(f"{ORIGIN}/**", handle_chat)
        ctx.add_init_script(INIT)
        page = ctx.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(e.message))
        page.goto(ORIGIN + "/")
        page.wait_for_function("window.readingUI && document.querySelectorAll('.conv').length >= 10", timeout=20000)
        page.evaluate("openConv(convItems.find(c => c.id === 'c1'))")
        page.wait_for_function("document.querySelectorAll('#cvMsgs .plan-card').length === 1", timeout=10000)
        page.wait_for_timeout(400)
        seen = page.evaluate("""[...document.getElementById('cvMsgs').children].map(n => n.classList.contains('plan-card') ? 'plan'
            : n.tagName === 'DETAILS' ? n.querySelector('summary').textContent : n.classList.contains('thinking') ? 'thinking' : n.className.split(' ').slice(0, 2).join(' '))""")
        ok("thinking lines sit between the steps as on the desktop, and only the latest checklist shows",
           seen == ["bub user", "已执行 2 步操作", "thinking", "已执行 2 步操作", "plan", "thinking"], seen)
        marks = page.evaluate("[...document.querySelectorAll('#cvMsgs .plan-card .plan-row')].map(r => r.className.replace('plan-row ', ''))")
        ok("the checklist shows each step's state (done, under way, to do)", marks == ["done", "doing", "todo"], marks)
        notes = page.evaluate("""[...document.querySelectorAll('#cvMsgs .bub.thinking')].map(n => ({copy: !!n.querySelector('.message-actions'),
            long: n.classList.contains('long'), muted: getComputedStyle(n).color}))""")
        ok("thinking lines are grey notes without a copy button; a long one folds",
           len(notes) == 2 and not any(n["copy"] for n in notes) and [n["long"] for n in notes] == [False, True], notes)
        if shots:
            page.evaluate("document.querySelector('#cvMsgs .plan-card').scrollIntoView({block: 'center'})"); page.wait_for_timeout(300)
            page.screenshot(path=str(Path(shots) / "claude_progress.png"))
        page.click("#cvMsgs .bub.thinking.long"); page.wait_for_timeout(200)
        ok("a tap opens the long one", page.evaluate("document.querySelector('#cvMsgs .bub.thinking.long').classList.contains('open')"))
        ok("no page errors around Claude's progress", not errors, errors[:3])
        browser.close()


def run_claude_next(check, shots=None):
    """10-16: Claude desktop ends a turn with a next-step box (a recap, a question and buttons) and may propose a task in a
    card; the phone showed neither."""
    ok = check
    old = {"role": "next", "tool_id": "toolu_old", "recap": "方案初稿写好了。", "ask": "要先看第一节吗？", "actions": [{"label": "先看第一节", "message": "先看第一节"}],
           "text": "方案初稿写好了。\n\n要先看第一节吗？"}
    box = {"role": "next", "tool_id": "toolu_box1", "recap": "部署方案已写好，放在 docs/deploy_plan.md。", "ask": "要不要开始第 0 步实测？",
           "actions": [{"label": "开始第 0 步", "message": "开始第 0 步，用你建议的 3 份原文 Word。"}, {"label": "先改方案", "message": "先不实测，我对方案有几处要改。"}],
           "open": True, "text": "部署方案已写好。\n\n要不要开始第 0 步实测？"}
    title = "部署流程：先在测试环境跑通，再切到正式环境"
    task = {"role": "task", "tool_id": "toolu_task", "title": title, "offer": False, "text": title,
            "brief": "目标：让部署流程能「人和脚本轮流改」：脚本跑一轮 → 人在测试环境里核对 → 重新同步 → 再跑。" * 3}
    rows = [{"role": "user", "text": "写一个方案。"}, {"role": "assistant", "text": "初稿在这里。"}, old, {"role": "user", "text": "先看第一节"},
            {"role": "assistant", "text": "方案已写好。"}, task, box]
    messages = [{**m, "id": f"n{i}", "time": f"2026-10-16T01:59:{i:02d}Z"} for i, m in enumerate(rows)]
    pressed, tasks_pressed, state = [], [], {"tasks": [title]}
    sent = "电脑上这个框没有按钮，已把「先改方案」要说的话发过去"

    def handle_chat(route, request):
        u = urlsplit(request.url)
        js = lambda obj: route.fulfill(status=200, content_type="application/json; charset=utf-8", body=json.dumps(obj, ensure_ascii=False))
        if u.path == "/api/chat" and parse_qs(u.query).get("id", [""])[0] == "c1":
            return js({"app": "claude", "id": "c1", "title": "部署方案", "status": "idle", "folder": "D:/demo", "size": 1000,
                       "messages": messages, "note": "", "has_more": False, "next_cursor": None})
        if u.path == "/api/claude/state" and parse_qs(u.query).get("id", [""])[0] == "c1":  # the PC shows it, the task card waiting or not
            return js({"settings": {}, "available": True, "on_screen": True, "actions": [], "running": False, "tasks": list(state["tasks"])})
        if u.path == "/api/claude/next":
            pressed.append(json.loads(request.post_data))
            return js({"ok": True, "sent": True, "text": sent})
        if u.path == "/api/claude/task":
            tasks_pressed.append(json.loads(request.post_data)); state["tasks"] = []
            return js({"ok": True, "text": "已在电脑上开始了，新对话会出现在列表里"})
        return handle(route, request)

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        ctx = browser.new_context(viewport={"width": W, "height": H}, device_scale_factor=3, is_mobile=True, has_touch=True)
        ctx.route(f"{ORIGIN}/**", handle_chat)
        ctx.add_init_script(INIT)
        page = ctx.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(e.message))
        page.goto(ORIGIN + "/")
        page.wait_for_function("window.claudeUI && document.querySelectorAll('.conv').length >= 10", timeout=20000)
        page.evaluate("openConv(convItems.find(c => c.id === 'c1'))")
        page.wait_for_function("document.querySelectorAll('#cvMsgs .next-card').length === 2", timeout=10000)
        card = page.evaluate("""(() => { const n = document.querySelector('#cvMsgs .next-card:not(.closed)');
            return {recap: n.querySelector('.next-recap')?.textContent, ask: n.querySelector('.next-ask')?.textContent,
                    buttons: [...n.querySelectorAll('.next-actions button')].map(b => [b.textContent, b.classList.contains('big')]),
                    last: n === document.querySelector('#cvMsgs').lastElementChild}; })()""")
        ok("Claude's next-step box shows its recap, question and buttons at the end, the first one the main one",
           card == {"recap": box["recap"], "ask": box["ask"], "buttons": [["开始第 0 步", True], ["先改方案", False]], "last": True}, card)
        closed = page.evaluate("""(() => { const n = document.querySelector('#cvMsgs .next-card.closed');
            return [n.textContent, n.querySelectorAll('button').length, !!n.querySelector('.next-ask')]; })()""")
        ok("an answered box keeps only its recap", closed == [old["recap"], 0, False], closed)
        if shots:
            page.evaluate("document.querySelector('#cvMsgs .next-card:not(.closed)').scrollIntoView({block: 'center'})"); page.wait_for_timeout(300)
            page.screenshot(path=str(Path(shots) / "claude_next.png"))
        page.wait_for_function("document.querySelectorAll('#cvMsgs .task-card').length === 1", timeout=10000)
        shown = page.evaluate("""(() => { const n = document.querySelector('#cvMsgs .task-card');
            return {head: n.querySelector('.task-head').textContent, title: n.querySelector('.task-title').textContent,
                    clamped: n.querySelector('.task-brief').scrollHeight > n.querySelector('.task-brief').clientHeight + 4,
                    buttons: [...n.querySelectorAll('.next-actions button')].map(b => b.textContent), settled: n.classList.contains('settled')}; })()""")
        ok("a task Claude proposes is a card as on the PC: title, a brief cut to three lines, 开始 / 在这里做 / 不要了",
           shown == {"head": "Claude 提议新开一个任务", "title": title, "clamped": True, "buttons": ["开始", "在这里做", "不要了"], "settled": False}, shown)
        page.click("#cvMsgs .next-card:not(.closed) .next-actions button:nth-child(2)")
        page.wait_for_function("!!document.querySelector('#cvMsgs .next-card:not(.closed) .next-status')", timeout=10000)
        after = page.evaluate("""(() => { const n = document.querySelector('#cvMsgs .next-card:not(.closed)');
            return [n.querySelector('.next-status').textContent, n.querySelectorAll('button').length]; })()""")
        ok("a button is pressed as on the PC, named by its box and place, and gives way to what was done at once",
           pressed == [{"id": "c1", "tool_id": "toolu_box1", "index": 1, "label": "先改方案"}] and after == [sent, 0], [pressed, after])
        page.click("#cvMsgs .task-card .next-actions button:nth-child(1)")
        page.wait_for_function("document.querySelector('#cvMsgs .task-card').classList.contains('settled')", timeout=15000)
        gone = page.evaluate("""(() => { const n = document.querySelector('#cvMsgs .task-card');
            return [getComputedStyle(n.querySelector('.next-actions')).display, n.querySelector('.task-note').textContent]; })()""")
        ok("开始 starts it on the PC's card with the same title; settled there, the card keeps no buttons",
           tasks_pressed == [{"id": "c1", "title": title, "button": "start"}] and gone[0] == "none" and gone[1].startswith("电脑上已经处理过了"), [tasks_pressed, gone])
        ok("no page errors around the next-step box and task cards", not errors, errors[:3])
        browser.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--shots", help="folder for mid-gesture screenshots")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    if args.shots:
        Path(args.shots).mkdir(parents=True, exist_ok=True)
    check = Checks()
    run(args.shots, reduced=False, check=check)
    run(None, reduced=True, check=check)
    run_fixes(check)
    run_computers(check)
    run_notify(check)
    run_update(check)
    run_sidebar_quiet(check)
    run_new_model(check, args.shots)
    run_claude_progress(check, args.shots)
    run_claude_next(check, args.shots)
    print(f"\n{len(check.rows) - len(check.failed)}/{len(check.rows)} passed")
    sys.exit(1 if check.failed else 0)


if __name__ == "__main__":
    main()
