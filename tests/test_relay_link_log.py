"""The desktop's record of the relay link: connect, disconnect (with a reason), reconnect, and recovery."""
import asyncio
from datetime import datetime
from pathlib import Path
import sys
import tempfile
import threading
import time
import types
import unittest
from unittest.mock import Mock, patch

from aiohttp import (ClientSession, ClientTimeout, ClientSSLError, ConnectionTimeoutError,
                     ServerTimeoutError, WSServerHandshakeError, web)

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import relay_agent
import relay_controller
import relay_desktop as desktop
from relay_identity import Identity
from relay_service import Service


REPORT='中转：还没连上'


class FakeSocket:
    """Just the two things relay_agent.close_reason() reads from a ClientWebSocketResponse."""
    def __init__(self,code=None,error=None):
        self.close_code=code
        self._error=error
    def exception(self):
        return self._error


class LeakyError(Exception):
    """An exception whose text carries a URL and a key: the log must never contain either."""
    def __str__(self):
        return 'Bearer sk-live-3f8a1c2d https://app.example.test/tunnel/connect'


def link_log(lines,now=None):
    from relay_agent import LinkLog
    return LinkLog(lines.append,clock=(lambda:now[0]) if now is not None else time.monotonic)


class LinkLogTests(unittest.TestCase):
    def test_first_connect_disconnect_ten_minute_report_and_reconnect(self):
        now=[1000.0];lines=[];log=link_log(lines,now)
        log.connected()
        self.assertEqual(lines,['中转：连上了'])
        now[0]+=120
        log.lost('测试原因')
        self.assertEqual(lines[-1],'中转：断开了（测试原因），这次连了 2 分钟')
        now[0]+=60
        log.attempt();log.failed('网络断了')
        self.assertEqual(len(lines),2)  # under ten minutes: no periodic line
        now[0]+=480
        log.attempt();log.failed('网络断了')
        self.assertEqual(len(lines),2)
        now[0]+=120  # 660 seconds after the disconnect
        log.attempt();log.failed('网络断了')
        self.assertEqual(lines[-1],'中转：还没连上（已经断了 11 分钟，重连 3 次；最近一次：网络断了）')
        now[0]+=60
        log.attempt();log.connected()
        self.assertEqual(lines[-1],'中转：重新连上了（断了 12 分钟，重连 4 次）')

    def test_first_connect_after_startup_failures_is_the_first_connected_line(self):
        now=[0.0];lines=[];log=link_log(lines,now)
        log.attempt();log.failed('连不上中转（ClientConnectorError）')
        self.assertEqual(lines,['中转：连不上（连不上中转（ClientConnectorError））'])
        now[0]+=30
        log.attempt();log.connected()
        self.assertEqual(lines[-1],'中转：连上了')

    def test_duration_words(self):
        for seconds,text in ((59,'59 秒'),(300,'5 分钟'),(3600,'1 小时'),(3900,'1 小时 5 分钟')):
            with self.subTest(seconds=seconds):
                now=[0.0];lines=[];log=link_log(lines,now)
                log.connected();now[0]+=seconds;log.lost('原因')
                self.assertEqual(lines[-1],f'中转：断开了（原因），这次连了 {text}')

    def test_refused_credential_line_and_then_silence(self):
        now=[0.0];lines=[];log=link_log(lines,now)
        log.attempt();log.failed('连不上中转（ClientConnectorError）')
        now[0]+=5
        log.attempt();log.refused(403)
        self.assertEqual(lines[-1],'中转：不认这台电脑的凭据（HTTP 403），停止重连，要在电脑上重新绑定')

    def test_periodic_line_written_once_per_ten_minutes(self):
        now=[0.0];lines=[];log=link_log(lines,now)
        log.attempt();log.failed('原因')
        start=now[0]
        for seconds in (599,600,601,1199,1200):
            now[0]=start+seconds
            log.attempt();log.failed('原因')
        reports=[line for line in lines if line.startswith(REPORT)]
        self.assertEqual(len(reports),2)


