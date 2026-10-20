import json,sys,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import machines,remote

STATUS={'Self':{'DNSName':'home-pc.tail1.ts.net.','OS':'windows','Online':True,'UserID':1},
        'User':{'1':{'ID':1,'LoginName':'me@example.com'},'2':{'ID':2,'LoginName':'friend@example.com'}},
        'Peer':{'a':{'DNSName':'work-pc.tail1.ts.net.','OS':'windows','Online':True,'UserID':1},
                'b':{'DNSName':'iphone.tail1.ts.net.','OS':'iOS','Online':True,'UserID':1},
                'c':{'DNSName':'old-pc.tail1.ts.net.','OS':'windows','Online':False,'UserID':1},
                'd':{'DNSName':'other-pc.tail1.ts.net.','OS':'windows','Online':True,'UserID':1},
                'e':{'DNSName':'friends-pc.tail1.ts.net.','OS':'windows','Online':True,'UserID':2}}}  # shared in by another account

class ComputersTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.memory=Path(self.temp.name)/'computers.json';self.asked=[]
    def tearDown(self):self.temp.cleanup()
    def probe(self,url):
        self.asked.append(url)
        return {'app':'agent_remote','name':'公司电脑'} if url=='https://work-pc.tail1.ts.net/' else None
    def test_only_online_windows_computers_are_asked_and_only_ours_listed(self):
        found=machines.Computers('家里电脑',self.memory,status=lambda:STATUS,probe=self.probe).listing()
        # other-pc does not answer on 443, so it is asked on 8443 too
        self.assertEqual(sorted(self.asked),['https://other-pc.tail1.ts.net/','https://other-pc.tail1.ts.net:8443/','https://work-pc.tail1.ts.net/'])
        self.assertEqual(found,{'self':{'name':'家里电脑','url':'https://home-pc.tail1.ts.net/'},
                                'others':[{'name':'公司电脑','url':'https://work-pc.tail1.ts.net/','reachable':True}]})
    def test_only_devices_of_this_computers_own_account_are_asked(self):
        machines.Computers('家里电脑',self.memory,status=lambda:STATUS,probe=self.probe).listing()
        self.assertEqual([url for url in self.asked if 'friends-pc' in url],[])
        nobody={**STATUS,'Self':{k:v for k,v in STATUS['Self'].items() if k!='UserID'}}  # this computer's account unknown: nobody
        self.asked.clear();machines.Computers('家里电脑',self.memory,status=lambda:nobody,probe=self.probe).look();self.assertEqual(self.asked,[])
    def test_a_computer_whose_page_is_on_8443_is_found_there(self):
        probe=lambda url:{'app':'agent_remote','name':'公司电脑'} if url=='https://work-pc.tail1.ts.net:8443/' else None
        found=machines.Computers('家里电脑',self.memory,status=lambda:STATUS,probe=probe).listing()
        self.assertEqual(found['others'],[{'name':'公司电脑','url':'https://work-pc.tail1.ts.net:8443/','reachable':True}])
    def test_a_computer_seen_before_stays_listed_when_switched_off(self):
        machines.Computers('家里电脑',self.memory,status=lambda:STATUS,probe=self.probe).listing()
        off={**STATUS,'Peer':{'a':{**STATUS['Peer']['a'],'Online':False}}}
        found=machines.Computers('家里电脑',self.memory,status=lambda:off,probe=self.probe).listing()
        self.assertEqual(found['others'],[{'name':'公司电脑','url':'https://work-pc.tail1.ts.net/','reachable':False}])
    def test_the_last_look_comes_at_once_and_a_new_one_starts_after_a_minute(self):
        clock=[0.0];later=[]
        computers=machines.Computers('家里电脑',self.memory,status=lambda:STATUS,probe=self.probe,clock=lambda:clock[0],spawn=later.append)
        first=computers.listing();clock[0]=30;computers.listing();self.assertEqual((len(self.asked),later),(3,[]))
        clock[0]=61;self.assertIs(computers.listing(),first);self.assertEqual(len(later),1)  # answered at once, a look started
        computers.listing();self.assertEqual(len(later),1)  # not a second one while it runs
        later[0]();self.assertEqual(len(self.asked),6);self.assertFalse(computers.looking)
    def test_without_tailscale_only_this_computer(self):
        found=machines.Computers('家里电脑',self.memory,status=lambda:{},probe=self.probe).listing()
        self.assertEqual(found,{'self':{'name':'家里电脑','url':''},'others':[]})

