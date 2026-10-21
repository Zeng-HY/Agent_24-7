import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import archives
import chats
import claude_archive


IDENTITY = 'local_11111111-1111-4111-8111-111111111111'
OTHER = 'local_22222222-2222-4222-8222-222222222222'


class IndexTests(unittest.TestCase):
    def test_archived_records_preserve_identity_and_never_offer_delete(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            target = base / 'account' / 'org'
            target.mkdir(parents=True)
            row = {'sessionId': IDENTITY, 'cliSessionId': 'transcript', 'isArchived': True,
                   'title': '同名测试', 'cwd': 'D:/test', 'lastActivityAt': 12}
            (target / (IDENTITY + '.json')).write_text(json.dumps(row), encoding='utf-8')
            with patch('chats.claude_index_dirs', return_value=[base, base]):
                self.assertEqual(claude_archive.record(IDENTITY), row)
                result = claude_archive.archived()
                self.assertEqual(len(result), 1)
                self.assertEqual(result[0]['id'], IDENTITY)
                self.assertEqual(result[0]['cli'], 'transcript')
                self.assertFalse(result[0]['can_delete'])
                with self.assertRaises(chats.ChatError):
                    claude_archive.record('../invalid')

    def test_same_titles_are_selected_by_full_id_and_duplicates_refused(self):
        first = SimpleNamespace(AutomationId='command-palette-item-' + OTHER, Name='同名测试')
        target = SimpleNamespace(AutomationId='command-palette-item-' + IDENTITY, Name='同名测试')
        self.assertIs(claude_archive.exact_result([first, target], IDENTITY), target)
        self.assertIsNone(claude_archive.exact_result([first], IDENTITY))
        with self.assertRaises(chats.ChatError):
            claude_archive.exact_result([target, target], IDENTITY)

    def test_search_activation_uses_default_action_not_selection(self):
        action = Mock()
        control = SimpleNamespace(GetInvokePattern=lambda: None,
                                  GetLegacyIAccessiblePattern=lambda: SimpleNamespace(DoDefaultAction=action),
                                  GetSelectionItemPattern=Mock(side_effect=AssertionError('selection is not opening')))
        claude_archive.activate_result(control)
        action.assert_called_once()
        control.GetSelectionItemPattern.assert_not_called()


class ActionTests(unittest.TestCase):
    def setUp(self):
        self.controller = Mock()
        self.actions = claude_archive.SessionActions(self.controller)
        self.row = {'sessionId': IDENTITY, 'cliSessionId': 'original', 'title': '测试', 'isArchived': False}
        self.actions.open_session = Mock()
        self.actions._action = Mock(return_value='button')
        self.actions._controls = Mock(return_value=[])
        self.controller._document.return_value = (1, 'root', 'document')
        patches = [patch('claude_archive.record', side_effect=lambda identity: dict(self.row)),
                   patch('chats.summary', return_value={'status': 'idle'}), patch('chats.require_send_desktop')]
        for fixture in patches:
            fixture.start()
            self.addCleanup(fixture.stop)

    def test_archive_restore_and_repeated_requests_only_click_once_each(self):
        self.controller._invoke.side_effect = lambda button: self.row.update(isArchived=not self.row['isArchived'])
        self.assertTrue(self.actions._apply(IDENTITY, True)['archived'])
        self.assertTrue(self.actions._apply(IDENTITY, True)['archived'])
        self.assertFalse(self.actions._apply(IDENTITY, False)['archived'])
        self.assertFalse(self.actions._apply(IDENTITY, False)['archived'])
        self.assertEqual(self.controller._invoke.call_count, 2)
        self.assertEqual(self.row['cliSessionId'], 'original')

    def test_unknown_result_blocks_same_and_opposite_requests(self):
        self.actions.pending[IDENTITY] = True
        for desired in [True, False]:
            with self.assertRaisesRegex(chats.ChatError, '尚未确认'):
                self.actions._apply(IDENTITY, desired)
        self.controller._invoke.assert_not_called()
        self.row['isArchived'] = True
        self.assertTrue(self.actions._apply(IDENTITY, True)['archived'])
        self.assertNotIn(IDENTITY, self.actions.pending)

    def test_lost_click_reply_is_reconciled_from_disk(self):
        def delivered(button):
            self.row['isArchived'] = True
            raise chats.ChatError('reply lost')
        self.controller._invoke.side_effect = delivered
        self.assertTrue(self.actions._apply(IDENTITY, True)['archived'])
        self.controller._invoke.assert_called_once()

    def test_running_unknown_and_worktree_are_refused_before_navigation(self):
        for status in ['running', 'waiting', 'unknown']:
            with patch('chats.summary', return_value={'status': status}), self.assertRaises(chats.ChatError):
                self.actions._apply(IDENTITY, True)
        self.row['worktreePath'] = 'D:/worktree'
        with self.assertRaises(chats.ChatError):
            self.actions._apply(IDENTITY, True)
        self.actions.open_session.assert_not_called()

    def test_replaced_transcript_and_changed_page_prevent_click(self):
        self.actions._action.side_effect = lambda *args: self.row.update(cliSessionId='replacement') or 'button'
        with self.assertRaisesRegex(chats.ChatError, '记录已改变'):
            self.actions._apply(IDENTITY, True)
        self.controller._invoke.assert_not_called()

    def test_wrong_page_prevents_mutation(self):
        self.controller._document.side_effect = chats.ChatError('wrong session')
        with self.assertRaises(chats.ChatError):
            self.actions._apply(IDENTITY, True)
        self.controller._invoke.assert_not_called()

    def test_unsent_draft_prevents_archive(self):
        self.actions._controls.side_effect = lambda scope, kind, name: ['draft'] if name == 'Prompt' else []
        self.controller.desktop._value.return_value = '未发送的测试文字'
        with self.assertRaisesRegex(chats.ChatError, '草稿'):
            self.actions._apply(IDENTITY, True)
        self.controller._invoke.assert_not_called()

    def test_deadline_prevents_late_click(self):
        self.actions.deadline = 0
        with self.assertRaisesRegex(chats.ChatError, '已超时'):
            self.actions._apply(IDENTITY, True)
        self.controller._invoke.assert_not_called()

    def test_timeout_keeps_uncertain_operation_for_reconciliation(self):
        self.actions._wait = Mock(side_effect=chats.ChatError('unknown'))
        with self.assertRaises(chats.ChatError):
            self.actions._apply(IDENTITY, True)
        self.assertTrue(self.actions.pending[IDENTITY])
        with self.assertRaises(chats.ChatError):
            self.actions._apply(IDENTITY, True)
        self.controller._invoke.assert_called_once()

    def test_compose_input_is_never_used_for_search(self):
        self.actions._search = Mock(return_value='dialog')
        self.actions._controls = Mock(return_value=[SimpleNamespace(AutomationId='command-palette-input', Name='Write a message…')])
        with self.assertRaisesRegex(chats.ChatError, '不是会话搜索'):
            self.actions._query('root', 'test')


class WiringTests(unittest.TestCase):
    def test_routes_reach_claude_and_invalidate_the_list(self):
        controller, history = Mock(), Mock()
        manager = archives.Archives(history=history, claude=controller, deepseek=Mock(), apps=lambda: ['claude'])
        manager.archive('claude', IDENTITY)
        controller.session_actions.change.assert_called_with(IDENTITY, True)
        manager.unarchive('claude', IDENTITY)
        controller.session_actions.change.assert_called_with(IDENTITY, False)
        self.assertEqual(history.invalidate.call_count, 2)
        with patch('claude_archive.archived', return_value=[{'id': IDENTITY, 'can_delete': False}]):
            result = manager.archived()
        self.assertEqual(result['apps'], ['claude'])
        self.assertEqual(result['deletable'], [])
        self.assertFalse(manager.delete([{'app': 'claude', 'id': IDENTITY}])['ok'])


class NavigationTests(unittest.TestCase):
    def setUp(self):
        self.controller = Mock()
        self.actions = claude_archive.SessionActions(self.controller)
        self.desktop = self.controller.desktop
        self.opened = None
        self.searching = False
        self.filtered = False
        self.query = ''
        self.invoked = []
        self.desktop._claude_root.return_value = (1, 'root')
        self.desktop._claude_document.side_effect = lambda root, identity: 'document' if self.opened == identity else None
        self.desktop._value.side_effect = lambda node: self.query
        self.desktop._find.side_effect = self.find
        self.controller._invoke.side_effect = self.invoke
        self.press = patch('claude_archive.winctl.press', side_effect=self.key).start()
        self.addCleanup(patch.stopall)

    def node(self, name, identity=''):
        node = SimpleNamespace(Name=name, AutomationId=identity, IsOffscreen=False, IsEnabled=True,
                               GetValuePattern=lambda: SimpleNamespace(SetValue=self.set_query))
        node.GetInvokePattern = lambda: SimpleNamespace(Invoke=lambda: self.invoke(node))
        return node

    def set_query(self, value):
        self.query = value

    def key(self, hwnd, command):
        self.assertEqual(command, 'Control+k')
        self.searching = True

    def find(self, scope, kind, name=None):
        result = []
        if kind == 'WindowControl' and self.searching:
            result = [self.node('Search')]
        elif kind == 'ButtonControl' and not self.searching:
            result = [self.node('Search', 'open-search')]
        elif self.searching and kind == 'ComboBoxControl':
            result = [self.node('Search', 'command-palette-input')]
        elif self.searching and kind == 'GroupControl' and self.filtered:
            result = [self.node('Archived')]
        elif self.searching and kind == 'ListItemControl':
            if self.query == '/archived':
                result = [self.node('Filter by Archived', 'command-palette-item-filter-hint:archived')]
            elif self.query == '同名测试':
                result = [self.node('同名测试', 'command-palette-item-' + OTHER),
                          self.node('同名测试', 'command-palette-item-' + IDENTITY)]
        return [node for node in result if name is None or node.Name == name]

    def invoke(self, node):
        if node.AutomationId == 'open-search':
            self.searching = True
            return
        self.invoked.append(node.AutomationId)
        if node.AutomationId == 'command-palette-item-filter-hint:archived':
            self.filtered = True
            self.query = ''
        else:
            self.opened = node.AutomationId.removeprefix('command-palette-item-')
            self.searching = False

    def test_search_opens_exact_id_despite_same_title_and_confirms_document(self):
        self.assertEqual(self.actions.open_session({'id': IDENTITY, 'title': '同名测试'}, False), (1, 'root'))
        self.assertEqual(self.invoked, ['command-palette-item-' + IDENTITY])
        self.assertEqual(self.opened, IDENTITY)

    def test_archived_search_applies_filter_before_selecting_id(self):
        self.actions.open_session({'id': IDENTITY, 'title': '同名测试'}, True)
        self.assertTrue(self.filtered)
        self.assertEqual(self.invoked, ['command-palette-item-filter-hint:archived', 'command-palette-item-' + IDENTITY])

    def test_current_target_needs_no_search(self):
        self.opened = IDENTITY
        self.actions.open_session({'id': IDENTITY, 'title': '同名测试'}, True)
        self.press.assert_not_called()

    def test_existing_search_is_not_overwritten(self):
        self.searching = True
        with self.assertRaisesRegex(chats.ChatError, '正在使用'):
            self.actions.open_session({'id': IDENTITY, 'title': '同名测试'}, True)
        self.press.assert_not_called()


if __name__ == '__main__':
    unittest.main()