class ReasonTests(unittest.TestCase):
    def test_heartbeat_timeout_is_recognized_from_the_socket_exception(self):
        reason=relay_agent.close_reason(FakeSocket(1006,ServerTimeoutError('No PONG received')))
        self.assertIn('心跳超时',reason)

    def test_close_codes(self):
        self.assertEqual(relay_agent.close_reason(FakeSocket(1000)),'中转正常关闭（1000）')
        self.assertEqual(relay_agent.close_reason(FakeSocket(1001)),'中转那边在关闭（1001）')
        self.assertEqual(relay_agent.close_reason(FakeSocket(1008)),
            '中转关掉了这条连接（1008：中转重启、同一台电脑又连了一条，或被撤销、重新绑定）')
        self.assertEqual(relay_agent.close_reason(FakeSocket(1006)),'连接被掐断，没收到关闭信号（1006）')
        self.assertEqual(relay_agent.close_reason(FakeSocket(None)),'连接被掐断，没收到关闭信号（1006）')
        self.assertEqual(relay_agent.close_reason(FakeSocket(1002)),'中转关闭了连接（代码 1002）')

    def test_handshake_status_and_connection_timeout(self):
        self.assertEqual(relay_agent.exception_reason(WSServerHandshakeError(None,(),status=502)),
            '中转没接受连接（HTTP 502）')
        self.assertEqual(relay_agent.exception_reason(ConnectionTimeoutError('fixture')),
            '连中转超时（ConnectionTimeoutError）')

    def test_tls_error_is_not_reported_as_a_plain_connection_error(self):
        reason=relay_agent.exception_reason(ClientSSLError(None,OSError(1,'fixture')))
        self.assertIn('加密连接',reason)
        self.assertNotIn('连不上中转',reason)

    def test_no_url_or_key_in_any_reason(self):
        for reason in (relay_agent.exception_reason(LeakyError()),
                       relay_agent.exception_reason(ClientSSLError(None,OSError(1,str(LeakyError())))),
                       relay_agent.close_reason(FakeSocket(1006,LeakyError()))):
            self.assertNotIn('app.example.test',reason)
            self.assertNotIn('sk-live',reason)
        lines=[];log=link_log(lines)
        log.attempt();log.failed(relay_agent.exception_reason(LeakyError()))
        self.assertNotIn('app.example.test',lines[0]);self.assertNotIn('sk-live',lines[0])


class FakeProcess:
    def __init__(self):
        self.terminated=False
    def poll(self):
        return 0 if self.terminated else None
    def terminate(self):
        self.terminated=True
    def wait(self,timeout=None):
        return 0
    def kill(self):
        self.terminated=True


def wait_until(predicate,timeout=5):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        if predicate():return True
        time.sleep(0.01)
    return predicate()


async def wait_until_async(predicate,timeout=8):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        if predicate():return True
        await asyncio.sleep(0.05)
    return predicate()


def fake_agent(instances):
    class FakeAgent:
        def __init__(self,origin,key,port,token,*,state=None,link=None):
            self.state=state;self.link=link;self.stopped=False;instances.append(self)
        async def run(self):
            self.state('online')
            try:
                await asyncio.sleep(3600)
            finally:
                self.stopped=True
                self.state('offline')
    return FakeAgent


