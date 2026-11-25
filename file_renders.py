"""Thumbnails and image sizes for the phone (docs/handoff-file-preview.md §5.1, §5.3, §5.8, segment D).

Only the computer reads this cache; it is not an answer file and does not go through
file_policy.  A thumbnail is a WebP, quality 82, long edge at most ``w``, EXIF upright,
GIF first frame.  SVG goes through resvg (no external file or URL is loaded).
"""
from __future__ import annotations

import hashlib
import io
import ntpath
import os
import re
import threading
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from pathlib import Path

from PIL import Image, ImageOps

try:  # an optional component; without it SVG keeps its file card
    import pillow_heif
    pillow_heif.register_heif_opener()
except Exception:  # pragma: no cover - only when the component is absent
    pillow_heif = None

try:
    import resvg_py
    RESVG_VERSION = getattr(resvg_py, "__resvg_version__", "unknown")
except Exception:  # pragma: no cover - only when the component is absent
    resvg_py = None
    RESVG_VERSION = ""

VERSION = "1"
WIDTHS = (320, 640, 1280, 2048)
SVG_WIDTHS = WIDTHS + (4096,)
MAX_SOURCE = 100 << 20
MAX_PIXELS = 100_000_000
MAX_SVG = 10 << 20
MAX_TOTAL = 300 << 20
TIMEOUT = 15.0
Image.MAX_IMAGE_PIXELS = MAX_PIXELS

_executor = ThreadPoolExecutor(max_workers=2)
_locks: dict[tuple, threading.Lock] = {}
_locks_guard = threading.Lock()
_size_lock = threading.Lock()
_size_cache: dict[tuple, tuple[float, tuple[int | None, int | None, bool]]] = {}


class RenderError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def available() -> bool:
    return resvg_py is not None


def _stat(path):
    try:
        return os.stat(path)
    except (OSError, ValueError):
        return None


def _cache_root(cache_dir=None) -> Path:
    if cache_dir is not None:
        return Path(cache_dir)
    from app_paths import DATA
    return Path(DATA) / "cache" / "thumbs"


def _cache_name(path, st, width: int) -> str:
    raw = f"{ntpath.normcase(str(path))}\0{st.st_size}\0{st.st_mtime_ns}\0{width}\0{VERSION}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:40] + ".webp"


def cache_path(path, width: int, cache_dir=None, st=None) -> Path | None:
    st = st or _stat(path)
    if st is None:
        return None
    return _cache_root(cache_dir) / _cache_name(path, st, width)


def _prune(cache_dir, max_total: int) -> None:
    root = Path(cache_dir)
    try:
        files = [(entry.stat().st_mtime, entry.stat().st_size, entry)
                 for entry in root.iterdir() if entry.is_file()]
    except OSError:
        return
    total = sum(size for _, size, _ in files)
    if total <= max_total:
        return
    for _, size, entry in sorted(files):
        if total <= max_total:
            break
        try:
            entry.unlink()
            total -= size
        except OSError:
            continue


def prune(cache_dir=None, max_total: int = MAX_TOTAL) -> None:
    _prune(_cache_root(cache_dir), max_total)


def clear(cache_dir=None) -> None:
    root = _cache_root(cache_dir)
    try:
        for entry in root.iterdir():
            if entry.is_file():
                entry.unlink()
    except OSError:
        pass
    with _size_lock:
        _size_cache.clear()


def _svg_error(message: str):
    return RenderError(message, 400)


def _number(value) -> float | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    match = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)(?:px)?", value, re.I)
    return float(match.group(1)) if match else None


def _root(svg_text: str):
    try:
        return ET.fromstring(svg_text)
    except (ET.ParseError, ValueError):
        return None


