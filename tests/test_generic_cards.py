"""说明书里的 skills 能力、此刻能力的打底规则、假助手的通用批准 / 回答卡片（第二批设计 P1–P3、P6）。

只用源码和内存里的假数据：不连 Codex，不读任何真实用户目录。
"""
from __future__ import annotations

import io
import json
import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import archives  # noqa: E402
import chat_history  # noqa: E402
import remote  # noqa: E402
import usage_limits  # noqa: E402
from agents import registry, testing  # noqa: E402
from agents.base import Agent, make_manifest  # noqa: E402


class SkillsCapabilityTests(unittest.TestCase):
    """P1：说明书里没写 skills 的按类属性 has_skills 补，模块自己写了的以模块为准。"""

    def test_three_builtin_manifests_take_skills_from_has_skills(self):
        caps = {app: registry.get(app).manifest()["capabilities"] for app in ("codex", "claude", "deepseek")}
        self.assertIs(caps["codex"]["skills"], True)
        self.assertIs(caps["claude"]["skills"], True)
        self.assertIs(caps["deepseek"]["skills"], False)

    def test_a_module_writing_skills_itself_wins(self):
        # 假助手自己写了 skills: True（说明书里显式写的那条路）
        self.assertIs(registry.get("testing", include_testing=True).manifest()["capabilities"]["skills"], True)

        class ModuleSaysNo(Agent):
            has_skills = True

            def build_manifest(self) -> dict:
                return make_manifest(ident="module_says_no", zh="假助手", en="Fake", order=90, color="#111111",
                                     capabilities={"skills": False})

        class ModuleSaysYes(Agent):
            has_skills = False

            def build_manifest(self) -> dict:
                return make_manifest(ident="module_says_yes", zh="假助手", en="Fake", order=91, color="#111111",
                                     capabilities={"skills": True})

        self.assertIs(ModuleSaysNo().manifest()["capabilities"]["skills"], False)
        self.assertIs(ModuleSaysYes().manifest()["capabilities"]["skills"], True)


class NarrowAgent(Agent):
    """此刻能力只给了一个键：其余键要按说明书补回来。"""

    id = "narrow"
    has_skills = True

    def build_manifest(self) -> dict:
        return make_manifest(ident="narrow", zh="半能力助手", en="Narrow", order=92, color="#123456",
                             capabilities={"stop": True, "approve": True, "answer": True, "skills": True})

    def capabilities_now(self, server, conv_id: str) -> dict | None:
        return {"capabilities": {"stop": False, "approve": True}, "notes": {"stop": "测试里不能停止"}}


class CapabilitiesNowPaddingTests(unittest.TestCase):
    """P2：发出去之前用说明书打底；can_now 遇到没写的键退回说明书。"""

    def setUp(self):
        self.agent = NarrowAgent()

    def handler(self, protocol: int):
        return SimpleNamespace(_client_protocol=lambda: protocol, server=object())

    def test_attach_pads_missing_keys_from_the_manifest(self):
        data = {"available": True, "status": "waiting"}
        out = self.agent.attach_capabilities_now(self.handler(2), "c-1", data)
        caps = out["capabilities_now"]
        self.assertIs(caps["stop"], False)
        self.assertIs(caps["approve"], True)
        self.assertIs(caps["answer"], True)   # 模块没提到，等于说明书
        self.assertIs(caps["skills"], True)   # 模块没提到，等于说明书
        self.assertEqual(out["capability_notes"], {"stop": "测试里不能停止"})
        self.assertEqual(data, {"available": True, "status": "waiting"})  # 原来的字典没被改

    def test_protocol_one_gets_the_same_object_untouched(self):
        data = {"available": True}
        out = self.agent.attach_capabilities_now(self.handler(1), "c-1", data)
        self.assertIs(out, data)
        self.assertNotIn("capabilities_now", out)

    def test_a_handler_without_protocol_counts_as_one(self):
        data = {"available": True}
        out = self.agent.attach_capabilities_now(SimpleNamespace(server=object()), "c-1", data)
        self.assertIs(out, data)

    def test_can_now_falls_back_to_the_manifest_for_missing_keys(self):
        server = object()
        self.assertIs(self.agent.can_now("stop", server, "c-1"), False)
        self.assertIs(self.agent.can_now("approve", server, "c-1"), True)
        self.assertIs(self.agent.can_now("answer", server, "c-1"), True)

    def test_can_now_without_a_server_uses_the_manifest(self):
        self.assertIs(self.agent.can_now("stop"), True)

    def test_codex_apptools_state_carries_skills_and_never_widens(self):
        """新版 Codex 的字典里没有 skills：打底以后协议 2 的控制态有它，且每一项不比说明书宽。"""
        codex = registry.get("codex")
        manifest_caps = codex.manifest()["capabilities"]

        class Handler:
            server = SimpleNamespace()

            def _client_protocol(self):
                return 2

        with patch("codex_apptools.current_route", return_value="apptools"), \
             patch("codex_hooks.read_trust_status", return_value="enabled"):
            out = codex.attach_capabilities_now(Handler(), "c-1", {"available": True})
        now = out["capabilities_now"]
        self.assertIs(now["skills"], True)
        self.assertIs(now["stop"], True)
        self.assertIs(now["slash_commands"], False)
        self.assertEqual(now["settings"], ["model", "effort"])
        for key, value in now.items():
            self.assertIn(key, manifest_caps)
            if isinstance(manifest_caps[key], bool):
                self.assertFalse(value and not manifest_caps[key], key)


