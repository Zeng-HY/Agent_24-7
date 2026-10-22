"""Small HTML responses only; files and SSE remain streaming."""
from pathlib import Path
import re


def scoped_page(body, device):
    if len(body)>2*1024*1024: raise ValueError('HTML page exceeds relay limit')
    if not re.fullmatch('[0-9a-f]{32}',device): raise ValueError('invalid device')
    text=body.decode('utf-8')
    base='/d/'+device
    # Existing static source attributes must be scoped before browser parsing.
    text=re.sub(r'((?:src|href|action)=["\'])/(?!/|account(?:/|["\']))',lambda m:m[1]+base+'/',text)
    script=Path(__file__).with_name('relay_routing.js').read_text(encoding='utf-8')
    return text.replace('<head>','<head><script>'+script+'</script>',1).encode('utf-8')
