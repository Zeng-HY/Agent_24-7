"""The voice dictionary: words the microphone should know, kept in voice_terms.txt next to this file.

One word per line. Recognition leans towards these words (the Qwen3-ASR model on this PC takes them as
hotwords, the cloud service gets them as a hint), the 整理 step gets them as the spellings to use, and
every result has them written the same way: "Chat GPT", "chatgpt" and "Chat-GPT" all become "ChatGPT".
A word that keeps coming out wrong can list its usual wrong forms after "=", separated by commas:
    ChatGPT = catGPT, 个CPT
Lines starting with # are notes. The file is read again whenever it changes; nothing needs a restart.
"""

from __future__ import annotations

import re
import threading
from pathlib import Path
from app_paths import DATA

HERE = Path(__file__).resolve().parent
TERMS_FILE = DATA / "voice_terms.txt"
MAX_HOTWORDS = 60
MAX_FILE_CHARS = 20000

DEFAULT_TEXT = """\
# 每行一个词：说话时优先认这些词，写法也按这里统一。
# 老被认错的词，在后面写上错成的样子，用 = 和逗号隔开，例如 ChatGPT = catGPT, 个CPT
Claude = cloud
ChatGPT = catGPT, 个CPT, 猫GPT
Codex = codeex
OpenAI
GPT
Gemini
DeepSeek
Typeless
Playwright
Tailscale = talescale
OpenRouter
Obsidian
Safari
iPhone
搜狗
"""

_lock = threading.Lock()
_cache: dict = {"key": None, "entries": [], "rules": []}

_ASCII = re.compile(r"[A-Za-z0-9]")
_CJK = re.compile(r"[㐀-鿿豈-﫿]")


def _key() -> tuple:
    try:
        st = TERMS_FILE.stat()
        return (st.st_mtime_ns, st.st_size)
    except OSError:
        return (0, 0)


def read_text() -> str:
    """The dictionary as the user wrote it; the default list when there is no file yet."""
    try:
        return TERMS_FILE.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        return DEFAULT_TEXT
    except OSError:
        return DEFAULT_TEXT


def ensure_file() -> None:
    if not TERMS_FILE.exists():
        try:
            TERMS_FILE.write_bytes(DEFAULT_TEXT.encode("utf-8"))
        except OSError:
            pass


def save_text(text: str) -> int:
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    if len(text) > MAX_FILE_CHARS:
        raise ValueError(f"词典太长了（最多 {MAX_FILE_CHARS} 个字符）")
    if text and not text.endswith("\n"):
        text += "\n"
    TERMS_FILE.write_bytes(text.encode("utf-8"))  # bytes: no newline translation on Windows
    return len(entries())


def _parse(text: str) -> list[tuple[str, list[str]]]:
    out, seen = [], set()
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        word, _, wrong = line.partition("=")
        word = " ".join(word.split())
        if not word or len(word) > 60 or word.casefold() in seen:
            continue
        seen.add(word.casefold())
        forms = [" ".join(w.split()) for w in re.split(r"[,，、]", wrong)]
        out.append((word, [w for w in forms if w and w.casefold() != word.casefold()]))
    return out


def _spelling_pattern(word: str) -> str | None:
    """'ChatGPT' also matches 'Chat GPT', 'chat-gpt', 'chatgpt'. Only for words with Latin letters."""
    if not _ASCII.search(word) or _CJK.search(word):
        return None
    chars = [c for c in word if not c.isspace() and c != "-"]
    if not chars:
        return None
    loose = len(chars) >= 5  # long words: a space may fall anywhere ("Tail Scale", "Type less")
    out = []
    for i, c in enumerate(chars):
        if i:
            a = chars[i - 1]
            boundary = (a.islower() and c.isupper()) or (a.isalpha() != c.isalpha())
            out.append(r"[ \-]?" if loose or boundary else "")
        out.append(re.escape(c))
    return r"(?<![A-Za-z0-9])" + "".join(out) + r"(?![A-Za-z0-9])"