class TestingAnswerTests(unittest.TestCase):
    """P3：假助手的卡片、答复校验，以及答完回到 idle。"""

    def setUp(self):
        testing.reset()
        self.addCleanup(testing.reset)
        self.agent = registry.get("testing", include_testing=True)

    def pending(self, conv_id: str = "test-waiting"):
        return self.agent.state(conv_id)["questions"]

    def test_the_waiting_conversation_lists_an_approval_card_and_a_question_card(self):
        cards = self.pending()
        self.assertEqual([c["kind"] for c in cards], ["approval", "question"])
        approval = cards[0]
        self.assertEqual(approval["id"], "approval-7")
        self.assertEqual(approval["status"], "pending")
        self.assertEqual(approval["title"], "测试助手想运行命令")
        self.assertEqual(approval["detail"].split("\n"), ["npm test", "在 C:\\测试\\项目"])
        self.assertEqual(approval["answer_revision"], "")
        self.assertEqual(approval["expires_at"], 0)
        self.assertEqual([q["id"] for q in approval["questions"]], ["decision"])
        self.assertEqual([o["label"] for o in approval["questions"][0]["options"]], ["允许一次", "拒绝"])
        question = cards[1]
        self.assertEqual(question["kind"], "question")
        self.assertNotIn("title", question)  # 没有 title：客户端用第一题的 header
        self.assertEqual(len(question["questions"]), 2)
        first, second = question["questions"]
        self.assertIs(first["isOther"], True)
        self.assertIsNot(first["isMultiple"], True)
        self.assertIs(second["isMultiple"], True)
        self.assertEqual(question["answer_revision"], "rev-1")

    def test_answering_the_approval_and_then_the_question_returns_to_idle(self):
        out = self.agent.answer({"id": "test-waiting", "question_id": "approval-7",
                                 "answers": {"decision": ["允许一次"]}, "answer_revision": ""})
        self.assertEqual(out, {"ok": True, "accepted": True, "text": "已允许本次操作"})
        self.assertEqual([c["id"] for c in self.pending()], ["question-8"])
        self.assertNotEqual(self.agent.state("test-waiting")["status"], "idle")

        out = self.agent.answer({"id": "test-waiting", "question_id": "question-8",
                                 "answers": {"plan": ["方案 A"], "files": ["a.py"]},
                                 "answer_revision": "rev-1"})
        self.assertEqual(out["text"], "答案已提交")
        self.assertEqual(self.pending(), [])
        self.assertEqual(self.agent.state("test-waiting")["status"], "idle")
        self.assertEqual(self.agent.find("test-waiting")["status"], "idle")

    def test_declining_says_so(self):
        out = self.agent.answer({"id": "test-waiting", "question_id": "approval-7",
                                 "answers": {"decision": ["拒绝"]}})
        self.assertEqual(out["text"], "已拒绝本次操作")

    def test_an_answered_or_unknown_card_is_409(self):
        self.agent.answer({"id": "test-waiting", "question_id": "approval-7",
                           "answers": {"decision": ["允许一次"]}})
        with self.assertRaises(Exception) as caught:
            self.agent.answer({"id": "test-waiting", "question_id": "approval-7",
                               "answers": {"decision": ["允许一次"]}})
        self.assertEqual(getattr(caught.exception, "status", None), 409)
        self.assertEqual(str(caught.exception), "这个问题已回答或已失效，请刷新")
        with self.assertRaises(Exception) as caught:
            self.agent.answer({"id": "test-waiting", "question_id": "no-such-card", "answers": {}})
        self.assertEqual(getattr(caught.exception, "status", None), 409)
        # 被退回的答复不会把卡片答掉
        self.assertEqual([c["id"] for c in self.pending()], ["question-8"])

    def test_bad_answers_are_400(self):
        bad = [
            {"question_id": "approval-7", "answers": {}},                             # 没答
            {"question_id": "approval-7", "answers": {"decision": []}},               # 空
            {"question_id": "approval-7", "answers": {"decision": [""]}},             # 空字符串
            {"question_id": "approval-7", "answers": {"decision": ["允许一次", "拒绝"]}},  # 单选给了两个
            {"question_id": "approval-7", "answers": {"decision": ["随便写的"]}},       # 批准卡只认给出的选项
            {"question_id": "approval-7", "answers": {"decision": ["允" * 8001]}},     # 太长
            {"question_id": "question-8", "answers": {"plan": ["方案 A"]}},            # 没答全
            {"question_id": "question-8", "answers": {"plan": ["方案 A"], "files": ["c.py"]}},  # 不认识的选项
        ]
        for body in bad:
            with self.subTest(body=body):
                with self.assertRaises(Exception) as caught:
                    self.agent.answer({"id": "test-waiting", **body})
                self.assertEqual(getattr(caught.exception, "status", None), 400)
                self.assertTrue(str(caught.exception))
        self.assertEqual([c["id"] for c in self.pending()], ["approval-7", "question-8"])

    def test_free_text_is_taken_where_the_card_allows_it(self):
        out = self.agent.answer({"id": "test-waiting", "question_id": "question-8",
                                 "answers": {"plan": ["我自己写的方案"], "files": ["a.py", "b.py"]},
                                 "answer_revision": "rev-1"})
        self.assertEqual(out["text"], "答案已提交")

    def test_reset_puts_the_cards_back(self):
        self.agent.answer({"id": "test-waiting", "question_id": "approval-7",
                           "answers": {"decision": ["允许一次"]}})
        testing.reset()
        self.assertEqual([c["id"] for c in self.pending()], ["approval-7", "question-8"])
        self.assertEqual(self.agent.state("test-waiting")["status"], "waiting")

    def test_the_waiting_conversation_still_reads_and_lists(self):
        self.assertEqual(self.agent.read("test-waiting")["status"], "waiting")
        self.assertIn("test-waiting", [row["id"] for row in self.agent.catalog()["items"]])


