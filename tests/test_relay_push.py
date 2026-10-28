"""遥应's own notifications through Apple (relay_push.py, 10-26): the provider token, the request Apple gets, the
phones' registry behind the sign-in, and a computer's event read through its tunnel and sent to its account's phone
only. Apple is never asked: a fake sender takes what would go, and httpx's MockTransport answers for Apple."""
import asyncio
import base64
import json
from pathlib import Path
import sys
import tempfile
import unittest

from aiohttp import web, ClientSession, ClientTimeout

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import relay_push  # noqa: E402
from relay_agent import Agent  # noqa: E402
from relay_identity import Identity  # noqa: E402
from relay_service import Service, COOKIE  # noqa: E402

try:
    import httpx
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
except ImportError:  # the relay's own requirements: pip install -r requirements-relay.txt
    httpx = None

PHONE = 'ab' * 32   # an APNs device token as the app sends it: 64 hex characters
OTHER = 'cd' * 32


def unb64(text):
    return base64.urlsafe_b64decode(text + '=' * (-len(text) % 4))


def new_key():
    key = ec.generate_private_key(ec.SECP256R1())
    return key, key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())


class FakeSender:
    """Takes what would go to Apple and answers as Apple would ([answers], in turn; 200 when they run out)."""
    def __init__(self, *answers):
        self.sent, self.answers = [], list(answers)

    async def send(self, environment, token, payload, collapse, expires, push_type='alert', priority=10, topic=None):
        self.sent.append({'environment': environment, 'token': token, 'payload': payload, 'collapse': collapse, 'expires': expires,
                          'push_type': push_type, 'priority': priority, 'topic': topic})
        return self.answers.pop(0) if self.answers else (200, '')

    async def close(self):
        pass


@unittest.skipIf(httpx is None, 'needs httpx, h2 and cryptography (requirements-relay.txt)')
class AppleTests(unittest.IsolatedAsyncioTestCase):
    def test_the_provider_token_is_es256_with_the_key_id_and_the_team(self):
        key, _ = new_key()
        token = relay_push.provider_token(key, 'KEY1234567', 'CPSVJ7235A', 1_800_000_000)
        head, claims, signature = token.split('.')
        self.assertEqual(json.loads(unb64(head)), {'alg': 'ES256', 'kid': 'KEY1234567'})
        self.assertEqual(json.loads(unb64(claims)), {'iss': 'CPSVJ7235A', 'iat': 1_800_000_000})
        raw = unb64(signature)
        self.assertEqual(len(raw), 64)  # r and s, 32 bytes each, as JWT wants (not DER)
        der = encode_dss_signature(int.from_bytes(raw[:32], 'big'), int.from_bytes(raw[32:], 'big'))
        key.public_key().verify(der, f'{head}.{claims}'.encode(), ec.ECDSA(hashes.SHA256()))  # raises when wrong

    async def test_one_post_per_phone_with_the_headers_apple_wants(self):
        _, pem = new_key()
        now = [1_800_000_000.0]
        seen = []

        def apple(request):
            seen.append(request)
            return httpx.Response(200)

        apns = relay_push.Apns(pem, 'KEY1234567', 'CPSVJ7235A', clock=lambda: now[0], transport=httpx.MockTransport(apple))
        payload = {'aps': {'alert': {'title': 'Codex · 家里电脑', 'body': '有个对话好了'}}, 'teleply': {'d': 'a' * 32, 'a': 'codex', 'c': 'x'}}
        self.assertEqual(await apns.send('production', PHONE, payload, 'thread1', now[0] + 86400), (200, ''))
        request = seen[0]
        self.assertEqual(str(request.url), f'https://api.push.apple.com/3/device/{PHONE}')
        self.assertEqual({k: request.headers[k] for k in ('apns-topic', 'apns-push-type', 'apns-priority', 'apns-expiration', 'apns-collapse-id')},
                         {'apns-topic': 'com.pocketagentdesk.teleply', 'apns-push-type': 'alert', 'apns-priority': '10',
                          'apns-expiration': str(int(now[0] + 86400)), 'apns-collapse-id': 'thread1'})
        self.assertTrue(request.headers['authorization'].startswith('bearer '))
        self.assertEqual(json.loads(request.content), payload)
        first = request.headers['authorization']
        await apns.send('development', PHONE, payload, '', now[0])
        self.assertEqual(seen[1].url.host, 'api.sandbox.push.apple.com')
        self.assertNotIn('apns-collapse-id', seen[1].headers)  # a test push replaces nothing
        self.assertEqual(seen[1].headers['authorization'], first)  # within 50 minutes the same token
        now[0] += relay_push.TOKEN_AGE
        await apns.send('production', PHONE, payload, 't', now[0])
        self.assertNotEqual(seen[2].headers['authorization'], first)
        await apns.close()

    async def test_an_island_post_carries_the_live_activity_topic_and_its_priority(self):
        _, pem = new_key()
        now = [1_800_000_000.0]
        seen = []

        def apple(request):
            seen.append(request)
            return httpx.Response(200)

        apns = relay_push.Apns(pem, 'KEY1234567', 'CPSVJ7235A', clock=lambda: now[0], transport=httpx.MockTransport(apple))
        payload = {'aps': {'timestamp': int(now[0]), 'event': 'update', 'content-state': {'state': 'working', 'since': int(now[0]),
                                                                                          'turn': int(now[0])}}}
        self.assertEqual(await apns.send('production', PHONE, payload, '', now[0] + 600, push_type='liveactivity',
                                         priority=5, topic=relay_push.ISLAND_TOPIC), (200, ''))
        headers = seen[0].headers
        self.assertEqual((headers['apns-topic'], headers['apns-push-type'], headers['apns-priority'], headers['apns-expiration']),
                         ('com.pocketagentdesk.teleply.push-type.liveactivity', 'liveactivity', '5', str(int(now[0] + 600))))
        self.assertEqual(json.loads(seen[0].content), payload)
        await apns.close()

    async def test_a_stale_provider_token_is_made_again_once_and_reasons_come_back(self):
        _, pem = new_key()
        answers = [httpx.Response(403, json={'reason': 'ExpiredProviderToken'}), httpx.Response(200),
                   httpx.Response(410, json={'reason': 'Unregistered', 'timestamp': 1}), httpx.Response(500, text='busy')]
        seen = []

        def apple(request):
            seen.append(request.headers['authorization'])
            return answers.pop(0)

        apns = relay_push.Apns(pem, 'KEY1234567', 'CPSVJ7235A', transport=httpx.MockTransport(apple))
        self.assertEqual(await apns.send('production', PHONE, {}, 'c', 0), (200, ''))
        self.assertNotEqual(seen[0], seen[1])
        self.assertEqual(await apns.send('production', PHONE, {}, 'c', 0), (410, 'Unregistered'))
        self.assertEqual(await apns.send('production', PHONE, {}, 'c', 0), (500, ''))
        await apns.close()

    async def test_settings_from_the_servers_file_or_push_stays_off(self):
        self.assertIsNone(relay_push.from_env({}))
        pem = new_key()[1]
        env = {'AR_APNS_KEY': base64.b64encode(pem).decode(), 'AR_APNS_KEY_ID': 'KEY1234567', 'AR_APNS_TEAM_ID': 'CPSVJ7235A'}
        sender = relay_push.from_env(env)  # as configure-push.py writes push.env
        self.assertEqual((sender.topic, sender.key_id, sender.team_id), ('com.pocketagentdesk.teleply', 'KEY1234567', 'CPSVJ7235A'))
        await sender.close()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'apns.p8'
            path.write_bytes(pem)
            files = {'AR_APNS_KEY_FILE': str(path), 'AR_APNS_KEY_ID': 'KEY1234567', 'AR_APNS_TEAM_ID': 'CPSVJ7235A', 'AR_APNS_TOPIC': 'x.y'}
            sender = relay_push.from_env(files)
            self.assertEqual(sender.topic, 'x.y')
            await sender.close()
            with self.assertLogs('relay.push', 'WARNING') as logged:
                self.assertIsNone(relay_push.from_env({**files, 'AR_APNS_KEY_FILE': str(Path(tmp) / 'missing.p8')}))
                self.assertIsNone(relay_push.from_env({**env, 'AR_APNS_KEY': 'not base64!'}))
            self.assertIn('push off', logged.output[0])
            self.assertNotIn(env['AR_APNS_KEY'][:20], ''.join(logged.output))


