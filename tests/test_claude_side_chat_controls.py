"""11-17, the follow-up to the side-chat send fix: Claude's side chat shows a Stop of its own, its own queued messages
and (one day) its own model, task and next-step controls, all on the same page as the session's. The phone must read and
press only the session's own. The page structure is the one read from the window on 11-17
(`uia-side-chat-open.txt`): a control's parents reach either the dock (the session) or two layers named "Side chat"."""
import sys, unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import chats, claude_control

ASK = '要不要开始第 0 步实测？'


class Node:
    """A control in Claude's window as UI Automation gives it."""
    def __init__(self, name='', kind='GroupControl', cls='', children=(), enabled=True, offscreen=False):
        self.Name, self.ControlTypeName, self.ClassName = name, kind, cls
        self.IsEnabled, self.IsOffscreen = enabled, offscreen
        self.children = list(children); self.parent = None; self.pressed = 0
        for child in self.children: child.parent = self

    def GetParentControl(self): return self.parent

    def GetRuntimeId(self): return id(self)

    def GetInvokePattern(self):
        node = self

        class Invoke:
            def Invoke(self): node.pressed += 1; return True
        return Invoke()


DOCUMENT = Node(kind='DocumentControl', name='会话 - Claude Code')


def mount(top, side_chat=False):
    """The page around top: a composer, then either the session's dock or the side chat's two 'Side chat' layers."""
    top.parent = None
    composer = Node(cls='bg-surface-3 rounded-composer', children=[top])
    if side_chat:
        group = Node(name='Side chat', cls='flex h-full min-h-0 flex-col', children=[composer])
        Node(name='Side chat', cls='relative isolate flex min-h-0 min-w-0 flex-col', children=[group]).parent = DOCUMENT
    else:
        dock = Node(cls='group/approval-dock pointer-events-auto', children=[composer])
        Node(cls='relative isolate min-w-0 epitaxy-chat-panel', children=[dock]).parent = DOCUMENT
    return top


def button(name, side_chat=False, enabled=True, offscreen=False):
    return mount(Node(name, 'ButtonControl', cls='cds-reset group/btn', enabled=enabled, offscreen=offscreen), side_chat)


def queued_message(text, side_chat=False):
    """One queued message as Claude draws it: its text and a 'Send now' button inside a group named 'Message <n>'."""
    send_now = Node('Send now', 'ButtonControl')
    message = Node('Message 1', children=[Node(text, 'TextControl'), send_now])
    mount(message, side_chat)
    return send_now


def walk(node, maxDepth=30, depth=0):
    for child in node.children:
        yield child, depth + 1
        if depth + 1 < maxDepth: yield from walk(child, maxDepth, depth + 1)


class Desktop:
    """A Desktop that reads a fake page and judges place with the real chats.Desktop._claude_where."""
    auto = SimpleNamespace(WalkControl=staticmethod(walk))

    def __init__(self, buttons=(), found=None):
        self.buttons = list(buttons); self.found = dict(found or {}); self.walked = []

    def run(self, fn, *args, **kwargs): return fn(*args)

    def _find(self, scope, kind, name=None):
        if (kind, name) in self.found: return list(self.found[(kind, name)])
        if kind == 'ButtonControl' and name is None: return list(self.buttons)
        if kind == 'ButtonControl': return [b for b in self.buttons if b.Name == name]
        return []

    def _claude_where(self, ctrl):
        self.walked.append(ctrl)
        return chats.Desktop._claude_where(self, ctrl)  # the real walk up the fake page

    def _claude_unminimize(self): pass

    def _claude_show(self, hwnd): pass

    def _claude_ask(self, root, doc=None): return None

    def log(self, text): pass


class SideChatCase(unittest.TestCase):
    def controller(self, desktop):
        c = claude_control.Controller(desktop)
        c._document = lambda item, open_first=False: (1, Node(), 'doc')  # an empty window around the page
        return c

    def reading(self, buttons, summary='idle'):
        desktop = Desktop(buttons); c = self.controller(desktop)
        with patch('claude_control.settings', return_value={'model': 'claude-opus-5-5', 'effort': 'high', 'mode': 'auto', 'recorded_at': 1}), \
             patch('claude_control.chats.conv_path', return_value=None), \
             patch('claude_control.chats.summary', return_value={'status': summary}), \
             patch('claude_control.turn_anchor', return_value='turn'):
            return desktop, c, c._read_once({'id': 's', 'title': 't'})


