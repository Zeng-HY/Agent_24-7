"""Local speech recognition for the microphone button: text appears while the user is still talking.

The phone sends 16 kHz audio in small pieces while it records (POST /api/voice/stream/chunk). Each piece
goes through a voice-activity detector (Silero VAD), which cuts the talk into stretches at the pauses.
Two recognisers work on it, both on this PC's CPU (sherpa-onnx), nothing goes over the internet:
  - SenseVoice is fast (a tenth of a second per stretch). It shows the stretch still being spoken, again
    every few hundred milliseconds, so the phone can show the words growing.
  - Qwen3-ASR is slower (about a fifth of the stretch's length) but much better with English words, and it
    takes the voice dictionary (voice_terms.txt) as hotwords. Every finished stretch is recognised again
    by it in the background, and its text replaces SenseVoice's on screen. When the start of a stretch is
    unclear it sometimes writes out the dictionary instead of what was said (voice_terms.copied_run); such a
    stretch is recognised once more by a second copy of the model that has no dictionary.
When the user lets go only the last stretch is left for Qwen3-ASR, so the final text comes within about a
second. Without the Qwen3-ASR model everything still works with SenseVoice alone.

Models live in %LOCALAPPDATA%\\AgentRemote\\models (from the sherpa-onnx releases on GitHub):
  sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2024-07-17\\   (fast, adds punctuation)
  sherpa-onnx-qwen3-asr-0.6B-int8-2026-03-25\\                (accurate, takes hotwords)
  silero_vad.onnx                                            (speech / silence detector)
remote_config.json "voice": {"local_model": "<folder>", "accurate_model": "<folder or empty to turn off>",
  "models_dir": "...", "local_threads": 4, "keep_recordings": 20}
keep_recordings: the last few recordings and their texts stay in %LOCALAPPDATA%\\AgentRemote\\
voice_samples, to check the recognisers against real speech later; 0 keeps none.
"""

from __future__ import annotations

import json
import os
import queue
import re
import secrets
import threading
import time
import wave
from pathlib import Path

import voice_terms

RATE = 16000
DEFAULT_MODEL = "sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2024-07-17"
ACCURATE_MODEL = "sherpa-onnx-qwen3-asr-0.6B-int8-2026-03-25"
MAX_SECONDS = 300           # one recording
KEEP_AFTER_END = 180        # seconds the audio stays for a cloud re-run after the user let go
IDLE_LIMIT = 120            # an abandoned recording is dropped after this many quiet seconds
PARTIAL_EVERY = 0.4         # seconds of new audio before the open stretch is recognised again
EDGE = int(0.2 * RATE)      # audio kept around each stretch for the accurate pass
FINAL_WAIT = 12             # seconds end() waits for the accurate pass before using the fast text


class LocalError(Exception):
    pass


def _join(parts) -> str:
    out = ""
    for part in parts:
        part = (part or "").strip()
        if not part:
            continue
        if out and re.search(r"[A-Za-z0-9.,!?;:'\")\]]$", out) and re.match(r"[A-Za-z0-9]", part):
            out += " "  # between English words, and after English punctuation: "failed. Then", not "failed.Then"
        out += part
    return out


def _plausible(accurate: str, fast: str) -> bool:
    """Language models sometimes loop ('too seldom too seldom ...') or answer with nothing."""
    if not accurate:
        return False
    if fast and len(accurate) > 3 * len(fast) + 20:
        return False
    return not re.search(r"(.{2,12}?)\1{4,}", accurate)


