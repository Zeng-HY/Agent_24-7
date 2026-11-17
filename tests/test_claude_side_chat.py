"""11-17: Claude's side chat (a column right of the session, in the same page, with its own Prompt box and Send button,
both named like the session's) must never be written into, pressed or shown on the phone. The session's own box is found
by the dock it sits in; the page's own name is never read, because a session may be titled "Side chat" too.
The structure built here is the one read from the window on 11-17 (`uia-side-chat-open.txt`)."""
import sys, threading, unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, call, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import chats

PAGE = 'Source First 工作流顶层设计优化 - Claude Code'
COMPOSER = ('', 'bg-surface-3 [--cmp-pad-x:0.5rem] relative z-[1] flex w-full min-w-0 flex-col text-primary rounded-composer')
DOCK = ('', 'group/approval-dock pointer-events-auto relative min-h-0 flex flex-col gap-2 [&>*]:shrink-0 [&_.epitaxy-approval-card]:shrink')
CHAT_PANEL = ('', 'relative isolate min-w-0 epitaxy-chat-panel')
SIDE_GROUP = ('Side chat', 'flex h-full min-h-0 flex-col')
SIDE_REGION = ('Side chat', 'relative isolate flex min-h-0 min-w-0 flex-col')


def prompt_box(value='\n'):
    edit = SimpleNamespace(Name='Prompt', ClassName='tiptap ProseMirror', ControlTypeName='EditControl',
                           IsOffscreen=False, IsEnabled=True, Value=value)
    edit.GetValuePattern = lambda: edit
    return edit


def stack(bottom, *layers, page=PAGE):
    """The control and the parents above it, lowest first, with the page (a DocumentControl) on top. The page's own name
    is deliberately the session title: no code may take it for a side chat's."""
    node = bottom
    for name, cls in layers:
        upper = SimpleNamespace(Name=name, ClassName=cls, ControlTypeName='GroupControl')
        node.GetParentControl = (lambda upper=upper: upper)
        node = upper
    document = SimpleNamespace(Name=page, ClassName='', ControlTypeName='DocumentControl', GetParentControl=lambda: None)
    node.GetParentControl = (lambda document=document: document)
    return bottom


def main_box(value='\n'):
    return stack(prompt_box(value), COMPOSER, DOCK, CHAT_PANEL)


def side_box(value='\n'):
    return stack(prompt_box(value), COMPOSER, SIDE_GROUP, SIDE_REGION)


def dock_of(box):
    node = box
    for _ in range(40):
        node = node.GetParentControl()
        if 'group/approval-dock' in (node.ClassName or '').split():
            return node
    return None


def sent_button(parent, invoke=None):
    invoke = invoke or Mock(return_value=True)
    pattern = SimpleNamespace(Invoke=invoke)
    button = SimpleNamespace(Name='Send', ClassName='cds-reset group/btn relative isolate inline-flex',
                             ControlTypeName='ButtonControl', IsOffscreen=False, IsEnabled=True,
                             GetParentControl=lambda: parent, GetInvokePattern=lambda: pattern)
    button.invoke = invoke
    return button


def side_send(value='\n', invoke=None):
    """The side chat's Send: inside its composer, above them both the "Side chat" group and region."""
    return sent_button(side_box(value).GetParentControl(), invoke)


def verified(boxes):
    d = object.__new__(chats.Desktop)
    d._claude_document = Mock(return_value='doc')
    d._find = Mock(return_value=list(boxes))
    return d


def sender(box, find):
    """A Desktop that sends without touching any window: the box and the page are the fakes given here."""
    d = object.__new__(chats.Desktop)
    d.input_lock = threading.Lock(); d.log = Mock(); d.sent_last = {}
    d._claude_open = Mock(return_value=(1, 'root')); d._claude_show = Mock(); d._claude_wait_prompt = Mock()
    d._claude_verified_prompt = Mock(return_value=('doc', box)); d._fill_claude_prompt = Mock(return_value=('doc', box))
    d._value = lambda ctrl: 'hello'
    d._find = find if callable(find) else Mock(return_value=list(find))
    return d