class ControllerRecoveryTests(unittest.TestCase):
    def make_controller(self,lines):
        c=relay_controller.DesktopController.__new__(relay_controller.DesktopController)
        c.stop=threading.Event();c.agent_stop=threading.Event()
        c.auth_stop=threading.Event();c.cancel_download=threading.Event()
        c.binding={'origin':'http://127.0.0.1:9','key':'k','device':'d'}
        c.cfg={'port':8765,'token':'t'}
        c.state='连接中';c.detail='';c.online=False;c.worker=None
        c.shell=None;c.icon=None;c.window=None;c.exiting=False
        c.link=link_log(lines)
        return c

    def test_one_or_two_health_failures_do_not_stop_the_connection(self):
        lines=[];c=self.make_controller(lines);instances=[];processes=[];calls=[0]
        values=[False,True,False,False,True]
        lock=threading.Lock()
        def healthy(cfg):
            with lock:
                calls[0]+=1
                return values.pop(0) if values else True
        def backend(cfg,cancel=None):
            process=FakeProcess();processes.append(process);return process
        with patch.object(relay_controller,'HEALTH_INTERVAL',0.01), \
             patch.object(desktop,'healthy',healthy),patch.object(desktop,'backend',backend), \
             patch('relay_agent.Agent',fake_agent(instances)):
            worker=threading.Thread(target=lambda:asyncio.run(c.run_agent(c.agent_stop)),daemon=True)
            c.worker=worker;worker.start()
            try:
                self.assertTrue(wait_until(lambda:calls[0]>=5,5))
                self.assertFalse(any('本机服务：连续 3 次没回应' in line for line in lines))
                self.assertEqual(len(instances),1)
                self.assertFalse(processes[0].terminated)
                self.assertEqual(c.state,'已连接')
            finally:
                c.agent_stop.set();c.stop.set();worker.join(2)
        self.assertFalse(worker.is_alive())

    def test_three_health_failures_restart_the_local_service_and_reconnect(self):
        lines=[];c=self.make_controller(lines);instances=[];processes=[];calls=[0]
        lock=threading.Lock()
        def healthy(cfg):
            with lock:
                calls[0]+=1
                return calls[0]>3
        def backend(cfg,cancel=None):
            process=FakeProcess();processes.append(process);return process
        with patch.object(relay_controller,'HEALTH_INTERVAL',0.01), \
             patch.object(relay_controller,'RECOVERY_WAIT',0.05), \
             patch.object(desktop,'healthy',healthy),patch.object(desktop,'backend',backend), \
             patch('relay_agent.Agent',fake_agent(instances)):
            worker=threading.Thread(target=lambda:asyncio.run(c.run_agent(c.agent_stop)),daemon=True)
            c.worker=worker;worker.start()
            try:
                self.assertTrue(wait_until(lambda:any('本机服务：连续 3 次没回应' in line for line in lines),5))
                self.assertRegex(lines[0],r'^本机服务：连续 3 次没回应（每次等 3 秒），先断开中转，[\d.]+ 秒后重启本机服务再连$')
                self.assertTrue(wait_until(lambda:c.state=='已连接' and len(instances)>=2,5))
                self.assertTrue(instances[0].stopped)
                self.assertTrue(processes[0].terminated)
                self.assertGreaterEqual(len(processes),2)
            finally:
                c.agent_stop.set();c.stop.set();worker.join(2)
        self.assertFalse(worker.is_alive())

    def test_backend_value_error_is_logged_once_and_retried(self):
        lines=[];c=self.make_controller(lines);calls=[0]
        def backend(cfg,cancel=None):
            calls[0]+=1
            raise ValueError('端口已被其他程序占用，未启动重复服务')
        with patch.object(relay_controller,'HEALTH_INTERVAL',0.01), \
             patch.object(relay_controller,'RECOVERY_WAIT',0.2), \
             patch.object(desktop,'healthy',lambda cfg:True),patch.object(desktop,'backend',backend):
            worker=threading.Thread(target=lambda:asyncio.run(c.run_agent(c.agent_stop)),daemon=True)
            c.worker=worker;worker.start()
            try:
                self.assertTrue(wait_until(lambda:any('本机服务：没启动起来' in line for line in lines),5))
                self.assertTrue(wait_until(lambda:calls[0]>=3 and c.state=='连接失败',5))
                self.assertRegex(lines[0],r'^本机服务：没启动起来（端口已被其他程序占用，未启动重复服务），[\d.]+ 秒后再试$')
                self.assertEqual(sum('本机服务：没启动起来' in line for line in lines),1)
                self.assertEqual(c.state,'连接失败')
                self.assertEqual(c.detail,'端口已被其他程序占用，未启动重复服务')
            finally:
                c.agent_stop.set();c.stop.set();worker.join(2)
        self.assertFalse(worker.is_alive())

    def test_quit_while_waiting_to_retry_stops_the_worker_and_is_logged(self):
        lines=[];c=self.make_controller(lines)
        def backend(cfg,cancel=None):
            raise ValueError('本机服务启动失败')
        with patch.object(relay_controller,'HEALTH_INTERVAL',0.01), \
             patch.object(relay_controller,'RECOVERY_WAIT',3), \
             patch.object(desktop,'healthy',lambda cfg:True),patch.object(desktop,'backend',backend):
            worker=threading.Thread(target=lambda:asyncio.run(c.run_agent(c.agent_stop)),daemon=True)
            c.worker=worker;worker.start()
            try:
                self.assertTrue(wait_until(lambda:any('本机服务：没启动起来' in line for line in lines),5))
                started=time.monotonic();c.quit();elapsed=time.monotonic()-started
                self.assertLess(elapsed,2)
                self.assertFalse(worker.is_alive())
                self.assertEqual(lines[-1],'中转：电脑端退出，断开连接')
            finally:
                c.agent_stop.set();c.stop.set();worker.join(2)

    def test_rebind_line_only_after_the_confirmation(self):
        lines=[];c=self.make_controller(lines)
        c.window=Mock();c.begin_auth=Mock()
        c.window.create_confirmation_dialog.return_value=False
        c.rebind()
        self.assertEqual(lines,[])
        c.window.create_confirmation_dialog.return_value=True
        with patch.object(relay_controller,'save'):
            c.rebind()
        self.assertEqual(lines,['中转：重新绑定，断开连接'])
        c.begin_auth.assert_called_once()