def _svg_dims(svg_text: str) -> tuple[int, int] | None:
    root = _root(svg_text)
    if root is None:
        return None
    width, height = _number(root.get("width")), _number(root.get("height"))
    box = root.get("viewBox") or root.get("viewbox")
    vb = [float(v) for v in re.split(r"[\s,]+", box.strip())] if isinstance(box, str) and box.strip() else []
    if len(vb) != 4:
        vb = []
    if width and height:
        return max(1, round(width)), max(1, round(height))
    if vb:
        vw, vh = vb[2], vb[3]
        if width and not height:
            if not vw:
                return None
            return max(1, round(width)), max(1, round(width * vh / vw))
        if height and not width:
            if not vh:
                return None
            return max(1, round(height * vw / vh)), max(1, round(height))
        return max(1, round(vw)), max(1, round(vh))
    return None


def _sanitize_svg(text: str) -> str:
    """Drop external hrefs, scripts and external CSS resources; keep fragments and data: images."""
    root = _root(text)
    if root is None:
        raise _svg_error("SVG 文件无法解析")
    href_name = "{http://www.w3.org/1999/xlink}href"

    def clean(element):
        tag = element.tag.rsplit("}", 1)[-1].lower()
        if tag in ("script", "foreignobject"):
            return False
        for key in list(element.attrib):
            low = key.lower()
            if low.startswith("on"):
                element.attrib.pop(key, None)
            elif low in ("href", href_name.lower(), "xlink:href"):
                value = (element.attrib.get(key) or "").strip()
                if not (value.startswith("#") or value.lower().startswith("data:")):
                    element.attrib.pop(key, None)
            elif low == "style":
                value = element.attrib[key]
                value = re.sub(r"@import[^;]*;", "", value, flags=re.I)
                value = re.sub(r"url\([^)]*(?:https?:|file:|ftp:)[^)]*\)", "none", value, flags=re.I)
                element.attrib[key] = value
        for child in list(element):
            if not clean(child):
                element.remove(child)
        return True

    clean(root)
    return ET.tostring(root, encoding="unicode")


def _oriented_size(im: Image.Image) -> tuple[int, int]:
    width, height = im.size
    try:
        if im.getexif().get(274) in (5, 6, 7, 8):
            width, height = height, width
    except Exception:
        pass
    return width, height


def _image_size(path, st, max_source, max_pixels):
    if st.st_size > max_source:
        return None, None, False
    try:
        with Image.open(path) as im:
            width, height = _oriented_size(im)
    except Exception:
        return None, None, False
    if width <= 0 or height <= 0:
        return None, None, False
    return width, height, width * height <= max_pixels


def _svg_size(path, st, max_svg):
    if st.st_size > max_svg or resvg_py is None:
        return None, None, False
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None, None, False
    dims = _svg_dims(text)
    if dims is None:
        return None, None, False
    return dims[0], dims[1], True


def size(path, view, st=None, cache_dir=None, clock=time.monotonic, max_source=MAX_SOURCE,
         max_pixels=MAX_PIXELS, max_svg=MAX_SVG):
    """(width, height, thumb) for one answer file; header-only, cached with the file information."""
    st = st or _stat(path)
    if st is None:
        return None, None, False
    key = (ntpath.normcase(str(path)), st.st_size, st.st_mtime_ns, view,
           max_source, max_pixels, max_svg)
    now = clock()
    with _size_lock:
        cached = _size_cache.get(key)
        if cached is not None and cached[0] > now:
            return cached[1]
    if view == "image":
        result = _image_size(path, st, max_source, max_pixels)
    elif view == "svg":
        result = _svg_size(path, st, max_svg)
    else:
        result = (None, None, False)
    with _size_lock:
        if len(_size_cache) > 4096:
            _size_cache.pop(next(iter(_size_cache)))
        _size_cache[key] = (now + 5.0, result)
    return result


def _webp(im: Image.Image, width: int) -> bytes:
    if im.mode not in ("RGB", "RGBA"):
        im = im.convert("RGBA" if "A" in im.getbands() else "RGB")
    im.thumbnail((width, width), Image.Resampling.LANCZOS)
    buffer = io.BytesIO()
    im.save(buffer, "WEBP", quality=82, method=6)
    return buffer.getvalue()