class OwnerTests(unittest.TestCase):
    def test_this_computers_account_comes_from_tailscale(self):
        self.assertEqual(machines.owner_login(STATUS),'me@example.com');self.assertEqual(machines.owner_login({}),'')
    def test_read_again_soon_while_unknown_then_kept_five_minutes(self):
        clock=[0.0];answers=[{},STATUS,STATUS]
        owner=machines.Owner(status=lambda:answers.pop(0),clock=lambda:clock[0])
        self.assertEqual(owner.login(),'');clock[0]=10;self.assertEqual(owner.login(),'');self.assertEqual(len(answers),2)  # Tailscale starting
        clock[0]=15;self.assertEqual(owner.login(),'me@example.com')
        clock[0]=314;owner.login();self.assertEqual(len(answers),1)  # kept
        clock[0]=315;owner.login();self.assertEqual(answers,[])

class AppsTests(unittest.TestCase):
    def test_desktop_apps_found_by_their_folders(self):
        with tempfile.TemporaryDirectory() as temp:
            local,roaming=Path(temp)/'Local',Path(temp)/'Roaming';(local/'Packages'/'OpenAI.Codex_2p2nqsd0c76g0').mkdir(parents=True);roaming.mkdir()
            with patch.object(machines,'LOCALAPPDATA',local),patch.object(machines,'APPDATA',roaming),patch.object(machines.Path,'home',return_value=Path(temp)):
                self.assertEqual(machines.installed_apps(),['codex'])
                (local/'Packages'/'Claude_pzs8sxrjxfjjc').mkdir()
                self.assertEqual(machines.installed_apps(),['codex','claude'])
                (Path(temp)/'.dsh').mkdir()
                self.assertEqual(machines.installed_apps(),['codex','claude','deepseek'])

class PageTests(unittest.TestCase):
    MACHINE={'name':'公司电脑','apps':['codex'],'voice':False}
    def handler(self,path,headers=None):
        handler=object.__new__(remote.Handler);sent=[]
        handler.path=path;handler.headers=headers or {};handler.close_connection=False
        handler.server=SimpleNamespace(machine=self.MACHINE,cfg={'token':'secret'})
        handler._send=lambda code,body,ctype,extra=None:sent.append((code,body))
        return handler,sent
    def test_facts_from_the_config(self):
        self.assertEqual(remote.machine_facts({'name':'公司电脑','voice':False,'apps':['codex']}),self.MACHINE)
        with patch.object(remote.machines,'installed_apps',return_value=['codex','claude']),patch.object(remote.socket,'gethostname',return_value='DESKTOP-1'):
            self.assertEqual(remote.machine_facts({}),{'name':'DESKTOP-1','apps':['codex','claude'],'voice':True})
    def test_hello_tells_only_the_name_and_wants_what_the_page_wants(self):
        handler,sent=self.handler('/api/hello?t=secret');handler.do_GET()
        self.assertEqual(sent[0][0],200);self.assertEqual(json.loads(sent[0][1]),{'app':'agent_remote','name':'公司电脑','version':remote.VERSION})
        handler,sent=self.handler('/api/hello');handler.do_GET()
        self.assertEqual(sent[0][0],403)
    def test_the_page_knows_which_computer_it_is_on(self):
        handler,sent=self.handler('/?t=secret');handler.do_GET()
        page=sent[0][1].decode('utf-8')
        self.assertIn('<script>window.MACHINE={"name": "公司电脑", "apps": ["codex"], "voice": false, "version": "'+remote.VERSION+'"};</script>',page)
        self.assertNotIn('<!--machine-->',page)
    def test_without_the_token_the_page_says_how_to_get_it(self):
        handler,sent=self.handler('/');handler.do_GET()
        self.assertEqual(sent[0][0],403);self.assertIn('手机链接.cmd',sent[0][1].decode('utf-8'))
    def test_the_sidebar_has_no_claude_group_without_claude(self):
        handler,sent=self.handler('/api/chat/projects?t=secret');handler.server.history=SimpleNamespace(catalog=lambda:[],ungrouped=lambda:[])
        tree={'apps':[{'app':'codex','name':'Codex','projects':[]},{'app':'claude','name':'Claude','projects':[]}],'now':1}
        with patch.object(remote.chat_projects,'tree',return_value=tree):handler.do_GET()
        self.assertEqual([a['app'] for a in json.loads(sent[0][1])['apps']],['codex'])
    def test_no_voice_on_a_computer_without_it(self):
        handler,sent=self.handler('/api/voice/status?t=secret');handler.do_GET()
        self.assertEqual(sent[0][0],404)
        handler,sent=self.handler('/api/voice?t=secret');handler.do_POST()
        self.assertEqual(sent[0][0],404);self.assertTrue(handler.close_connection)

