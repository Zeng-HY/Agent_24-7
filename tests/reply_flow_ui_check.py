"""A reply runs out smoothly (10-22): the real page, a scripted event stream, the words on screen recorded every frame.

Text used to land in lumps (Codex's stream reads its log once a second, DeepSeek's sends five updates a second, Claude
writes whole blocks). Checked here: a streamed reply grows in many small steps at about the pace it comes in; its copy
button is not rebuilt under the finger; the view follows it down from the end and leaves a reader alone; a block that
lands whole runs out within about a second; DeepSeek's hand-over to the saved copy carries on rather than starting again;
the first paint, a pile of rows at once, Reduce Motion and the page just back on screen show the text as it is.

    .venv\\Scripts\\python.exe tests\\reply_flow_ui_check.py
"""
import json
import sys
from urllib.parse import parse_qs, urlsplit

from playwright.sync_api import sync_playwright

from motion_check import HERE, ORIGIN, handle

FAKE_STREAM = """
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
// every frame: how much of the watched reply is on screen (characters other than spaces and line breaks: a blank line may
// become a code block's margin), and how far the view is from the end
window.watch = key => {
  window.seen = []; window.watching = true;
  const loop = () => { if (!window.watching) return;
    const n = document.querySelector(`#cvMsgs [data-key="${key}"] .reply-text`), box = document.getElementById('cvMsgs');
    window.seen.push({t: performance.now(), len: n ? n.textContent.replace(/\\s/g, '').length : -1, end: box.scrollHeight - box.scrollTop - box.clientHeight});
    requestAnimationFrame(loop); };
  requestAnimationFrame(loop);
};
"""

WORDS = '我把这个问题拆成三步来看：先确认日志里的时间，再核对配置文件，最后跑一遍测试。'  # 40 characters


def chat(app, cid, messages):
    return {"app": app, "id": cid, "title": "回复测试", "status": "running", "folder": "D:/demo", "size": 100,
            "messages": messages, "has_more": False, "next_cursor": None, "has_newer": False}


