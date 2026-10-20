import json,sys,tempfile,time,unittest
from pathlib import Path
from datetime import datetime,timezone
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import chats
from activity import TaskCenter
class StatusTests(unittest.TestCase):
 def test_long_running_turn_and_completion(self):
  with tempfile.TemporaryDirectory() as td:
   p=Path(td)/'log.jsonl';now=datetime.now(timezone.utc).isoformat()
   def event(payload):return json.dumps({'type':'event_msg','timestamp':now,'payload':payload})+'\n'
   p.write_text(event({'type':'task_started'})+event({'type':'item_completed','item':{'type':'AgentMessage','content':[{'text':'working'}],'phase':'commentary'}})+''.join(event({'type':'item_completed','item':{'type':'Reasoning','text':'x'*2000}}) for _ in range(220))+event({'type':'item_completed','item':{'type':'AgentMessage','content':[{'text':'still working'}],'phase':'commentary'}}),encoding='utf-8')
   with patch('chats.conv_path',return_value=p):
    self.assertEqual(chats.summary({'app':'codex'})['status'],'running')
    with p.open('a') as f:f.write(event({'type':'task_complete'}))
    self.assertEqual(chats.summary({'app':'codex'})['status'],'idle')
 def test_task_center_retains_evidence_and_prefers_fresh_desktop(self):
  t=TaskCenter(None);t.start=lambda:None;t.last_catalog=time.time();t.rows=[{'app':'codex','id':'s','status':'running','updated':1}]
  self.assertEqual(t.summary()['items'][0]['task_state'],'running')
  t.live['s']={'source':'desktop','observed_at':time.time()*1000,'running':False}
  self.assertEqual(t.apply_status([dict(t.rows[0])])[0]['status'],'idle')
  t.live['s']['observed_at']-=60000
  self.assertEqual(t.apply_status([dict(t.rows[0])])[0]['status'],'running')
if __name__=='__main__':unittest.main()