class MessageBoxTests(unittest.TestCase):
    def test_with_a_side_chat_open_the_sessions_own_box_is_the_one(self):
        # 11-17 07:26: two boxes named Prompt, the session's and the side chat's; the phone's message was refused
        main, side = main_box(), side_box()
        d = verified([main, side])
        self.assertEqual(d._claude_verified_prompt('root', 's'), ('doc', main))
        d._find.assert_called_once_with('doc', 'EditControl', 'Prompt')

    def test_with_only_the_side_chats_box_nothing_is_sent(self):
        # the session's box can be taken by a question card, leaving the side chat's box alone on the page
        d = verified([side_box()])
        with self.assertRaises(chats.InputNotSubmitted) as refused:
            d._claude_verified_prompt('root', 's')
        self.assertEqual(str(refused.exception), 'Claude 输入框不唯一或尚未就绪，尚未发送')

    def test_two_boxes_of_the_session_are_still_not_told_apart(self):
        # e.g. a later split view: both in docks, neither in a side chat
        d = verified([main_box(), main_box()])
        with self.assertRaises(chats.InputNotSubmitted):
            d._claude_verified_prompt('root', 's')

    def test_a_side_chat_box_that_also_has_a_dock_is_not_the_sessions(self):
        inside = stack(prompt_box(), COMPOSER, DOCK, SIDE_GROUP, SIDE_REGION)
        main = main_box()
        self.assertEqual(verified([inside, main])._claude_verified_prompt('root', 's'), ('doc', main))
        with self.assertRaises(chats.InputNotSubmitted):
            verified([inside])._claude_verified_prompt('root', 's')

    def test_a_box_whose_parents_cannot_be_read_is_not_used(self):
        broken = prompt_box()
        broken.GetParentControl = lambda: (_ for _ in ()).throw(chats.COMError(chats.ELEMENT_GONE, '事件无法调用任何订户', (None, None, None, 0, None)))
        main = main_box()
        self.assertEqual(verified([broken, main])._claude_verified_prompt('root', 's'), ('doc', main))
        with self.assertRaises(chats.InputNotSubmitted):
            verified([broken])._claude_verified_prompt('root', 's')

    def test_a_session_titled_side_chat_uses_its_own_box(self):
        # the page is named "<title> - Claude Code": the title alone means nothing
        main = stack(prompt_box(), COMPOSER, DOCK, CHAT_PANEL, page='Side chat - Claude Code')
        self.assertEqual(verified([main])._claude_verified_prompt('root', 's'), ('doc', main))

    def test_a_new_page_needs_no_dock_and_no_side_chat_counts(self):
        new = stack(prompt_box(), COMPOSER, CHAT_PANEL)  # the new page's layout was not measured with a dock
        main = main_box()
        self.assertEqual(verified([new])._claude_verified_prompt('root', '__new__'), ('doc', new))
        self.assertEqual(verified([side_box(), new])._claude_verified_prompt('root', '__new__'), ('doc', new))
        with self.assertRaises(chats.InputNotSubmitted):
            verified([side_box()])._claude_verified_prompt('root', '__new__')

    def test_a_refusal_counts_the_boxes_in_the_log_only(self):
        # the phone's words stay as they were; the log says what was on the page (11-17: "两个框" was all it said)
        unclear = prompt_box()
        outside = stack(prompt_box(), COMPOSER)  # no dock: an existing session's box never sits there
        d = verified([side_box(), outside, stack(prompt_box(), COMPOSER, CHAT_PANEL), unclear])
        with self.assertRaises(chats.InputNotSubmitted) as refused:
            d._claude_verified_prompt('root', 's')
        self.assertEqual(str(refused.exception), 'Claude 输入框不唯一或尚未就绪，尚未发送')
        detail = refused.exception.detail
        self.assertIn('4 个', detail)
        for words in ('1 个在侧边对话里', '2 个不在主对话的输入区里', '1 个说不清'):
            self.assertIn(words, detail)
        d.log = Mock(); d._send_claude = Mock(side_effect=refused.exception); d._keyboard_owner = Mock(return_value=None)
        with patch('chats.find', return_value={'id': 's', 'title': 't'}), patch('chats.conv_path', return_value=None), \
             patch('chats.file_size', return_value=0), patch('chats.require_send_desktop'):
            with self.assertRaises(chats.InputNotSubmitted):
                d.send('claude', 's', 'hello')
        self.assertIn(detail, d.log.call_args.args[0])


class SendButtonTests(unittest.TestCase):
    def test_both_sends_available_the_docks_is_pressed(self):
        box = main_box('hello'); dock = dock_of(box); main = sent_button(dock); side = side_send('hello')
        d = sender(box, [main, side])
        with patch('chats.require_send_desktop'), patch('chats.conversation_title', return_value='t'):
            d._send_claude_now({'id': 's', 'title': 't'}, 'hello')
        self.assertEqual(main.invoke.call_count, 1)
        self.assertEqual(side.invoke.call_count, 0)

    def test_with_no_send_in_the_dock_the_side_chats_is_not_pressed(self):
        # the session's Send is not lit yet, the side chat has a draft: the side chat's Send is the only one lit
        box = main_box('hello'); dock = dock_of(box); side = side_send('draft')
        d = sender(box, lambda scope, kind, name=None: [] if scope is dock else [side])
        with patch('chats.require_send_desktop'), patch('chats.conversation_title', return_value='t'):
            with self.assertRaises(chats.InputNotSubmitted) as refused:
                d._send_claude_now({'id': 's', 'title': 't'}, 'hello')
        self.assertEqual(str(refused.exception), '没有唯一可用的 Claude 发送按钮，尚未发送')
        self.assertEqual(side.invoke.call_count, 0)

    def test_a_new_pages_send_is_the_pages_own_not_a_side_chats(self):
        new = stack(prompt_box('hello'), COMPOSER, CHAT_PANEL)
        main = sent_button(new.GetParentControl()); side = side_send('draft')
        d = sender(new, [main, side])
        self.assertIs(d._claude_send_button('doc', new, '__new__'), main)

    def test_a_new_page_with_only_a_side_chats_send_is_not_sent(self):
        new = stack(prompt_box('hello'), COMPOSER, CHAT_PANEL)
        d = sender(new, [side_send('draft')])
        with self.assertRaises(chats.InputNotSubmitted) as refused:
            d._claude_send_button('doc', new, '__new__')
        self.assertEqual(str(refused.exception), 'Claude 新对话发送按钮尚未就绪')