class AccessTests(unittest.TestCase):
    """Who gets in (10-20): through tailscale serve the account in Tailscale-User-Login decides; without it, the token."""
    MACHINE={'name':'家里电脑','apps':['codex'],'voice':False}
    def ask(self,path,login=None,bind='127.0.0.1',allowed=None,owner='me@example.com',method='GET'):
        handler=object.__new__(remote.Handler);sent=[]
        handler.path=path;handler.headers={'Tailscale-User-Login':login} if login else {};handler.close_connection=False
        handler.server=SimpleNamespace(machine=self.MACHINE,owner=SimpleNamespace(login=lambda:owner),
                                       cfg={'token':'secret','bind':bind,'allowed_logins':allowed or []})
        handler._send=lambda code,body,ctype,extra=None:sent.append((code,body.decode('utf-8'),extra or {}))
        handler.do_POST() if method=='POST' else handler.do_GET()
        return sent[0]
    def test_this_computers_own_account_gets_in_without_the_token(self):
        self.assertEqual(self.ask('/',login='me@example.com')[0],200)
        self.assertEqual(self.ask('/api/hello',login='Me@Example.com')[0],200)  # however Tailscale writes the case
    def test_another_account_is_refused_even_with_the_token(self):
        code,text,_=self.ask('/?t=secret',login='friend@example.com')
        self.assertEqual(code,403);self.assertIn('friend@example.com',text);self.assertIn('allowed_logins',text)
        self.assertNotIn('me@example.com',text)  # the page does not tell whose computer it is
        code,text,_=self.ask('/api/status?t=secret',login='friend@example.com');self.assertEqual(code,403);self.assertIn('friend@example.com',text)
        self.assertEqual(self.ask('/api/voice?t=secret',login='friend@example.com',method='POST')[0],403)
    def test_an_account_in_allowed_logins_gets_in(self):
        self.assertEqual(self.ask('/',login='friend@example.com',allowed=['Friend@example.com'])[0],200)
        self.assertEqual(remote.allowed_logins({'allowed_logins':' friend@example.com '}),['friend@example.com'])
        self.assertEqual(remote.allowed_logins({'allowed_logins':['a@x',3,'']}),['a@x'])
    def test_without_the_header_the_token_is_needed(self):
        self.assertEqual(self.ask('/')[0],403);self.assertEqual(self.ask('/?t=secret')[0],200)
        self.assertEqual(self.ask('/api/hello')[0],403);self.assertEqual(self.ask('/api/hello?t=wrong')[0],403)
        self.assertEqual(self.ask('/api/hello?t=secret')[0],200)
    def test_hello_is_checked_like_the_page(self):
        self.assertEqual(self.ask('/api/hello',login='me@example.com')[0],200)
        self.assertEqual(self.ask('/api/hello',login='friend@example.com')[0],403)
        self.assertEqual(self.ask('/api/hello',login='friend@example.com',allowed=['friend@example.com'])[0],200)
    def test_listening_beyond_this_computer_the_header_counts_for_nothing(self):
        for bind in ('0.0.0.0','192.168.1.5','::'):
            self.assertEqual(self.ask('/',login='me@example.com',bind=bind)[0],403)
            self.assertEqual(self.ask('/api/hello',login='me@example.com',bind=bind)[0],403)
            self.assertEqual(self.ask('/?t=secret',login='friend@example.com',bind=bind)[0],200)
        self.assertEqual(self.ask('/',login='me@example.com',bind='localhost')[0],200)
    def test_a_login_tailscale_wrote_as_an_rfc2047_word_is_read(self):
        self.assertEqual(remote.header_login('=?utf-8?q?=E6=9B=BE@example.com?='),'曾@example.com')
        self.assertEqual(remote.header_login('me@example.com'),'me@example.com')
        self.assertEqual(self.ask('/',login='=?utf-8?q?=E6=9B=BE@example.com?=',owner='曾@example.com')[0],200)
    def test_the_cookie_comes_only_from_the_token_itself(self):
        self.assertNotIn('Set-Cookie',self.ask('/?t=wrong',login='me@example.com')[2])  # let in by account: no token handed out
        self.assertIn('lbr=secret',self.ask('/?t=secret')[2]['Set-Cookie'])
    def test_the_microphones_https_link_carries_no_token(self):
        handler=object.__new__(remote.Handler);sent=[]
        handler.path='/api/voice/https-link';handler.close_connection=False
        handler.headers={'Tailscale-User-Login':'me@example.com','Host':'home-pc.tail1.ts.net'}
        handler.server=SimpleNamespace(machine={**self.MACHINE,'voice':True},owner=SimpleNamespace(login=lambda:'me@example.com'),
                                       cfg={'token':'secret','bind':'127.0.0.1'})
        handler._send=lambda code,body,ctype,extra=None:sent.append((code,json.loads(body)))
        handler.do_GET();self.assertEqual(sent,[(200,{'url':'https://home-pc.tail1.ts.net/'})])
    def test_while_this_computers_account_is_unknown_only_allowed_logins_get_in(self):
        self.assertEqual(self.ask('/',login='me@example.com',owner='')[0],403)
        self.assertEqual(self.ask('/',login='me@example.com',owner='',allowed=['me@example.com'])[0],200)

