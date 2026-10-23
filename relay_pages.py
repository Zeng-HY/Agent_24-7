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


def device_error_page(status):
    """Fixed recovery UI for document navigation; no device names, paths or credentials."""
    title = {403:'没有权限访问这台电脑',404:'电脑不存在或已移除'}.get(status,'电脑暂时无法连接')
    detail = '请返回我的电脑，选择你有权访问的设备。' if status in (403,404) else '电脑可能已经离线。请确认电脑端已启动，或返回选择其他电脑。'
    return ('<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">'
        '<meta name="theme-color" content="#ffffff"><title>Teleply</title>'
        '<script src="/account/theme.js?v=__TELEPLY_VERSION__"></script>'
        '<link rel="stylesheet" href="/account/theme.css?v=__TELEPLY_VERSION__"></head>'
        '<body><main class="connection-error"><h1>'+title+'</h1><p>'+detail+'</p>'
        '<a href="/account?choose=1">返回我的电脑</a><a href="">重试</a></main></body></html>').encode('utf-8')
