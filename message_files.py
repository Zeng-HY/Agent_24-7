"""Only actual Markdown nodes authorize exact files; code examples authorize nothing."""
import os
import re
from urllib.parse import unquote
from markdown_it import MarkdownIt
from markdown_it.common.utils import unescapeAll

PARSER=MarkdownIt('commonmark',{'html':True}).enable('table')
_validate=PARSER.validateLink
PARSER.validateLink=lambda url: bool(re.match(r'^[A-Za-z]:[\\/]',url)) or _validate(url)

def references(text):
    result=[]
    for block in PARSER.parse(text):
        for token in block.children or []:
            value=token.attrGet('href') if token.type=='link_open' else token.attrGet('src') if token.type=='image' else None
            if value and re.match(r'^[A-Za-z]:[\\/]',unquote(value)):
                result.append(re.sub(r':\d+(?:-\d+)?$','',unquote(value)))
    return result

# A link's destination in the text: <…> or a bare one, as CommonMark reads them (balanced parentheses, escapes).
_DESTINATION=re.compile(r'\]\(\s*(<(?:[^<>\n\\]|\\.)*>|(?:[^\s()<>\\]|\\.|\((?:[^\s()<>\\]|\\.)*\))+)')
_CODE_SPAN=re.compile(r'(`+)[\s\S]*?(?<!`)\1(?!`)')

def _resolve(href,cwd):
    """The file a relative link names, as <D:/…> text with its line number kept; None for anything else."""
    path=unquote(href).split('#',1)[0]
    if not path or path.startswith(('/','\\','?','~')) or re.match(r'^[A-Za-z][A-Za-z0-9+.-]*:',path):return None
    path,line=re.fullmatch(r'(.*?)((?::\d+(?:-\d+)?)?)',path).groups()
    full=os.path.normpath(os.path.join(cwd,path))
    return '<'+full.replace('\\','/')+line+'>' if os.path.isfile(full) else None

def absolute_links(text,cwd):
    """Claude writes file links relative to its working folder ([x](dist/x.exe), as Claude's desktop app asks), but
    the phones and the web open only full paths. Each such link to a file that exists becomes <D:/…/x.exe>; the rest
    of the text, code included, stays exactly as written (10-27: the phone showed 「链接未开放」)."""
    if not cwd or not os.path.isabs(cwd) or '](' not in text:return text
    found={}
    tokens=PARSER.parse(text)
    for block in tokens:
        for token in block.children or []:
            href=token.attrGet('href') if token.type=='link_open' else token.attrGet('src') if token.type=='image' else None
            if href and href not in found:found[href]=_resolve(href,cwd)
    if not any(found.values()):return text
    # Code blocks and code spans keep their text even when it reads like one of these links.
    lines=text.splitlines(keepends=True);starts=[0]
    for line in lines:starts.append(starts[-1]+len(line))
    masked=[(starts[b.map[0]],starts[min(b.map[1],len(lines))]) for b in tokens if b.type in ('fence','code_block') and b.map]
    masked+=[m.span() for m in _CODE_SPAN.finditer(text)]
    out=[];at=0
    for match in _DESTINATION.finditer(text):
        start,end=match.span(1)
        if any(a<=start<b for a,b in masked):continue
        raw=match.group(1);raw=raw[1:-1] if raw.startswith('<') else raw
        new=found.get(PARSER.normalizeLink(unescapeAll(raw)))
        if new:out+=[text[at:start],new];at=end
    return ''.join(out)+text[at:] if out else text