class SetupTests(unittest.TestCase):
    def test_a_new_computer_gets_a_token_and_no_voice_without_models(self):
        import setup_machine
        cfg=setup_machine.configure({},'公司电脑',has_models=False)
        self.assertEqual((cfg['name'],cfg['port'],cfg['bind'],cfg['voice']),('公司电脑',8765,'127.0.0.1',False));self.assertGreaterEqual(len(cfg['token']),12)
    def test_what_is_set_stays(self):
        import setup_machine
        cfg=setup_machine.configure({'token':'kept','port':9000,'name':'家里电脑'},'',has_models=True)
        self.assertEqual(cfg,{'token':'kept','port':9000,'name':'家里电脑','bind':'127.0.0.1'})
    def test_the_link_page_holds_a_qr_code_of_the_link(self):
        import setup_machine
        with tempfile.TemporaryDirectory() as temp:
            page=setup_machine.link_page('公司<电脑>','https://work-pc.tail1.ts.net/',Path(temp)).read_text(encoding='utf-8')
        self.assertIn('data:image/svg+xml',page);self.assertIn('公司&lt;电脑&gt;',page);self.assertIn('https://work-pc.tail1.ts.net/',page)
        self.assertIn('链接里没有口令',page)
    def test_the_phone_link_carries_no_token(self):  # the phone gets in by its Tailscale account (10-20)
        import setup_machine
        for port,url in ((443,'https://home-pc.tail1.ts.net/'),(8443,'https://home-pc.tail1.ts.net:8443/')):
            linked,said=[],[]
            with patch.object(setup_machine,'link_page',lambda name,link:linked.append(link) or Path('x.html')),\
                 patch.object(setup_machine.os,'startfile',lambda path:None),patch.object(setup_machine,'say',said.append):
                setup_machine.show_link({'token':'secret','name':'家里电脑'},STATUS,port)
            self.assertEqual(linked,[url]);self.assertNotIn('secret',' '.join(said))

def serving(proxy,port='443',**more):  # `tailscale serve status --json` with one web handler at /
    return {'TCP':{port:{'HTTPS':True}},'Web':{f'home-pc.tail1.ts.net:{port}':{'Handlers':{'/':{'Proxy':proxy}}}},**more}

