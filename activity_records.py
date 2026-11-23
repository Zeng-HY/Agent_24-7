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


def enrich(app, raw, messages, context, record=None):
    """Called once per complete source line, alongside the existing transcript parser.

    [record] is that line already parsed by the transcript parser, so a big file is not read twice (11-16).
    """
    if record is None:
        try:
            record = json.loads(raw)
        except (ValueError, TypeError):
            return messages
    ts = record.get('timestamp') or ''
    from agents import registry
    try:
        agent = registry.get(app)
    except Exception:
        agent = None
    turn = agent.enrich_activity(record, messages, context, ts) if agent is not None else None
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
