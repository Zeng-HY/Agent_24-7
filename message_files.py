"""Only actual Markdown nodes authorize exact files; code examples authorize nothing."""
import re
from urllib.parse import unquote
from markdown_it import MarkdownIt

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
