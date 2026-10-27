"""10-16: Claude desktop ends a turn with a next-step box (its mcp__ccd_turn__wrap_up tool): a recap, a question and a
button or two, drawn at the end of the chat. The phone showed none of it, read the turn as still running (停止这一轮),
and never pushed a notice for it."""
import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import chats  # noqa: E402
import claude_control  # noqa: E402
import notify  # noqa: E402

ASK = "要不要开始第 0 步实测？"
RECAP = "部署方案已写好，放在 docs/deploy_plan.md。没改任何代码，没花钱。"
BOX = {"type": "tool_use", "id": "toolu_box1", "name": "mcp__ccd_turn__wrap_up",
       "input": {"recap": RECAP, "ask": ASK,
                 "actions": [{"label": "开始第 0 步", "message": "开始第 0 步，用你建议的 3 份原文 Word。"}, {"label": "先改方案"}]}}


def assistant(*blocks, stop="tool_use", mid="m1", ts="2026-10-16T01:59:48Z"):
    return json.dumps({"type": "assistant", "timestamp": ts, "uuid": mid + "-u",
                       "message": {"id": mid, "stop_reason": stop, "content": list(blocks)}}, ensure_ascii=False).encode()


def result(tool_id, ts="2026-10-16T01:59:49Z", text="Shown in the next-step box. The box ends your turn."):
    return json.dumps({"type": "user", "timestamp": ts, "uuid": "r-" + tool_id,
                       "message": {"content": [{"type": "tool_result", "tool_use_id": tool_id, "content": text}]}}).encode()


def said(text, ts="2026-10-16T02:05:00Z"):
    return json.dumps({"type": "user", "timestamp": ts, "uuid": "u-" + ts, "message": {"content": text}}, ensure_ascii=False).encode()


TURN = [said("写一个部署方案", ts="2026-10-16T01:40:00Z"),
        assistant({"type": "text", "text": "方案已写好。"}, mid="m0", ts="2026-10-16T01:59:40Z"),
        assistant(BOX), result("toolu_box1")]


