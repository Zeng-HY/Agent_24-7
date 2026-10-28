"""Can the relay's APNs key send to the iPhone's 灵动岛 (Live Activities)? Asks Apple three times, for a made-up phone,
and says what the answers mean. Nothing is saved or restarted, nothing reaches a phone, the key is never shown.

    sudo /opt/agent-relay-027/.venv/bin/python check-island-topic.py

The key is the one the service uses: /etc/agent-relay/push.env (configure-push.py), read the way the service reads it
(relay_push.from_env, imported from the installed service, so this file can be uploaded on its own). One provider
token serves all three, on one HTTP/2 connection: Apple turns away a key whose tokens change too often.

1. An ordinary notification to the topic the key was made for (com.pocketagentdesk.teleply). Apple should answer
   BadDeviceToken: it took the key, only the phone is made up. Anything else is trouble with the key itself.
2. The same to a topic nobody has. Apple should turn it away, which shows it looks at the topic before the phone;
   only then does the third answer mean something.
3. A Live Activity update: push type liveactivity, topic com.pocketagentdesk.teleply.push-type.liveactivity.
   BadDeviceToken: the key may send to the 灵动岛. Turned away like the second: it may not.

A real Live Activity token (phase 0 of docs/handoff-dynamic-island.md) settles it for good.
"""
import asyncio
import json
import os
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, '/opt/agent-relay-027')  # the running service's code before a copy beside this file
try:
    import relay_push  # noqa: E402
except ImportError:
    raise SystemExit('用 /opt/agent-relay-027/.venv/bin/python 运行：系统自带的 python3 缺推送用的库') from None

ENV = Path('/etc/agent-relay/push.env')
HOST = 'https://api.push.apple.com'  # production: the key is a Production key, and TestFlight builds use production
PHONE = '00' * 32                    # the made-up phone configure-push.py asks for
NOBODY = relay_push.TOPIC + '.no-such-topic'
ISLAND = relay_push.TOPIC + '.push-type.liveactivity'
TOOK = ('BadDeviceToken', 'DeviceTokenNotForTopic')  # Apple took the key for that topic; the phone is what it refused
WHY = {
    'InvalidProviderToken': '苹果说这把密钥对这个主题无效。',
    'TopicDisallowed': '苹果说这把密钥不能发这个主题。',
    'BadTopic': '苹果说这个主题不对。',
    'BadEnvironmentKeyIdInToken': '这把密钥不是生产环境（Production）的。',
    'ExpiredProviderToken': '签名的时间不对：看看服务器的时钟。',
    'TooManyProviderTokenUpdates': '密钥签得太勤：过 20 分钟再试一次。',
    'InvalidPushType': '苹果不认这种推送类型。',
    'Forbidden': '苹果拒绝了：看看开发者账号是否正常。',
}


def read_env(path):
    """push.env as configure-push.py writes it: NAME="value" lines, each value a JSON string."""
    values = {}
    for line in path.read_text(encoding='utf-8').splitlines():
        name, sep, value = line.partition('=')
        if sep and name.strip():
            try:
                values[name.strip()] = json.loads(value)
            except ValueError:
                values[name.strip()] = value.strip()
    return values


def checks(now):
    """(what, topic, push type, payload) for the three questions, in the order the module docstring gives."""
    plain = {'aps': {'alert': {'title': '遥应', 'body': '设置检查'}}}
    island = {'aps': {'timestamp': now, 'event': 'update',
                      'content-state': {'state': 'working', 'since': now, 'turn': now}}}
    return [('普通通知', relay_push.TOPIC, 'alert', plain),
            ('对照：没人用的主题', NOBODY, 'alert', plain),
            ('灵动岛', ISLAND, 'liveactivity', island)]


async def ask(sender, questions):
    """(what, topic, status, reason, HTTP version) for each question; status 0 when Apple could not be reached."""
    bearer = sender.bearer()
    answers = []
    for what, topic, push_type, payload in questions:
        headers = {'authorization': 'bearer ' + bearer, 'apns-topic': topic, 'apns-push-type': push_type,
                   'apns-priority': '10', 'apns-expiration': '0', 'content-type': 'application/json'}
        body = json.dumps(payload, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
        try:
            response = await sender.client.post(f'{HOST}/3/device/{PHONE}', content=body, headers=headers)
        except Exception as exc:  # no route to Apple, a TLS problem: said by name, without the request
            answers.append((what, topic, 0, type(exc).__name__, ''))
            continue
        reason = ''
        if response.status_code != 200:
            try:
                reason = str(response.json().get('reason', ''))
            except (ValueError, AttributeError):
                reason = ''
        answers.append((what, topic, response.status_code, reason, response.http_version))
    return answers


async def run(sender, questions):
    try:
        return await ask(sender, questions)
    finally:
        await sender.close()


def took(answer):
    return answer[2] == 400 and answer[3] in TOOK


def why(answer):
    status, reason = answer[2], answer[3]
    if status == 0:
        return f'连不上苹果的推送服务 api.push.apple.com（{reason}）。'
    return WHY.get(reason) or f'苹果的回答是 {status} {reason}'.rstrip() + '。'


def verdict(answers):
    """(what the answers mean, exit code): 0 the key may send to the 灵动岛, 1 it may not, 2 this check cannot tell."""
    plain, nobody, island = answers
    if plain[2] == 0:
        return why(plain) + '先查服务器连不连得上苹果（README-027.md「开启遥应通知」第 1 步）。', 2
    if not took(plain):
        return '普通通知也没被收下，是密钥本身的问题，先别管灵动岛。' + why(plain), 2
    if took(nobody):
        return '没人用的主题也被当成收下了，说明苹果先看手机、后看主题，这个办法看不出来。等手机上有了真的岛，用真令牌再试。', 2
    if took(island):
        return '能发。这把密钥认灵动岛的主题，不用换密钥。', 0
    return ('不能发。' + why(island) + '要在苹果后台给这把密钥加上灵动岛的主题，或者新建一把'
            '（docs/handoff-dynamic-island.md 第 3.5 节）。'), 1


def main():
    if os.geteuid() != 0:
        raise SystemExit('用 sudo 运行：要读 /etc/agent-relay/push.env')
    try:
        values = read_env(ENV)
    except OSError:
        raise SystemExit('这台服务器还没装推送密钥（没有 /etc/agent-relay/push.env）：先运行 configure-push.py') from None
    sender = relay_push.from_env(values)
    if sender is None:
        raise SystemExit('读不出服务用的推送密钥：push.env 不完整，或者 cryptography、httpx 没装（先运行 update-027.sh）')
    print('正在问苹果，发给一部不存在的手机，不会推到任何手机上…')
    answers = asyncio.run(run(sender, checks(int(time.time()))))
    for answer in answers:
        what, topic, status, reason, version = answer
        said = f'{status} {reason}'.strip() if status else '连不上'
        print(f'{what}（{topic}）：{said}' + (f'，{version}' if version else ''))
    text, code = verdict(answers)
    print('结论：' + text)
    raise SystemExit(code)


if __name__ == '__main__':
    main()
