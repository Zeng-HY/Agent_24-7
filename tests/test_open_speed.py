"""Opening a conversation faster: gzip on the wire and the DeepSeek port found only when needed (11-16)."""
import gzip
import io
import json
import sys
import unittest
from email.message import Message
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import deepseek_control
import remote


class FakeResponse:
    def __init__(self, body):
        self.status = 200
        self._body = body

    def read(self):
        return self._body


class FakeHTTP:
    """Stands in for http.client.HTTPConnection: echoes the rpcId back as DeepSeek does."""
    def __init__(self, *args, **kwargs):
        self.body = b""

    def request(self, method, path, body, headers):
        self.body = body.encode() if isinstance(body, str) else body

    def getresponse(self):
        rid = json.loads(self.body)["rpcId"]
        return FakeResponse(json.dumps({"rpcId": rid, "result": {"ok": True, "value": {"session": []}}}).encode())

    def close(self):
        pass


class HeaderTests(unittest.TestCase):
    def handler(self, accept="gzip", range_header=None):
        handler = object.__new__(remote.Handler)
        handler.headers = Message()
        if accept is not None:
            handler.headers["Accept-Encoding"] = accept
        if range_header is not None:
            handler.headers["Range"] = range_header
        handler.sent = []
        handler.body = io.BytesIO()
        handler.send_response = Mock()
        handler.send_header = Mock(side_effect=lambda k, v: handler.sent.append((k, v)))
        handler.end_headers = Mock()
        handler.wfile = handler.body
        return handler

    @staticmethod
    def headers(handler):
        return {k.lower(): v for k, v in handler.sent}

    def test_json_over_a_kilobyte_is_gzipped_and_unpacks_to_the_same_page(self):
        page = {"messages": [{"text": "字" * 2000}]}
        body = json.dumps(page, ensure_ascii=False).encode()
        handler = self.handler()
        handler._send(200, body, "application/json; charset=utf-8")
        sent = self.headers(handler)
        self.assertEqual(sent.get("content-encoding"), "gzip")
        self.assertEqual(sent.get("vary"), "Accept-Encoding")
        self.assertEqual(gzip.decompress(handler.body.getvalue()), body)
        self.assertEqual(int(sent["content-length"]), len(handler.body.getvalue()))

    def test_small_json_html_ranges_and_plain_clients_get_the_plain_body(self):
        big = b'{"a":"' + b"x" * 2000 + b'"}'
        cases = [
            (b'{"a":1}', "application/json; charset=utf-8", "gzip", None),   # too small to be worth it
            (b"<html>" + b"x" * 2000, "text/html; charset=utf-8", "gzip", None),  # the relay rewrites this page
            (big, "application/json", "gzip", "bytes=0-1"),
            (big, "application/json", None, None),
            (big, "application/json", "deflate", None),
        ]
        for body, ctype, accept, range_header in cases:
            handler = self.handler(accept=accept, range_header=range_header)
            handler._send(200, body, ctype)
            self.assertNotIn("content-encoding", self.headers(handler), (ctype, accept, range_header))
            self.assertEqual(handler.body.getvalue(), body)

    def test_a_body_already_encoded_is_not_compressed_again(self):
        body = b'{"a":"' + b"x" * 2000 + b'"}'
        handler = self.handler()
        handler._send(200, body, "application/json", {"Content-Encoding": "br"})
        sent = self.headers(handler)
        self.assertEqual(sent.get("content-encoding"), "br")
        self.assertEqual(handler.body.getvalue(), body)


class DownHTTP:
    def __init__(self, *args, **kwargs):
        pass

    def request(self, *args, **kwargs):
        raise OSError("down")

    def close(self):
        pass


class DeepSeekConnectionTests(unittest.TestCase):
    def test_a_working_connection_is_found_once_not_every_thirty_seconds(self):
        client = deepseek_control.Client()
        clock = iter([0, 40, 80, 120, 160, 200, 240])
        with patch("deepseek_control.discover", return_value=1234) as discover, \
             patch("deepseek_control.credential_cookie", return_value="cookie") as cookie, \
             patch("deepseek_control.time.monotonic", side_effect=lambda: next(clock)):
            self.assertEqual(client.connection_info(), (1234, "cookie"))
            for _ in range(3):
                self.assertEqual(client.connection_info(), (1234, "cookie"))
        self.assertEqual((discover.call_count, cookie.call_count), (1, 1))

    def test_a_successful_call_never_starts_a_search_for_the_port(self):
        client = deepseek_control.Client()
        client.connection = (1234, "cookie")
        with patch("http.client.HTTPConnection", FakeHTTP), \
             patch("deepseek_control.discover", side_effect=AssertionError("started PowerShell")):
            self.assertEqual(client.call("catalog", {}), {"session": []})
        self.assertEqual(client.connection, (1234, "cookie"))

    def test_a_failed_call_drops_the_connection_and_the_next_one_finds_it_again(self):
        client = deepseek_control.Client()
        client.connection = (1, "old")
        with patch("http.client.HTTPConnection", DownHTTP):
            with self.assertRaises(deepseek_control.DeepSeekError):
                client.call("catalog", {})
        self.assertIsNone(client.connection)
        with patch("deepseek_control.discover", return_value=2222), \
             patch("deepseek_control.credential_cookie", return_value="new"):
            self.assertEqual(client.connection_info(), (2222, "new"))


if __name__ == "__main__":
    unittest.main()