class Parse(unittest.TestCase):
    def test_the_box_is_a_card_waiting_on_the_user_and_the_turn_is_over(self):
        msgs, state = chats.parse_claude(TURN)
        box = msgs[-1]
        self.assertEqual([m["role"] for m in msgs], ["user", "assistant", "next"])
        self.assertEqual((box["recap"], box["ask"], box["tool_id"], box["open"]), (RECAP, ASK, "toolu_box1", True))
        self.assertEqual(box["actions"], [{"label": "开始第 0 步", "message": "开始第 0 步，用你建议的 3 份原文 Word。"},
                                          {"label": "先改方案", "message": "先改方案"}])  # no message: the label is sent
        self.assertIs(state["running"], False)  # the phone offered 停止这一轮 for it

    def test_answered_the_recap_stays_without_question_or_buttons(self):
        msgs, state = chats.parse_claude(TURN + [said("开始第 0 步")])
        box = next(m for m in msgs if m["role"] == "next")
        self.assertNotIn("open", box)
        self.assertEqual(box["text"], RECAP + "\n\n" + ASK)
        self.assertIs(state["running"], True)

    def test_a_box_with_nothing_to_ask_does_not_end_the_turn(self):
        quiet = {**BOX, "id": "toolu_box2", "input": {"recap": "改好了，测试都过了。"}}
        msgs, state = chats.parse_claude([said("改一下"), assistant(quiet), result("toolu_box2", text="Nothing is pending")])
        self.assertEqual((msgs[-1]["role"], msgs[-1]["actions"], msgs[-1].get("open")), ("next", [], None))
        self.assertIs(state["running"], True)  # its closing message is still to come
        _, state = chats.parse_claude([said("改一下"), assistant(quiet), result("toolu_box2"),
                                       assistant({"type": "text", "text": "改好了。"}, stop="end_turn", mid="m9")])
        self.assertIs(state["running"], False)

    def test_an_app_button_is_named_for_what_it_does(self):
        app = {**BOX, "input": {"recap": "改好了。", "ask": "要提交吗？", "actions": [{"action": "commit"}, {"label": "先不提交"}]}}
        msgs, _ = chats.parse_claude([assistant(app), result("toolu_box1")])
        self.assertEqual(msgs[0]["actions"], [{"label": "提交", "action": "commit"}, {"label": "先不提交", "message": "先不提交"}])

    def test_the_open_box_from_a_conversation_record(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "s.jsonl"
            path.write_bytes(b"\n".join(TURN) + b"\n")
            with mock.patch.object(chats, "conv_path", lambda item: path):
                self.assertEqual(chats.claude_open_next({"app": "claude"})["tool_id"], "toolu_box1")
                path.write_bytes(b"\n".join(TURN + [said("先改方案")]) + b"\n")
                self.assertIsNone(chats.claude_open_next({"app": "claude"}))


class LineByLine(unittest.TestCase):
    """The phone reads a conversation through chat_history.Transcript, which parses its record a line at a time: a box
    looked open on its own line for good, after the user had answered (10-16, a planning conversation), and the line with
    its result knew nothing of the box, so the turn read as running."""

    def test_open_until_answered_and_its_turn_over(self):
        import chat_history
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "s.jsonl"
            path.write_bytes(b"\n".join(TURN) + b"\n")
            record = chat_history.Transcript(path, "claude").refresh()
            box = next(m for m in record.messages if m["role"] == "next")
            self.assertTrue(box.get("open"))
            self.assertIs(record.state["running"], False)
            with path.open("ab") as f:
                f.write(said("我们现在的部署流程是什么样的？") + b"\n")
            record.refresh()
            self.assertNotIn("open", box)
            self.assertIs(record.state["running"], True)


class Notice(unittest.TestCase):
    def test_a_turn_that_ends_with_a_question_is_told(self):
        end = notify.turn_end("claude", TURN)
        self.assertEqual(end, {"state": "done", "key": "toolu_box1", "time": "2026-10-16T01:59:49Z", "text": ASK, "asks": True})
        self.assertEqual(notify.turn_end("claude", TURN[:-1])["state"], "running")  # the box drawn, its result not written yet

    def test_it_says_claude_waits_on_you(self):
        sent = []
        n = notify.Notifier({"token": "t", "bark": {"server": "https://api.day.app", "key": "k" * 22}}, "家里电脑", lambda *a: None, lambda: None,
                            sender=lambda *a, **k: sent.append((a, k)), page_url=lambda: "https://pc.example.ts.net/")
        n._tell({"key": "k"}, {"app": "claude", "id": "c1", "title": "部署方案"}, notify.turn_end("claude", TURN))
        (_, title, body), extra = sent[0]
        self.assertEqual((title, body, extra["subtitle"]), ("部署方案", ASK, "家里电脑 · Claude 在等你选"))


class Node:
    """A control in the desktop's tree, as UI Automation gives it."""
    def __init__(self, kind, name="", children=(), enabled=True):
        self.ControlTypeName, self.Name, self.IsEnabled, self.children, self.parent = kind, name, enabled, list(children), None
        self.pressed = 0
        for c in self.children:
            c.parent = self

    def GetParentControl(self):
        return self.parent

    def GetInvokePattern(self):
        node = self

        class Invoke:
            def Invoke(self):
                node.pressed += 1
                return True
        return Invoke()


def walk(node, maxDepth=30, depth=0):
    for c in node.children:
        yield c, depth + 1
        if depth + 1 < maxDepth:
            yield from walk(c, maxDepth, depth + 1)


def desktop_box(ask=ASK, labels=("开始第 0 步", "先改方案")):
    """The box as recorded on the desktop on 10-16 at 10:00, taking a click."""
    buttons = [Node("ButtonControl", label) for label in labels]
    actions = Node("GroupControl", "Suggested next actions", buttons)
    Node("GroupControl", "", [Node("GroupControl", "", [Node("TextControl", RECAP)]), Node("ButtonControl", "Dismiss"),
                              Node("GroupControl", "", [Node("TextControl", ask)]), actions])
    return actions, buttons


def desktop_list(ask=ASK, labels=("开始第 0 步", "先改方案")):
    """The box as recorded at 12:40: text, with its choices as a plain list and nothing to click. Returns its question."""
    question = Node("TextControl", ask)
    items = [Node("ListItemControl", label, [Node("TextControl", "•"), Node("TextControl", label)]) for label in labels]
    Node("GroupControl", "", [Node("GroupControl", "", [Node("TextControl", RECAP)]), Node("GroupControl", "", [question]),
                              Node("ListControl", "", items)])
    return question


TITLE = "部署流程：先在测试环境跑通，再切到正式环境"


def task_card(title=TITLE):
    """A task card as recorded on 10-16. Returns the button bearing its title and the card's buttons by name."""
    head = Node("ButtonControl", title, [Node("GroupControl", "", [Node("TextControl", title)])])
    named = {n: Node("ButtonControl", n) for n in ("Dismiss suggestion " + title, "Options", "Do it here", "Start")}
    Node("GroupControl", "1 suggested task", [Node("TextControl", "New session"), head, *named.values()])
    return head, named


class Press(unittest.TestCase):
    def setUp(self):
        self.found, self.logged, self.opened, self.sent, self.clock = {}, [], [], [], [0.0]
        test = self

        class Desktop:
            auto = type("Auto", (), {"WalkControl": staticmethod(walk)})()
            def run(self, fn, *args, timeout=None): return fn(*args)
            def _find(self, doc, kind, name): return list(test.found.get((kind, name), []))
            def _claude_show(self, hwnd): pass
            def log(self, text): test.logged.append(text)
            def send(self, app, tid, text): test.sent.append((app, tid, text)); return {"ok": True}
        self.ctrl = claude_control.Controller.__new__(claude_control.Controller)
        self.ctrl.desktop, self.ctrl.lock, self.ctrl.cache = Desktop(), threading.RLock(), {}
        self.ctrl._document = lambda item, open_first=False: (self.opened.append(open_first), (1, None, "doc"))[1]
        box = chats.parse_claude(TURN)[0][-1]
        for p in (mock.patch.object(chats, "find", lambda app, tid: {"id": tid, "app": app, "title": "部署方案"}),
                  mock.patch.object(chats, "claude_open_next", lambda item: box),
                  mock.patch.object(claude_control.time, "monotonic", lambda: self.clock[0]),
                  mock.patch.object(claude_control.time, "sleep", lambda s: self.clock.__setitem__(0, self.clock[0] + s))):
            p.start()
            self.addCleanup(p.stop)

    def box(self, group):
        self.found[("GroupControl", "Suggested next actions")] = [group]

    def test_the_same_button_is_pressed_on_the_pc(self):
        group, buttons = desktop_box()
        self.box(group)
        self.assertEqual(self.ctrl.next_step("c1", "toolu_box1", 1, "先改方案")["text"], "已在电脑上点了「先改方案」")
        self.assertEqual([b.pressed for b in buttons], [0, 1])
        self.assertTrue(self.opened[0])  # the PC opens the conversation first when it shows another
        self.assertEqual(self.logged, ["Claude「部署方案」：下一步点了「先改方案」"])
        self.assertEqual(self.sent, [])

    def test_a_box_answered_or_replaced_is_never_pressed(self):
        group, buttons = desktop_box()
        self.box(group)
        with self.assertRaises(chats.ChatError):
            self.ctrl.next_step("c1", "toolu_old", 0, "开始第 0 步")  # not the box the record holds now
        with self.assertRaises(chats.ChatError):
            self.ctrl.next_step("c1", "toolu_box1", 0, "先改方案")  # not that button
        self.assertEqual(([b.pressed for b in buttons], self.sent), ([0, 0], []))

    def test_a_box_drawn_as_a_plain_list_sends_the_buttons_words_at_once(self):
        # 10-16 12:40, a planning box: 合进 main pressed on the phone did nothing, the PC had no button to press
        self.found[("TextControl", ASK)] = [desktop_list()]
        result = self.ctrl.next_step("c1", "toolu_box1", 0, "开始第 0 步")
        self.assertEqual(self.sent, [("claude", "c1", "开始第 0 步，用你建议的 3 份原文 Word。")])
        self.assertTrue(result["sent"])
        self.assertLess(self.clock[0], 1)  # no wait for a box already found

    def test_a_box_no_longer_shown_sends_the_words_after_a_while(self):
        self.ctrl.next_step("c1", "toolu_box1", 1, "先改方案")
        self.assertEqual(self.sent, [("claude", "c1", "先改方案")])  # no message of its own: its label is what a click sends
        self.assertGreaterEqual(self.clock[0], 8)  # waited for a long conversation to draw its end

    def test_a_box_on_the_pc_that_asks_something_else_is_left_alone(self):
        group, buttons = desktop_box(ask="要不要提交？")
        self.box(group)
        with self.assertRaises(chats.ChatError):
            self.ctrl.next_step("c1", "toolu_box1", 0, "开始第 0 步")
        self.assertEqual(([b.pressed for b in buttons], self.sent), ([0, 0], []))

    def test_buttons_that_do_not_match_the_record_are_left_alone(self):
        group, buttons = desktop_box(labels=("开始第 0 步",))
        self.box(group)
        with self.assertRaises(chats.ChatError):
            self.ctrl.next_step("c1", "toolu_box1", 0, "开始第 0 步")  # one button where the record has two
        group, buttons = desktop_box(labels=("开始第一步", "先改方案"))
        self.box(group)
        with self.assertRaises(chats.ChatError):
            self.ctrl.next_step("c1", "toolu_box1", 0, "开始第 0 步")  # a reply button must bear its label
        self.assertEqual(([b.pressed for b in buttons], self.sent), ([0, 0], []))

    def app_box(self):
        return chats.parse_claude([assistant({**BOX, "input": {"recap": RECAP, "ask": ASK, "actions": [{"action": "commit"}, {"label": "先不提交"}]}}),
                                   result("toolu_box1")])[0][-1]

    def test_an_app_button_is_pressed_by_its_place(self):
        group, buttons = desktop_box(labels=("Commit", "先不提交"))
        self.box(group)
        with mock.patch.object(chats, "claude_open_next", lambda item: self.app_box()):
            self.ctrl.next_step("c1", "toolu_box1", 0, "提交")
        self.assertEqual([b.pressed for b in buttons], [1, 0])

    def test_an_app_button_with_nothing_to_press_is_left_to_the_pc(self):
        with mock.patch.object(chats, "claude_open_next", lambda item: self.app_box()):
            with self.assertRaises(claude_control.NextGone):
                self.ctrl.next_step("c1", "toolu_box1", 0, "提交")
        self.assertEqual(self.sent, [])

    def test_a_task_card_is_started_or_dismissed_on_the_pc(self):
        head, named = task_card()
        self.found[("ButtonControl", TITLE)] = [head]
        self.assertEqual(self.ctrl.task_step("c1", TITLE, "start")["text"], "已在电脑上开始了，新对话会出现在列表里")
        self.ctrl.task_step("c1", TITLE, "dismiss")
        self.assertEqual({n: b.pressed for n, b in named.items() if b.pressed}, {"Start": 1, "Dismiss suggestion " + TITLE: 1})
        self.assertEqual(self.logged, [f"Claude「部署方案」：任务卡片「{TITLE}」开始了", f"Claude「部署方案」：任务卡片「{TITLE}」关掉了"])

    def test_a_task_card_gone_or_twice_is_left_alone(self):
        with self.assertRaises(chats.ChatError):
            self.ctrl.task_step("c1", TITLE, "here")
        self.assertGreaterEqual(self.clock[0], 8)
        (one, a), (two, b) = task_card(), task_card()
        self.found[("ButtonControl", TITLE)] = [one, two]
        with self.assertRaises(chats.ChatError):
            self.ctrl.task_step("c1", TITLE, "here")
        self.assertEqual(a["Do it here"].pressed + b["Do it here"].pressed, 0)
        with self.assertRaises(chats.ChatError):
            self.ctrl.task_step("c1", TITLE, "options")

    def test_the_cards_still_waiting_on_the_pc(self):
        head, named = task_card()
        self.assertEqual(claude_control.Controller._waiting_tasks([head, *named.values(), Node("ButtonControl", "Copy")]), [TITLE])


class Tasks(unittest.TestCase):
    def call(self, initiation, title=TITLE):
        return {"type": "tool_use", "id": "toolu_task", "name": "mcp__ccd_session__start_session",
                "input": {"initiation": initiation, "title": title, "prompt": "目标：让部署流程……", "context": "fresh"}}

    def test_a_proposed_task_is_a_card(self):
        msgs, _ = chats.parse_claude([assistant(self.call("own_initiative"))])
        self.assertEqual({k: msgs[0][k] for k in ("role", "tool_id", "title", "brief", "offer")},
                         {"role": "task", "tool_id": "toolu_task", "title": TITLE, "brief": "目标：让部署流程……", "offer": False})
        self.assertTrue(chats.parse_claude([assistant(self.call("offer"))])[0][0]["offer"])

    def test_a_session_started_at_once_or_resumed_is_one_more_step(self):
        self.assertEqual(chats.parse_claude([assistant(self.call("user_asked"))])[0][0]["role"], "tool")
        resumed = {"type": "tool_use", "id": "t2", "name": "mcp__ccd_session__start_session", "input": {"proposal_id": "task_ccaeace1"}}
        self.assertEqual(chats.parse_claude([assistant(resumed)])[0][0]["role"], "tool")


if __name__ == "__main__":
    unittest.main()