class ServePortTests(unittest.TestCase):
    """setup_machine.py leaves what is on 443 alone (10-20)."""
    def place(self,config):
        import setup_machine
        served,said=[],[]
        with patch.object(setup_machine.machines,'serve_config',return_value=config),patch.object(setup_machine,'say',said.append),\
             patch.object(setup_machine,'serve',lambda exe,https_port,port:served.append((https_port,port)) or True):
            return setup_machine.place('tailscale.exe',STATUS,8765),served,said
    def test_443_carrying_something_else_is_not_overwritten_the_page_goes_on_8443(self):
        placed,served,said=self.place(serving('http://127.0.0.1:3000'))
        self.assertEqual((placed,served),((8443,''),[(8443,8765)]))
        self.assertIn('https://home-pc.tail1.ts.net:8443/',' '.join(said))  # the address is printed
    def test_nothing_served_yet_goes_on_443(self):
        self.assertEqual(self.place({})[:2],((443,''),[(443,8765)]))
    def test_the_page_already_there_is_left_as_it_is(self):
        for proxy in ('http://127.0.0.1:8765','localhost:8765','8765','http://127.0.0.1:8765/'):
            self.assertEqual(self.place(serving(proxy))[:2],((443,''),[]))
        before={'TCP':{'443':{'HTTPS':True},'8443':{'HTTPS':True}},  # put on 8443 by an earlier setup: it stays there
                'Web':{'home-pc.tail1.ts.net:443':{'Handlers':{'/':{'Proxy':'http://127.0.0.1:3000'}}},
                       'home-pc.tail1.ts.net:8443':{'Handlers':{'/':{'Proxy':'http://127.0.0.1:8765'}}}}}
        self.assertEqual(self.place(before)[:2],((8443,''),[]))
    def test_a_port_open_to_the_internet_stops_the_setup(self):
        (port,problem),served,_=self.place(serving('http://127.0.0.1:8765',AllowFunnel={'home-pc.tail1.ts.net:443':True}))
        self.assertEqual((port,served),(0,[]));self.assertIn('Funnel',problem);self.assertIn('--https=443 off',problem)
        other={**serving('http://127.0.0.1:3000'),'AllowFunnel':{'home-pc.tail1.ts.net:8443':True}}  # 8443 is the one it would use
        (port,problem),served,_=self.place(other);self.assertEqual((port,served),(0,[]));self.assertIn('8443',problem)
    def test_both_ports_taken_or_settings_unreadable_change_nothing(self):
        both={'TCP':{'443':{'HTTPS':True},'8443':{'TCPForward':'127.0.0.1:22'}},'Web':serving('http://127.0.0.1:3000')['Web']}
        (port,problem),served,_=self.place(both);self.assertEqual((port,served),(0,[]));self.assertIn('443',problem)
        (port,problem),served,_=self.place(None);self.assertEqual((port,served),(0,[]));self.assertIn('serve status',problem)
    def test_the_address_carries_the_port_off_443(self):
        self.assertEqual(machines.own_url(STATUS,8443),'https://home-pc.tail1.ts.net:8443/')
        self.assertEqual(machines.own_url(STATUS),'https://home-pc.tail1.ts.net/')

class CodexCliTests(unittest.TestCase):
    def test_desktop_runtime_wins_over_npm_with_npm_only_fallback(self):
        import os,new_conversations
        with tempfile.TemporaryDirectory() as temp:
            roaming,local=Path(temp)/'Roaming',Path(temp)/'Local'
            old,new=local/'OpenAI/Codex/bin/aaa/codex.exe',local/'OpenAI/Codex/bin/bbb/codex.exe'
            for p in (old,new):p.parent.mkdir(parents=True);p.write_bytes(b'')
            os.utime(old,(1,1))
            with patch.dict(os.environ,{'APPDATA':str(roaming),'LOCALAPPDATA':str(local)}):
                self.assertEqual(new_conversations.codex_cli(),new)
                npm=roaming/'npm/node_modules/@openai/codex/node_modules/@openai/codex-win32-x64/vendor/x86_64-pc-windows-msvc/bin/codex.exe'
                npm.parent.mkdir(parents=True);npm.write_bytes(b'')
                self.assertEqual(new_conversations.codex_cli(),new)
                old.unlink();new.unlink()
                self.assertEqual(new_conversations.codex_cli(),npm)
            with patch.dict(os.environ,{'APPDATA':str(Path(temp)/'none'),'LOCALAPPDATA':str(Path(temp)/'none')}):
                self.assertIsNone(new_conversations.codex_cli())

if __name__=='__main__':unittest.main()
