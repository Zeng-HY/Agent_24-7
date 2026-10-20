import io,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch,Mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PIL import Image
from codex_control import Bridge,ControlError,selected_settings
from claude_control import Controller
import chats
class ParityTests(unittest.TestCase):
 def test_upload_owns_claude_and_rejects_unknown_app(self):
  with tempfile.TemporaryDirectory() as td,patch('codex_control.chats.find') as find:
   b=Bridge();b.data_root=Path(td);out=io.BytesIO();Image.new('RGB',(8,8),'blue').save(out,'PNG')
   meta=b.upload('claude-session','photo.png',out.getvalue(),'claude');find.assert_called_with('claude','claude-session')
   self.assertEqual(b.attachment(meta['id'],'claude-session')['app'],'claude')
   with self.assertRaises(ControlError):b.attachment(meta['id'],'other')
   with self.assertRaises(ControlError):b.upload('x','p.png',out.getvalue(),'bad')
 def test_speed_tier_validation_and_inheritance(self):
  state={'latestModel':'m','latestReasoningEffort':'high','latestThreadSettings':{'serviceTier':'priority'}}
  self.assertEqual(selected_settings(state)['service_tier'],'priority')
  with patch('codex_control.catalog',return_value={'models':[{'id':'m','efforts':['high'],'images':True,'service_tiers':[{'id':'priority'}]}]}):
   b=Bridge();self.assertEqual(b.validate_settings(None,state,False)['service_tier'],'priority')
   self.assertIsNone(b.validate_settings({'service_tier':None},state,False)['service_tier'])
   with self.assertRaises(ControlError):b.validate_settings({'service_tier':'invented'},state,False)
 def test_fast_and_standard_reach_transport_without_changing_effort(self):
  state={'latestModel':'m','latestReasoningEffort':'high','threadRuntimeStatus':{'type':'idle'}}
  models={'models':[{'id':'m','efforts':['high'],'images':True,'service_tiers':[{'id':'priority'}]}]}
  with tempfile.TemporaryDirectory() as td,patch('codex_control.catalog',return_value=models),patch('chats.require_send_desktop'):
   b=Bridge();b.data_root=Path(td);b.snapshot=Mock(return_value=({'id':'s'},'owner',state));pipe=Mock();pipe.call.return_value={'result':{'accepted':True}};b._pipe=lambda:pipe
   for i,tier in enumerate(['priority',None]):
    b.send({'id':'s','request_id':'speed-test-request-'+str(i),'text':'fixture','settings':{'service_tier':tier}})
    request=pipe.call.call_args.args[1]['turnStart']['request'];self.assertEqual(request['serviceTier'],tier);self.assertEqual(request['effort'],'high')
 def test_desktop_default_and_restored_draft_reach_transport(self):
  state={'latestModel':'m','latestReasoningEffort':'high','latestThreadSettings':{'serviceTier':'default'},'threadRuntimeStatus':{'type':'idle'}}
  models={'models':[{'id':'m','efforts':['high'],'images':True,'service_tiers':[{'id':'priority'}]}]}
  with tempfile.TemporaryDirectory() as td,patch('codex_control.catalog',return_value=models),patch('chats.require_send_desktop'):
   b=Bridge();b.data_root=Path(td);b.snapshot=Mock(return_value=({'id':'s'},'owner',state));pipe=Mock();pipe.call.return_value={'result':{'accepted':True}};b._pipe=lambda:pipe
   old={'model':'m','effort':'high','mode':'default','service_tier':'default'}
   for i,tier in enumerate(['default',None,'','fast','priority']):
    self.assertTrue(b.send({'id':'s','request_id':'default-regression-'+str(i),'text':'fixture','settings':{**old,'service_tier':tier},'expected_settings':old})['accepted'])
    request=pipe.call.call_args.args[1]['turnStart']['request'];self.assertEqual(request['serviceTier'],'priority' if tier in ('fast','priority') else None)
   self.assertIsNone(selected_settings(state)['service_tier'])
 def test_catalog_cache_never_reuses_mutation_ticket(self):
  c=Controller(Mock());c.catalogs={'s':{'model_id':'m','model':[{'name':'M'}],'updated_at':1}}
  with patch('claude_control.chats.find',return_value={'id':'s'}),patch('claude_control.settings',return_value={'model':'m'}):
   self.assertTrue(c.catalog('s')['cached']);c.desktop.run.assert_not_called()
 def test_stale_model_blocks_selection_before_native_action(self):
  c=Controller(Mock());c.menu=Mock()
  with patch('claude_control.chats.find',return_value={'id':'s'}),patch('claude_control.settings',return_value={'model':'new'}):
   with self.assertRaises(chats.ChatError):c.select_setting('s','effort','Effort',3,'old')
   c.menu.assert_not_called()
if __name__=='__main__':unittest.main()