def _render_image(path, width, max_source, max_pixels):
    st = _stat(path)
    if st is None:
        raise RenderError("图片读取失败", 404)
    if st.st_size > max_source:
        raise RenderError("图片超过 100 MB，无法生成缩略图", 413)
    try:
        with Image.open(path) as im:
            if im.width * im.height > max_pixels:
                raise RenderError("图片像素太多，无法生成缩略图", 413)
            im.seek(0)
            im = ImageOps.exif_transpose(im)
            im.load()
            return _webp(im, width)
    except RenderError:
        raise
    except Image.DecompressionBombError:
        raise RenderError("图片像素太多，无法生成缩略图", 413) from None
    except Exception as exc:
        raise RenderError(f"图片打不开，无法生成缩略图：{type(exc).__name__}", 400) from None


def _render_svg(path, width, max_svg):
    if resvg_py is None:
        raise RenderError("SVG 预览组件不可用", 400)
    st = _stat(path)
    if st is None:
        raise RenderError("SVG 读取失败", 404)
    if st.st_size > max_svg:
        raise RenderError("SVG 超过 10 MB，无法生成缩略图", 413)
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        raise RenderError("SVG 读取失败", 404) from None
    text = _sanitize_svg(text)
    dims = _svg_dims(text)
    if dims is None:
        raise RenderError("SVG 没有可用的尺寸", 400)
    sway, sh = dims
    scale = min(1.0, width / max(sway, sh))
    out_w, out_h = max(1, round(sway * scale)), max(1, round(sh * scale))
    try:
        png = resvg_py.svg_to_bytes(svg_string=text, width=out_w, height=out_h)
        with Image.open(io.BytesIO(png)) as im:
            im.load()
            return _webp(im, width)
    except Exception as exc:
        raise RenderError(f"SVG 转换失败：{type(exc).__name__}", 400) from None


def _render(path, view, width, max_source, max_pixels, max_svg):
    if view == "svg":
        return _render_svg(path, width, max_svg)
    return _render_image(path, width, max_source, max_pixels)


def _lock_for(key) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault(key, threading.Lock())


def thumbnail(path, view, width: int, st=None, cache_dir=None, timeout=TIMEOUT,
              max_source=MAX_SOURCE, max_pixels=MAX_PIXELS, max_svg=MAX_SVG,
              max_total=MAX_TOTAL):
    """WebP bytes for one file, from the cache when it is there."""
    if view not in ("image", "svg"):
        raise RenderError("这个文件不提供缩略图", 400)
    if width not in (SVG_WIDTHS if view == "svg" else WIDTHS):
        raise RenderError("缩略图宽度不支持", 400)
    st = st or _stat(path)
    if st is None:
        raise RenderError("文件已移动或删除", 404)
    target = cache_path(path, width, cache_dir, st)
    if target is None:
        raise RenderError("文件已移动或删除", 404)
    try:
        return target.read_bytes()
    except OSError:
        pass
    key = (ntpath.normcase(str(path)), st.st_size, st.st_mtime_ns, width, view)
    with _lock_for(key):
        try:
            return target.read_bytes()
        except OSError:
            pass
        root = _cache_root(cache_dir)
        root.mkdir(parents=True, exist_ok=True)
        future = _executor.submit(_render, path, view, width, max_source, max_pixels, max_svg)
        try:
            data = future.result(timeout=timeout)
        except FutureTimeout:
            raise RenderError("生成缩略图超时，请稍后再试", 504) from None
        except RenderError:
            raise
        except Exception as exc:
            raise RenderError(f"生成缩略图失败：{type(exc).__name__}", 400) from None
        temp = target.with_suffix(".part")
        try:
            temp.write_bytes(data)
            temp.replace(target)
        except OSError:
            temp.unlink(missing_ok=True)
            raise RenderError("缩略图缓存写入失败", 500) from None
        _prune(root, max_total)
        return data
