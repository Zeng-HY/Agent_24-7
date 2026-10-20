"""Focused phone interaction regression, with deterministic transport failures."""
import copy
import json
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright
import motion_check as fixture


def main():
    sent, replies, receipts, held = [], [], {}, []
    card = {"id": "async:test-call", "request_id": "test-call", "kind": "async", "turn_id": "test-turn",
            "status": "pending", "editable": True, "answer_revision": "0", "created_at": 1,
            "questions": [{"id": "0", "question": "测试金额", "options": [{"label": "10"}, {"label": "5"}], "isOther": True}]}
    state = {"available": True, "running": True, "active_turn_id": "test-turn", "questions": [card],
             "queue_available": True, "queued": [], "images": [], "plan": None,
             "settings": {"model": "gpt-5", "effort": "high", "mode": "default", "service_tier": None}, "catalog": {"models": []}}
    mode = {"hold": False, "lose": False}

    def route(r, req):
        path = urlsplit(req.url).path
        body = json.loads(req.post_data or "{}")
        def out(v): r.fulfill(status=200, content_type="application/json", body=json.dumps(v))
        if path == "/api/codex/state": return out(state)
        if path == "/api/codex/receipt":
            from urllib.parse import parse_qs
            rid = parse_qs(urlsplit(req.url).query)["request_id"][0]
            return out(receipts.get(rid, {"state": "unknown"}))
        if path == "/api/codex/answer":
            replies.append(body)
            card.update(status="answered", answers=body["answers"], answer_revision=str(len(replies)))
            receipts[body["request_id"]] = {"state": "accepted", "result": {"ok": True}}
            return out({"ok": True, "accepted": True})
        if path == "/api/codex/send":
            sent.append(body)
            queued = body["intent"] == "queue"
            result = {"ok": True, "accepted": True, "delivery_state": "queued" if queued else "accepted", "text": "已排队" if queued else "已交给 Codex"}
            receipts[body["request_id"]] = {"state": result["delivery_state"], "result": result}
            if queued: state["queued"].append({"id": body["request_id"], "text": body["text"], "status": "queued"})
            if mode["hold"]: held.append((r, result)); return
            if mode["lose"]: r.abort(); return
            return out(result)
        if path == "/api/codex/queue-action":
            state["queued"] = [q for q in state["queued"] if q["id"] != body["message_id"]]
            receipts[body["message_id"]] = {"state": "cancelled", "result": {"text": "已取消"}}
            return out({"ok": True, "text": "已取消"})
        if path == "/api/chat/send": raise AssertionError("Codex used legacy send")
        return fixture.handle(r, req)

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        ctx = browser.new_context(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
        ctx.route(fixture.ORIGIN + "/**", route)
        page = ctx.new_page(); errors = []
        page.on("pageerror", lambda e: errors.append(e.message))
        page.goto(fixture.ORIGIN)
        page.wait_for_function("window.codexUI && window.workspaceUI")
        page.evaluate("c=>openConv(c)", fixture.fake_chat("codex", "c4"))
        page.locator("#cvOpts .codex-ask").click()
        assert page.locator(".ask-next").is_disabled()
        page.locator(".ask-choice").first.click()
        assert not replies
        page.locator(".ask-next").click()
        page.wait_for_function("!overlays.some(o=>o.id==='codexAskSheet')")
        assert replies[-1]["answers"] == {"0": ["10"]}
        page.get_by_role("button", name="修改答案", exact=True).click()
        page.locator(".ask-choice").nth(1).click()
        assert len(replies) == 1
        page.locator(".ask-next").click()
        page.wait_for_function("!overlays.some(o=>o.id==='codexAskSheet')")
        assert replies[-1]["answers"] == {"0": ["5"]}
        assert replies[0]["request_id"] != replies[1]["request_id"]
        print("PASS explicit submit and revision")

        mode["hold"] = True
        page.locator("#cvText").fill("first")
        page.evaluate("void codexUI.send()")
        page.wait_for_timeout(200)
        assert held
        page.locator("#cvText").fill("new draft")
        rr, result = held.pop(); rr.fulfill(status=200, content_type="application/json", body=json.dumps(result))
        page.wait_for_function("!sending")
        assert page.locator("#cvText").input_value() == "new draft"
        assert sent[-1]["intent"] == "auto" and sent[-1]["expected_turn"] == "test-turn"
        print("PASS steering intent and newer draft preservation")
        mode.update(hold=False, lose=True)
        page.evaluate("void codexUI.send()")
        page.wait_for_function("!sending")
        assert len(sent) == 2
        print("PASS lost response reconciles without resend")
        mode["lose"] = False
        page.locator("#cvText").fill("queued")
        page.locator("#codexQueueSend").click()
        page.wait_for_function("!sending")
        assert sent[-1]["intent"] == "queue"
        page.locator("#codexQueue").get_by_role("button", name="取消排队").click()
        page.wait_for_function("!document.querySelector('#codexQueue .queue-row')")
        print("PASS explicit queue and cancel")
        assert not errors, errors
        print("PASS no JavaScript errors")
        browser.close()


if __name__ == "__main__": main()
