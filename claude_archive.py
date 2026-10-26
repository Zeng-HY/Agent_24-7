from __future__ import annotations

import json
import re
import time
from pathlib import Path

import chats
import winctl


SESSION_ID = re.compile(r"local_[0-9a-fA-F-]{36}\Z")


def records():
    found = {}
    for base in chats.claude_index_dirs():
        for path in base.glob('*/*/local_*.json'):
            try:
                row = json.loads(path.read_text(encoding='utf-8'))
            except (OSError, ValueError) as exc:
                raise chats.ChatError('Claude 会话索引暂时读不了，请稍后刷新') from exc
            identity = row.get('sessionId')
            if identity != path.stem:
                raise chats.ChatError('Claude 会话索引编号不一致，未操作')
            previous = found.get(identity)
            if previous is not None and previous != row:
                raise chats.ChatError('Claude 存在同编号但内容不同的会话索引，未操作')
            found[identity] = row
    return found


def record(identity):
    if not isinstance(identity, str) or not SESSION_ID.fullmatch(identity):
        raise chats.ChatError('Claude 会话编号无效')
    found = None
    for base in chats.claude_index_dirs():
        for path in base.glob('*/*/' + identity + '.json'):
            try:
                row = json.loads(path.read_text(encoding='utf-8'))
            except (OSError, ValueError) as exc:
                raise chats.ChatError('Claude 目标会话索引暂时读不了，请稍后刷新') from exc
            if row.get('sessionId') != identity or (found is not None and found != row):
                raise chats.ChatError('Claude 目标会话索引存在冲突，未操作')
            found = row
    if found is None:
        raise chats.ChatError('找不到这个 Claude 会话，请刷新列表')
    return found


def item_from_record(row):
    cwd = row.get('cwd') or row.get('originCwd') or ''
    return {'app': 'claude', 'id': row['sessionId'], 'title': row.get('title') or '（无标题）',
            'cwd': cwd, 'origin': row.get('originCwd') or cwd, 'folder': Path(cwd).name,
            'cli': row.get('cliSessionId'), 'updated': row.get('lastActivityAt') or 0,
            'archived': bool(row.get('isArchived')), 'can_delete': False}


def archived():
    return sorted((item_from_record(row) for row in records().values() if row.get('isArchived')),
                  key=lambda item: -item['updated'])


def exact_result(controls, identity):
    matches = [control for control in controls
               if control.AutomationId == 'command-palette-item-' + identity]
    if len(matches) > 1:
        raise chats.ChatError('Claude 搜索结果编号不唯一，未操作')
    return matches[0] if matches else None


def activate_result(control):
    for getter, method in [('GetInvokePattern', 'Invoke'), ('GetLegacyIAccessiblePattern', 'DoDefaultAction')]:
        try:
            pattern = getattr(control, getter)()
        except Exception:
            continue
        if pattern is None:
            continue
        try:
            if getattr(pattern, method)() is False:
                raise RuntimeError('action refused')
            return
        except Exception as exc:
            raise chats.ChatError('Claude 搜索项打开结果未确认，未重复操作') from exc
    raise chats.ChatError('Claude 搜索项没有可用的打开操作，未操作')