class RunningTests(SideChatCase):
    def test_a_side_chat_that_runs_does_not_make_the_session_look_busy(self):
        # 11-17: the side chat's Stop was the only one on the page; the phone would offer 停止这一轮 for the session
        _, _, state = self.reading([button('Stop', side_chat=True)])
        self.assertIs(state['running'], False)
        self.assertNotIn('stop_token', state)

    def test_the_records_running_state_is_unchanged(self):
        _, _, state = self.reading([], summary='running')
        self.assertIs(state['running'], True)

    def test_two_stops_press_the_sessions_own(self):
        main, side = button('Stop'), button('Stop', side_chat=True)
        c = self.controller(Desktop([main, side]))
        c._read = mock.Mock(return_value={'running': True, 'stop_revision': 'turn'})
        token = c._ticket('s', 'stop', {'name': 'Stop'}, 'turn')
        with patch('claude_control.chats.find', return_value={'id': 's', 'title': 't'}), patch('claude_control.time.sleep'):
            c.choose('s', token)
        self.assertEqual((main.pressed, side.pressed), (1, 0))

    def test_a_stop_only_in_the_side_chat_is_not_pressed(self):
        # a ticket from when the session still ran; now only the side chat's Stop is there
        side = button('Stop', side_chat=True)
        c = self.controller(Desktop([side]))
        c._read = mock.Mock(return_value={'running': True, 'stop_revision': 'turn'})
        token = c._ticket('s', 'stop', {'name': 'Stop'}, 'turn')
        with patch('claude_control.chats.find', return_value={'id': 's', 'title': 't'}), patch('claude_control.time.sleep'):
            with self.assertRaises(chats.ChatError):
                c.choose('s', token)
        self.assertEqual(side.pressed, 0)

    def test_a_stop_whose_place_cannot_be_told_is_not_pressed(self):
        class Gone:
            Name, ControlTypeName, IsOffscreen, IsEnabled = 'Stop', 'ButtonControl', False, True
            def GetParentControl(self): raise chats.COMError(chats.ELEMENT_GONE, '事件无法调用任何订户', (None, None, None, 0, None))
        _, _, state = self.reading([Gone()])
        self.assertIs(state['running'], False)
        self.assertNotIn('stop_token', state)


class QueuedTests(SideChatCase):
    def test_a_side_chats_queued_message_is_not_the_sessions(self):
        main = queued_message('主对话排队的话')
        side = queued_message('侧边对话排队的话', side_chat=True)
        c = self.controller(Desktop())
        queue = c._queued('doc', [side, main])  # the side chat's drawn second, but given first here
        self.assertEqual([q['full_text'] for _, q in queue], ['主对话排队的话'])

    def test_a_queued_message_whose_place_cannot_be_told_is_not_the_sessions(self):
        class Gone:
            Name, ControlTypeName, IsOffscreen, IsEnabled = 'Send now', 'ButtonControl', False, True
            def GetParentControl(self): raise chats.COMError(chats.ELEMENT_GONE, '事件无法调用任何订户', (None, None, None, 0, None))
        c = self.controller(Desktop())
        self.assertEqual(c._queued('doc', [Gone()]), [])


class SettingTests(SideChatCase):
    def test_the_sessions_model_is_read_from_its_own_button(self):
        side, main = button('Model: Sonnet 5.5', side_chat=True), button('Model: Opus 5.5')
        _, _, state = self.reading([side, main])
        self.assertEqual((state['model_label'], state['available']), ('Opus 5.5', True))

    def test_the_sessions_mode_comes_from_its_own_button(self):
        side = button('Auto', side_chat=True)
        main = button('Manual')
        _, _, state = self.reading([side, main])
        self.assertEqual(state['mode_label'], 'Manual')

    def test_the_menus_trigger_is_the_sessions_own(self):
        main, side = button('Model: Opus 5.5'), button('Model: Sonnet 5.5', side_chat=True)
        c = self.controller(Desktop([main, side]))
        root = SimpleNamespace(MenuControl=lambda **kw: SimpleNamespace(Exists=lambda *a: False))
        c._document = lambda item, open_first=False: (1, root, 'doc')
        expanded = []; c._expand = lambda ctrl, opened: expanded.append(ctrl)
        with patch('claude_control.chats.find', return_value={'id': 's', 'title': 't'}), patch('claude_control.time.sleep'), \
             patch('claude_control.time.monotonic', side_effect=iter(range(10000)).__next__):
            with self.assertRaises(chats.ChatError) as refused:
                c._menu({'id': 's', 'title': 't'}, 'model')
        self.assertEqual(expanded, [main])
        self.assertIn('可读取的设置菜单', str(refused.exception))  # one trigger: it went on to open the menu

    def test_the_popups_trigger_is_the_sessions_own(self):
        main, side = button('Model: Opus 5.5'), button('Model: Sonnet 5.5', side_chat=True)
        c = self.controller(Desktop([main, side]))
        popup = SimpleNamespace(Name='Model: Opus 5.5', Exists=lambda *a: True, IsOffscreen=False)
        collapsed = []; c._expand = lambda ctrl, opened: collapsed.append((ctrl, opened))
        with patch('claude_control.chats.find', return_value={'id': 's', 'title': 't'}):
            c._dismiss_popup({'id': 's'}, page=(1, SimpleNamespace(MenuControl=lambda **kw: popup), 'doc'))
        self.assertEqual(collapsed, [(main, False)])


