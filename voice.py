"""Voice input for the phone page: the phone records, this PC turns the recording into text.

Same key and models as VoiceAnywhere, a voice input tool, when it is on this PC: its src folder goes in
remote_config.json as "voice": {"voiceanywhere_src": ...} or in the VOICEANYWHERE_SRC variable. Without it, the
key is the OPENROUTER_API_KEY variable. The words to listen for come from the voice dictionary (voice_terms.txt,
see voice_terms.py) plus VoiceAnywhere's own terms. Its settings live in %LOCALAPPDATA%\\VoiceAnywhere; the
OpenRouter key there is stored with Windows DPAPI for this user, and VoiceAnywhere's own SettingsStore reads
both. Two steps, as in VoiceAnywhere:
1. /audio/transcriptions turns the recording into a raw transcript (the term list goes along as a hint);
2. when the phone's 整理 switch is on, /chat/completions rewrites the transcript into the message the
   user meant to type, following voice_tidy_prompt.txt (edit that file to tune the wording).
Audio and text stay in memory; the log keeps sizes and durations, never words.
"""

from __future__ import annotations

import http.client
import json
import os
import secrets
import ssl
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

import voice_terms

HERE = Path(__file__).resolve().parent
PROMPT_FILE = HERE / "voice_tidy_prompt.txt"
DEFAULT_VOICEANYWHERE_SRC = os.environ.get("VOICEANYWHERE_SRC", "")  # VoiceAnywhere's src folder, when it is here
OPENROUTER = "https://openrouter.ai/api/v1"
MAX_AUDIO_BYTES = 25 << 20
TIDY_SCHEMA = {
    "name": "voice_tidy",
    "strict": True,
    "schema": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"],
               "additionalProperties": False},
}
EXTENSIONS = {"audio/wav": "wav", "audio/x-wav": "wav", "audio/wave": "wav", "audio/mp4": "m4a", "audio/m4a": "m4a",
              "audio/x-m4a": "m4a", "audio/aac": "m4a", "audio/webm": "webm", "audio/ogg": "ogg", "audio/mpeg": "mp3"}


class VoiceError(Exception):
    """Something the phone can show as it is."""

    def __init__(self, text: str, status: int = 400):
        super().__init__(text)
        self.status = status


def _short(text: str, n: int = 160) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= n else text[: n - 1] + "…"


def _multipart(fields: dict[str, str], filename: str, data: bytes, mime: str) -> tuple[bytes, str]:
    boundary = "----lbrvoice" + secrets.token_hex(12)
    parts = [f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode("utf-8")
             for k, v in fields.items()]
    parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\n'
                 f"Content-Type: {mime}\r\n\r\n".encode("utf-8") + data + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode("utf-8"))
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


class _Connections:
    """Kept-open HTTPS connections. Through the home proxy each new one costs 0.5-0.7 s of handshake,
    so a voice input reuses one that is already open, and the phone opens one as recording starts."""

    IDLE = 45  # seconds; servers and the proxy drop quiet connections, so older ones are replaced

    def __init__(self):
        self.lock = threading.Lock()
        self.idle: dict[str, list] = {}  # host -> [(connection, last used)]

    def _take(self, host: str):
        with self.lock:
            pool = self.idle.get(host) or []
            while pool:
                conn, used = pool.pop()
                if time.time() - used < self.IDLE:
                    return conn
                conn.close()
        return None

    def _give(self, host: str, conn) -> None:
        with self.lock:
            self.idle.setdefault(host, []).append((conn, time.time()))

    @staticmethod
    def _new(host: str, timeout: float):
        return http.client.HTTPSConnection(host, timeout=timeout, context=ssl.create_default_context())

    def warm(self, url: str) -> None:
        """Open a connection ahead of the request, unless a fresh one is waiting already."""
        host = urlsplit(url).netloc
        conn = self._take(host)
        if conn is None:
            conn = self._new(host, 20)
            try:
                conn.connect()
            except OSError:
                return
        self._give(host, conn)

    def post(self, url: str, headers: dict, body: bytes, timeout: float) -> tuple[int, bytes]:
        parts = urlsplit(url)
        host, path = parts.netloc, parts.path + (f"?{parts.query}" if parts.query else "")
        conn = self._take(host)
        for attempt in (1, 2):
            reused = conn is not None
            conn = conn or self._new(host, timeout)
            try:
                conn.timeout = timeout
                if conn.sock is not None:
                    conn.sock.settimeout(timeout)
                conn.request("POST", path, body=body, headers=headers)
                response = conn.getresponse()
                data = response.read()
            except (http.client.HTTPException, OSError):
                conn.close()
                conn = None
                if reused and attempt == 1:
                    continue  # the kept connection had gone stale: once more on a new one
                raise
            if response.will_close:
                conn.close()
            else:
                self._give(host, conn)
            return response.status, data
        raise OSError("连接失败")


