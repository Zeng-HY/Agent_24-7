import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from codex_control import Bridge, ControlError, catalog
from new_conversations import NewConversations


class CatalogTests(unittest.TestCase):
    def test_sol_high_from_cache_through_selection_and_send_validation(self):
        with tempfile.TemporaryDirectory() as root, patch('chats.CODEX_HOME', Path(root)):
            Path(root, 'models_cache.json').write_text(json.dumps({'models': [{
                'slug': 'gpt-6.1-sol', 'visibility': 'list',
                'supported_reasoning_levels': [{'effort': e} for e in ['low', 'high']],
                'default_reasoning_level': 'low', 'input_modalities': ['text', 'image']
            }]}), encoding='utf-8')
            service = object.__new__(NewConversations)
            chosen = service._settings('codex', {'model': 'gpt-6.1-sol', 'effort': 'high'})
            settings = service._picked({'mode': 'default', 'service_tier': None}, chosen)
            self.assertEqual(Bridge().validate_settings(settings, {}, True), settings)
            with self.assertRaisesRegex(ControlError, '不支持推理强度'):
                Bridge().validate_settings({**settings, 'effort': 'invented'}, {}, False)
            with self.assertRaisesRegex(ControlError, '目录中没有'):
                Bridge().validate_settings({**settings, 'model': 'invented'}, {}, False)
            Path(root, 'models_cache.json').write_text('{', encoding='utf-8')
            self.assertEqual(catalog()['models'], [])
            with self.assertRaisesRegex(ControlError, '暂时无法读取'):
                Bridge().validate_settings(settings, {}, False)
