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

    async def send(self, environment, token, payload, collapse, expires):
        self.sent.append({'environment': environment, 'token': token, 'payload': payload, 'collapse': collapse, 'expires': expires})
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
        self.assertEqual(sent['payload'], {'aps': {'alert': {'title': 'Claude · alice的电脑', 'body': '有个对话在等你处理'}, 'sound': 'default',
                                                   'thread-id': sent['collapse']},
                                           'teleply': {'d': self.devices[0], 'a': 'claude', 'c': 'chat-1'}})
        self.assertEqual(len(sent['collapse']), 24)
        self.assertGreater(sent['expires'], 1_000_000_000)
        # the same event again (the relay came back and asked for the last ten minutes), then another kind
        await self.events[0].put(event)
        await self.events[0].put({**event, 'id': 'e2', 'kind': 'done'})
        self.assertTrue(await self.until(lambda: len(self.sender.sent) == 2))
        await asyncio.sleep(.2)
        self.assertEqual([s['payload']['aps']['alert']['body'] for s in self.sender.sent], ['有个对话在等你处理', '有个对话好了'])
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


if __name__ == '__main__':
    unittest.main()