_CONNECTIONS = _Connections()


def _post(url: str, key: str, data: bytes, ctype: str, timeout: float, what: str) -> dict:
    if not key:
        raise VoiceError("没找到 OpenRouter 密钥：在 VoiceAnywhere 的设置里保存一次，或者设环境变量 OPENROUTER_API_KEY", 500)
    headers = {"Authorization": f"Bearer {key}", "Content-Type": ctype,
               "HTTP-Referer": "https://voiceanywhere.local", "X-Title": "Phone remote voice input"}
    try:
        if urllib.request.getproxies().get("https"):  # an explicit proxy: let urllib handle it
            request = urllib.request.Request(url, data=data, method="POST", headers=headers)
            try:
                with urllib.request.urlopen(request, timeout=timeout) as response:
                    status, raw = response.status, response.read()
            except urllib.error.HTTPError as exc:
                status, raw = exc.code, exc.read()
        else:
            status, raw = _CONNECTIONS.post(url, headers, data, timeout)
    except (urllib.error.URLError, http.client.HTTPException, OSError) as exc:
        raise VoiceError(f"连不上{what}服务：{_short(getattr(exc, 'reason', exc))}", 502) from None
    if status >= 400:
        raise VoiceError(f"{what}服务返回 HTTP {status}：{_short(raw[:600].decode('utf-8', 'replace'))}", status)
    try:
        payload = json.loads(raw.decode("utf-8"))
    except ValueError:
        raise VoiceError(f"{what}服务返回的不是 JSON", 502) from None
    if isinstance(payload, dict) and payload.get("error"):  # OpenRouter can report a failure inside an HTTP 200
        error = payload["error"]
        raise VoiceError(f"{what}服务出错：{_short(error.get('message') if isinstance(error, dict) else error)}", 502)
    return payload if isinstance(payload, dict) else {}