class RelayTests(unittest.IsolatedAsyncioTestCase):
    """The relay as it runs: two accounts, each with a computer connected through relay_agent to a small backend that
    stands in for remote.py and serves /api/notify/push from a queue."""

    sender = None

    async def start(self, app):
        runner = web.AppRunner(app, access_log=None)
        await runner.setup()
        site = web.TCPSite(runner, '127.0.0.1', 0)
        await site.start()
        self.runners.append(runner)
        return site._server.sockets[0].getsockname()[1]

    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.runners, self.tasks = [], []
        self.store = Identity(Path(self.tmp.name) / 'state.sqlite3')
        self.service = Service('https://relay.test', self.store, mailer=type('Mail', (), {'ready': False})(), sender=self.sender)
        port = await self.start(self.service.app)
        self.origin = 'http://127.0.0.1:' + str(port)
        self.service.origin, self.service.authority = self.origin, '127.0.0.1:' + str(port)
        self.client = ClientSession(timeout=ClientTimeout(total=20))
        self.tokens, self.devices, self.events, self.asked = [], [], [], [[], []]
        for index, name in enumerate(('alice', 'bob')):
            await asyncio.to_thread(self.store.register, name, 'password-for-' + name, self.store.grant('invite'))
            token = await asyncio.to_thread(self.store.login, name, 'password-for-' + name)
            self.tokens.append(token)
            key = ('a' if index == 0 else 'b') * 43
            self.devices.append(self.store.approve(token, self.store.start_authorization(key, name + '的电脑')))
            events = asyncio.Queue()
            self.events.append(events)

            async def backend(req, i=index, events=events):
                if req.cookies.get('lbr') != 'local-' + str(i):
                    return web.Response(status=401)
                if req.path != '/api/notify/push':
                    return web.Response(status=404)
                self.asked[i].append(req.query.get('since'))
                stream = web.StreamResponse(headers={'Content-Type': 'application/x-ndjson'})
                await stream.prepare(req)
                await stream.write(b'{"event":"open"}\n')
                while req.transport is not None and not req.transport.is_closing():  # until the agent hangs up
                    try:
                        line = await asyncio.wait_for(events.get(), .2)
                    except asyncio.TimeoutError:
                        continue
                    await stream.write(json.dumps(line).encode() + b'\n')
                return stream

            app = web.Application()
            app.router.add_route('*', '/{path:.*}', backend)
            local = await self.start(app)
            agent = Agent(self.origin, key, local, 'local-' + str(index), test_http=True)
            self.tasks.append(asyncio.create_task(agent.run()))
        for _ in range(50):
            if len(self.service.hub.connections) == 2:
                break
            await asyncio.sleep(.05)
        self.assertEqual(len(self.service.hub.connections), 2)

    async def asyncTearDown(self):
        for task in self.tasks:
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        await self.client.close()
        for runner in reversed(self.runners):
            await runner.cleanup()
        self.tmp.cleanup()

    async def post(self, action, data, user=0, cookie=True):
        headers = {'Origin': self.origin, **({'Cookie': COOKIE + '=' + self.tokens[user]} if cookie else {})}
        async with self.client.post(self.origin + '/account/push/' + action, json=data, headers=headers) as r:
            return r.status, await r.json()