def _wrong_pattern(form: str) -> str:
    """A listed wrong form, ignoring case and spaces between Chinese and Latin letters."""
    out = []
    for i, c in enumerate(form):
        if c.isspace():
            out.append(r"\s*")
            continue
        if i and not form[i - 1].isspace() and (bool(_CJK.match(form[i - 1])) != bool(_CJK.match(c))):
            out.append(r"\s?")
        out.append(re.escape(c))
    pattern = "".join(out)
    if _ASCII.match(form[0]):
        pattern = r"(?<![A-Za-z0-9])" + pattern
    if _ASCII.match(form[-1]):
        pattern += r"(?![A-Za-z0-9])"
    return pattern


def entries() -> list[tuple[str, list[str]]]:
    key = _key()
    with _lock:
        if _cache["key"] != key:
            parsed = _parse(read_text())
            wrong_rules, spell_rules = [], []
            for word, wrong in parsed:
                for form in wrong:
                    wrong_rules.append((len(form), re.compile(_wrong_pattern(form), re.IGNORECASE), word))
                pattern = _spelling_pattern(word)
                if pattern:
                    spell_rules.append((len(word), re.compile(pattern, re.IGNORECASE), word))
            # wrong forms first, then spellings; longer before shorter, so "ChatGPT" is settled before "GPT"
            wrong_rules.sort(key=lambda r: -r[0])
            spell_rules.sort(key=lambda r: -r[0])
            _cache.update(key=key, entries=parsed, rules=[(p, w) for _, p, w in wrong_rules + spell_rules])
        return list(_cache["entries"])


def signature() -> tuple:
    return _key()


def words(extra=()) -> list[str]:
    seen, out = set(), []
    for word in [w for w, _ in entries()] + [str(t) for t in extra or ()]:
        word = " ".join(word.split())
        if word and word.casefold() not in seen:
            seen.add(word.casefold())
            out.append(word)
    return out


def hotwords(extra=()) -> str:
    return ",".join(w.replace(",", " ") for w in words(extra)[:MAX_HOTWORDS])


_RUN_GAP = re.compile(r"[\s,，、;；.。:：·/|\-]*")


def copied_run(text: str, heard: str = "") -> list[str]:
    """Dictionary words that a text has one right after another in the dictionary's own order, most of which the fast
    recogniser did not hear (heard: its text for the same stretch); [] when there are none.
    Qwen3-ASR gets the dictionary as hotwords, and when the start of a stretch is unclear it sometimes writes out the
    list instead of what was said: on 10-12 "Codex 提问的提示条" came out as "Claude ChatGPT Codex 提问的提示条" (the
    first three words of the list), and a laugh as the whole dictionary. Replayed with small changes to the same audio,
    that stretch came out right 58 times in 150 with the dictionary and 120 times without it."""
    order = words()
    if len(order) < 2 or not text:
        return []
    index = {w.casefold(): i for i, w in enumerate(order)}
    spans = []  # (start, end, place in the list), longest words first so 'ChatGPT' is not also taken for 'GPT'
    for word in sorted(order, key=len, reverse=True):
        pattern = re.escape(word)
        if _ASCII.match(word[0]):
            pattern = r"(?<![A-Za-z0-9])" + pattern
        if _ASCII.match(word[-1]):
            pattern += r"(?![A-Za-z0-9])"
        for m in re.finditer(pattern, text, re.IGNORECASE):
            if not any(a < m.end() and m.start() < b for a, b, _ in spans):
                spans.append((m.start(), m.end(), index[word.casefold()]))
    spans.sort()
    best, run = [], []
    for span in spans:
        if run and span[2] == run[-1][2] + 1 and _RUN_GAP.fullmatch(text[run[-1][1]:span[0]]):
            run.append(span)
        else:
            run = [span]
        if len(run) > len(best):
            best = list(run)
    if len(best) < 2:
        return []
    found = [order[i] for _, _, i in best]
    heard = (heard or "").casefold()
    unheard = [w for w in found if w.casefold() not in heard]
    return found if 2 * len(unheard) > len(found) else []


def normalize(text: str) -> str:
    """Write every dictionary word the way the dictionary spells it."""
    if not text:
        return text
    entries()  # refresh the rules when the file changed
    with _lock:
        rules = list(_cache["rules"])
    for pattern, word in rules:
        text = pattern.sub(word, text)
    return text
