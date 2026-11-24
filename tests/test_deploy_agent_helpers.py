"""The packaged helper programs are listed from the assistant registry (batch 3).

Nothing here runs csc.exe or version.py: only the two small functions are called.
"""
from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
WINDOWS = ROOT / "deploy" / "windows"
if str(WINDOWS) not in sys.path:
    sys.path.insert(0, str(WINDOWS))

import agent_helpers
import codex_hooks


class HelperListTests(unittest.TestCase):
    def test_the_list_is_exactly_the_codex_hook_program(self):
        self.assertEqual(agent_helpers.helpers(),
                         (("deploy/windows/TeleplyCodexHook.cs", "TeleplyCodexHook.exe"),))
        self.assertEqual(agent_helpers.helpers()[0][1], codex_hooks.HOOK_EXE_NAME)
        self.assertTrue((ROOT / agent_helpers.helpers()[0][0]).is_file())

    def test_agent_helpers_iss_matches_the_old_setup_line_byte_for_byte(self):
        expected = ('Source: "..\\..\\build\\TeleplyCodexHook.exe"; DestDir: "{app}"; '
                    'Flags: ignoreversion uninsneveruninstall\n')
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "agent-helpers.iss"
            agent_helpers.write_iss(out)
            self.assertEqual(out.read_text(encoding="utf-8"), expected)


class SetupFileTests(unittest.TestCase):
    def setUp(self):
        self.text = (WINDOWS / "setup.iss").read_text(encoding="utf-8")

    def test_files_section_includes_the_generated_list_instead_of_naming_the_program(self):
        self.assertIn('#include "..\\..\\build\\agent-helpers.iss"', self.text)
        self.assertNotIn('Source: "..\\..\\build\\TeleplyCodexHook.exe"', self.text)

    def test_uninstall_runs_the_one_agent_wide_switch(self):
        section = self.text.split("[UninstallRun]", 1)[1].split("[UninstallDelete]", 1)[0]
        self.assertIn("--remove-agent-hooks", section)
        self.assertNotIn("--remove-claude-hook", section)
        self.assertNotIn("--remove-codex-hook", section)
        self.assertEqual(section.count("Filename:"), 1)


if __name__ == "__main__":
    unittest.main()
