"""The feel of sending and of a message held (10-22), against the real page with fake APIs and real DevTools touches.

The user, after WhatsApp, iMessage and ChatGPT: a sent message should pop up silkily, the message box should stand out
rather than be sunk in, and a message tapped or held should come up with 复制 and the like. Checked: the box is a raised
white card; a sent bubble springs up from small once (not again when its line changes, nor after a reload) while the list
glides up to it; holding a message gives a little, then lifts it out over the blurred page with a menu beside it, whose
复制 copies its words; a tap on one of yours does the same, a tap on a reply or a scroll does nothing; a hold whose words are
rewritten under the finger and let go early opens nothing; Reduce Motion pops nothing.

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
        messages.append({"id": f"a{i}", "role": "assistant", "text": f"第 {i} 个回答：" + WORDS * 2, "time": "2026-10-22T08:00:05Z"})

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
            return page.evaluate("overlays.some(o => o.id === 'msgFocus')")

        def close_menu():
            page.evaluate("closeSheet('msgFocus')"); page.wait_for_timeout(400)

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

        # -- holding a reply: it gives a little, then lifts out over the blurred page with a menu
        page.evaluate("document.querySelector('[data-key=\"a7\"]').scrollIntoView({block: 'center'})"); page.wait_for_timeout(300)
        x, y = middle("[data-key='a7']")
        touch("touchStart", x, y); page.wait_for_timeout(250)
        pressing = page.evaluate("document.querySelector('[data-key=\"a7\"]').classList.contains('pressing')")
        page.wait_for_timeout(450); touch("touchEnd"); page.wait_for_timeout(600)
        ok("held, the message gives a little under the finger first", pressing)
        ok("then a menu opens for it", menu_open())
        look = page.evaluate("""(() => { const card = document.querySelector('#msgFocus .focus-lift'), menu = document.querySelector('#msgFocus .box');
            const c = card.getBoundingClientRect(), m = menu.getBoundingClientRect(), dim = getComputedStyle(document.querySelector('#msgFocus .focus-dim'));
            return {scale: new DOMMatrixReadOnly(getComputedStyle(card).transform).a, words: card.textContent.includes('第 7 个回答'),
              rows: [...menu.querySelectorAll('.menu-row span:first-child')].map(n => n.textContent),
              apart: m.top >= c.bottom - 1 || m.bottom <= c.top + 1, inside: m.left >= 0 && m.right <= innerWidth && m.top >= 0 && m.bottom <= innerHeight,
              blur: dim.backdropFilter || dim.webkitBackdropFilter, original: getComputedStyle(document.querySelector('[data-key="a7"]')).visibility}; })()""")
        ok("the message comes up a little, its words on it", look["scale"] > 1.005 and look["words"], look)
        ok("the page behind is blurred, and the message itself is not left behind in it", "blur" in (look["blur"] or "") and look["original"] == "hidden", look)
        ok("the menu offers 复制 and 选择文字, beside the message and on screen", look["rows"][:2] == ["复制", "选择文字"] and look["apart"] and look["inside"], look)
        page.locator("#msgFocus .menu-row", has_text="复制").click(); page.wait_for_timeout(500)
        copied = page.evaluate("navigator.clipboard.readText()")
        ok("复制 copies the whole reply", copied.startswith("第 7 个回答：") and copied.endswith(WORDS), copied[:30])
        back = page.evaluate("({menu: overlays.some(o => o.id === 'msgFocus'), card: !!document.querySelector('#msgFocus .focus-lift'), original: getComputedStyle(document.querySelector('[data-key=\"a7\"]')).visibility})")
        ok("and the message is put back in its place", back == {"menu": False, "card": False, "original": "visible"}, back)

        # -- 选择文字: the words to pick from
        touch("touchStart", x, y); page.wait_for_timeout(700); touch("touchEnd"); page.wait_for_timeout(500)
        page.locator("#msgFocus .menu-row", has_text="选择文字").click(); page.wait_for_timeout(500)
        picked = page.evaluate("({open: overlays.some(o => o.id === 'copyTextSheet'), words: document.querySelector('#copyTextSheet textarea')?.value || ''})")
        ok("选择文字 shows the words to pick from", picked["open"] and picked["words"].startswith("第 7 个回答："), picked["open"])
        page.evaluate("closeSheet('copyTextSheet')"); page.wait_for_timeout(400)

        # -- a tap on one of yours opens it too, the menu by its right edge; a tap on a reply, or a scroll, does nothing
        page.evaluate("document.querySelector('[data-key=\"u7\"]').scrollIntoView({block: 'center'})"); page.wait_for_timeout(300)
        page.locator("[data-key='u7']").tap(); page.wait_for_timeout(600)
        mine = page.evaluate("""(() => { if (!overlays.some(o => o.id === 'msgFocus')) return null; const c = document.querySelector('#msgFocus .focus-lift').getBoundingClientRect(),
            m = document.querySelector('#msgFocus .box').getBoundingClientRect(); return {right: Math.abs(c.right - m.right) < 4}; })()""")
        ok("a tap on one of your messages lifts it with the menu by its right edge", mine == {"right": True}, mine)
        page.mouse.click(30, 120); page.wait_for_timeout(400)
        ok("a tap beside it puts it back", not menu_open())
        page.locator("[data-key='a6']").tap(); page.wait_for_timeout(600)
        ok("a tap on a reply opens nothing", not menu_open())
        x2, y2 = middle("[data-key='a6']")
        touch("touchStart", x2, y2)
        for i in range(1, 7): page.wait_for_timeout(16); touch("touchMove", x2, y2 - 8 * i)
        page.wait_for_timeout(600); touch("touchEnd"); page.wait_for_timeout(300)
        ok("a finger that scrolls opens nothing", not menu_open())

        # -- held, the words rewritten under the finger, let go early: nothing (that touchend never reaches the page)
        page.evaluate("const b = document.getElementById('cvMsgs'); b.scrollTop = b.scrollHeight"); page.wait_for_timeout(200)
        page.evaluate("v => deliver(v)", {"app": "codex", "id": "c1", "messages": [{"id": "live9", "role": "assistant", "phase": "final_answer", "text": WORDS * 3, "streaming": True}], "streaming_ids": ["live9"], "meta": {"status": "running"}})
        page.wait_for_timeout(1500)
        x3, y3 = middle("[data-key='live9'] .reply-text")
        touch("touchStart", x3, y3); page.wait_for_timeout(100)
        page.evaluate("v => deliver(v)", {"app": "codex", "id": "c1", "messages": [{"id": "live9", "role": "assistant", "phase": "final_answer", "text": WORDS * 4, "streaming": True}], "streaming_ids": ["live9"], "meta": {"status": "running"}})
        page.wait_for_timeout(100); touch("touchEnd"); page.wait_for_timeout(700)
        ok("a short touch on words rewritten under it opens nothing", not menu_open())

        # -- a right-click on a computer, and Android's long-press right-click after the hold: one menu
        page.evaluate("document.querySelector('[data-key=\"a5\"]').scrollIntoView({block: 'center'})"); page.wait_for_timeout(300)
        page.evaluate("document.querySelector('[data-key=\"a5\"] .reply-text').dispatchEvent(new MouseEvent('contextmenu', {bubbles: true, cancelable: true}))")
        page.wait_for_timeout(500)
        ok("a right-click lifts the message too", menu_open())
        page.evaluate("document.querySelector('#msgFocus').dispatchEvent(new MouseEvent('contextmenu', {bubbles: true, cancelable: true}))")
        page.wait_for_timeout(200)
        ok("and a second one right after does not open another", page.evaluate("overlays.filter(o => o.id === 'msgFocus').length") == 1)
        close_menu()

        # -- Reduce Motion: no pop
        page.emulate_media(reduced_motion="reduce")
        page.locator("#cvText").fill("安静地发出去"); page.evaluate("updateSendButton()")
        page.locator("#cvBtn").click(); page.wait_for_timeout(100)
        still = page.evaluate("[...document.querySelectorAll('#cvMsgs .bub.outbox')].at(-1).getAnimations().length")
        ok("with Reduce Motion a sent bubble just appears", still == 0, still)

        ok("no page errors", not errors, errors[:3])
        browser.close()
    print(f"bubble motion ui check: {'FAILED ' + str(len(fails)) if fails else 'ok'}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
