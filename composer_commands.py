"""What a phone offers after / in a conversation's box, and how a typed command runs (0.6.6, user 10-31).

Codex and DeepSeek run their commands themselves, so the words never reach the model: Codex compacts through its
desktop (codex_control.Bridge.compact), DeepSeek runs any command of its own list (deepseek_control commands/execute).
Claude reads slash commands from its own box, so for Claude they go as words. Only commands that do something the
phone can see are offered; the ones that open a desktop menu or download to the computer are not.
"""
import re

LINE = re.compile(r'/([A-Za-z][\w:.-]{0,63})(?:\s+([\s\S]*))?')
COMPACT = {'name': 'compact', 'title': '压缩上下文', 'detail': '把较早的对话压成摘要，腾出上下文'}
CODEX = (COMPACT,)
CLAUDE = (
    {**COMPACT, 'detail': '把较早的对话压成摘要，腾出上下文；后面可写要保留的重点', 'input': '要保留的重点'},
    {'name': 'init', 'title': '生成 CLAUDE.md', 'detail': '读一遍这个项目，写一份给 Claude 看的说明'},
    {'name': 'review', 'title': '审查改动', 'detail': '审查当前的代码改动'},
    {'name': 'security-review', 'title': '安全审查', 'detail': '检查当前改动里的安全问题'},
)
# DeepSeek's own list (commands/list) in the phone's words; its descriptions are English. export downloads a ZIP on the
# computer, so it is left out.
DEEPSEEK = {
    'compact': COMPACT,
    'goal': {'title': '长任务目标', 'detail': '设定、查看或暂停一个长任务的目标'},
    'plan': {'title': '计划模式', 'detail': '进入或离开计划模式'},
    'permission': {'title': '切换权限', 'detail': '换一个权限档位（沙盒和批准方式）'},
    'feedback': {'title': '反馈', 'detail': '给这个对话记一条反馈'},
}
DEEPSEEK_HIDDEN = {'export'}


def parse(text):
    """(name, the words after it) when the message is one slash command, as '/compact', '要点'; None otherwise."""
    match = LINE.fullmatch((text or '').strip())
    return ('/' + match[1], (match[2] or '').strip()) if match else None


def item(name, title='', detail='', input='', scope='内置命令'):
    return {'name': name, 'text': '/' + name, 'title': title, 'detail': detail, 'input': input, 'scope': scope}


def one_line(text, limit=120):
    text = ' '.join(str(text or '').split())
    return text if len(text) <= limit else text[:limit - 1] + '…'


def catalog(app, tid, references=None, deepseek=None):
    """The / list of one conversation: {'items': [...]} in the order the phone shows it."""
    if app == 'codex':
        return {'items': [item(**v) for v in CODEX]}
    if app == 'claude':
        rows = [item(**v) for v in CLAUDE]
        taken = {v['name'] for v in rows}
        if references is not None:  # its own commands and skills: Claude runs them as /name too
            for skill in references.skills('claude', tid):
                name = skill['name']
                if name in taken or not re.fullmatch(r'[A-Za-z][\w:.-]{0,63}', name):
                    continue
                taken.add(name)
                rows.append(item(name, detail=one_line(skill.get('description')), scope=skill.get('scope') or ''))
        return {'items': rows}
    if app == 'deepseek' and deepseek is not None:
        rows = []
        for command in deepseek.commands(tid):
            name = command['name']
            if name in DEEPSEEK_HIDDEN:
                continue
            words = DEEPSEEK.get(name, {})
            rows.append(item(name, words.get('title', ''), words.get('detail') or one_line(command.get('description')),
                             command.get('hint', '')))
        return {'items': rows}
    return {'items': []}
