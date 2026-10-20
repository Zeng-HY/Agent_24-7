import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import remote  # noqa: E402


class PageVersionTest(unittest.TestCase):
    """The page's scripts carry the service's version; the page itself carries none (0.20.2)."""

    def test_every_script_carries_the_service_version(self):
        stamped = remote.stamp_page(remote.PAGE_FILE.read_bytes()).decode("utf-8")
        scripts = [line for line in stamped.splitlines() if "<script src=" in line]
        self.assertGreaterEqual(len(scripts), 12)
        for line in scripts:
            self.assertIn("?v=" + remote.VERSION, line, line)

    def test_the_page_has_no_version_of_its_own(self):
        page = remote.PAGE_FILE.read_text(encoding="utf-8")
        self.assertNotIn("?v=", page)

    def test_only_local_scripts_are_stamped(self):
        page = (b'<script src="https://cdn.example.com/x.js"></script>'
                b'<link rel="icon" href="/icon-192.png?v=1">'
                b'<script>var inline = 1;</script>'
                b'<script src="/voice-ui.js?v=0.1"></script>')
        out = remote.stamp_page(page)
        self.assertIn(b'<script src="https://cdn.example.com/x.js"></script>', out)
        self.assertIn(b'<link rel="icon" href="/icon-192.png?v=1">', out)
        self.assertIn(b'<script>var inline = 1;</script>', out)
        self.assertIn(('<script src="/voice-ui.js?v=%s"></script>' % remote.VERSION).encode(), out)

    def test_stamping_twice_changes_nothing(self):
        once = remote.stamp_page(b'<script src="/a.js"></script>')
        self.assertEqual(remote.stamp_page(once), once)


if __name__ == "__main__":
    unittest.main()