class DayLogTests(unittest.TestCase):
    def test_line_goes_into_the_days_file(self):
        with tempfile.TemporaryDirectory() as temp:
            data=Path(temp)/'data'
            with patch.object(desktop,'DATA',data):
                desktop.day_log('测试 文字')
            files=list((data/'logs').glob('*.log'))
            self.assertEqual(len(files),1)
            self.assertRegex(files[0].name,r'^\d{8}\.log$')
            text=files[0].read_text(encoding='utf-8')
            self.assertRegex(text,r'^\d\d:\d\d:\d\d 测试 文字\n$')
            self.assertNotIn('\r\n',text)

    def test_unwritable_folder_does_not_raise(self):
        with tempfile.TemporaryDirectory() as temp:
            data=Path(temp)/'data'
            data.write_text('a file, not a folder',encoding='utf-8')
            with patch.object(desktop,'DATA',data):
                desktop.day_log('x')


class RelayLinkIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.runners=[];self.runs=[]
        self.store=Identity(Path(self.tmp.name)/'state.sqlite3')
        self.service=Service('https://relay.test',self.store,types.SimpleNamespace(send=lambda *args:None))
        runner=web.AppRunner(self.service.app,access_log=None);await runner.setup()
        site=web.TCPSite(runner,'127.0.0.1',0);await site.start()
        self.runners.append(runner)
        port=site._server.sockets[0].getsockname()[1]
        self.origin='http://127.0.0.1:'+str(port)
        self.service.origin=self.origin;self.service.authority='127.0.0.1:'+str(port)
        self.client=ClientSession(timeout=ClientTimeout(total=20))
        await asyncio.to_thread(self.store.register,'alice','password-for-alice',self.store.grant('invite'))
        token=await asyncio.to_thread(self.store.login,'alice','password-for-alice')
        self.key='a'*43
        auth=self.store.start_authorization(self.key,'alice')
        self.device=self.store.approve(token,auth)
        async def backend(request):
            return web.Response(text='ok')
        app=web.Application();app.router.add_route('*','/{path:.*}',backend)
        backend_runner=web.AppRunner(app,access_log=None);await backend_runner.setup()
        backend_site=web.TCPSite(backend_runner,'127.0.0.1',0);await backend_site.start()
        self.runners.append(backend_runner)
        self.backend_port=backend_site._server.sockets[0].getsockname()[1]
        self.lines=[]

    async def asyncTearDown(self):
        for task in self.runs:task.cancel()
        await asyncio.gather(*self.runs,return_exceptions=True)
        await self.client.close()
        for runner in reversed(self.runners):await runner.cleanup()
        self.tmp.cleanup()

    async def test_real_agent_logs_connect_the_1008_close_and_the_reconnect(self):
        from relay_agent import Agent
        agent=Agent(self.origin,self.key,self.backend_port,'local',test_http=True,link=link_log(self.lines))
        self.runs.append(asyncio.create_task(agent.run()))
        self.assertTrue(await wait_until_async(lambda:self.device in self.service.hub.connections,8))
        self.assertEqual(self.lines,['中转：连上了'])
        await self.service.hub.disconnect(self.device)
        self.assertTrue(await wait_until_async(lambda:len(self.lines)>=2,8))
        self.assertRegex(self.lines[1],
            r'^中转：断开了（中转关掉了这条连接（1008：中转重启、同一台电脑又连了一条，或被撤销、重新绑定）），这次连了 \d+ 秒$')
        self.assertTrue(await wait_until_async(lambda:any(line.startswith('中转：重新连上了') for line in self.lines),10))
        reconnected=next(line for line in self.lines if line.startswith('中转：重新连上了'))
        self.assertRegex(reconnected,r'^中转：重新连上了（断了 \d+ 秒，重连 1 次）$')

    async def test_bad_credential_logs_the_refusal_and_the_agent_stops(self):
        from relay_agent import Agent
        lines=[]
        agent=Agent(self.origin,'z'*43,self.backend_port,'local',test_http=True,link=link_log(lines))
        await asyncio.wait_for(agent.run(),8)
        self.assertEqual(lines,['中转：不认这台电脑的凭据（HTTP 401），停止重连，要在电脑上重新绑定'])


if __name__=='__main__':unittest.main()