class SessionActions:
    def __init__(self, controller):
        self.controller = controller
        self.desktop = controller.desktop
        self.pending = {}

    def _wait(self, read, reason, seconds=8):
        deadline = min(time.monotonic() + seconds, getattr(self, 'deadline', float('inf')))
        while True:
            value = read()
            if value:
                return value
            if time.monotonic() >= deadline:
                raise chats.ChatError(reason)
            time.sleep(.2)

    def _controls(self, scope, kind, name=None):
        return [control for control in self.desktop._find(scope, kind, name)
                if not control.IsOffscreen and control.IsEnabled]

    def _one(self, scope, kind, name):
        controls = self._controls(scope, kind, name)
        if len(controls) > 1:
            raise chats.ChatError('Claude 控件不唯一，未操作')
        return controls[0] if controls else None

    def _search(self, root):
        return self._one(root, 'WindowControl', 'Search')

    def _entry(self, root):
        """The button that opens the conversation search. Since Claude's dframe window (10-26) it is a row at the top of
        the sidebar's list, named Search with the shortcut Control+k, and scrolls away with the conversations below it:
        whenever the sidebar was scrolled down it was out of view, and archiving from the phone said there was nothing
        to search with. Invoke presses it out of view all the same. Every Search button with that shortcut opens the same
        search, the one in view first; without one (a Claude from before), the single Search button in view."""
        controls = [control for control in self.desktop._find(root, 'ButtonControl', 'Search') if control.IsEnabled]
        keyed = sorted((control for control in controls if (control.AcceleratorKey or '').lower() == 'control+k'),
                       key=lambda control: bool(control.IsOffscreen))
        if keyed:
            return keyed[0]
        shown = [control for control in controls if not control.IsOffscreen]
        if len(shown) > 1:
            raise chats.ChatError('Claude 控件不唯一，未操作')
        return shown[0] if shown else None

    def _input(self, root):
        dialog = self._search(root)
        if dialog is None:
            raise chats.ChatError('Claude 搜索窗口已改变，未操作')
        controls = [control for control in self._controls(dialog, 'ComboBoxControl')
                    if control.AutomationId == 'command-palette-input' and control.Name == 'Search']
        if len(controls) != 1:
            raise chats.ChatError('Claude 当前不是会话搜索模式，未输入或发送文字')
        return controls[0]

    def _query(self, root, text):
        control = self._input(root)
        control.GetValuePattern().SetValue(text)
        self._wait(lambda: self.desktop._value(self._input(root)) == text,
                   'Claude 搜索文字未确认，未操作')

    def _result(self, root, identity):
        dialog = self._search(root)
        if dialog is None:
            raise chats.ChatError('Claude 搜索窗口已关闭，未操作')
        return exact_result(self._controls(dialog, 'ListItemControl'), identity)

    def open_session(self, item, is_archived):
        desktop = self.desktop
        hwnd, root = desktop._claude_root()
        desktop._claude_show(hwnd)
        if self._search(root) is not None:
            raise chats.ChatError('电脑上的 Claude 搜索窗口正在使用，请先关闭它')
        if desktop._claude_document(root, item['id']) is not None:
            return hwnd, root
        search = self._entry(root)
        if search is None:
            raise chats.ChatError('Claude 没有可用的搜索入口，请在电脑上展开侧边栏')
        self.controller._invoke(search)
        dialog = self._wait(lambda: self._search(root), 'Claude 搜索窗口未打开')
        search_buttons = self._controls(dialog, 'ButtonControl', 'Search')
        if len(search_buttons) == 1:
            self.controller._invoke(search_buttons[0])
        self._input(root)
        if is_archived:
            self._query(root, '/archived')
            choice = self._wait(lambda: self._result(root, 'filter-hint:archived'),
                                'Claude 不支持已归档筛选，未操作')
            activate_result(choice)
            self._wait(lambda: self._one(self._search(root), 'GroupControl', 'Archived'),
                       'Claude 已归档筛选未生效，未操作')
        self._query(root, item['title'])
        self._wait(lambda: self._result(root, item['id']), 'Claude 搜索没有返回目标会话，未操作', 12)
        target = self._result(root, item['id'])
        if target is None:
            raise chats.ChatError('Claude 搜索结果已改变，未操作')
        activate_result(target)
        self._wait(lambda: desktop._claude_document(root, item['id']),
                   'Claude 尚未显示目标会话，未执行归档或恢复', 12)
        return hwnd, root

    def _action(self, item, desired):
        hwnd, root, document = self.controller._document(item)
        if not desired:
            return self._wait(lambda: self._one(document, 'ButtonControl', 'Unarchive'),
                              'Claude 没有显示恢复按钮，未操作')
        buttons = self._controls(root, 'ButtonControl')
        triggers = [button for button in buttons if button.Name == 'More options for ' + item['title']
                    and self._in_titlebar(button)]
        if len(triggers) != 1:
            raise chats.ChatError('找不到目标会话标题栏菜单，未归档')
        self.controller._expand(triggers[0], True)
        menu = self._wait(lambda: self._one(root, 'MenuControl', 'More options for ' + item['title']),
                          '目标会话菜单未打开，未归档')
        return self._wait(lambda: self._one(menu, 'MenuItemControl', 'Archive'),
                          '目标会话没有归档菜单，未操作')

    @staticmethod
    def _in_titlebar(control):
        for depth in range(6):
            control = control.GetParentControl()
            if control is None:
                return False
            if 'epitaxy-titlebar' in (control.ClassName or ''):
                return True
        return False

    def _guard(self, row, desired):
        if not desired:
            return
        if row.get('worktreePath') or row.get('worktreePaths'):
            raise chats.ChatError('这个 Claude 会话有工作副本，请在电脑上检查改动后归档')
        if row.get('isRunning') or chats.summary(item_from_record(row)).get('status') != 'idle':
            raise chats.ChatError('Claude 会话正在运行、等待处理或状态不明，未归档')

    def _guard_document(self, item, desired):
        hwnd, root, document = self.controller._document(item)
        if desired:
            if self._controls(document, 'ButtonControl', 'Stop') or self._controls(document, 'ButtonControl', 'Send now'):
                raise chats.ChatError('Claude 会话有正在运行或排队的消息，未归档')
            for prompt in self._controls(document, 'EditControl', 'Prompt'):
                if self.desktop._value(prompt).strip():
                    raise chats.ChatError('Claude 会话有未发送的草稿，未归档')

    def _apply(self, identity, desired):
        row = record(identity)
        if identity in self.pending:
            if bool(row.get('isArchived')) != self.pending[identity]:
                raise chats.ChatError('上次 Claude 操作结果尚未确认，未重复点击；请在电脑上核对状态')
            self.pending.pop(identity)
        if bool(row.get('isArchived')) == desired:
            return {'ok': True, 'app': 'claude', 'id': identity, 'archived': desired}
        chats.require_send_desktop()
        self._guard(row, desired)
        item = item_from_record(row)
        self.open_session(item, not desired)
        self._guard_document(item, desired)
        action = self._action(item, desired)
        fresh = record(identity)
        if fresh.get('cliSessionId') != row.get('cliSessionId'):
            raise chats.ChatError('Claude 会话记录已改变，未操作')
        if bool(fresh.get('isArchived')) == desired:
            return {'ok': True, 'app': 'claude', 'id': identity, 'archived': desired}
        self._guard(fresh, desired)
        self._guard_document(item, desired)
        chats.require_send_desktop()
        if time.monotonic() >= getattr(self, 'deadline', float('inf')):
            raise chats.ChatError('Claude 操作已超时，尚未点击归档或恢复')
        self.pending[identity] = desired
        try:
            self.controller._invoke(action)
        except chats.ChatError:
            pass
        self._wait(lambda: bool(record(identity).get('isArchived')) == desired,
                   'Claude 操作结果尚未确认；请刷新已归档列表核对，不要重复操作。若电脑出现清理确认框，请在那里处理', 10)
        self.pending.pop(identity, None)
        return {'ok': True, 'app': 'claude', 'id': identity, 'archived': desired}

    def change(self, identity, desired):
        record(identity)
        with self.controller.lock:
            deadline = time.monotonic() + 50
            def run():
                with self.desktop.input_lock:
                    if time.monotonic() >= deadline:
                        raise chats.ChatError('Claude 桌面任务排队超时，未操作')
                    self.deadline = deadline
                    try:
                        return self._apply(identity, desired)
                    finally:
                        del self.deadline
            future = self.desktop.pool.submit(run)
            try:
                return future.result(55)
            except TimeoutError:
                future.cancel()
                raise chats.ChatError('Claude 操作超时，结果尚未确认；请刷新列表或在电脑上核对') from None
            finally:
                self.controller.cache.pop(identity, None)