class WithoutAppleTests(RelayTests):
    async def test_a_server_without_a_key_says_so_and_keeps_nothing(self):
        self.assertEqual(await self.post('state', {'token': PHONE}), (200, {'available': False, 'registered': False, 'phones': 0}))
        status, answer = await self.post('register', {'token': PHONE})
        self.assertEqual((status, answer['code']), (409, 'push_unavailable'))
        self.assertEqual(answer['error'], '服务器还没开通遥应通知')
        self.assertEqual((await self.post('state', {}, cookie=False))[0], 401)


class WithAppleTests(RelayTests):
    def setUp(self):
        self.sender = FakeSender()

    async def until(self, condition, seconds=5.0):
        for _ in range(int(seconds / .05)):
            if condition():
                return True
            await asyncio.sleep(.05)
        return False

    def phones(self):
        with self.store.connect() as db:
            return [dict(r) for r in db.execute('SELECT * FROM push_phones ORDER BY refreshed')]

    async def test_a_phone_is_kept_for_the_account_tried_and_removed(self):
        self.assertEqual((await self.post('register', {'token': PHONE.upper(), 'label': 'iPhone', 'version': '0.5.0'}))[0], 200)
        self.assertEqual(await self.post('state', {'token': PHONE}), (200, {'available': True, 'registered': True, 'phones': 1}))
        self.assertEqual(await self.post('test', {'token': PHONE}), (200, {'ok': True, 'text': '刚推了一条，看看通知'}))
        tried = self.sender.sent[0]
        self.assertEqual((tried['environment'], tried['token'], tried['payload']['aps']['alert']['title']), ('production', PHONE, '遥应'))
        self.assertNotIn('teleply', tried['payload'])
        # the same phone signed in to bob now: it follows the sign-in
        self.assertEqual((await self.post('register', {'token': PHONE}, user=1))[0], 200)
        self.assertFalse((await self.post('state', {'token': PHONE}))[1]['registered'])
        self.assertTrue((await self.post('state', {'token': PHONE}, user=1))[1]['registered'])
        self.assertEqual((await self.post('test', {'token': PHONE}))[0], 400)  # not alice's any more
        self.assertEqual(await self.post('unregister', {'token': PHONE}, user=1), (200, {'ok': True}))
        self.assertEqual(self.phones(), [])

    async def test_what_is_not_a_phones_token_is_turned_away(self):
        for data, words in (({'token': 'not-hex'}, '推送令牌无效'), ({'token': PHONE, 'platform': 'android'}, '这种手机还不能收遥应通知'),
                            ({'token': PHONE, 'environment': 'staging'}, '推送环境无效')):
            status, answer = await self.post('register', data)
            self.assertEqual((status, answer['error']), (400, words))
        self.assertEqual(self.phones(), [])

    async def test_ten_phones_at_most_and_a_new_password_drops_them(self):
        for n in range(relay_push.PHONES + 1):
            self.service.push.clock = lambda n=n: 1_800_000_000.0 + n
            await self.post('register', {'token': f'{n:064x}'})
        tokens = [p['token'] for p in self.phones()]
        self.assertEqual(len(tokens), relay_push.PHONES)
        self.assertNotIn(f'{0:064x}', tokens)  # the one not seen for longest made way
        await asyncio.to_thread(self.store.change_password, self.tokens[0], 'password-for-alice', 'a-new-password-for-alice')
        self.assertEqual(self.phones(), [])

    async def test_an_event_reaches_the_accounts_phone_once_with_no_conversation_in_it(self):
        await self.post('register', {'token': PHONE})
        self.assertTrue(await self.until(lambda: self.asked[0]))  # the relay listens to alice's computer
        self.assertEqual(self.asked[0][0], relay_push.SINCE)
        self.assertEqual(self.asked[1], [])  # bob has no phone: his computer is not asked
        event = {'id': 'e1', 'event': 'message', 'kind': 'waiting', 'app': 'claude', 'chat': 'chat-1', 'title': '', 'message': ''}
        await self.events[0].put(event)
        self.assertTrue(await self.until(lambda: self.sender.sent))
        sent = self.sender.sent[0]
        fallback = 'Claude · alice的电脑'
        self.assertEqual(sent['payload'], {'aps': {'alert': {'title': fallback, 'subtitle': fallback, 'body': '在等你选'},
                                                   'sound': 'default', 'thread-id': relay_push.notice_thread(self.devices[0]),
                                                   'category': relay_push.NOTICE_CATEGORY},
                                           'teleply': {'d': self.devices[0], 'a': 'claude', 'c': 'chat-1'}})
        self.assertEqual(sent['push_type'], 'alert')
        self.assertEqual(sent['priority'], 10)
        self.assertEqual(sent['collapse'], relay_push.notice_collapse(self.devices[0], 'claude', 'chat-1'))
        self.assertGreater(sent['expires'], 1_000_000_000)
        # the same event again (the relay came back and asked for the last ten minutes), then another kind
        await self.events[0].put(event)
        await self.events[0].put({**event, 'id': 'e2', 'kind': 'done'})
        self.assertTrue(await self.until(lambda: len(self.sender.sent) == 2))
        await asyncio.sleep(.2)
        self.assertEqual([s['payload']['aps']['alert']['body'] for s in self.sender.sent], ['在等你选', '好了'])
        # one sound an account in ten seconds: the done right after the waiting went in silently (user 10-28)
        self.assertNotIn('sound', self.sender.sent[1]['payload']['aps'])
        self.assertEqual(self.sender.sent[1]['payload']['aps']['interruption-level'], 'passive')
        await self.events[0].put({**event, 'id': 'e3', 'kind': 'done'})  # the same again within a minute: held back
        await self.events[0].put({**event, 'id': 'e4', 'app': 'mail'})   # not an app the relay knows
        await asyncio.sleep(.3)
        self.assertEqual(len(self.sender.sent), 2)
        self.assertEqual(self.service.push.since[self.devices[0]], 'e4')

    async def test_a_phone_apple_says_is_gone_is_dropped(self):
        self.sender.answers = [(410, 'Unregistered')]
        await self.post('register', {'token': PHONE})
        self.assertTrue(await self.until(lambda: self.asked[0]))
        await self.events[0].put({'id': 'e1', 'event': 'message', 'kind': 'done', 'app': 'codex', 'chat': 'x'})
        self.assertTrue(await self.until(lambda: not self.phones()))
        with self.assertLogs('relay.push', 'WARNING') as logged:
            self.sender.answers = [(400, 'BadDeviceToken')]
            await self.post('register', {'token': OTHER})
            self.assertEqual((await self.post('test', {'token': OTHER}))[1]['error'], '这部手机的推送令牌已失效，请重新打开遥应通知')
        self.assertNotIn(OTHER, ''.join(logged.output))  # a token shows as the start of its hash
        self.assertEqual(self.phones(), [])

    async def test_a_computer_gone_is_not_listened_to(self):
        await self.post('register', {'token': PHONE})
        self.assertTrue(await self.until(lambda: self.devices[0] in self.service.push.watchers))
        self.tasks[0].cancel()
        await asyncio.gather(self.tasks[0], return_exceptions=True)
        await self.service.hub.disconnect(self.devices[0])
        self.service.push.look()
        self.assertNotIn(self.devices[0], self.service.push.watchers)


