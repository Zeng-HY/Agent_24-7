"""claude_control._dock_read on a real recording of Claude desktop's question dock (AskUserQuestion, 10-11)."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import claude_control  # noqa: E402

# depth, control type, name, top of its rectangle, offscreen — recorded with UI Automation from the dock while
# Claude asked a two-question AskUserQuestion; the question area sits above the message box ('Prompt').
ROWS = [
    [1, 'StatusBarControl', '', 1238, False],
    [1, 'StatusBarControl', '', 1238, False],
    [1, 'StatusBarControl', '', 1238, False],
    [1, 'GroupControl', '', 1240, False],
    [2, 'TextControl', '1', 1274, False],
    [2, 'TextControl', '/', 1274, False],
    [2, 'TextControl', '2', 1274, False],
    [2, 'TextControl', 'Claude 在等你选的时候，手机上用哪种方式出现比较顺手？', 1271, False],
    [2, 'ButtonControl', 'View question options', 1264, False],
    [2, 'ButtonControl', 'Dismiss question', 1264, False],
    [2, 'ButtonControl', '输入框上方一条提示，点开是面板（推荐） 平时不挡对话、不和键盘抢地方；点提示条从底部弹出面板，显示问题原文、每个选项和它的说明，按钮宽大好点。 1', 1336, False],
    [3, 'GroupControl', '', 1352, False],
    [4, 'TextControl', '输入框上方一条提示，点开是面板（推荐）', 1354, False],
    [3, 'GroupControl', '', 1394, False],
    [4, 'TextControl', '平时不挡对话、不和键盘抢地方；点提示条从底部弹出面板，显示问题原文、每个选项和它的说明，按钮宽大好点。', 1394, False],
    [3, 'TextControl', '1', 1374, False],
    [2, 'ButtonControl', '一出现就直接弹出面板 不用多点一下；但你正在打字时也会弹出来，盖住输入框。 2', 1446, False],
    [3, 'GroupControl', '', 1462, False],
    [4, 'TextControl', '一出现就直接弹出面板', 1464, False],
    [3, 'GroupControl', '', 1504, False],
    [4, 'TextControl', '不用多点一下；但你正在打字时也会弹出来，盖住输入框。', 1504, False],
    [3, 'TextControl', '2', 1484, False],
    [2, 'ButtonControl', '像 Codex 那样放进对话里 显示在消息末尾，和 Codex 的提问卡片一个样子；要滚到底才看得到。 3', 1556, False],
    [3, 'GroupControl', '', 1572, False],
    [4, 'TextControl', '像 Codex 那样放进对话里', 1574, False],
    [3, 'GroupControl', '', 1614, False],
    [4, 'TextControl', '显示在消息末尾，和 Codex 的提问卡片一个样子；要滚到底才看得到。', 1614, False],
    [3, 'TextControl', '3', 1594, False],
    [2, 'ButtonControl', 'Other 4', 1682, False],
    [3, 'TextControl', 'Other', 1684, False],
    [3, 'TextControl', '4', 1687, False],
    [2, 'EditControl', 'Other option', 1744, False],
    [2, 'ButtonControl', 'Skip', 1846, False],
    [2, 'ButtonControl', 'Next', 1846, False],
    [1, 'GroupControl', '', 1240, False],
    [1, 'StatusBarControl', '', 1238, False],
    [1, 'StatusBarControl', '', 1928, False],
    [2, 'TextControl', 'Chat mode', 1930, True],
    [1, 'StatusBarControl', '', 1928, False],
    [1, 'GroupControl', '', 1930, False],
    [2, 'GroupControl', '', 1946, False],
    [3, 'GroupControl', '', 1946, False],
    [4, 'GroupControl', '', 1946, False],
    [5, 'GroupControl', '', 1946, False],
    [6, 'EditControl', 'Prompt', 1950, False],
    [7, 'GroupControl', '', 1950, False],
    [8, 'TextControl', '\n', 0, False],
    [6, 'StatusBarControl', '', 1946, False],
    [3, 'GroupControl', '', 1946, False],
    [4, 'GroupControl', '', 1946, False],
    [5, 'ButtonControl', 'Stop', 1946, False],
    [1, 'GroupControl', '', 1994, False],
    [2, 'ButtonControl', 'Add', 2022, False],
    [2, 'GroupControl', 'Press and hold to record', 2022, False],
    [3, 'ButtonControl', 'Press and hold to record', 2022, False],
    [3, 'ButtonControl', 'Dictation settings', 2022, False],
    [2, 'ButtonControl', 'Auto', 2022, False],
    [2, 'ButtonControl', 'Model: Opus 5.5', 2022, False],
    [2, 'ButtonControl', 'Effort: Extra', 2022, False],
    [2, 'ButtonControl', 'Usage: Context 785.2k / 1M (79%), Weekly · all models: 21%, Resets Sat 3:00 PM', 2022, False],
    [2, 'StatusBarControl', '', 2041, False],
    [3, 'TextControl', 'Fast mode off', 2041, False],
    [2, 'StatusBarControl', '', 2041, False]
]


class Rect:
    def __init__(self, top):
        self.top = top


class Ctrl:
    def __init__(self, depth, kind, name, top, off):
        self.ControlTypeName, self.Name, self.IsOffscreen, self.IsEnabled = kind, name, off, True
        self.BoundingRectangle = Rect(top)

    def GetTogglePattern(self):
        return None

    def GetSelectionItemPattern(self):
        return None


class Auto:
    def WalkControl(self, node, maxDepth=30):
        for depth, kind, name, top, off in ROWS:
            yield Ctrl(depth, kind, name, top, off), depth


class Desktop:
    auto = Auto()


def old_options():
    """The options as _read collected them before 10-11 (they make the action revision, so they must not change)."""
    out = []
    for depth, kind, name, top, off in ROWS:
        name = (name or "").strip()
        if off or kind not in ("ButtonControl", "RadioButtonControl", "CheckBoxControl") or not name:
            continue
        if name in claude_control.chats.CLAUDE_FIXED_BUTTONS or name.startswith(claude_control.chats.CLAUDE_FIXED_PREFIXES) \
                or name in ("Plan", "Manual", "Ask", "Ask permissions", "Accept edits"):
            continue
        out.append({"type": kind, "name": name})
    return out


class DockReadTest(unittest.TestCase):
    def setUp(self):
        self.ctrl = claude_control.Controller.__new__(claude_control.Controller)
        self.ctrl.desktop = Desktop()
        self.options, self.prompt = self.ctrl._dock_read(object())

    def test_options_unchanged(self):
        self.assertEqual(self.options, old_options())
        self.assertEqual(len(self.options), 8)

    def test_question_and_progress(self):
        self.assertEqual(self.prompt["progress"], "1 / 2")
        self.assertEqual(self.prompt["title"], "Claude 在等你选的时候，手机上用哪种方式出现比较顺手？")

    def test_choices_split_into_label_and_description(self):
        choices = self.prompt["choices"]
        self.assertEqual([c["label"] for c in choices], ["输入框上方一条提示，点开是面板（推荐）", "一出现就直接弹出面板", "像 Codex 那样放进对话里"])
        self.assertTrue(choices[0]["description"].startswith("平时不挡对话"))
        self.assertTrue(all(c["name"].endswith(str(i + 1)) for i, c in enumerate(choices)))  # the real button names, for the click

    def test_other_navigation_and_hidden(self):
        self.assertEqual(self.prompt["other"], {"name": "Other 4"})
        self.assertEqual([(n["name"], n["label"]) for n in self.prompt["nav"]], [("Dismiss question", "不回答"), ("Skip", "跳过"), ("Next", "下一题")])
        names = [c["name"] for c in self.prompt["choices"]] + [n["name"] for n in self.prompt["nav"]]
        self.assertNotIn("View question options", names)

    def test_texts_below_the_message_box_are_left_out(self):
        self.assertNotIn("Fast mode off", self.prompt["title"])


class UsageMeterTest(unittest.TestCase):
    """10-14: a conversation with no context figure yet names the usage meter "Usage, Weekly · …" (not "Usage: …"), and the
    phone showed it as the one choice of a question Claude waited on ("Claude 在等你选")."""

    def dock(self, rows):
        class Walk:
            def WalkControl(self, node, maxDepth=30):
                for depth, kind, name, top, off in rows:
                    yield Ctrl(depth, kind, name, top, off), depth
        ctrl = claude_control.Controller.__new__(claude_control.Controller)
        ctrl.desktop = type("D", (), {"auto": Walk()})()
        return ctrl._dock_read(object())

    def test_the_meter_is_no_choice(self):
        meter = [2, "ButtonControl", "Usage, Weekly · all models: 38%, Resets Sat 3:00 PM", 1900, False]
        composer = [[0, "GroupControl", "", 1900, False], [1, "EditControl", "Prompt", 1946, False], [1, "ButtonControl", "Stop", 1946, False],
                    [2, "ButtonControl", "Add", 2022, False], [2, "ButtonControl", "Auto", 2022, False],
                    [2, "ButtonControl", "Model: Opus 5.5", 2022, False], [2, "ButtonControl", "Effort: High", 2022, False]]
        self.assertEqual(self.dock(composer + [meter]), ([], None))              # above the message box
        self.assertEqual(self.dock([r for r in composer if r[1] != "EditControl"] + [meter]), ([], None))  # no box found

    def test_max_effort_notice_and_environment_are_not_questions(self):
        warning = 'Claude thinks longer with Max effort and can consume 3.5× or more usage than Medium.'
        rows = [[1, 'EditControl', 'Prompt', 100, False],
                [1, 'ButtonControl', warning, 50, False],
                [2, 'TextControl', warning, 50, False],
                [1, 'ButtonControl', 'Dismiss', 50, False],
                [1, 'ButtonControl', 'Environment: notes_app', 150, False],
                [1, 'ButtonControl', 'Permissions: Auto', 150, False]]
        self.assertEqual(self.dock(rows), ([], None))

    # 10-16, recorded from the dock while Claude showed the weekly usage-limit notice above the message box: the phone
    # showed "Approaching weekly usage limit 去选择" and "Claude 有待处理操作", its Get more usage button taken for a choice.
    NOTICE = [[1, 'StatusBarControl', '', 1178, False], [1, 'StatusBarControl', '', 1178, False], [1, 'GroupControl', '', 1179, False],
              [1, 'StatusBarControl', '', 1179, False],
              [2, 'TextControl', 'Approaching weekly usage limit', 1197, False], [2, 'TextControl', 'Resets', 1197, False],
              [2, 'TextControl', 'Sat, Oct 17, 3:00 PM', 1197, False], [2, 'ButtonControl', 'Get more usage', 1194, False],
              [2, 'ButtonControl', 'Dismiss', 1191, False],
              [1, 'StatusBarControl', '', 1178, False], [1, 'StatusBarControl', '', 1247, False], [2, 'TextControl', 'Chat mode', 1249, True],
              [1, 'StatusBarControl', '', 1247, False], [1, 'GroupControl', '', 1248, False], [2, 'GroupControl', '', 1260, False],
              [3, 'GroupControl', '', 1260, False], [4, 'GroupControl', '', 1260, False], [5, 'GroupControl', '', 1260, False],
              [6, 'EditControl', 'Prompt', 1266, False], [7, 'GroupControl', '', 1266, False], [8, 'TextControl', '', 0, True],
              [6, 'StatusBarControl', '', 1260, False], [3, 'GroupControl', '', 1260, False], [4, 'ButtonControl', 'Add', 1260, False],
              [4, 'GroupControl', '', 1260, False], [3, 'GroupControl', '', 1260, False], [4, 'ButtonControl', 'Press and hold to record', 1260, False],
              [1, 'GroupControl', '', 1308, False], [2, 'ButtonControl', 'Auto', 1329, False], [2, 'ButtonControl', 'Model: Opus 5.5 High', 1329, False],
              [3, 'TextControl', 'Opus 5.5', 1335, False], [3, 'TextControl', 'High', 1335, False],
              [2, 'ButtonControl', 'Usage: Weekly · all models: 86%, Resets Sat 3:00 PM', 1329, False],
              [2, 'StatusBarControl', '', 1346, False], [3, 'TextControl', 'Fast mode off', 1345, False], [2, 'StatusBarControl', '', 1346, False]]

    def test_the_usage_limit_notice_is_no_question(self):
        self.assertEqual(self.dock(self.NOTICE), ([], None))

    def test_nothing_in_a_notice_bar_is_a_question_whatever_its_name(self):
        renamed = [[d, k, 'Upgrade your plan' if n == 'Get more usage' else n, t, o] for d, k, n, t, o in self.NOTICE]
        self.assertEqual(self.dock(renamed), ([], None))
        # the same button outside a notice bar is still one: the rule is where it sits, not what it is called
        bar = self.NOTICE[3:9]
        loose = [r for r in self.NOTICE if r not in bar] + [[1, 'ButtonControl', 'Upgrade your plan', 1194, False]]
        self.assertEqual(self.dock(loose)[0], [{'type': 'ButtonControl', 'name': 'Upgrade your plan'}])

    def test_attachment_previews_are_not_question_choices(self):
        rows=[[1,'EditControl','Prompt',100,False],
              [1,'ButtonControl','image.png',50,False],
              [1,'ButtonControl','Remove image.png',50,True]]
        self.assertEqual(self.dock(rows), ([],None))


if __name__ == "__main__":
    unittest.main()