class DockAndQuestionTests(unittest.TestCase):
    def test_the_dock_comes_from_the_sessions_box_even_when_the_side_chats_comes_first(self):
        main, side = main_box(), side_box()
        d = object.__new__(chats.Desktop); d._find = Mock(return_value=[side, main])
        root = SimpleNamespace(GroupControl=Mock(side_effect=AssertionError('the window must not be searched')))
        self.assertIs(d._claude_dock(root), dock_of(main))
        d._find.assert_called_once_with(root, 'EditControl', 'Prompt')

    def test_the_fallback_for_a_taken_box_skips_a_side_chats_dock(self):
        main, side = main_box(), side_box()
        side_dock = stack(SimpleNamespace(Name='', ClassName=DOCK[1], ControlTypeName='GroupControl'), SIDE_GROUP, SIDE_REGION)
        variant = SimpleNamespace(Name='', ClassName='[&_.epitaxy-approval-card]:h-[var(--approval-dock-floor,168px)]',
                                  ControlTypeName='GroupControl')
        stack(variant, CHAT_PANEL)
        d = object.__new__(chats.Desktop); d._find = Mock(return_value=[])
        d._find_class = Mock(return_value=[variant, side_dock, dock_of(main)])
        root = SimpleNamespace(GroupControl=Mock(side_effect=AssertionError('the window must not be searched')))
        self.assertIs(d._claude_dock(root), dock_of(main))
        d._find_class = Mock(return_value=[variant, side_dock])
        self.assertIsNone(d._claude_dock(root))

    def test_a_question_in_the_side_chat_is_not_the_sessions_question(self):
        def card(name, *layers):
            return stack(SimpleNamespace(name=name, ClassName='epitaxy-approval-card relative isolate flex flex-col'), *layers)
        older = card('older', CHAT_PANEL)
        newer = card('newer', COMPOSER, SIDE_GROUP, SIDE_REGION)
        d = object.__new__(chats.Desktop); d._claude_dock = Mock(return_value='dock')
        d._find = Mock(return_value=[SimpleNamespace(IsEnabled=True)])
        d._find_class = Mock(return_value=[older, newer])
        self.assertIs(d._claude_ask('root', 'doc'), older)
        d._find_class = Mock(return_value=[newer])
        self.assertEqual(d._claude_ask('root', 'doc'), 'dock')


class ImageTests(unittest.TestCase):
    def test_pasting_an_image_focuses_the_sessions_own_box(self):
        main, side = main_box(), side_box()
        focused = []
        main.SetFocus = lambda: (focused.append('main'), setattr(main, 'HasKeyboardFocus', True))
        side.SetFocus = lambda: focused.append('side')
        main.HasKeyboardFocus = False
        d = verified([main, side]); d._claude_image_count = Mock(return_value=1)
        clipboard = SimpleNamespace(EnumClipboardFormats=lambda fmt: 0, EmptyClipboard=lambda: None,
                                    SetClipboardData=lambda fmt, data: None, GetClipboardSequenceNumber=lambda: 1,
                                    CloseClipboard=lambda: None, GetClipboardData=lambda fmt: b'')
        with patch.dict(sys.modules, {'win32clipboard': clipboard,
                                      'PIL': SimpleNamespace(Image=SimpleNamespace(open=lambda path: FakeImage()))}), \
             patch('chats._clip_open'), patch('chats.winctl.focus') as focus, patch('chats.winctl.press') as press:
            d._paste_claude_image(7, 'root', {'id': 's'}, main, 'one.png', 1)
        self.assertEqual(focused, ['main'])
        focus.assert_called_once_with(7)
        self.assertEqual(press.call_args_list, [call(7, 'Control+v')])


class FakeImage:
    def __enter__(self): return self
    def __exit__(self, *args): return False
    def convert(self, mode): return self
    def save(self, buffer, format): buffer.write(b'\0' * 30)


if __name__ == '__main__':
    unittest.main()