class GenericAnswerHttpTests(unittest.TestCase):
    """统一地址 POST /api/agents/testing/answer：成功 200，过时 409，不合格 400，都是中文原因。"""

    def setUp(self):
        testing.reset()
        self.addCleanup(testing.reset)
        env = patch.dict(os.environ, {"TELEPLY_TEST_AGENTS": "1"})
        env.start()
        self.addCleanup(env.stop)
        apps = ["testing"]
        history = chat_history.History()
        self.server = SimpleNamespace(
            machine={"name": "测试电脑", "apps": list(apps), "voice": False},
            cfg={"token": "secret"},
            history=history,
            archives=archives.Archives(history=history, apps=lambda: list(apps), log=lambda _msg: None),
            usage=usage_limits.Usage(apps=lambda: list(apps), desktop=None, log=lambda _msg: None),
            tasks=SimpleNamespace(apply_status=lambda items: items),
            references=None, deepseek=None, new_chats=None,
            log=SimpleNamespace(write=lambda _msg: None),
        )

    def _call(self, method: str, path: str, *, protocol=2, body=None):
        handler = object.__new__(remote.Handler)
        sent = []
        handler.path = path
        handler.server = self.server
        handler.close_connection = False
        handler._responded = False
        headers = {"X-Teleply-Protocol": str(protocol)} if protocol is not None else {}
        payload = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else b""
        headers["Content-Length"] = str(len(payload))
        handler.rfile = io.BytesIO(payload)
        handler.headers = headers
        handler._send = lambda code, data, ctype, extra=None: sent.append((code, json.loads(data) if data else None))
        if method == "GET":
            handler.do_GET()
        else:
            handler.do_POST()
        self.assertEqual(len(sent), 1, f"expected one response for {method} {path}, got {sent}")
        return sent[0]

    def test_answer_succeeds_409s_and_400s_with_chinese_reasons(self):
        code, body = self._call("POST", "/api/agents/testing/answer?t=secret", body={
            "id": "test-waiting", "request_id": "r1", "question_id": "approval-7",
            "answers": {"decision": ["允许一次"]}})
        self.assertEqual(code, 200)
        self.assertEqual(body["text"], "已允许本次操作")

        code, body = self._call("POST", "/api/agents/testing/answer?t=secret", body={
            "id": "test-waiting", "request_id": "r2", "question_id": "approval-7",
            "answers": {"decision": ["允许一次"]}})
        self.assertEqual(code, 409)
        self.assertEqual(body["error"], "这个问题已回答或已失效，请刷新")

        code, body = self._call("POST", "/api/agents/testing/answer?t=secret", body={
            "id": "test-waiting", "request_id": "r3", "question_id": "question-8",
            "answers": {"plan": [], "files": ["a.py"]}})
        self.assertEqual(code, 400)
        self.assertTrue(body["error"])

    def test_protocol_one_still_cannot_reach_the_fake_assistant(self):
        code, _ = self._call("POST", "/api/agents/testing/answer?t=secret", protocol=1, body={
            "id": "test-waiting", "question_id": "approval-7", "answers": {"decision": ["允许一次"]}})
        self.assertEqual(code, 404)


if __name__ == "__main__":
    unittest.main()
