"""Generate Teleply assets from the approved SVG masters. Requires Pillow and skia-python."""
from pathlib import Path
import io
import re
import shutil
import xml.etree.ElementTree as ET
import skia
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'brand/teleply-final/source'
NS = {'s':'http://www.w3.org/2000/svg'}

def render(svg, size):
    dom = skia.SVGDOM.MakeFromStream(skia.MemoryStream(svg.encode()))
    surface = skia.Surface(size, size)
    canvas = surface.getCanvas()
    canvas.clear(skia.ColorTRANSPARENT)
    view = ET.fromstring(svg).attrib['viewBox'].split()
    canvas.scale(size / float(view[2]), size / float(view[3]))
    dom.render(canvas)
    return Image.open(io.BytesIO(bytes(surface.makeImageSnapshot().encodeToData()))).convert('RGBA')

def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8')

def main():
    static = ROOT / 'static'
    app = (SOURCE/'teleply-app-icon.svg').read_text(encoding='utf-8')
    mark = (SOURCE/'teleply-mark.svg').read_text(encoding='utf-8')
    dark = app.replace('#FFFFFF','#000000').replace('fill="#000000" d=', 'fill="#FFFFFF" d=')
    white = mark.replace('#000000','#FFFFFF')
    for name, svg in [('teleply-app-icon-dark.svg',dark),('teleply-mark-white.svg',white)]:
        write(SOURCE/name,svg)
    write(ROOT/'brand/logo.svg',app)
    inline = mark.replace('fill="#000000"','fill="currentColor"')
    inline = re.sub(r' width="[^"]+"| height="[^"]+"','',inline)
    inline = inline.replace('<svg ', '<svg class="mark" aria-hidden="true" ',1).strip()
    write(ROOT/'brand/mark.svg',inline)
    for name in ['relay_account.html','mobile/src/index.html']:
        path=ROOT/name
        text=path.read_text(encoding='utf-8')
        if '<svg class="mark"' in text:
            text,count=re.subn(r'<svg class="mark"[^>]*>.*?</svg>',lambda _:inline,text,count=1,flags=re.S)
        else:
            text,count=re.subn(r'<i>A</i>',lambda _:inline,text,count=1)
        if count != 1: raise ValueError(f'Expected one brand mark: {name}')
        write(path,text)
    sizes=(256,128,96,64,48,40,32,24,20,16)
    frames=[render(app,n) for n in sizes]
    frames[0].save(static/'app.ico',sizes=[(n,n) for n in sizes],append_images=frames[1:])
    for name,color in [('tray-online.png','#16884B'),('tray-offline.png','#C48300')]:
        im=render(app,256)
        ImageDraw.Draw(im).ellipse((4,176,80,252),fill=color,outline='white',width=10)
        im.save(static/name,optimize=True)
    png=ROOT/'brand/teleply-final/png'
    for src,dst in [('icon-192.png','icon-192.png'),('icon-512.png','icon-512.png'),('icon-maskable-512.png','icon-maskable-512.png'),('apple-touch-icon.png','apple-touch-icon.png'),('favicon.ico','favicon.ico')]:
        shutil.copyfile(png/'web'/src,static/dst)
    favicon=(SOURCE/'favicon.svg').read_text(encoding='utf-8')
    write(static/'favicon.svg',favicon)
    write(static/'favicon-dark.svg',favicon.replace('#FFFFFF','#000000').replace('fill="#000000" d=','fill="#FFFFFF" d='))
    for size in [256,512,1024]:
        render(dark,size).save(png/'logo'/f'teleply-dark-{size}.png',optimize=True)
    ios=ROOT/'mobile/resources/ios';ios.mkdir(exist_ok=True,parents=True)
    shutil.copyfile(png/'ios/AppIcon-1024.png',ios/'AppIcon-512@2x.png')
    Image.new('RGB',(64,64),'white').save(ios/'splash.png')
    res=ROOT/'mobile/resources/android'
    svg=ET.parse(SOURCE/'teleply-android-adaptive-foreground.svg')
    data=svg.find('s:path',NS).attrib['d']
    vector=lambda body:f'<vector xmlns:android="http://schemas.android.com/apk/res/android" android:width="108dp" android:height="108dp" android:viewportWidth="108" android:viewportHeight="108">{body}</vector>\n'
    write(res/'drawable/agent_remote_mark.xml',vector(f'<path android:fillColor="#000000" android:pathData="{data}"/>'))
    write(res/'drawable/agent_remote_tile.xml',vector('<path android:fillColor="#FFFFFF" android:pathData="M0,0H108V108H0Z"/>'))
    adaptive='<adaptive-icon xmlns:android="http://schemas.android.com/apk/res/android"><background android:drawable="@drawable/agent_remote_tile"/><foreground android:drawable="@drawable/agent_remote_mark"/><monochrome android:drawable="@drawable/agent_remote_mark"/></adaptive-icon>\n'
    for name in ['ic_launcher.xml','ic_launcher_round.xml']:write(res/'mipmap-anydpi-v26'/name,adaptive)
    for folder in (png/'android').glob('mipmap-*'):
        for name in ['ic_launcher.png','ic_launcher_round.png']:
            target=res/folder.name/name;target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(folder/'ic_launcher.png',target)
    print('Teleply SVG, Windows, browser, Android and iOS assets generated.')

if __name__=='__main__':main()