def main():
    errors, fails = [], []
    transcripts = {
        ("codex", "c1"): [{"id": "u1", "role": "user", "text": "看一下日志", "time": "2026-10-22T08:00:00Z"},
                          {"id": "a1", "role": "assistant", "text": "早先的回答：" + WORDS * 3, "time": "2026-10-22T08:00:05Z"}],
        ("claude", "c3"): [{"id": "cu1", "role": "user", "text": "写一段说明", "time": "2026-10-22T08:00:00Z"}],
        ("deepseek", "d1"): [{"id": "1", "role": "user", "text": "开始", "order": 1, "time": "2026-10-22T08:00:00Z"}],
    }

    def ok(name, cond, detail=""):
        print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail and not cond else ""), flush=True)
        if not cond: fails.append(name)

    def route(r, req):
        u = urlsplit(req.url)
        if u.path == "/":
            html = (HERE / "remote.html").read_text(encoding="utf-8").replace(
                "<!--machine-->", '<script>window.MACHINE={apps:["codex","claude","deepseek"],voice:false};</script>')
            return r.fulfill(status=200, content_type="text/html; charset=utf-8", body=html)
        if u.path == "/api/chat":
            q = parse_qs(u.query); key = (q.get("app", [""])[0], q.get("id", [""])[0])
            if key in transcripts:
                return r.fulfill(status=200, content_type="application/json", body=json.dumps(chat(*key, transcripts[key]), ensure_ascii=False))
        if u.path == "/api/codex/state":
            return r.fulfill(status=200, content_type="application/json", body=json.dumps({"available": True, "running": True, "settings": {"model": "gpt-5", "effort": "high", "mode": "default"}, "questions": [], "queued": [], "images": [], "catalog": {"models": []}}))
        if u.path == "/api/deepseek/state":
            return r.fulfill(status=200, content_type="application/json", body=json.dumps({"available": True, "running": True, "settings": {}, "questions": [], "interactions": [], "inbox": {}}))
        return handle(r, req)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, channel="chrome")
        ctx = browser.new_context(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
        ctx.add_init_script(FAKE_STREAM)
        ctx.route(ORIGIN + "/**", route)
        page = ctx.new_page()
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(ORIGIN)
        page.wait_for_function("window.readingUI && window.workspaceUI && window.codexUI")

        def open_chat(app, cid):
            page.evaluate("([app, id]) => openConv({app, id, title: '回复测试', status: 'running'})", [app, cid])
            page.wait_for_function("document.getElementById('cvMsgs').dataset.ready && window.sources.some(x => !x.closed)")
            page.wait_for_timeout(300)

        def send(app, cid, messages, live=()):
            assert page.evaluate("v => window.deliver(v)", {"app": app, "id": cid, "messages": messages, "streaming_ids": list(live), "meta": {"status": "running"}})

        # -- the first paint shows what is there as it is
        open_chat("codex", "c1")
        first = page.evaluate("document.querySelector('[data-key=\"a1\"] .reply-text').textContent")
        ok("opening a conversation shows its replies whole at once", first == "早先的回答：" + WORDS * 3, first[:40])

        # -- a reply streamed in three lumps a second apart runs out in many small steps
        page.evaluate("const b = document.getElementById('cvMsgs'); b.scrollTop = b.scrollHeight")
        page.evaluate("watch('live1')")
        text = ""
        for i in range(3):
            text += WORDS * 3
            send("codex", "c1", [{"id": "live1", "role": "assistant", "phase": "final_answer", "text": text, "streaming": True}], ["live1"])
            if i == 1:  # mid-stream: the copy button is a node that stays put between updates
                page.wait_for_timeout(150)
                page.evaluate("document.querySelector('[data-key=\"live1\"] .message-actions button').__mark = 1")
                page.wait_for_timeout(400)
                kept = page.evaluate("!!document.querySelector('[data-key=\"live1\"] .message-actions button').__mark")
                ok("while the words run out, the copy button under them is not rebuilt", kept)
                page.wait_for_timeout(450)
            else:
                page.wait_for_timeout(1000)
        final = text + "\n\n```\nnpm test\n```"
        send("codex", "c1", [{"id": "live1", "role": "assistant", "phase": "final_answer", "text": final}], [])
        page.wait_for_timeout(1800)
        seen = page.evaluate("window.watching = false, window.seen")
        lens = [s["len"] for s in seen if s["len"] >= 0]
        steps = [b - a for a, b in zip(lens, lens[1:]) if b != a]
        shown = page.evaluate("document.querySelector('[data-key=\"live1\"] .reply-text').textContent")
        ok("a streamed reply grows in many small steps, not one lump per update", len(set(lens)) >= 40, f"{len(set(lens))} sizes over {len(lens)} frames")
        ok("no step shows more than a sliver at once (a lump was 120 characters)", steps and max(steps) <= 30, f"largest step {max(steps) if steps else None}")
        ok("the words only ever grow", all(s > 0 for s in steps), [s for s in steps if s <= 0][:5])
        ok("in the end the whole reply is there", shown.replace("\n", "").startswith(text) and "npm test" in shown, shown[-30:])
        ok("once run out, its code gets the copy button", page.locator("[data-key='live1'] .code-copy").count() == 1)
        late = [s["end"] for s in seen[len(seen) // 3:]]
        ok("from the end of the conversation, the view follows the words down", max(late) <= 30, f"farthest {max(late):.0f}px")

        # -- a reader scrolled up is left where they are
        page.evaluate("watch('live2')")
        send("codex", "c1", [{"id": "live2", "role": "assistant", "phase": "final_answer", "text": WORDS * 4, "streaming": True}], ["live2"])
        page.wait_for_timeout(100)
        page.evaluate("document.getElementById('cvMsgs').scrollTop = 0")
        page.wait_for_timeout(400)
        send("codex", "c1", [{"id": "live2", "role": "assistant", "phase": "final_answer", "text": WORDS * 8, "streaming": True}], ["live2"])
        page.wait_for_timeout(1200)
        top = page.evaluate("window.watching = false, document.getElementById('cvMsgs').scrollTop")
        ok("someone reading higher up is not pulled down while the words run out", top < 40, f"scrollTop {top}")
        page.evaluate("const b = document.getElementById('cvMsgs'); b.scrollTop = b.scrollHeight")

        # -- a finger lifted off words that were rewritten under it (its touchend reaches only the node it went down on,
        #    which has left the page): the view follows the words down again at once
        cdp = ctx.new_cdp_session(page)
        send("codex", "c1", [{"id": "live3", "role": "assistant", "phase": "final_answer", "text": WORDS * 3, "streaming": True}], ["live3"])
        page.wait_for_timeout(1500)
        b = page.locator("[data-key='live3'] .reply-text").bounding_box()
        cdp.send("Input.dispatchTouchEvent", {"type": "touchStart", "touchPoints": [{"x": b["x"] + b["width"] / 2, "y": b["y"] + b["height"] / 2, "id": 1}]})
        page.wait_for_timeout(50)
        send("codex", "c1", [{"id": "live3", "role": "assistant", "phase": "final_answer", "text": WORDS * 4, "streaming": True}], ["live3"])
        page.wait_for_timeout(100)
        cdp.send("Input.dispatchTouchEvent", {"type": "touchEnd", "touchPoints": []})
        page.wait_for_timeout(1100)
        page.evaluate("const b = document.getElementById('cvMsgs'); b.scrollTop = b.scrollHeight")
        page.evaluate("watch('live3')")
        send("codex", "c1", [{"id": "live3", "role": "assistant", "phase": "final_answer", "text": WORDS * 12, "streaming": True}], ["live3"])
        page.wait_for_timeout(1200)
        ends = [s["end"] for s in page.evaluate("window.watching = false, window.seen")]
        ok("a finger lifted off words rewritten under it: the view follows the words down again at once", ends and max(ends) <= 30, f"farthest {max(ends):.0f}px")

        # -- a fresh read of the conversation (one follows every send) while a reply is being written: the record does not
        #    have the reply yet, and it used to blink out until the stream brought it back
        send("codex", "c1", [{"id": "live4", "role": "assistant", "phase": "final_answer", "text": WORDS * 2, "streaming": True}], ["live4"])
        page.wait_for_timeout(900)
        page.evaluate("""window.missing = 0; window.watching = true; (function loop() { if (!window.watching) return;
            if (!document.querySelector('#cvMsgs [data-key="live4"] .reply-text')) window.missing++; requestAnimationFrame(loop); })()""")
        page.evaluate("loadConv(true)")
        page.wait_for_timeout(800)
        missing = page.evaluate("window.watching = false, window.missing")
        ok("a fresh read while a reply is being written (one follows every send) keeps the reply on screen", missing == 0, f"missing in {missing} frames")

        # -- a block that lands whole (how Claude writes) runs out within about a second
        open_chat("claude", "c3")
        page.evaluate("watch('cb1')")
        block = WORDS * 10  # 400 characters
        send("claude", "c3", [{"id": "cb1", "role": "assistant", "text": block, "time": "2026-10-22T08:00:10Z"}])
        page.wait_for_timeout(250)
        part = page.evaluate("document.querySelector('[data-key=\"cb1\"] .reply-text').textContent.length")
        page.wait_for_timeout(1100)
        whole = page.evaluate("window.watching = false, document.querySelector('[data-key=\"cb1\"] .reply-text').textContent.length")
        ok("a block that lands whole runs out rather than appearing at once", 0 < part < len(block), f"{part} of {len(block)} after 0.25 s")
        ok("and is all there within about a second", whole == len(block), f"{whole} of {len(block)}")

        # -- a pile of new rows at once (back to the latest, a long gap) shows as it is
        pile = [{"id": f"cp{i}", "role": "assistant", "text": WORDS * 2, "time": f"2026-10-22T08:01:0{i}Z"} for i in range(5)]
        send("claude", "c3", pile)
        page.wait_for_timeout(60)
        lens = page.evaluate("[...document.querySelectorAll('[data-key^=\"cp\"] .reply-text')].map(n => n.textContent.length)")
        ok("five new replies at once show whole, without running out", lens == [len(WORDS) * 2] * 5, lens)

        # -- DeepSeek hands a streamed reply over to its saved copy under another name: it carries on, no fresh start
        open_chat("deepseek", "d1")
        page.evaluate("""window.watching = true; window.seen = []; (function loop() { if (!window.watching) return;
            const n = document.querySelector('#cvMsgs .bub.assistant:not(.thinking) .reply-text');
            window.seen.push(n ? n.textContent.replace(/\\s/g, '').length : -1); requestAnimationFrame(loop); })()""")
        live = WORDS * 6
        send("deepseek", "d1", [{"id": "live:a:1", "role": "assistant", "text": live, "streaming": True, "order": 2.5}], ["live:a:1"])
        page.wait_for_timeout(300)
        send("deepseek", "d1", [{"id": "3", "role": "assistant", "text": live + WORDS, "order": 3}], [])
        page.wait_for_timeout(1500)
        seen = page.evaluate("window.watching = false, window.seen")
        grown = [n for n in seen if n >= 0]
        drops = [(a, b) for a, b in zip(grown, grown[1:]) if b < a]
        ok("DeepSeek's hand-over to the saved copy carries on where it was, with no fresh start", not drops and grown and grown[-1] == len(live + WORDS), (drops[:3], grown[-1:] if grown else None))
        ok("only the saved copy is left", page.locator("#cvMsgs .bub.assistant:not(.thinking)").count() == 1)

        # -- Reduce Motion: the words show as they come
        page.emulate_media(reduced_motion="reduce")
        send("deepseek", "d1", [{"id": "4", "role": "assistant", "text": WORDS * 5, "order": 4}])
        page.wait_for_timeout(60)
        now = page.evaluate("document.querySelector('[data-key=\"4\"] .reply-text').textContent.length")
        ok("with Reduce Motion a new reply shows whole at once", now == len(WORDS) * 5, now)
        page.emulate_media(reduced_motion="no-preference")

        # -- just back on screen: what came meanwhile shows as it is
        page.evaluate("""Object.defineProperty(document, 'hidden', {configurable: true, get: () => true}); document.dispatchEvent(new Event('visibilitychange'));
            Object.defineProperty(document, 'hidden', {configurable: true, get: () => false}); document.dispatchEvent(new Event('visibilitychange'))""")
        page.wait_for_function("window.sources.some(x => !x.closed)")
        send("deepseek", "d1", [{"id": "5", "role": "assistant", "text": WORDS * 5, "order": 5}])
        page.wait_for_timeout(60)
        now = page.evaluate("document.querySelector('[data-key=\"5\"] .reply-text').textContent.length")
        ok("right after the page comes back on screen, a new reply shows whole", now == len(WORDS) * 5, now)

        ok("no page errors", not errors, errors[:3])
        browser.close()
    print(f"reply flow ui check: {'FAILED ' + str(len(fails)) if fails else 'ok'}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
