"""The Agent Remote mark, and every icon file made from it:  python brand/make_icons.py

The mark is a letter A whose crossbar is a dot. The dot is the app's "connected" light (the dot before 已连接):
in the tray it goes grey while this computer is not connected. Everything below is drawn from one set of shapes
in a 1024 square, so the SVG, the Windows icon, the phone home-screen icons and the Android launcher icon cannot
drift apart. Only Pillow is needed (it is in requirements.txt).
"""
import math
from pathlib import Path
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
INK = '#111113'  # the UI's ink; the flat mark in the pages uses it as is
TOP, BOTTOM = (0x2a, 0x2a, 0x2e), (0x0c, 0x0c, 0x0e)  # the icon tile: the same ink, lit a little from above
DIM = (0x5c, 0x5c, 0x63)  # the dot while not connected
WEIGHT, DOT = 96, 52  # stroke and dot radius at full size
# The A: its top and baseline, half its spread at the baseline, the width of its flat top, its corner rounding
A_TOP, A_BOTTOM, A_SPREAD, A_FLAT, A_ROUND, DOT_AT = 252, 742, 236, 56, 14, 604


def tile():
    """The rounded square, with corners that ease in like a phone icon's: a path in the 1024 square."""
    R, smooth = 229, .6  # Figma's 'iOS' corner: radius 22.4% and 60% smoothing
    arc = math.radians(90 * (1 - smooth))
    p = (1 + smooth) * R
    arc_len = math.sin(arc / 2) * R * math.sqrt(2)
    c = R * math.tan((math.pi / 2 - arc) / 4) * math.cos(math.radians(45 * smooth))
    d = c * math.tan(math.radians(45 * smooth))
    b = (p - arc_len - c - d) / 3
    a = 2 * b
    # The top-right corner around the centre; the others are the same turned by 90 degrees
    x0, y0 = 512 - p, -512
    x1, y1 = x0 + a + b + c, y0 + d
    x2, y2 = x1 + arc_len, y1 + arc_len
    corner = [('C', (x0 + a, y0), (x0 + a + b, y0), (x1, y1)), ('A', R, (512 - R, -512 + R), (x2, y2)),
              ('C', (512, y2 + c), (512, y2 + b + c), (512, y2 + a + b + c))]
    turn = lambda pt, k: [pt, (-pt[1], pt[0]), (-pt[0], -pt[1]), (pt[1], -pt[0])][k]
    shift = lambda pt, k: (round(turn(pt, k)[0] + 512, 2), round(turn(pt, k)[1] + 512, 2))
    path = [('M', shift((x0, y0), 0))]
    for k in range(4):
        if k: path.append(('L', shift((x0, y0), k)))
        for seg in corner:
            path.append((seg[0],) + tuple(v if isinstance(v, (int, float)) else shift(v, k) for v in seg[1:]))
    return path


def rounded(points, radius):
    """A closed polygon with each corner rounded off: a path."""
    corners = []
    for i, p in enumerate(points):
        before, after = points[i - 1], points[(i + 1) % len(points)]
        u = [(q[0] - p[0], q[1] - p[1]) for q in (before, after)]
        u = [(x / math.hypot(x, y), y / math.hypot(x, y)) for x, y in u]
        half = math.acos(max(-1, min(1, u[0][0] * u[1][0] + u[0][1] * u[1][1]))) / 2
        t = radius / math.tan(half)
        bis = (u[0][0] + u[1][0], u[0][1] + u[1][1])
        n = math.hypot(*bis)
        centre = (p[0] + bis[0] / n * radius / math.sin(half), p[1] + bis[1] / n * radius / math.sin(half))
        corners.append(((p[0] + u[0][0] * t, p[1] + u[0][1] * t), centre, (p[0] + u[1][0] * t, p[1] + u[1][1] * t)))
    path = [('M', corners[-1][2])]
    for start, centre, end in corners:
        path += [('L', start), ('A', radius, centre, end)]
    return path


def glyph(px=1024):
    """The A (a path) and its dot (centre, radius). Below 32 px the shapes land on whole pixels and get heavier."""
    top, bottom, weight, dot, dot_at = A_TOP, A_BOTTOM, WEIGHT, DOT, DOT_AT
    if px < 32:
        u = 1024 / px
        top = round(A_TOP / u) * u
        bottom = top + round((A_BOTTOM - A_TOP) / u) * u
        weight = max(WEIGHT, 1.9 * u)
        dot = max(DOT, 1.05 * u)
        dot_at = round((top + (DOT_AT - A_TOP) / (A_BOTTOM - A_TOP) * (bottom - top)) / u) * u
    spread = A_SPREAD * (bottom - top) / (A_BOTTOM - A_TOP)
    slope = spread / (bottom - top)
    thick = weight / math.cos(math.atan(slope))  # the stroke measured along the baseline
    flat = A_FLAT / 2
    inner = bottom - (spread + flat - thick) / slope
    points = [(512 - flat, top), (512 + flat, top), (512 + flat + spread, bottom), (512 + flat + spread - thick, bottom),
              (512, inner), (512 - flat - spread + thick, bottom), (512 - flat - spread, bottom)]
    return rounded(points, A_ROUND), ((512, dot_at), dot)


