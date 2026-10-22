"""The feel of sending and of a message tapped (10-22), against the real page with fake APIs and real DevTools touches.

The user, after WhatsApp, iMessage and ChatGPT: a sent message should pop up silkily, the message box should stand out
rather than be sunk in, and a tapped message should come up with 复制 and the like. Then, of 0.25.0's held message lifted
out over a blurred page: too much blur, a poor copy, and no way to pick words out freely; and the ✓ of 电脑已接收 should not
be green. Checked: the box is a raised white card; a sent bubble springs up from small once (not again when its line
changes, nor after a reload) while the list glides up to it; the ✓ is in its line's grey; a held message is left to the
phone's own selection; a tap shows a small menu by the message (复制 · 选择文字) with nothing blurred, dimmed or blocked;
复制 writes the clipboard in the tap itself, for a long message shown in part too; 选择文字 shows the words as they read,
large, to pick from, with 复制全部; a tap elsewhere, a scroll, a tap that puts the keyboard away or clears picked-out words
opens nothing; on a computer a right-click opens it, a click a moment later, a double click not at all; words picked out of
a reply still being written stay put till let go; Reduce Motion pops nothing.

    .venv\\Scripts\\python.exe tests\\bubble_motion_ui_check.py
"""
import json
import sys
from urllib.parse import parse_qs, urlsplit

from playwright.sync_api import sync_playwright

from motion_check import HERE, ORIGIN, handle

INIT = """
window.sources = [];
window.EventSource = class extends EventTarget {
  constructor(url) { super(); this.url = url; this.closed = false; this.seq = 0; window.sources.push(this); }
  close() { this.closed = true; }
};
window.copies = [];
for (const [name, how] of [['writeText', 'text'], ['write', 'item']]) {
  const c = navigator.clipboard, real = c?.[name]?.bind(c);
  if (real) c[name] = v => { window.copies.push({how, during: window.event?.type || null}); return real(v); };
}
window.deliver = v => {
  const s = window.sources.findLast(x => !x.closed); if (!s) return false;
  s.seq++; s.dispatchEvent(new MessageEvent('update', {data: JSON.stringify({protocol: 1, type: 'update', streaming_ids: [], seq: s.seq, ...v})}));
  return true;
};
"""
WORDS = "这一段是用来撑出滚动的回答文字，先确认日志时间，再核对配置，最后跑测试。"


