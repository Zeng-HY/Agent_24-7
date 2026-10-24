"""Public activity metadata and source-record diffs. Never reads current files."""
from __future__ import annotations
import difflib
import hashlib
import json
import re
from datetime import datetime


def milliseconds(value):
    try:
        return int(datetime.fromisoformat(value.replace('Z', '+00:00')).timestamp() * 1000)
    except (ValueError, TypeError, AttributeError):
        return None


def change(path, patch, kind='modify', scope='file'):
    if not isinstance(path, str) or not isinstance(patch, str) or not patch or '\x00' in patch or len(patch) > 2_000_000:
        return None
    lines = patch.splitlines()
    # Only source-provided unified patches, not arbitrary tool output.
    if not any(line.startswith('@@') for line in lines):
        return None
    return {'path': path, 'kind': kind, 'scope': scope, '_patch': patch,
            'added': sum(s.startswith('+') and not s.startswith('+++') for s in lines),
            'removed': sum(s.startswith('-') and not s.startswith('---') for s in lines)}


def enrich(app, raw, messages, context):
    """Called once per complete source line, alongside the existing transcript parser."""
    try:
        record = json.loads(raw)
    except (ValueError, TypeError):
        return messages
    ts = record.get('timestamp') or ''
    if app == 'codex':
        p = record.get('payload') or {}
        kind = p.get('type')
        current = context.get('activity_turn')
        # Blocking question calls have source timestamps on both call and result.
        # Async notifications do not pause a turn, and reasoning payloads are ignored.
        if record.get('type') == 'response_item' and current:
            timing = context.get('activity_turns', {}).get(current, {})
            if kind == 'function_call' and str(p.get('name', '')).split('.')[-1] == 'request_user_input':
                context.setdefault('activity_waits', {})[p.get('call_id')] = current
                timing.setdefault('paused_at', milliseconds(ts))
            elif kind == 'function_call_output':
                waiting = context.setdefault('activity_waits', {}).pop(p.get('call_id'), None)
                if waiting:
                    clock = context['activity_turns'][waiting]
                    start = clock.pop('paused_at', None)
                    end = milliseconds(ts)
                    if start is not None and end is not None:
                        clock['paused_ms'] = clock.get('paused_ms', 0) + max(0, end-start)
                        clock.setdefault('pauses', []).append([start,end])
            return messages
        if kind == 'task_started':
            context['activity_turn'] = p.get('turn_id') or 'start:' + ts
            context.setdefault('activity_turns', {})[context['activity_turn']] = {
                'status': 'running', 'started_at': milliseconds(ts), 'pauses': []}
        turn = context.get('activity_turn')
        if kind in ('task_complete', 'turn_aborted') and turn:
            context['activity_turns'][turn].update(
                status='stopped' if kind == 'turn_aborted' else 'completed', ended_at=milliseconds(ts))
        item = p.get('item') or {}
        if kind == 'item_completed' and item.get('type') in ('FileChange', 'fileChange'):
            changes = []
            source_changes = item.get('changes') or []
            if isinstance(source_changes, dict):
                source_changes = [dict(value, path=path) for path, value in source_changes.items() if isinstance(value, dict)]
            for row in source_changes:
                if not isinstance(row, dict):
                    continue
                k = row.get('kind', 'modify')
                k = k.get('type', 'modify') if isinstance(k, dict) else row.get('type', k)
                patch = row.get('diff') or row.get('unified_diff')
                if k in ('add', 'delete') and isinstance(row.get('content'), str):
                    content = row['content'].splitlines()
                    patch = '\n'.join(difflib.unified_diff([] if k == 'add' else content, content if k == 'add' else [], fromfile='/dev/null' if k == 'add' else row['path'], tofile=row['path'] if k == 'add' else '/dev/null', lineterm=''))
                c = change(row.get('path'), patch, k)
                if c and isinstance(row.get('move_path'), str):
                    c.update(kind='rename',destination=row['move_path'])
                if c:
                    changes.append(c)
            succeeded = str(item.get('status', '')).lower() in ('completed', 'success', 'succeeded')
            messages.append({'role': 'tool', 'text': '修改文件', 'time': ts, 'source_id': item.get('id'),
                             'tool_status': 'completed' if succeeded else 'failed' if item.get('status') == 'failed' else 'unknown', '_changes': changes})
        if kind == 'item_completed' and item.get('type') == 'CommandExecution':
            for m in messages:
                if m['role'] == 'tool':
                    command = item.get('command')
                    m['detail'] = (command if isinstance(command, str) else json.dumps(command, ensure_ascii=False))[:16000]
                    m['result'] = str(item.get('aggregated_output') or '')[:16000]
                    m['tool_status'] = 'failed' if item.get('exit_code', item.get('exitCode', 0)) not in (0, None) else 'completed'
                    # ripgrep's documented exit 1 means no matches only for a
                    # single direct invocation without shell composition/output.
                    if item.get('exit_code',item.get('exitCode'))==1 and isinstance(command,str) and re.match(r'^\s*(?:rg|ripgrep)\s',command) and not re.search(r'[;&|<>\r\n`]',command) and not m['result'].strip():
                        m['tool_status']='no_matches';m['result']='搜索完成，没有匹配项'
    elif app == 'claude':
        blocks = (record.get('message') or {}).get('content')
        blocks = blocks if isinstance(blocks, list) else []
        pending = context.setdefault('activity_tools', {})
        for block in blocks:
            if not isinstance(block, dict):
                continue
            if block.get('type') == 'tool_use':
                args = block.get('input') or {}
                name = block.get('name', '')
                if name in ('Edit', 'Write', 'Read', 'Bash', 'Grep', 'Glob'):
                    # Find by the existing visible label; special question/plan cards stay separate.
                    m = next((m for m in messages if m['role'] == 'tool' and not m.get('source_id') and m['text'].startswith(name + '：')), None)
                    if m is None:
                        continue
                    m['source_id'] = block.get('id')
                    m['tool_status'] = 'running'
                    m['detail'] = str(args.get('command') or args.get('file_path') or args.get('pattern') or '')[:16000]
                    if name in ('Edit', 'Write') and isinstance(args.get('file_path'), str):
                        m['current_file'] = args['file_path']
                    m['activity_title'] = {'Edit':'修改文件','Write':'写入文件','Read':'读取文件','Bash':'运行命令','Grep':'搜索内容','Glob':'查找文件'}[name]
                    if name in ('Edit', 'Write', 'Read'):
                        m['activity_title'] += ' · ' + str(args.get('file_path') or '').replace('\\', '/').rsplit('/',1)[-1]
                    m['_changes'] = []
                    if name == 'Edit' and all(isinstance(args.get(k), str) for k in ('file_path', 'old_string', 'new_string')):
                        patch = '\n'.join(difflib.unified_diff(args['old_string'].splitlines(), args['new_string'].splitlines(), fromfile=args['file_path'], tofile=args['file_path'], lineterm=''))
                        c = change(args['file_path'], patch, scope='fragment')
                        if c:
                            m['_changes'].append(c)
                    if name == 'Write':
                        m['change_notice'] = '该记录没有保存修改前内容'
                    pending[block.get('id')] = m
            elif block.get('type') == 'tool_result':
                m = pending.get(block.get('tool_use_id'))
                if m:
                    m['tool_status'] = 'failed' if block.get('is_error') else 'completed'
                    if block.get('is_error'):
                        m['_changes'] = []
                    m['result'] = str(block.get('content') or '')[:16000]
        # Claude has no reliable source turn clock here. Group by explicit user records only.
        if any(m['role'] == 'user' for m in messages):
            context['activity_turn'] = 'user:' + str(record.get('uuid') or ts)
        turn = context.get('activity_turn')
    else:
        turn = None
    for m in messages:
        if turn:
            m['activity_turn'] = turn
        for i, c in enumerate(m.get('_changes', [])):
            c['ref'] = hashlib.sha256(json.dumps([app, m.get('source_id'), ts, i, c['path'], c['_patch']], ensure_ascii=False).encode()).hexdigest()
    return messages


def public_message(message):
    result = {k: v for k, v in message.items() if not k.startswith('_')}
    # A proposed edit is not a completed file modification.
    if message.get('tool_status') == 'completed':
        result['changes'] = [{k: v for k, v in c.items() if not k.startswith('_')} for c in message.get('_changes', [])]
    return result


def diff_page(messages, ref, offset=0):
    for message in messages:
        if message.get('tool_status') != 'completed':
            continue
        for c in message.get('_changes', []):
            if c['ref'] != ref:
                continue
            lines = c['_patch'].splitlines()
            starts = [i for i, line in enumerate(lines) if line.startswith('@@')]
            chunks = [lines[i:starts[n+1] if n+1 < len(starts) else len(lines)] for n, i in enumerate(starts)]
            offset = max(0, int(offset))
            return {**{k: v for k, v in c.items() if not k.startswith('_')},
                    'hunks': ['\n'.join(chunk) for chunk in chunks[offset:offset+8]],
                    'next': offset+8 if offset+8 < len(chunks) else None,
                    'message_id': message['id'], 'turn_id': message.get('activity_turn')}
    return None