def svg_path(path):
    out, here = [], None
    for op, *args in path:
        if op == 'A':
            radius, centre, end = args
            out.append('A%s %s 0 0 %d %s %s' % (num(radius), num(radius), sweep(centre, here, end), num(end[0]), num(end[1])))
            here = end
        else:
            out.append(op + ' '.join('%s %s' % (num(x), num(y)) for x, y in args))
            here = args[-1]
    return ''.join(out) + 'Z'


def sweep(centre, start, end):
    """1 when the arc turns clockwise (on screen) from start to end."""
    return int((start[0] - centre[0]) * (end[1] - centre[1]) - (start[1] - centre[1]) * (end[0] - centre[0]) > 0)


def num(v):
    return ('%.2f' % v).rstrip('0').rstrip('.')


def points(path, step=2.0):
    """The path as a polygon, with curves cut into pieces about `step` long."""
    out = []
    for op, *args in path:
        if op in 'ML':
            out.append(args[0])
        elif op == 'C':
            p0, (p1, p2, p3) = out[-1], args
            n = max(2, int(math.dist(p0, p3) / step))
            for i in range(1, n + 1):
                t = i / n
                out.append(tuple((1 - t) ** 3 * a + 3 * (1 - t) ** 2 * t * b + 3 * (1 - t) * t * t * c + t ** 3 * d
                                 for a, b, c, d in zip(p0, p1, p2, p3)))
        else:
            radius, centre, end = args
            start = out[-1]
            a0 = math.atan2(start[1] - centre[1], start[0] - centre[0])
            a1 = math.atan2(end[1] - centre[1], end[0] - centre[0])
            turn = (a1 - a0) % (2 * math.pi)
            if not sweep(centre, start, end):
                turn -= 2 * math.pi
            n = max(2, int(abs(turn) * radius / step))
            out += [(centre[0] + radius * math.cos(a0 + turn * i / n), centre[1] + radius * math.sin(a0 + turn * i / n))
                    for i in range(1, n + 1)]
    return out