class IslandTests(RelayTests):
    """灵动岛 (阶段零): registering an island's token, one update to it with the Live Activity topic, the sample the
    Swift tests read too."""

    def setUp(self):
        self.sender = FakeSender()

    def activities(self):
        with self.store.connect() as db:
            return [dict(r) for r in db.execute('SELECT * FROM push_activities ORDER BY created')]

    def starts(self):
        with self.store.connect() as db:
            return [dict(r) for r in db.execute('SELECT * FROM push_start')]

    @staticmethod
    def fixture():
        return json.loads((Path(__file__).resolve().parents[1] / 'tests' / 'fixtures' / 'island-states.json').read_text())

    def registration(self, **changes):
        data = {'op': 'register', 'token': 'ef' * 32, 'device': self.devices[0], 'app': 'claude', 'chat': 'chat-1',
                'environment': 'production', 'state': 'working', 'since': 1761629700, 'turn': 1761629700}
        data.update(changes)
        data['since'], data['turn'] = str(data['since']), str(data['turn'])  # the account requests take strings
        return data

    async def test_register_then_one_update_with_the_island_topic_and_the_sample(self):
        self.service.push.clock = lambda: 1761630000.0
        self.assertEqual(await self.post('activity', self.registration()), (200, {'ok': True}))
        kept = self.activities()
        self.assertEqual(len(kept), 1)
        self.assertEqual((kept[0]['owner'], kept[0]['device'], kept[0]['app'], kept[0]['chat'], kept[0]['state']),
                         (self.store.owner(self.tokens[0]), self.devices[0], 'claude', 'chat-1', 'working'))
        status, answer = await self.post('island-test', {'device': self.devices[0], 'app': 'claude', 'chat': 'chat-1'})
        self.assertEqual((status, answer['ok'], answer['text']), (200, True, '中转推了一条，岛应该变成 ✓ 了'))
        sent = self.sender.sent[0]
        self.assertEqual((sent['push_type'], sent['topic'], sent['priority']),
                         ('liveactivity', 'com.pocketagentdesk.teleply.push-type.liveactivity', 10))
        self.assertEqual(sent['expires'], 1761630000 + 600)
        aps = sent['payload']['aps']
        self.assertEqual((aps['timestamp'], aps['event'], aps['relevance-score']), (1761630000, 'update', 10))
        self.assertEqual(aps['content-state'], self.fixture()['done'])  # the sample the Swift tests decode
        self.assertEqual(aps['alert']['body'], '好了')
        self.assertNotIn('chat-1', json.dumps(sent['payload']))
        self.assertEqual(self.activities()[0]['state'], 'done')

    async def test_the_long_press_list_has_every_running_conversation_with_its_title(self):
        self.service.push.clock = lambda: 1761630000.0
        await self.post('activity', self.registration(chat='c1', token='ef' * 32, title='改登录页'))
        await self.post('activity', self.registration(chat='c2', token='cd' * 32, title='跑测试'))
        self.sender.sent.clear()
        await self.service.push.deliver(self.devices[0], {'id': 'r1', 'event': 'message', 'kind': 'running',
                                                          'app': 'claude', 'chat': 'c1', 'since': 1761629700})
        peers = self.sender.sent[0]['payload']['aps']['content-state']['peers']
        self.assertEqual({p['chat']: (p['title'], p['state']) for p in peers},
                         {'c1': ('改登录页', 'working'), 'c2': ('跑测试', 'working')})

    async def test_a_running_turn_updates_its_island_quietly(self):
        self.service.push.clock = lambda: 1761630000.0
        await self.post('activity', self.registration(state='working', since='1761629700', turn='1761629700'))
        self.sender.sent.clear()
        await self.service.push.deliver(self.devices[0], {'id': 'r1', 'event': 'message', 'kind': 'running',
                                                          'app': 'claude', 'chat': 'chat-1', 'since': 1761629700})
        self.assertEqual(len(self.sender.sent), 1)
        sent = self.sender.sent[0]
        self.assertEqual((sent['push_type'], sent['priority'], sent['topic']),
                         ('liveactivity', 5, relay_push.ISLAND_TOPIC))
        self.assertEqual(sent['payload']['aps']['content-state'],
                         relay_push.island_state('working', 1761629700, 1761629700,
                                                 peers=[{'app': 'claude', 'chat': 'chat-1', 'title': '',
                                                         'state': 'working', 'since': 1761629700, 'turn': 1761629700}]))
        self.assertNotIn('alert', sent['payload']['aps'])  # no banner for 在干活
        self.assertEqual(sent['payload']['aps']['stale-date'], 1761630900)

    async def test_a_finished_turn_changes_the_island_instead_of_notifying(self):
        self.service.push.clock = lambda: 1761630000.0
        await self.post('activity', self.registration(state='working', since='1761629700', turn='1761629700'))
        self.sender.sent.clear()
        await self.service.push.deliver(self.devices[0], {'id': 'd1', 'event': 'message', 'kind': 'done',
                                                          'app': 'claude', 'chat': 'chat-1'})
        self.assertEqual(len(self.sender.sent), 1)  # user 10-28: only the island, no second banner
        sent = self.sender.sent[0]
        self.assertEqual(sent['payload']['aps']['alert']['body'], '有个对话好了')
        self.assertEqual(sent['payload']['aps']['content-state'],
                         relay_push.island_state('done', 1761630000, 1761629700, peers=[]))
        self.assertEqual(self.activities()[0]['state'], 'done')

    async def test_without_an_island_a_finished_turn_is_still_a_notice(self):
        await self.post('register', {'token': PHONE})
        self.sender.sent.clear()
        await self.service.push.deliver(self.devices[0], {'id': 'd1', 'event': 'message', 'kind': 'done',
                                                          'app': 'claude', 'chat': 'chat-1'})
        self.assertEqual(len(self.sender.sent), 1)
        self.assertEqual(self.sender.sent[0]['push_type'], 'alert')
        self.assertIn('teleply', self.sender.sent[0]['payload'])
        self.assertEqual(self.sender.sent[0]['payload']['aps']['alert']['body'], '好了')  # no known start: no 用时

    async def test_a_dead_island_falls_back_to_a_notice(self):
        self.service.push.clock = lambda: 1761630000.0
        await self.post('register', {'token': PHONE})
        await self.post('activity', self.registration())
        self.sender.answers = [(410, 'Unregistered')]
        await self.service.push.deliver(self.devices[0], {'id': 'd1', 'event': 'message', 'kind': 'done',
                                                          'app': 'claude', 'chat': 'chat-1'})
        self.assertEqual([s['push_type'] for s in self.sender.sent], ['liveactivity', 'alert'])
        self.assertEqual(self.sender.sent[1]['payload']['aps']['alert']['body'], '好了 · 用了 5 分钟')
        self.assertEqual(self.sender.sent[1]['priority'], 10)
        self.assertEqual(self.activities(), [])  # the dead island is gone

    async def test_one_sound_for_a_burst_of_notices_and_they_stack_per_computer(self):
        self.service.push.clock = lambda: 1761630000.0
        await self.post('register', {'token': PHONE})
        self.sender.sent.clear()
        await self.service.push.deliver(self.devices[0], {'id': 'b1', 'event': 'message', 'kind': 'done',
                                                          'app': 'claude', 'chat': 'c1', 'title': '改登录页'})
        self.service.push.clock = lambda: 1761630002.0
        await self.service.push.deliver(self.devices[0], {'id': 'b2', 'event': 'message', 'kind': 'done',
                                                          'app': 'codex', 'chat': 'c2', 'title': '跑测试'})
        self.assertEqual(len(self.sender.sent), 2)
        first, second = self.sender.sent
        self.assertEqual(first['payload']['aps']['sound'], 'default')  # the first of the burst rings
        self.assertNotIn('sound', second['payload']['aps'])            # the second only goes to the notification centre
        self.assertEqual(second['payload']['aps']['interruption-level'], 'passive')
        self.assertEqual(second['priority'], 5)
        # one stack per computer: the same thread-id, one row per conversation
        self.assertEqual(first['payload']['aps']['thread-id'], second['payload']['aps']['thread-id'])
        self.assertNotEqual(first['collapse'], second['collapse'])
        await self.service.push.deliver(self.devices[0], {'id': 'b3', 'event': 'message', 'kind': 'waiting',
                                                          'app': 'claude', 'chat': 'c1', 'title': '改登录页'})
        self.service.push.clock = lambda: 1761630065.0
        await self.service.push.deliver(self.devices[0], {'id': 'b4', 'event': 'message', 'kind': 'done',
                                                          'app': 'claude', 'chat': 'c1', 'title': '改登录页'})
        self.assertEqual(self.sender.sent[3]['collapse'], first['collapse'])  # one conversation, one row

    async def test_one_sound_for_a_burst_of_island_updates(self):
        self.service.push.clock = lambda: 1761630000.0
        await self.post('activity', self.registration(chat='c1', token='ef' * 32))
        await self.post('activity', self.registration(chat='c2', token='cd' * 32))
        self.sender.sent.clear()
        await self.service.push.deliver(self.devices[0], {'id': 'i1', 'event': 'message', 'kind': 'done',
                                                          'app': 'claude', 'chat': 'c1'})
        self.service.push.clock = lambda: 1761630003.0
        await self.service.push.deliver(self.devices[0], {'id': 'i2', 'event': 'message', 'kind': 'failed',
                                                          'app': 'claude', 'chat': 'c2'})
        self.assertEqual([s['push_type'] for s in self.sender.sent], ['liveactivity', 'liveactivity'])
        self.assertEqual(self.sender.sent[0]['payload']['aps']['alert']['sound'], 'default')
        second = self.sender.sent[1]
        self.assertNotIn('alert', second['payload']['aps'])  # the burst's second changes the island, silently
        self.assertEqual(second['priority'], 5)
        self.assertEqual(second['payload']['aps']['content-state']['state'], 'failed')
        self.assertEqual(self.activities()[1]['state'], 'failed')

    async def test_a_notice_carries_the_title_the_subtitle_and_how_long_the_turn_took(self):
        self.service.push.clock = lambda: 1761630000.0
        await self.post('register', {'token': PHONE})
        await self.service.push.deliver(self.devices[0], {'id': 't0', 'event': 'message', 'kind': 'running',
                                                          'app': 'claude', 'chat': 'chat-1', 'since': 1761629640,
                                                          'title': '改登录页'})
        self.assertEqual(self.sender.sent, [])  # 在干活 without an island says nothing
        await self.service.push.deliver(self.devices[0], {'id': 't1', 'event': 'message', 'kind': 'done',
                                                          'app': 'claude', 'chat': 'chat-1', 'title': '改登录页'})
        aps = self.sender.sent[0]['payload']['aps']
        self.assertEqual(aps['alert'], {'title': '改登录页', 'subtitle': 'Claude · alice的电脑',
                                        'body': '好了 · 用了 6 分钟'})
        self.assertEqual(aps['category'], 'teleply.conversation')
        self.assertEqual(self.service.push.starts, {})  # the turn it took is not needed after the notice

    async def test_a_conversation_seen_under_a_minute_says_only_好了(self):
        self.service.push.clock = lambda: 1761630000.0
        await self.post('register', {'token': PHONE})
        await self.service.push.deliver(self.devices[0], {'id': 's0', 'event': 'message', 'kind': 'running',
                                                          'app': 'codex', 'chat': 'c9', 'since': 1761629985})
        await self.service.push.deliver(self.devices[0], {'id': 's1', 'event': 'message', 'kind': 'done',
                                                          'app': 'codex', 'chat': 'c9'})
        self.assertEqual(self.sender.sent[0]['payload']['aps']['alert']['body'], '好了')
        self.assertEqual(self.sender.sent[0]['payload']['aps']['alert']['title'], 'Codex · alice的电脑')

    async def test_a_turn_running_a_minute_is_started_from_afar_with_the_start_token(self):
        self.service.push.clock = lambda: 1761630000.0
        await self.post('start-token', {'token': 'ef' * 32, 'environment': 'production'})
        await self.service.push.deliver(self.devices[0], {'id': 'r1', 'event': 'message', 'kind': 'running',
                                                          'app': 'claude', 'chat': 'chat-1', 'since': 1761630000})
        self.assertEqual(self.sender.sent, [])  # not after the first look
        self.service.push.clock = lambda: 1761630061.0
        await self.service.push.sweep_islands()
        self.assertEqual(len(self.sender.sent), 1)
        sent = self.sender.sent[0]
        aps = sent['payload']['aps']
        self.assertEqual((sent['token'], sent['push_type'], sent['priority']), ('ef' * 32, 'liveactivity', 10))
        self.assertEqual((aps['event'], aps['attributes-type'], aps['input-push-token']),
                         ('start', 'IslandAttributes', 1))
        self.assertEqual(aps['attributes'], {'device': self.devices[0], 'app': 'claude', 'chat': 'chat-1',
                                             'computer': 'alice的电脑', 'title': ''})
        self.assertEqual(aps['content-state'],
                         relay_push.island_state('working', 1761630000, 1761630000,
                                                 peers=[{'app': 'claude', 'chat': 'chat-1', 'title': '',
                                                         'state': 'working', 'since': 1761630000,
                                                         'turn': 1761630000}]))
        self.assertEqual(self.service.push.starts, {})  # started once, not every half minute

    async def test_a_quiet_event_changes_the_island_but_shows_no_banner(self):
        self.service.push.clock = lambda: 1761630000.0
        await self.post('activity', self.registration())
        self.sender.sent.clear()
        await self.service.push.deliver(self.devices[0], {'id': 'q1', 'event': 'message', 'kind': 'done',
                                                          'app': 'claude', 'chat': 'chat-1', 'quiet': True})
        self.assertEqual(len(self.sender.sent), 1)
        self.assertEqual(self.sender.sent[0]['push_type'], 'liveactivity')
        self.assertNotIn('alert', self.sender.sent[0]['payload']['aps'])  # 正开着这个对话: silent
        self.assertEqual(self.activities()[0]['state'], 'done')

    async def test_a_quiet_event_without_an_island_sends_nothing(self):
        await self.post('register', {'token': PHONE})
        self.sender.sent.clear()
        await self.service.push.deliver(self.devices[0], {'id': 'q1', 'event': 'message', 'kind': 'done',
                                                          'app': 'claude', 'chat': 'chat-1', 'quiet': True})
        self.assertEqual(self.sender.sent, [])
        self.assertEqual(self.activities(), [])

    async def test_a_finished_island_ends_five_minutes_later_and_leaves_a_silent_record(self):
        self.service.push.clock = lambda: 1761630000.0
        await self.post('register', {'token': PHONE})
        await self.post('activity', self.registration(title='改登录页'))
        await self.service.push.deliver(self.devices[0], {'id': 'd1', 'event': 'message', 'kind': 'done',
                                                          'app': 'claude', 'chat': 'chat-1', 'title': '改登录页'})
        self.sender.sent.clear()
        self.service.push.clock = lambda: 1761630301.0
        await self.service.push.sweep_islands()
        self.assertEqual([s['push_type'] for s in self.sender.sent], ['liveactivity', 'alert'])
        self.assertEqual(self.sender.sent[0]['payload']['aps']['event'], 'end')
        record = self.sender.sent[1]
        self.assertEqual(record['priority'], 5)
        self.assertNotIn('sound', record['payload']['aps'])
        self.assertEqual(record['payload']['aps']['interruption-level'], 'passive')
        self.assertEqual(record['payload']['aps']['alert'],
                         {'title': '改登录页', 'subtitle': 'Claude · alice的电脑', 'body': '好了 · 用了 5 分钟'})
        self.assertEqual(record['payload']['aps']['thread-id'], relay_push.notice_thread(self.devices[0]))
        self.assertEqual(record['collapse'], relay_push.notice_collapse(self.devices[0], 'claude', 'chat-1'))
        self.assertEqual(self.activities(), [])

    async def test_a_computer_gone_goes_grey_and_comes_back(self):
        clock = 1761630000.0
        self.service.push.clock = lambda: clock
        await self.post('activity', self.registration())
        self.service.push.seen.add(self.devices[0])
        connection = self.service.hub.connections[self.devices[0]]
        await self.service.hub.disconnect(self.devices[0])
        self.sender.sent.clear()
        self.service.push.clock = lambda: clock + 1
        await self.service.push.sweep_islands()  # first miss is remembered
        self.assertEqual(self.sender.sent, [])
        self.service.push.clock = lambda: clock + 61
        await self.service.push.sweep_islands()
        self.assertEqual(len(self.sender.sent), 1)
        aps = self.sender.sent[0]['payload']['aps']
        self.assertEqual(aps['content-state']['state'], 'offline')
        self.assertNotIn('alert', aps)  # user 10-28: grey, no sound
        kept = self.activities()[0]
        self.assertEqual((kept['state'], kept['saved_state']), ('offline', 'working'))
        self.service.hub.connections[self.devices[0]] = connection  # plugged back in
        self.sender.sent.clear()
        self.service.push.clock = lambda: clock + 120
        await self.service.push.sweep_islands()
        self.assertEqual(len(self.sender.sent), 1)
        self.assertEqual(self.sender.sent[0]['payload']['aps']['content-state']['state'], 'working')
        self.assertEqual(self.activities()[0]['state'], 'working')

    async def test_a_computer_gone_half_an_hour_ends_the_island(self):
        clock = 1761630000.0
        self.service.push.clock = lambda: clock
        await self.post('activity', self.registration())
        self.service.push.seen.add(self.devices[0])
        await self.service.hub.disconnect(self.devices[0])
        self.sender.sent.clear()
        self.service.push.clock = lambda: clock + 1
        await self.service.push.sweep_islands()
        self.service.push.clock = lambda: clock + 61
        await self.service.push.sweep_islands()  # grey first
        self.sender.sent.clear()
        self.service.push.clock = lambda: clock + 1802
        await self.service.push.sweep_islands()
        self.assertEqual(len(self.sender.sent), 1)
        aps = self.sender.sent[0]['payload']['aps']
        self.assertEqual((aps['event'], aps['content-state']['state']), ('end', 'offline'))
        self.assertEqual(aps['dismissal-date'], int(clock + 1802) + 3600)
        self.assertEqual(self.activities(), [])

    async def test_the_sample_and_the_relay_agree_on_every_state(self):
        for name, state in self.fixture().items():
            extra = {key: value for key, value in state.items() if key not in ('state', 'since', 'turn')}
            built = relay_push.island_state(state['state'], state['since'], state['turn'], **extra)
            self.assertEqual(built, state, name)
            self.assertTrue(set(state) <= {'state', 'since', 'turn', 'ask', 'askType', 'choices', 'askText', 'askOptions',
                                           'step', 'resets'})

    async def test_what_is_not_an_island_is_turned_away(self):
        cases = [(self.registration(device=self.devices[1]), '这台电脑不属于这个账号'),
                 (self.registration(token='not-hex'), '岛的推送令牌无效'),
                 (self.registration(app='mail'), '岛的内容无效'),
                 (self.registration(environment='staging'), '推送环境无效'),
                 (self.registration(op='dance'), '不认识的操作')]
        for data, words in cases:
            status, answer = await self.post('activity', data)
            self.assertEqual((status, answer['error']), (400, words))
        self.assertEqual(self.activities(), [])
        self.assertEqual(await self.post('island-test', {'device': self.devices[0], 'app': 'claude', 'chat': 'chat-1'}),
                         (400, {'error': '先在这部手机上开一个岛，再点这个。'}))

    async def test_the_same_island_registers_again_and_unregisters(self):
        await self.post('activity', self.registration())
        await self.post('activity', self.registration(state='waiting', since=1761630000))
        kept = self.activities()
        self.assertEqual(len(kept), 1)
        self.assertEqual((kept[0]['state'], kept[0]['since']), ('waiting', 1761630000))
        self.assertEqual(await self.post('activity', self.registration(op='unregister')), (200, {'ok': True}))
        self.assertEqual(self.activities(), [])
        self.assertEqual((await self.post('island-test', {'device': self.devices[0], 'app': 'claude', 'chat': 'chat-1'}))[0], 400)

    async def test_a_dead_island_token_is_dropped(self):
        self.sender.answers = [(410, 'Unregistered')]
        await self.post('activity', self.registration())
        status, answer = await self.post('island-test', {'device': self.devices[0], 'app': 'claude', 'chat': 'chat-1'})
        self.assertEqual(status, 400)
        self.assertIn('苹果不认这个岛的令牌', answer['error'])
        self.assertEqual(self.activities(), [])
        self.assertEqual(len(self.sender.sent), 1)

    async def test_a_topic_the_key_may_not_send_is_said_with_the_handoff_hint(self):
        self.sender.answers = [(400, 'TopicDisallowed')]
        await self.post('activity', self.registration())
        status, answer = await self.post('island-test', {'device': self.devices[0], 'app': 'claude', 'chat': 'chat-1'})
        self.assertEqual(status, 400)
        self.assertIn('主题', answer['error'])
        self.assertEqual(len(self.activities()), 1)  # the island is still there to try again

    async def test_a_start_token_is_kept_and_a_new_password_drops_it(self):
        await self.post('start-token', {'token': 'ef' * 32, 'environment': 'production'})
        self.assertEqual([(row['owner'], row['environment']) for row in self.starts()],
                         [(self.store.owner(self.tokens[0]), 'production')])
        await self.post('start-token', {'token': 'ef' * 32, 'environment': 'development'}, user=1)
        self.assertEqual([(row['owner'], row['environment']) for row in self.starts()],
                         [(self.store.owner(self.tokens[1]), 'development')])
        await asyncio.to_thread(self.store.change_password, self.tokens[1], 'password-for-bob', 'a-new-password-for-bob')
        self.assertEqual(self.starts(), [])


if __name__ == '__main__':
    unittest.main()
