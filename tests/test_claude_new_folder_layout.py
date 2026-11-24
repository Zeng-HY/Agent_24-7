"""Tests for Claude desktop 6.x new-session page layout ('Environment: This computer' + 'Folder: <full path>')."""
from __future__ import annotations

import os
import sys
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import chats  # noqa: E402


class NewFolderLayoutTests(unittest.TestCase):
    def _make_button(self, name: str, help_text: str = "", document=None):
        expand_fail = Mock(side_effect=AssertionError("must not open folder menu when full path is on the button"))
        btn = SimpleNamespace(
            Name=name,
            HelpText=help_text,
            IsOffscreen=False,
            IsEnabled=True,
            GetParentControl=lambda: document,
            GetExpandCollapsePattern=lambda: SimpleNamespace(Expand=expand_fail),
        )
        return btn

    def _desktop(self, button_specs, *, doc=None):
        """Build a fake chats.Desktop without touching real Claude windows or os.startfile."""
        d = object.__new__(chats.Desktop)
        d.input_lock = threading.RLock()
        d.log = Mock()
        d._claude_root = Mock(return_value=(1, "root"))
        d._claude_show = Mock()
        d._front = Mock(return_value=1)
        d._need_auto = Mock(return_value=SimpleNamespace(ControlFromHandle=lambda hwnd: "root"))
        document = doc or SimpleNamespace(
            Name="new - Claude Code",
            ClassName="",
            ControlTypeName="DocumentControl",
            GetParentControl=lambda: None,
        )

        def make_buttons(specs):
            out = []
            for spec in specs:
                if isinstance(spec, tuple):
                    out.append(self._make_button(spec[0], spec[1], document))
                else:
                    out.append(self._make_button(spec, "", document))
            return out

        if callable(button_specs):
            d._claude_new_buttons = Mock(side_effect=lambda root: (document, make_buttons(button_specs())))
        else:
            buttons = make_buttons(button_specs)
            d._claude_new_buttons = Mock(return_value=(document, buttons))

        d._claude_verified_prompt = Mock(return_value=(document, "edit"))
        d._fill_claude_prompt = Mock(return_value=(document, "edit"))
        d._claude_image_count = Mock(return_value=0)
        d._value = lambda edit: "hello"
        invoke = Mock(return_value=True)
        send = self._make_button("Send", "", document)
        send.GetInvokePattern = lambda: SimpleNamespace(Invoke=invoke)
        d._find = lambda scope, kind, name=None: [send] if name == "Send" else []
        return d, invoke

    def test_new_layout_matching_full_path_fills_and_sends_without_menu(self):
        folder = str(Path("project").resolve())
        shown_folder = folder.swapcase() if os.name == "nt" else folder
        d, invoke = self._desktop([
            "Environment: This computer",
            (f"Folder: {shown_folder}", shown_folder),
            "Model: Opus 5.5 Max",
            "Permissions: Auto",
        ])
        dispatched = Mock()
        with patch("chats.require_send_desktop"), \
             patch("chats.os.startfile", side_effect=AssertionError("must not launch deep link when already ready")):
            d._new_claude_now(folder, "hello", [], dispatched, folder_unique=False)
        d._fill_claude_prompt.assert_called_once()
        dispatched.assert_called_once()
        invoke.assert_called_once()

    def test_new_layout_same_name_wrong_path_never_fills_or_sends(self):
        folder = str(Path("project").resolve())
        wrong = str(Path("other/project").resolve())

        # Case 1: Desktop keeps showing another folder with the same basename -> never fills or sends.
        d, invoke = self._desktop([
            "Environment: This computer",
            (f"Folder: {wrong}", wrong),
        ])
        clock = iter([0.0, 1.0, 20.0])
        with patch("chats.require_send_desktop"), \
             patch("chats.claude_sessions", return_value=[]), \
             patch("chats.os.startfile") as startfile, \
             patch("chats.time.sleep"), \
             patch("chats.time.monotonic", side_effect=lambda: next(clock, 30.0)):
            with self.assertRaises(chats.InputNotSubmitted):
                d._new_claude_now(folder, "hello", [], Mock(), folder_unique=True)
        startfile.assert_called_once()
        d._fill_claude_prompt.assert_not_called()
        invoke.assert_not_called()

        # Case 2: Matches during ready(), then switches to same-name wrong path before exact_folder() -> rejected.
        calls = {"n": 0}

        def changing_buttons():
            calls["n"] += 1
            if calls["n"] <= 2:
                return ["Environment: This computer", (f"Folder: {folder}", folder)]
            return ["Environment: This computer", (f"Folder: {wrong}", wrong)]

        d2, invoke2 = self._desktop(changing_buttons)
        with patch("chats.require_send_desktop"):
            with self.assertRaises(chats.InputNotSubmitted) as ctx:
                d2._new_claude_now(folder, "hello", [], Mock(), folder_unique=False)
        self.assertIn("目录与手机不一致", str(ctx.exception))
        d2._fill_claude_prompt.assert_not_called()
        invoke2.assert_not_called()

    def test_new_layout_non_local_environment_never_sends(self):
        folder = str(Path("project").resolve())
        for env_label in ("Environment: Cloud", "Environment: project"):
            d, invoke = self._desktop([
                env_label,
                (f"Folder: {folder}", folder),
            ])
            clock = iter([0.0, 1.0, 20.0])
            with patch("chats.require_send_desktop"), \
                 patch("chats.claude_sessions", return_value=[]), \
                 patch("chats.os.startfile"), \
                 patch("chats.time.sleep"), \
                 patch("chats.time.monotonic", side_effect=lambda: next(clock, 30.0)):
                with self.assertRaises(chats.InputNotSubmitted):
                    d._new_claude_now(folder, "hello", [], Mock(), folder_unique=True)
            d._fill_claude_prompt.assert_not_called()
            invoke.assert_not_called()

    def test_new_layout_help_text_full_path_is_accepted_and_bare_name_without_help_text_is_not(self):
        folder = str(Path("project").resolve())
        wrong = str(Path("other/project").resolve())

        # Folder button name has only basename, HelpText carries the full path -> accepted.
        d, invoke = self._desktop([
            "Environment: This computer",
            ("Folder: project", folder),
        ])
        dispatched = Mock()
        with patch("chats.require_send_desktop"), \
             patch("chats.os.startfile", side_effect=AssertionError("must not launch deep link")):
            d._new_claude_now(folder, "hello", [], dispatched, folder_unique=False)
        d._fill_claude_prompt.assert_called_once()
        dispatched.assert_called_once()
        invoke.assert_called_once()

        # Bare name with empty or mismatched HelpText is NOT ready.
        bare_btn = SimpleNamespace(Name="Folder: project", HelpText="")
        wrong_help_btn = SimpleNamespace(Name="Folder: project", HelpText=wrong)
        env_btn = SimpleNamespace(Name="Environment: This computer", HelpText="")
        self.assertFalse(chats.Desktop._claude_folder_ready([], "project", folder, buttons=[env_btn, bare_btn]))
        self.assertFalse(chats.Desktop._claude_folder_ready([], "project", folder, buttons=[env_btn, wrong_help_btn]))

    def test_pick_no_folder_failure_logs_only_bar_buttons(self):
        folder = str(Path("project").resolve())
        closed_menu = SimpleNamespace(Exists=lambda *a: False, IsOffscreen=True)
        doc = SimpleNamespace(
            Name="new - Claude Code",
            ClassName="",
            ControlTypeName="DocumentControl",
            GetParentControl=lambda: None,
            MenuControl=lambda **kw: closed_menu,
        )
        env_btn = SimpleNamespace(
            Name="Environment: This computer",
            HelpText="",
            IsOffscreen=False,
            IsEnabled=True,
            GetParentControl=lambda: doc,
            GetExpandCollapsePattern=lambda: SimpleNamespace(Expand=lambda: True),
        )
        other_names = [
            "Menu",
            "Private sidebar item",
            "Usage: 44% of 5-hour limit",
            "Add",
            f"Folder: {folder}",
            "Model: Opus 5.5 Max",
            "Permissions: Auto",
        ]
        d = object.__new__(chats.Desktop)
        d.input_lock = threading.RLock()
        d.log = Mock()
        d._claude_root = Mock(return_value=(1, "root"))
        d._claude_show = Mock()
        d._front = Mock(return_value=1)
        d._need_auto = Mock(return_value=SimpleNamespace(ControlFromHandle=lambda hwnd: "root"))
        buttons = [env_btn] + [self._make_button(n, "", doc) for n in other_names]
        d._claude_new_buttons = Mock(return_value=(doc, buttons))
        d._find = lambda scope, kind, name=None: []

        with patch("chats.require_send_desktop"), patch("chats.time.sleep"):
            with self.assertRaises(chats.InputNotSubmitted):
                d._new_claude_now("", "hello", [], Mock())

        d.log.assert_called_once()
        logged = d.log.call_args.args[0]
        self.assertIn("Environment: This computer", logged)
        self.assertIn(f"Folder: {folder}", logged)
        self.assertIn("Model: Opus 5.5 Max", logged)
        self.assertIn("Permissions: Auto", logged)
        for excluded in ("Menu", "Private sidebar item", "Usage:", "Add"):
            self.assertNotIn(excluded, logged)

    def test_ambiguous_or_cloud_no_folder_buttons_are_not_ready(self):
        folder = str(Path("project").resolve())
        self.assertFalse(chats.Desktop._claude_folder_ready(
            ["Environment: This computer", f"Folder: {folder}", f"Folder: {folder}"],
            "project",
            folder,
        ))
        self.assertFalse(chats.Desktop._claude_folder_ready(
            ["Environment: This computer", "Environment: Cloud", f"Folder: {folder}"],
            "project",
            folder,
        ))
        self.assertFalse(chats.Desktop._claude_folder_ready(
            ["Environment: Cloud", "Folder: Choose folder…"],
            chats.CLAUDE_NO_FOLDER,
        ))


if __name__ == "__main__":
    unittest.main()