def coverage(px, draw):
    """An L-mode mask at px x px: `draw(canvas, scale)` paints white on black at a larger size, then it is averaged."""
    k = max(4, -(-4096 // px))  # at least 4x4 samples per pixel, and a 4096 canvas for the small ones
    big = Image.new('L', (px * k, px * k), 0)
    draw(ImageDraw.Draw(big), px * k / 1024)
    return big.reduce(k)


def shape(path):
    return lambda canvas, s: canvas.polygon([(x * s, y * s) for x, y in points(path, 1 / s)], fill=255)


def disc(dot):
    (x, y), r = dot
    return lambda canvas, s: canvas.ellipse([(x - r) * s, (y - r) * s, (x + r) * s, (y + r) * s], fill=255)


def icon(px, rounded_tile=True, lit=True):
    """The icon at px x px (RGBA): the tile with its corners cut (or filling the square), and the white mark."""
    a, dot = glyph(px)
    ramp = Image.new('RGB', (1, px))
    ramp.putdata([tuple(round(t + (b - t) * (y + .5) / px) for t, b in zip(TOP, BOTTOM)) for y in range(px)])
    out = ramp.resize((px, px)).convert('RGBA')
    if rounded_tile:
        out.putalpha(coverage(px, shape(tile())))
    out = laid(out, (255, 255, 255), coverage(px, shape(a)))
    return laid(out, (255, 255, 255) if lit else DIM, coverage(px, disc(dot)))


def laid(image, colour, mask):
    """`image` with `colour` laid over it where `mask` is white."""
    layer = Image.new('RGBA', image.size, colour + (0,))
    layer.putalpha(mask)
    return Image.alpha_composite(image, layer)


def moved(path, scale, dx=0, dy=0):
    """The path scaled about (0, 0) and then shifted."""
    at = lambda p: (p[0] * scale + dx, p[1] * scale + dy)
    return [(op, args[0] * scale, at(args[1]), at(args[2])) if op == 'A' else (op,) + tuple(map(at, args)) for op, *args in path]


def svg(px, backdrop):
    """The mark drawn in a px square over `backdrop` (SVG markup)."""
    a, ((x, y), r) = glyph()
    k = px / 1024
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {px} {px}">{backdrop}'
            f'<path d="{svg_path(moved(a, k))}" fill="#fff"/>'
            f'<circle cx="{num(x * k)}" cy="{num(y * k)}" r="{num(r * k)}" fill="#fff"/></svg>\n')


def android(data):
    return f'    <path android:fillColor="#FFFFFF" android:pathData="{data}"/>\n'


def vector(body, extra=''):
    return ('<?xml version="1.0" encoding="utf-8"?>\n<!-- Written by brand/make_icons.py -->\n'
            f'<vector xmlns:android="http://schemas.android.com/apk/res/android"{extra}\n'
            '    android:width="108dp" android:height="108dp" android:viewportWidth="108" android:viewportHeight="108">\n'
            f'{body}</vector>\n')


def main():
    static, mobile = ROOT / 'static', ROOT / 'mobile' / 'resources'
    hexa = lambda c: '#%02x%02x%02x' % c
    # The master drawing, and the flat mark the pages carry inline (relay_account.html, mobile/src/index.html)
    ramp = (f'<defs><linearGradient id="ink" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{hexa(TOP)}"/>'
            f'<stop offset="1" stop-color="{hexa(BOTTOM)}"/></linearGradient></defs>')
    (ROOT / 'brand' / 'logo.svg').write_text(svg(1024, ramp + f'<path d="{svg_path(tile())}" fill="url(#ink)"/>'), encoding='utf-8')
    (ROOT / 'brand' / 'mark.svg').write_text(svg(32, f'<rect width="32" height="32" rx="8" fill="{INK}"/>'), encoding='utf-8')
    # Windows: the program, its installer, window and taskbar; the tray shows tray-offline.png while not connected
    frames = [icon(px) for px in (256, 128, 96, 64, 48, 40, 32, 24, 20, 16)]
    frames[0].save(static / 'app.ico', sizes=[f.size for f in frames], append_images=frames[1:])
    icon(256, lit=False).save(static / 'tray-offline.png', optimize=True)
    # Home-screen icons of the phone page, and the iPhone app's: whole squares, the phone rounds the corners itself
    for px, path in ((192, static / 'icon-192.png'), (512, static / 'icon-512.png'), (1024, static / 'apple-touch-icon.png'),
                     (1024, mobile / 'ios' / 'AppIcon-512@2x.png')):
        path.parent.mkdir(parents=True, exist_ok=True)
        icon(px, rounded_tile=False).convert('RGB').save(path, optimize=True)
    # The iPhone app's launch screen is plain white, like the page it opens on
    Image.new('RGB', (64, 64), 'white').save(mobile / 'ios' / 'splash.png', optimize=True)
    # Android launcher icon (adaptive): the tile behind, the mark in front; the system shows the middle 72 of 108 dp
    res = mobile / 'android'
    for folder in ('drawable', 'mipmap-anydpi-v26'):
        (res / folder).mkdir(parents=True, exist_ok=True)
    k = 72 / 1024
    shift = 54 - 512 * k
    a, ((x, y), r) = glyph()
    x, y, r = x * k + shift, y * k + shift, r * k
    mark = android(svg_path(moved(a, k, shift, shift))) + android(
        f'M{num(x - r)} {num(y)}A{num(r)} {num(r)} 0 1 0 {num(x + r)} {num(y)}A{num(r)} {num(r)} 0 1 0 {num(x - r)} {num(y)}Z')
    (res / 'drawable' / 'agent_remote_mark.xml').write_text(vector(mark), encoding='utf-8')
    tile_fill = ('    <path android:pathData="M0 0H108V108H0Z">\n        <aapt:attr name="android:fillColor">\n'
                 f'            <gradient android:type="linear" android:startX="0" android:startY="18" android:endX="0" android:endY="90"\n'
                 f'                android:startColor="{hexa(TOP).upper()}" android:endColor="{hexa(BOTTOM).upper()}"/>\n'
                 '        </aapt:attr>\n    </path>\n')
    (res / 'drawable' / 'agent_remote_tile.xml').write_text(vector(tile_fill, '\n    xmlns:aapt="http://schemas.android.com/aapt"'), encoding='utf-8')
    adaptive = ('<?xml version="1.0" encoding="utf-8"?>\n<!-- Written by brand/make_icons.py -->\n'
                '<adaptive-icon xmlns:android="http://schemas.android.com/apk/res/android">\n'
                '    <background android:drawable="@drawable/agent_remote_tile"/>\n'
                '    <foreground android:drawable="@drawable/agent_remote_mark"/>\n'
                '    <monochrome android:drawable="@drawable/agent_remote_mark"/>\n'
                '</adaptive-icon>\n')
    for name in ('ic_launcher.xml', 'ic_launcher_round.xml'):
        (res / 'mipmap-anydpi-v26' / name).write_text(adaptive, encoding='utf-8')


if __name__ == '__main__':
    main()