class Voice:
    def __init__(self, cfg: dict, log):
        self.opts = cfg.get("voice") if isinstance(cfg.get("voice"), dict) else {}
        self.log = log
        self.src = str(self.opts.get("voiceanywhere_src") or DEFAULT_VOICEANYWHERE_SRC)

    # -- settings

    def settings(self) -> dict:
        """VoiceAnywhere's services, terms and keys; the OPENROUTER_API_KEY variable when it is not there."""
        conf = {"asr_base": OPENROUTER, "asr_model": "openai/gpt-transcribe", "text_base": OPENROUTER,
                "text_model": "openai/gpt-5.6-luna", "text_provider": "openrouter", "terms": [],
                "asr_key": "", "text_key": "", "source": "环境变量"}
        try:
            if not self.src:
                raise LookupError("VoiceAnywhere is not set up here")
            if self.src not in sys.path:
                sys.path.insert(0, self.src)
            from voiceanywhere.config import SettingsStore  # type: ignore
            store = SettingsStore()
            saved = store.load()
            p = saved.providers
            conf.update(asr_base=p.asr_base_url.rstrip("/"), asr_model=p.asr_model, text_base=p.text_base_url.rstrip("/"),
                        text_model=p.text_model, text_provider=p.text_provider,
                        terms=[t.canonical for t in saved.terms if t.canonical],
                        asr_key=store.asr_api_key(p) or "", text_key=store.text_api_key(p.text_provider) or "",
                        source="VoiceAnywhere")
        except Exception:
            pass
        fallback = os.environ.get("OPENROUTER_API_KEY", "")
        conf["asr_key"] = conf["asr_key"] or fallback
        conf["text_key"] = conf["text_key"] or (fallback if conf["text_provider"] == "openrouter" else "")
        for key in ("asr_model", "text_model"):
            if self.opts.get(key):
                conf[key] = str(self.opts[key])
        return conf

    def status(self) -> dict:
        conf = self.settings()
        return {"ready": bool(conf["asr_key"]), "source": conf["source"], "asr_model": conf["asr_model"],
                "text_model": conf["text_model"], "terms": len(conf["terms"])}

    @staticmethod
    def _terms(conf: dict) -> list[str]:
        """The voice dictionary (voice_terms.txt) first, then VoiceAnywhere's own terms."""
        return voice_terms.words(conf["terms"])[:60]

    # -- the two steps

    def transcribe(self, audio: bytes, mime: str, conf: dict, context: dict) -> str:
        ext = EXTENSIONS.get(mime.split(";")[0].strip().lower(), "wav")
        fields = {"model": conf["asr_model"]}
        hint = "可能出现的词：" + "、".join(self._terms(conf))
        if context.get("title"):
            hint += "。对话标题：" + context["title"]
        fields["prompt"] = hint[:400]
        url = conf["asr_base"] + "/audio/transcriptions"
        body, ctype = _multipart(fields, f"voice.{ext}", audio, mime.split(";")[0] or "audio/wav")
        try:
            payload = _post(url, conf["asr_key"], body, ctype, 90, "转写")
        except VoiceError as exc:
            if exc.status != 400:
                raise
            fields.pop("prompt")  # a service that refuses the hint field: once more without it
            body, ctype = _multipart(fields, f"voice.{ext}", audio, mime.split(";")[0] or "audio/wav")
            payload = _post(url, conf["asr_key"], body, ctype, 90, "转写")
        text = payload.get("text")
        return voice_terms.normalize(text.strip()) if isinstance(text, str) else ""

    def tidy(self, transcript: str, conf: dict, context: dict) -> str:
        prompt = PROMPT_FILE.read_text(encoding="utf-8").strip()  # read each time, so edits apply at once
        user = {"transcript": transcript,
                "context": {"app": context.get("app", ""), "conversation_title": context.get("title", ""),
                            "folder": context.get("folder", ""), "text_already_in_box": context.get("existing", "")},
                "terms": self._terms(conf)}
        body: dict = {"model": conf["text_model"], "max_tokens": 4096,
                      "messages": [{"role": "system", "content": prompt},
                                   {"role": "user", "content": json.dumps(user, ensure_ascii=False)}]}
        provider = conf["text_provider"]
        if provider in ("openrouter", "openai"):
            body["reasoning"] = {"effort": str(self.opts.get("reasoning") or "low")}
            body["response_format"] = {"type": "json_schema", "json_schema": TIDY_SCHEMA}
        if provider == "openrouter":
            body["provider"] = {"order": ["OpenAI"], "allow_fallbacks": False, "require_parameters": True}
        payload = _post(conf["text_base"] + "/chat/completions", conf["text_key"],
                         json.dumps(body, ensure_ascii=False).encode("utf-8"), "application/json", 60, "整理")
        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices:
            raise VoiceError("整理服务没有返回结果", 502)
        choice = choices[0] if isinstance(choices[0], dict) else {}
        if choice.get("finish_reason") in ("length", "content_filter"):
            raise VoiceError("整理结果被截断了", 502)
        content = (choice.get("message") or {}).get("content")
        try:
            text = json.loads(content).get("text") if isinstance(content, str) else None
        except ValueError:
            text = content  # a model that answered with plain text
        if not isinstance(text, str):
            raise VoiceError("整理服务没有返回正文", 502)
        return voice_terms.normalize(text.strip())

    def warm(self) -> None:
        """Open the connection to the tidy service while the user is still talking."""
        try:
            conf = self.settings()
            if conf["text_key"]:
                _CONNECTIONS.warm(conf["text_base"] + "/chat/completions")
        except Exception:
            pass

    def tidy_text(self, text: str, context: dict) -> dict:
        """The 整理 step on its own, for text already recognised on this PC."""
        text = (text or "").strip()
        if not text:
            return {"text": "", "seconds": 0}
        if len(text) > 8000:
            raise VoiceError("文字太长了，没有整理")
        started = time.time()
        result = self.tidy(text, self.settings(), context)
        spent = time.time() - started
        self.log(f"语音整理：{len(text)} 字，{spent:.1f} 秒")
        return {"text": result, "seconds": round(spent, 2)}

    def process(self, audio: bytes, mime: str, tidy: bool, context: dict) -> dict:
        if not audio:
            raise VoiceError("没有收到录音")
        if len(audio) > MAX_AUDIO_BYTES:
            raise VoiceError("录音太长了", 413)
        conf = self.settings()
        started = time.time()
        raw = self.transcribe(audio, mime, conf, context)
        heard = time.time()
        text, note, tidied = raw, "", False
        if tidy and raw:
            try:
                text, tidied = self.tidy(raw, conf, context), True
            except VoiceError as exc:
                note = "整理没成功，先给你原话：" + str(exc)
        done = time.time()
        self.log(f"语音输入：录音 {len(audio) // 1024} KB，转写 {heard - started:.1f} 秒"
                 + (f"，整理 {done - heard:.1f} 秒" if tidied else "") + (f"（{note[:60]}）" if note else ""))
        return {"text": text, "raw": raw, "tidied": tidied, "note": note,
                "seconds": {"transcribe": round(heard - started, 2), "tidy": round(done - heard, 2) if tidied else 0}}