class Session:
    def __init__(self, sid: str, vad, np):
        self.sid = sid
        self.np = np
        self.vad = vad
        self.lock = threading.Lock()
        self.created = self.used = time.time()
        self.ended = 0.0
        self.cancelled = False
        self.chunks: list = []        # float32 arrays as received, for the cloud re-run
        self.samples = 0
        self.pending = np.zeros(0, dtype=np.float32)  # not yet fed to the VAD (it takes 512-sample windows)
        self.fast: list[str] = []     # each finished stretch, as SenseVoice heard it
        self.parts: list[str] = []    # the same stretches, replaced by the accurate text when it arrives
        self.exact: list[bool] = []
        self.waiting = 0              # stretches queued for the accurate pass
        self.idle = threading.Event()
        self.idle.set()
        self.partial = ""
        self.partial_at = 0           # sample count when the open stretch was last recognised
        self.partial_cost = 0.0       # how long that took; slows the next try on a busy CPU
        self.copied = 0               # stretches where the accurate model wrote out the dictionary (taken again without it)

    def audio(self):
        return self.np.concatenate(self.chunks) if self.chunks else self.np.zeros(0, dtype=self.np.float32)


class LocalASR:
    def __init__(self, cfg: dict, log):
        opts = cfg.get("voice") if isinstance(cfg.get("voice"), dict) else {}
        root = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "AgentRemote"
        self.models = Path(opts.get("models_dir") or root / "models")
        self.model_name = str(opts.get("local_model") or DEFAULT_MODEL)
        self.accurate_name = str(opts["accurate_model"]) if "accurate_model" in opts else ACCURATE_MODEL
        self.threads = int(opts.get("local_threads") or 4)
        self.keep = int(opts.get("keep_recordings", 20) or 0)
        self.samples_dir = root / "voice_samples"
        self.log = log
        self.recognizer = None
        self.accurate = None
        self.plain = None             # the same accurate model without the dictionary, for stretches where it was copied out
        self.accurate_sig = None      # the dictionary the accurate model was built with
        self.accurate_error = ""
        self.rebuilding = False
        self.vad_config = None
        self.np = None
        self.sherpa = None
        self.error = ""
        self.ready = threading.Event()
        self.decode_lock = threading.Lock()    # one fast recognition at a time
        self.accurate_lock = threading.Lock()  # one accurate recognition at a time
        self.jobs: queue.Queue = queue.Queue()
        self.sessions: dict[str, Session] = {}
        self.sessions_lock = threading.Lock()
        voice_terms.ensure_file()
        threading.Thread(target=self._load, name="voice-model", daemon=True).start()
        threading.Thread(target=self._accurate_worker, name="voice-accurate", daemon=True).start()

    # -- models

    def _load(self) -> None:
        started = time.time()
        try:
            import numpy as np
            import sherpa_onnx
            folder = self.models / self.model_name
            model = next((folder / n for n in ("model.int8.onnx", "model.onnx") if (folder / n).is_file()), None)
            if model is None or not (folder / "tokens.txt").is_file():
                raise LocalError(f"没找到识别模型：{folder}")
            vad_file = self.models / "silero_vad.onnx"
            if not vad_file.is_file():
                raise LocalError(f"没找到语音检测模型：{vad_file}")
            # "zh" rather than "auto": with auto, Chinese with English words now and then came out as Japanese
            self.recognizer = sherpa_onnx.OfflineRecognizer.from_sense_voice(
                model=str(model), tokens=str(folder / "tokens.txt"), num_threads=self.threads, use_itn=True,
                language="zh")
            config = sherpa_onnx.VadModelConfig()
            config.silero_vad.model = str(vad_file)
            config.silero_vad.min_silence_duration = 0.45
            config.silero_vad.min_speech_duration = 0.2
            # long talk is cut at its smallest pauses: the accurate pass then has at most a few seconds left
            # to do when the user lets go
            config.silero_vad.max_speech_duration = 8.0
            config.sample_rate = RATE
            config.num_threads = 1
            self.vad_config, self.np, self.sherpa = config, np, sherpa_onnx
            stream = self.recognizer.create_stream()  # first run loads everything into memory
            stream.accept_waveform(RATE, np.zeros(RATE // 2, dtype=np.float32))
            self.recognizer.decode_stream(stream)
            self.log(f"本地语音识别已就绪（{self.model_name[12:]}，加载 {time.time() - started:.1f} 秒）")
        except Exception as exc:
            self.error = str(exc).splitlines()[0][:200] if str(exc) else type(exc).__name__
            self.recognizer = None
            self.log(f"本地语音识别不可用：{self.error}")
        finally:
            self.ready.set()
        if self.recognizer is not None and self.accurate_name:
            self._load_accurate()

    def _load_accurate(self) -> None:
        started = time.time()
        try:
            folder = self.models / self.accurate_name
            files = {"conv_frontend": folder / "conv_frontend.onnx", "encoder": folder / "encoder.int8.onnx",
                     "decoder": folder / "decoder.int8.onnx"}
            if not all(p.is_file() for p in files.values()) or not (folder / "tokenizer").is_dir():
                raise LocalError(f"没找到准确识别模型：{folder}")
            sig = voice_terms.signature()
            build = lambda hotwords: self.sherpa.OfflineRecognizer.from_qwen3_asr(
                **{k: str(v) for k, v in files.items()}, tokenizer=str(folder / "tokenizer"),
                num_threads=self.threads, max_new_tokens=256, hotwords=hotwords)
            recognizer = build(voice_terms.hotwords())
            # A second copy without the dictionary (about 1 GB more): a stretch where the first one wrote out the
            # dictionary instead of what was said is recognised again with it (voice_terms.copied_run, 10-12).
            plain = self.plain or build("")
            for model in (recognizer, plain):
                stream = model.create_stream()
                stream.accept_waveform(RATE, self.np.zeros(RATE // 2, dtype=self.np.float32))
                model.decode_stream(stream)
            with self.accurate_lock:
                self.accurate, self.accurate_sig, self.accurate_error, self.plain = recognizer, sig, "", plain
            self.log(f"准确识别已就绪（Qwen3-ASR，词典 {len(voice_terms.words())} 个词，加载 {time.time() - started:.1f} 秒）")
        except Exception as exc:
            self.accurate_error = str(exc).splitlines()[0][:200] if str(exc) else type(exc).__name__
            self.log(f"准确识别不可用，只用快速识别：{self.accurate_error}")
        finally:
            self.rebuilding = False

    def _refresh_dictionary(self) -> None:
        """A changed dictionary means new hotwords: rebuild the accurate model in the background."""
        if self.accurate is None or self.rebuilding or voice_terms.signature() == self.accurate_sig:
            return
        self.rebuilding = True
        threading.Thread(target=self._load_accurate, name="voice-accurate-load", daemon=True).start()

    def status(self) -> dict:
        return {"ready": self.recognizer is not None, "loading": not self.ready.is_set(), "error": self.error,
                "model": self.model_name, "accurate": self.accurate is not None, "plain": self.plain is not None,
                "accurate_error": self.accurate_error, "terms": len(voice_terms.words())}

    def _recognize(self, samples) -> tuple[str, float]:
        if len(samples) < RATE // 10:
            return "", 0.0
        with self.decode_lock:
            started = time.time()
            stream = self.recognizer.create_stream()
            stream.accept_waveform(RATE, samples)
            self.recognizer.decode_stream(stream)
            return voice_terms.normalize(stream.result.text.strip()), time.time() - started

    def _recognize_accurate(self, samples, plain: bool = False) -> str:
        with self.accurate_lock:
            model = self.plain if plain else self.accurate
            if model is None:
                return ""
            stream = model.create_stream()
            stream.accept_waveform(RATE, samples)
            model.decode_stream(stream)
            return voice_terms.normalize(stream.result.text.strip())

    def _accurate_text(self, samples, fast: str) -> tuple[str, bool]:
        """The accurate model's text for a stretch, and whether it had to be taken again without the dictionary: when
        the text holds dictionary words in the dictionary's own order that the fast model did not hear, the model wrote
        out its hotwords instead of what was said (10-12: "Claude ChatGPT Codex 提问…" for "Codex 提问…")."""
        text = self._recognize_accurate(samples)
        if text and self.plain is not None and voice_terms.copied_run(text, fast):
            return self._recognize_accurate(samples, plain=True), True
        return text, False

    def _accurate_worker(self) -> None:
        while True:
            s, index, samples = self.jobs.get()
            try:
                if not s.cancelled:
                    text, again = self._accurate_text(samples, s.fast[index])
                    with s.lock:
                        s.copied += again
                        if _plausible(text, s.fast[index]):
                            s.parts[index] = text
                            s.exact[index] = True
            except Exception as exc:
                self.log(f"准确识别出错，这一段用快速识别的结果：{str(exc)[:120]}")
            finally:
                with s.lock:
                    s.waiting -= 1
                    if s.waiting <= 0:
                        s.idle.set()

    # -- sessions

    def _sweep(self) -> None:
        now = time.time()
        with self.sessions_lock:
            for sid, s in list(self.sessions.items()):
                if (s.ended and now - s.ended > KEEP_AFTER_END) or (not s.ended and now - s.used > IDLE_LIMIT):
                    s.cancelled = True
                    del self.sessions[sid]

    def _session(self, sid: str) -> Session:
        with self.sessions_lock:
            s = self.sessions.get(sid)
        if s is None:
            raise LocalError("这段录音已经过期，重新录一次")
        return s

    def start(self) -> str:
        if not self.ready.wait(20):
            raise LocalError("本地识别还在加载，稍等再试")
        if self.recognizer is None and time.time() - getattr(self, "_retried", 0) > 30:
            self._retried = time.time()  # e.g. the models were put in place after the service started
            self.ready.clear()
            self._load()
        if self.recognizer is None:
            raise LocalError("本地识别没准备好：" + (self.error or "还在加载"))
        self._sweep()
        self._refresh_dictionary()
        sid = secrets.token_urlsafe(9)
        vad = self.sherpa.VoiceActivityDetector(self.vad_config, buffer_size_in_seconds=MAX_SECONDS + 10)
        with self.sessions_lock:
            self.sessions[sid] = Session(sid, vad, self.np)
        return sid

    def _drain(self, s: Session) -> None:
        """Recognise every stretch the VAD has finished; queue it for the accurate pass."""
        while not s.vad.empty():
            segment = s.vad.front
            samples = self.np.asarray(segment.samples, dtype=self.np.float32)
            start = int(getattr(segment, "start", -1))
            s.vad.pop()
            text, _ = self._recognize(samples)
            s.fast.append(text)
            s.parts.append(text)
            s.exact.append(False)
            s.partial, s.partial_at = "", s.samples
            if self.accurate is not None and len(samples) >= RATE // 4:
                if start >= 0:  # a little audio on both sides: words cut at the edge come back whole
                    audio = s.audio()
                    samples = audio[max(0, start - EDGE): min(len(audio), start + len(samples) + EDGE)]
                s.waiting += 1
                s.idle.clear()
                self.jobs.put((s, len(s.parts) - 1, samples))

    def feed(self, sid: str, pcm16: bytes) -> dict:
        s = self._session(sid)
        np = self.np
        with s.lock:
            if s.ended:
                raise LocalError("这段录音已经结束")
            samples = np.frombuffer(pcm16[: len(pcm16) // 2 * 2], dtype="<i2").astype(np.float32) / 32768.0
            if s.samples + len(samples) > MAX_SECONDS * RATE:
                raise LocalError(f"一次最多录 {MAX_SECONDS // 60} 分钟")
            s.used = time.time()
            if len(samples):
                s.chunks.append(samples)
                s.samples += len(samples)
                s.pending = np.concatenate([s.pending, samples])
                window = self.vad_config.silero_vad.window_size
                while len(s.pending) >= window:
                    s.vad.accept_waveform(s.pending[:window])
                    s.pending = s.pending[window:]
            self._drain(s)
            speaking = s.vad.is_speech_detected()
            wait = max(PARTIAL_EVERY * RATE, 2 * s.partial_cost * RATE)
            if speaking and s.samples - s.partial_at >= wait:
                current = s.vad.current_segment
                tail = np.asarray(current.samples, dtype=np.float32) if current is not None else np.zeros(0, np.float32)
                if len(tail) >= RATE // 4:
                    s.partial, s.partial_cost = self._recognize(tail)
                    s.partial_at = s.samples
            elif not speaking:
                s.partial = ""
            final = _join(s.parts)
            text = _join([final, s.partial])
            # the phone shows "partial" straight after "final", so it carries the space _join put between them
            return {"text": text, "final": final, "partial": text[len(final):], "speaking": speaking,
                    "seconds": round(s.samples / RATE, 1), "checking": s.waiting}

    def end(self, sid: str) -> dict:
        s = self._session(sid)
        np = self.np
        started = time.time()
        with s.lock:
            first_end = not s.ended
            if first_end:
                if len(s.pending):
                    window = self.vad_config.silero_vad.window_size
                    s.vad.accept_waveform(np.concatenate([s.pending, np.zeros(window - len(s.pending), np.float32)]))
                    s.pending = np.zeros(0, dtype=np.float32)
                s.vad.flush()
                self._drain(s)
                s.ended = time.time()
        s.idle.wait(FINAL_WAIT)  # the last stretch is still with the accurate model
        with s.lock:
            silent = first_end and not any(p.strip() for p in s.parts) and s.samples >= RATE // 2
        if silent:  # the detector heard no speech: try the whole recording once (outside the session lock,
            audio = s.audio()  # which the accurate worker takes while it holds its own lock)
            text, again = self._accurate_text(audio, "") if self.accurate is not None else ("", False)
            s.copied += again
            exact = bool(text)
            text = text or self._recognize(audio)[0]
            if text:
                with s.lock:
                    s.fast.append(text)
                    s.parts.append(text)
                    s.exact.append(exact)
        with s.lock:
            text = _join(s.parts)
            exact = bool(s.exact) and all(s.exact)
        spent = time.time() - started
        if first_end:
            self.log(f"本地语音识别：{s.samples / RATE:.1f} 秒录音，松手后 {spent:.2f} 秒出字"
                     + ("" if exact or self.accurate is None else "（有的段落用了快速识别的结果）")
                     + (f"（{s.copied} 段照抄了词典，改用不带词典的识别）" if s.copied else ""))
            if self.keep > 0:
                threading.Thread(target=self._keep_sample, args=(s, text), name="voice-sample", daemon=True).start()
        return {"text": text, "seconds": round(s.samples / RATE, 1), "finish_ms": round(spent * 1000),
                "accurate": exact}

    def cancel(self, sid: str) -> None:
        with self.sessions_lock:
            s = self.sessions.pop(sid, None)
        if s is not None:
            s.cancelled = True

    def wav(self, sid: str) -> bytes:
        """The whole recording as a 16 kHz WAV, for the cloud re-run."""
        import io
        buf = io.BytesIO()
        self._write_wav(buf, self._session(sid).audio())
        return buf.getvalue()

    def _write_wav(self, target, audio) -> None:
        pcm = (self.np.clip(audio, -1, 1) * 32767).astype("<i2").tobytes()
        with wave.open(target, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(RATE)
            w.writeframes(pcm)

    def _keep_sample(self, s: Session, text: str) -> None:
        """The recording and both texts, so the recognisers can be compared on real speech later."""
        try:
            self.samples_dir.mkdir(parents=True, exist_ok=True)
            name = time.strftime("%Y%m%d-%H%M%S") + "-" + s.sid[:4]
            self._write_wav(str(self.samples_dir / (name + ".wav")), s.audio())
            info = {"time": time.strftime("%Y-%m-%d %H:%M:%S"), "seconds": round(s.samples / RATE, 1),
                    "fast": _join(s.fast), "final": text, "accurate": list(s.exact), "copied": s.copied}
            (self.samples_dir / (name + ".json")).write_text(json.dumps(info, ensure_ascii=False, indent=1),
                                                             encoding="utf-8")
            kept = sorted(self.samples_dir.glob("*.wav"))
            for old in kept[: max(0, len(kept) - self.keep)]:
                old.unlink(missing_ok=True)
                old.with_suffix(".json").unlink(missing_ok=True)
        except OSError:
            pass