def main():
    errors, fails, held = [], [], []
    messages = []
    for i in range(1, 9):
        messages.append({"id": f"u{i}", "role": "user", "text": f"第 {i} 个问题", "time": "2026-10-22T08:00:00Z"})
        said = "**先看日志**，再跑 `npm test`。\n" if i == 3 else ""
        messages.append({"id": f"a{i}", "role": "assistant", "text": f"第 {i} 个回答：" + said + WORDS * 2, "time": "2026-10-22T08:00:05Z"})
    # a long reply the page has only the start of
    LONG = "第 9 个回答：" + WORDS * 40
    messages.append({"id": "a9", "role": "assistant", "text": LONG[:200], "truncated": True, "length": len(LONG), "time": "2026-10-22T08:00:09Z"})
    asked = []

    def ok(name, cond, detail=""):
        print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail and not cond else ""), flush=True)
        if not cond: fails.append(name)

    def route(r, req):
        u = urlsplit(req.url)
        js = lambda v: r.fulfill(status=200, content_type="application/json; charset=utf-8", body=json.dumps(v, ensure_ascii=False))
        if u.path == "/":
            html = (HERE / "remote.html").read_text(encoding="utf-8").replace("<!--machine-->", '<script>window.MACHINE={apps:["codex","claude"],voice:false};</script>')
            return r.fulfill(status=200, content_type="text/html; charset=utf-8", body=html)
        if u.path == "/api/chat" and parse_qs(u.query).get("id", [""])[0] == "c1":
            return js({"app": "codex", "id": "c1", "title": "手感测试", "status": "running", "folder": "D:/demo", "size": 1,
                       "messages": messages, "has_more": False, "next_cursor": None, "has_newer": False})
        if u.path == "/api/codex/state":
            return js({"available": True, "running": False, "settings": {"model": "gpt-5", "effort": "high", "mode": "default", "service_tier": None},
                       "questions": [], "queued": [], "queue_available": True, "images": [], "plan": None, "catalog": {"models": []}})
        if u.path == "/api/codex/receipt":
            return js({"state": "unknown"})
        if u.path == "/api/codex/send":
            held.append((r, json.loads(req.post_data or "{}"))); return
        if u.path == "/api/chat/message" and parse_qs(u.query).get("message", [""])[0] == "a9":
            asked.append(r); return  # answered when the check says
        return handle(r, req)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, channel="chrome")
        ctx = browser.new_context(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
        ctx.grant_permissions(["clipboard-read", "clipboard-write"], origin=ORIGIN)
        ctx.add_init_script(INIT)
        ctx.route(ORIGIN + "/**", route)
        page = ctx.new_page()
        page.on("pageerror", lambda e: errors.append(str(e)))
        cdp = ctx.new_cdp_session(page)
        page.goto(ORIGIN)
        page.wait_for_function("window.readingUI && window.workspaceUI && window.codexUI")
        page.evaluate("openConv({app:'codex', id:'c1', title:'手感测试', status:'running'})")
        page.wait_for_function("document.getElementById('cvMsgs').dataset.ready && window.sources.some(x => !x.closed)")
        page.wait_for_timeout(500)

        def touch(kind, x=0, y=0):
            cdp.send("Input.dispatchTouchEvent", {"type": kind, "touchPoints": [] if kind == "touchEnd" else [{"x": x, "y": y, "id": 1}]})

        def middle(selector):
            b = page.locator(selector).first.bounding_box()
            return b["x"] + b["width"] / 2, b["y"] + min(b["height"] / 2, 20)

        def menu_open():
            return page.evaluate("(() => { const m = document.querySelector('.msg-menu'); return !!m && !m.hidden && !m.classList.contains('closing'); })()")

        def into_view(key):
            page.evaluate(f"document.querySelector('[data-key=\"{key}\"]').scrollIntoView({{block: 'center'}})"); page.wait_for_timeout(300)

        def tap_words(key):
            page.locator(f"[data-key='{key}'] .reply-text").tap()

        def menu_tap(label):
            page.locator(".msg-menu button", has_text=label).tap()

        def clipboard():
            return page.evaluate("navigator.clipboard.readText()")

        # -- the message box stands out of the page (it was a grey well)
        box = page.evaluate("(() => { const s = getComputedStyle(document.querySelector('.cv-row')); return {bg: s.backgroundColor, shadow: s.boxShadow}; })()")
        ok("the message box is a white card with a shadow under it", box["bg"] == "rgb(255, 255, 255)" and box["shadow"] != "none", box)
        page.locator("#cvText").focus(); page.wait_for_timeout(300)
        deeper = page.evaluate("getComputedStyle(document.querySelector('.cv-row')).boxShadow")
        ok("while you type, its shadow deepens", deeper != box["shadow"], deeper)

        # -- a sent bubble springs up from small, once, while the list glides up to it
        page.evaluate("const b = document.getElementById('cvMsgs'); b.scrollTop = b.scrollHeight")
        page.evaluate("""window.track = []; window.tracking = true; (function loop() { if (!window.tracking) return;
            const n = document.querySelector('#cvMsgs .bub.outbox'), box = document.getElementById('cvMsgs');
            window.track.push({top: box.scrollTop, end: box.scrollHeight - box.clientHeight,
              scale: n ? new DOMMatrixReadOnly(getComputedStyle(n).transform === 'none' ? undefined : getComputedStyle(n).transform).a : null,
              opacity: n ? +getComputedStyle(n).opacity : null}); requestAnimationFrame(loop); })()""")
        page.locator("#cvText").fill("这条消息应该弹出来"); page.evaluate("updateSendButton()")
        page.locator("#cvBtn").click()
        page.wait_for_timeout(700)
        track = page.evaluate("window.tracking = false, window.track")
        shown = [t for t in track if t["scale"] is not None]
        ok("the sent bubble starts small and see-through", shown and shown[0]["scale"] < .9 and shown[0]["opacity"] < .6, shown[:2])
        ok("and springs a touch past its size before it settles", any(t["scale"] > 1.003 for t in shown), max((t["scale"] for t in shown), default=None))
        ok("and settles at its size", shown and abs(shown[-1]["scale"] - 1) < .001 and shown[-1]["opacity"] == 1, shown[-1:] if shown else None)
        tops = [t["top"] for t in track[track.index(shown[0]):]] if shown else []
        ok("the list glides up to it rather than jumping", len(set(tops)) >= 6 and all(b >= a for a, b in zip(tops, tops[1:])), sorted(set(tops))[:8])
        ok("and ends at the bottom", track and track[-1]["end"] - track[-1]["top"] <= 2, track[-1:])
        r, body = held.pop()
        r.fulfill(status=200, content_type="application/json", body=json.dumps({"ok": True, "accepted": True, "delivery_state": "accepted", "text": "已交给 Codex"}))
        page.wait_for_function("!sending"); page.wait_for_timeout(300)
        again = page.evaluate("document.querySelector('#cvMsgs .bub.outbox').getAnimations().length")
        ok("when its line changes to 电脑已接收 it does not pop again", again == 0, again)
        page.reload(); page.wait_for_function("window.workspaceUI && cur && cur.id === 'c1' && document.getElementById('cvMsgs').dataset.ready")
        page.wait_for_timeout(200)
        after = page.evaluate("(document.querySelector('#cvMsgs .bub.outbox')?.getAnimations() || []).length")
        ok("nor after the page reloads", after == 0, after)
        page.wait_for_timeout(500)

        # -- the ✓ of 电脑已接收 is in its line's own grey, not green
        tick = page.evaluate("""(() => { const n = document.querySelector('#cvMsgs .send-receipt.done'); if (!n) return null;
            const b = getComputedStyle(n, '::before'); return {mark: b.content, color: b.color, line: getComputedStyle(n).color}; })()""")
        ok("the ✓ of 电脑已接收 is the grey of its words", tick and "✓" in tick["mark"] and tick["color"] == tick["line"], tick)

        # -- held, a message's words are the phone's own to pick out: no menu of ours over them
        into_view("a7")
        style = page.evaluate("(() => { const s = getComputedStyle(document.querySelector('[data-key=\"a7\"]')); return {select: s.userSelect || s.webkitUserSelect, callout: s.webkitTouchCallout || ''}; })()")
        ok("a message's words can be picked out the phone's own way", style["select"] != "none" and style["callout"] != "none", style)
        x, y = middle("[data-key='a7'] .reply-text")
        touch("touchStart", x, y); page.wait_for_timeout(900); touch("touchEnd"); page.wait_for_timeout(400)
        ok("holding a message opens no menu over it", not menu_open())
        page.evaluate("getSelection().removeAllRanges()"); page.wait_for_timeout(700)

        # -- a tap on a reply: it is marked and a small menu shows by the finger; nothing blurred, dimmed or blocked
        page.touchscreen.tap(x, y); page.wait_for_timeout(450)
        look = page.evaluate("""(() => { const m = document.querySelector('.msg-menu'), r = m.getBoundingClientRect(), b = document.querySelector('[data-key="a7"]');
            const blurred = [...document.querySelectorAll('*')].filter(n => { const s = getComputedStyle(n); return [s.backdropFilter, s.webkitBackdropFilter].some(v => v && v !== 'none'); }).length;
            return {items: [...m.querySelectorAll('button span')].map(n => n.textContent), top: r.top, bottom: r.bottom, left: r.left, right: r.right,
              picked: b.classList.contains('picked'), bg: getComputedStyle(b).backgroundColor, overlays: overlays.length,
              inert: !!document.getElementById('cvMsgs').closest('[inert]'), blurred}; })()""")
        ok("a tap on a reply shows a small menu: 复制 · 选择文字", menu_open() and look["items"][:2] == ["复制", "选择文字"], look)
        ok("by the finger, clear of the line tapped, on the screen", (look["bottom"] <= y - 8 or look["top"] >= y + 8) and look["left"] >= 12 and look["right"] <= 390 - 12 and look["top"] >= 0, look)
        ok("the reply is marked with a light grey", look["picked"] and look["bg"] == "rgb(241, 243, 246)", look)
        ok("nothing is blurred or dimmed, and the page is not blocked", look["blurred"] == 0 and look["overlays"] == 0 and not look["inert"], look)
        page.evaluate("window.copies = []")
        menu_tap("复制"); page.wait_for_timeout(400)
        copied, how = clipboard(), page.evaluate("window.copies")
        ok("复制 copies the whole reply", copied.startswith("第 7 个回答：") and copied.endswith(WORDS), copied[:30])
        ok("the clipboard is written in the tap itself (Safari allows it nowhere else)", how[:1] == [{"how": "text", "during": "click"}], how)
        ok("and it says so", "已复制" in page.evaluate("document.getElementById('toast').textContent"))
        gone = page.evaluate("({open: !document.querySelector('.msg-menu').hidden, picked: document.querySelectorAll('#cvMsgs .picked').length})")
        ok("the menu goes, and the mark with it", gone == {"open": False, "picked": 0}, gone)

        # -- one of yours: it comes up a little, the menu just over it
        into_view("u7")
        page.locator("[data-key='u7']").tap(); page.wait_for_timeout(500)
        mine = page.evaluate("""(() => { const b = document.querySelector('[data-key="u7"]'), r = b.getBoundingClientRect(), q = document.querySelector('.msg-menu').getBoundingClientRect(), s = getComputedStyle(b);
            return {above: q.bottom <= r.top, near: r.top - q.bottom < 24, centred: Math.abs((q.left + q.right) / 2 - (r.left + r.right) / 2) < 2 || q.right >= innerWidth - 13,
              scale: new DOMMatrixReadOnly(s.transform === 'none' ? undefined : s.transform).a, shadow: s.boxShadow}; })()""")
        ok("a tap on one of yours brings it up a little, with the menu just over it", menu_open() and mine["above"] and mine["near"] and mine["centred"] and mine["scale"] > 1.02 and mine["shadow"] != "none", mine)

        # -- a tap elsewhere puts it away and does nothing else; the next one opens it
        tap_words("a6"); page.wait_for_timeout(400)
        ok("a tap elsewhere puts it away and opens nothing else", not menu_open() and page.evaluate("document.querySelectorAll('#cvMsgs .picked').length") == 0)
        page.wait_for_timeout(400)
        tap_words("a6"); page.wait_for_timeout(400)
        ok("the tap after that opens it", menu_open())
        page.locator("#cvText").tap(); page.wait_for_timeout(400)
        ok("the message box can be tapped straight away: the menu goes, the box has the keyboard", not menu_open() and page.evaluate("document.activeElement.id") == "cvText")
        # with the keyboard up, a tap on a message puts it away and opens nothing
        tap_words("a6"); page.wait_for_timeout(400)
        ok("with the keyboard up, a tap on a message opens nothing", not menu_open())
        page.evaluate("document.activeElement.blur()"); page.wait_for_timeout(300)
        # words picked out: the tap that clears them opens nothing
        page.evaluate("(() => { const r = document.createRange(); r.selectNodeContents(document.querySelector('[data-key=\"a6\"] .reply-text')); getSelection().removeAllRanges(); getSelection().addRange(r); })()")
        tap_words("a6"); page.wait_for_timeout(400)
        ok("with words picked out, a tap opens nothing", not menu_open())
        page.evaluate("getSelection().removeAllRanges()"); page.wait_for_timeout(300)
        x2, y2 = middle("[data-key='a5'] .reply-text")
        touch("touchStart", x2, y2)
        for i in range(1, 7): page.wait_for_timeout(16); touch("touchMove", x2, y2 - 8 * i)
        page.wait_for_timeout(300); touch("touchEnd"); page.wait_for_timeout(300)
        ok("a finger that scrolls opens nothing", not menu_open())

        # -- 选择文字: the words as they read (bold, code), large, to pick from; 复制全部
        into_view("a3")
        tap_words("a3"); page.wait_for_timeout(400)
        menu_tap("选择文字"); page.wait_for_timeout(500)
        reader = page.evaluate("""(() => { const t = document.querySelector('#readerSheet .reader-text'), s = t && getComputedStyle(t);
            return {open: overlays.at(-1)?.id === 'readerSheet', bold: t?.querySelector('b')?.textContent, code: t?.querySelector('code')?.textContent,
              select: s && (s.userSelect || s.webkitUserSelect), size: s && parseFloat(s.fontSize), box: !!document.querySelector('#readerSheet textarea'), menu: !document.querySelector('.msg-menu').hidden}; })()""")
        ok("选择文字 shows the reply as it reads, large, to pick from (no text box)", reader["open"] and reader["bold"] == "先看日志" and reader["code"] == "npm test" and reader["size"] >= 17 and reader["select"] != "none" and not reader["box"] and not reader["menu"], reader)
        page.evaluate("window.copies = []")
        page.locator("#readerSheet button", has_text="复制全部").tap(); page.wait_for_timeout(400)
        everything = clipboard()
        ok("复制全部 copies all of it", everything.startswith("第 3 个回答：**先看日志**，再跑 `npm test`。") and everything.endswith(WORDS), everything[:40])
        page.evaluate("closeSheet('readerSheet')"); page.wait_for_timeout(500)

        # -- a long reply the page has only the start of: 复制 still copies all of it, in the tap itself
        into_view("a9")
        tap_words("a9"); page.wait_for_timeout(400)
        ok("its whole words are asked for when the menu opens", len(asked) == 1, len(asked))
        page.evaluate("window.copies = []")
        menu_tap("复制"); page.wait_for_timeout(300)
        started = page.evaluate("window.copies")
        asked.pop().fulfill(status=200, content_type="application/json; charset=utf-8", body=json.dumps({"id": "a9", "role": "assistant", "text": LONG, "time": "2026-10-22T08:00:09Z"}, ensure_ascii=False))
        page.wait_for_timeout(600)
        whole = clipboard()
        ok("复制 on a reply shown in part starts in the tap, before its words are here", started[:1] and started[0]["during"] == "click", started)
        ok("and copies all of it once they come", whole == LONG, (len(whole), len(LONG)))

        # -- on a computer: a right-click opens it; a click a moment later; a double click picks a word instead
        into_view("a5")
        x4, y4 = middle("[data-key='a5'] .reply-text")
        page.mouse.click(x4, y4, button="right"); page.wait_for_timeout(300)
        ok("a right-click opens it", menu_open())
        page.keyboard.press("Escape"); page.wait_for_timeout(700)
        ok("Escape puts it away", not menu_open())
        page.mouse.click(x4, y4); page.wait_for_timeout(80)
        early = menu_open(); page.wait_for_timeout(450)
        ok("a click opens it a moment later (a second click could still come)", not early and menu_open(), early)
        page.keyboard.press("Escape"); page.wait_for_timeout(700)
        page.mouse.dblclick(x4, y4); page.wait_for_timeout(600)
        ok("a double click picks a word and opens nothing", not menu_open() and page.evaluate("String(getSelection()).length") > 0)
        page.evaluate("getSelection().removeAllRanges()"); page.wait_for_timeout(300)

        # -- words picked out of a reply still being written stay picked as more comes; let go, it carries on
        page.evaluate("const b = document.getElementById('cvMsgs'); b.scrollTop = b.scrollHeight"); page.wait_for_timeout(200)
        page.evaluate("v => deliver(v)", {"app": "codex", "id": "c1", "messages": [{"id": "live9", "role": "assistant", "phase": "final_answer", "text": WORDS * 3, "streaming": True}], "streaming_ids": ["live9"], "meta": {"status": "running"}})
        page.wait_for_timeout(1500)
        page.evaluate("(() => { const t = document.querySelector('[data-key=\"live9\"] .reply-text').firstChild, r = document.createRange(); r.setStart(t, 0); r.setEnd(t, 10); getSelection().removeAllRanges(); getSelection().addRange(r); })()")
        page.evaluate("v => deliver(v)", {"app": "codex", "id": "c1", "messages": [{"id": "live9", "role": "assistant", "phase": "final_answer", "text": WORDS * 5, "streaming": True}], "streaming_ids": ["live9"], "meta": {"status": "running"}})
        page.wait_for_timeout(1200)
        kept = page.evaluate("({picked: String(getSelection()), shown: document.querySelector('[data-key=\"live9\"] .reply-text').textContent.length})")
        ok("words picked out of a reply still being written stay picked while more comes", kept == {"picked": WORDS[:10], "shown": len(WORDS * 3)}, kept)
        page.evaluate("getSelection().removeAllRanges()"); page.wait_for_timeout(1800)
        shown = page.evaluate("document.querySelector('[data-key=\"live9\"] .reply-text').textContent.length")
        ok("let go, it carries on to what has come", shown == len(WORDS * 5), shown)

        # -- Reduce Motion: no pop
        page.emulate_media(reduced_motion="reduce")
        page.locator("#cvText").fill("安静地发出去"); page.evaluate("updateSendButton()")
        page.locator("#cvBtn").click(); page.wait_for_timeout(100)
        still = page.evaluate("[...document.querySelectorAll('#cvMsgs .bub.outbox')].at(-1).getAnimations().length")
        ok("with Reduce Motion a sent bubble just appears", still == 0, still)
        r, body = held.pop()
        r.fulfill(status=200, content_type="application/json", body=json.dumps({"ok": True, "accepted": True, "delivery_state": "accepted", "text": "已交给 Codex"}))
        page.wait_for_function("!sending"); page.wait_for_timeout(300)
        page.evaluate("document.activeElement.blur()"); into_view("u6")
        page.locator("[data-key='u6']").tap(); page.wait_for_timeout(100)
        quiet = page.evaluate("""(() => { const b = document.querySelector('[data-key="u6"]'), s = getComputedStyle(b); return {open: !document.querySelector('.msg-menu').hidden,
            moving: document.querySelector('.msg-menu').getAnimations().length, scale: new DOMMatrixReadOnly(s.transform === 'none' ? undefined : s.transform).a}; })()""")
        ok("and its menu just shows, the message not moving", quiet == {"open": True, "moving": 0, "scale": 1}, quiet)

        ok("no page errors", not errors, errors[:3])
        browser.close()
    print(f"bubble motion ui check: {'FAILED ' + str(len(fails)) if fails else 'ok'}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