class TaskTests(SideChatCase):
    TITLE = '部署流程：先在测试环境跑通，再切到正式环境'

    def task_card(self, side_chat=False):
        head = Node(self.TITLE, 'ButtonControl', children=[Node(cls='', children=[Node(self.TITLE, 'TextControl')])])
        start, here, dismiss = (Node('Start', 'ButtonControl'), Node('Do it here', 'ButtonControl'),
                                Node('Dismiss suggestion ' + self.TITLE, 'ButtonControl'))
        mount(Node(children=[head, start, here, dismiss]), side_chat)
        return head, start, dismiss

    def test_a_side_chats_task_card_is_not_offered(self):
        main_head, main_start, main_dismiss = self.task_card()
        side_head, side_start, side_dismiss = self.task_card(side_chat=True)
        desktop = Desktop(found={('ButtonControl', self.TITLE): [main_head, side_head]})
        c = self.controller(desktop)
        self.assertEqual(c._waiting_tasks([side_dismiss, main_start, main_dismiss], c._own), [self.TITLE])
        self.assertEqual(c._task_buttons('doc', self.TITLE, 'Start'), [main_start])
        with patch('claude_control.chats.find', return_value={'id': 's', 'title': 't'}), patch('claude_control.time.sleep'):
            c.task_step('s', self.TITLE, 'start')
        self.assertEqual((main_start.pressed, side_start.pressed), (1, 0))

    def test_only_the_side_chat_has_the_card(self):
        _, start, _ = self.task_card(side_chat=True)
        desktop = Desktop(found={('ButtonControl', self.TITLE): []})
        c = self.controller(desktop)
        with patch('claude_control.chats.find', return_value={'id': 's', 'title': 't'}), patch('claude_control.time.sleep'), \
             patch('claude_control.time.monotonic', side_effect=[0, 9]):
            with self.assertRaises(chats.ChatError):
                c.task_step('s', self.TITLE, 'start')
        self.assertEqual(start.pressed, 0)


class NextStepTests(SideChatCase):
    def next_box(self, labels, ask=ASK, side_chat=False):
        actions = Node('Suggested next actions', children=[Node(label, 'ButtonControl') for label in labels])
        mount(Node(children=[Node(ask, 'TextControl'), actions]), side_chat)
        return actions

    def test_the_sessions_own_next_step_box_is_used(self):
        main, side = self.next_box(['主对话按钮']), self.next_box(['侧边对话按钮'], side_chat=True)
        desktop = Desktop(found={('GroupControl', 'Suggested next actions'): [main, side]})
        c = self.controller(desktop)
        found = c._next_box('doc', {'ask': ASK, 'actions': [{'label': '主对话按钮'}]})
        self.assertEqual((found[0], [b.Name for b in found[1]]), ('buttons', ['主对话按钮']))

    def test_a_box_in_the_side_chat_is_never_taken_for_the_sessions(self):
        # the session's own box asks something else; only the side chat's asks the record's question
        main = self.next_box(['主对话按钮'], ask='先把方案发我？')
        side = self.next_box(['侧边对话按钮'], side_chat=True)
        desktop = Desktop(found={('GroupControl', 'Suggested next actions'): [main, side]})
        c = self.controller(desktop)
        self.assertEqual(c._next_box('doc', {'ask': ASK, 'actions': [{'label': '主对话按钮'}]}), ('other', []))

    def test_only_the_side_chat_has_a_next_step_box(self):
        side = self.next_box(['侧边对话按钮'], side_chat=True)
        desktop = Desktop(found={('GroupControl', 'Suggested next actions'): [side]})
        c = self.controller(desktop)
        self.assertIsNone(c._next_box('doc', {'ask': ASK, 'actions': [{'label': '侧边对话按钮'}]}))

    def test_a_plain_list_in_the_side_chat_is_not_the_sessions(self):
        labels = ['开始第 0 步', '先改方案']
        items = [Node(label, 'ListItemControl', children=[Node('•', 'TextControl'), Node(label, 'TextControl')]) for label in labels]
        question = Node(ASK, 'TextControl')
        row = Node(children=[Node(children=[question]), Node('ListControl', children=items)])
        mount(row, side_chat=True)
        desktop = Desktop(found={('TextControl', ASK): [question]})
        c = self.controller(desktop)
        self.assertIsNone(c._next_box('doc', {'ask': ASK, 'actions': [{'label': '开始第 0 步'}, {'label': '先改方案'}]}))


class CandidateTests(SideChatCase):
    def test_only_candidates_are_walked_up(self):
        # a walk up costs 0.015-0.018 s and the phone reads this every 5 s: the page holds dozens of other buttons
        many = [button('Copy %d' % i) for i in range(50)]
        stop, model = button('Stop'), button('Model: Opus 5.5')
        side_dismiss = Node('Dismiss suggestion 任务', 'ButtonControl'); mount(side_dismiss, side_chat=True)
        send_now = queued_message('排队的话')
        desktop, _, state = self.reading(many + [stop, model, side_dismiss, send_now])
        self.assertEqual(state['model_label'], 'Opus 5.5')
        self.assertEqual([c.Name for c in desktop.walked], ['Stop', 'Model: Opus 5.5', 'Dismiss suggestion 任务', 'Send now'])


if __name__ == '__main__':
    unittest.main()
