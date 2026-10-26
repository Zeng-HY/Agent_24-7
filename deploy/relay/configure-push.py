"""Switch on 遥应通知 on the relay server: the APNs key that lets it ask Apple to deliver to the iPhone app.

    sudo /opt/agent-relay-027/.venv/bin/python configure-push.py

Run it from the unpacked package (next to relay_push.py), after update-027.sh. It asks where the .p8 key is (a file
uploaded to the server, or its text pasted), its Key ID and the Team ID; never as arguments, and the key is never
shown. It then asks Apple once, for a made-up phone: Apple answering BadDeviceToken means it took the key, and only
then is anything saved: /etc/agent-relay/push.env (root 0600), which systemd reads for the service through a drop-in
(agent-relay-027.service.d/push.conf); the service is restarted. Nothing is saved when anything fails. The uploaded
file is left where it was: delete it afterwards.
"""
import asyncio
import base64
import json
import os
from pathlib import Path
import re
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import relay_push  # noqa: E402

SERVICE = 'agent-relay-027.service'
TEAM = 'CPSVJ7235A'  # the Apple developer team of 遥应 (App Store Connect, Codemagic)
DROP_IN = Path('/etc/systemd/system/agent-relay-027.service.d/push.conf')
# Apple's answers to a made-up phone, and what they say about the key (handling-notification-responses-from-apns)
TOOK = ('BadDeviceToken', 'DeviceTokenNotForTopic')
WHY = {
    'InvalidProviderToken': '苹果不认这把密钥：Key ID、Team ID 和 .p8 文件要是同一把。',
    'BadEnvironmentKeyIdInToken': '这把密钥不是生产环境（Production）的：TestFlight 的遥应用生产环境。',
    'TopicDisallowed': '这把密钥不能给遥应发：建密钥时要勾上 com.pocketagentdesk.teleply。',
    'BadTopic': '遥应的 Bundle ID 不对。',
    'Forbidden': '苹果拒绝了：看看开发者账号是否正常。',
}


def read_key():
    where = input('.p8 文件在服务器上的路径（直接回车就改为粘贴内容）：').strip()
    if where:
        try:
            return Path(where).read_bytes(), where
        except OSError as exc:
            raise SystemExit(f'读不到 {where}：{exc.strerror or type(exc).__name__}')
    print('把 .p8 文件的全部内容粘贴进来（从 -----BEGIN PRIVATE KEY----- 到 -----END PRIVATE KEY-----）：')
    lines = []
    while not lines or 'END PRIVATE KEY' not in lines[-1]:
        try:
            lines.append(input())
        except EOFError:
            break
    return ('\n'.join(lines).strip() + '\n').encode('ascii', 'replace'), ''


async def ask_apple(pem, key_id, team_id):
    sender = relay_push.Apns(pem, key_id, team_id)
    try:
        return await sender.send('production', '00' * 32, {'aps': {'alert': {'title': '遥应', 'body': '设置检查'}}}, '', 0)
    finally:
        await sender.close()


def main():
    if os.geteuid() != 0:
        raise SystemExit('用 sudo 运行')
    pem, uploaded = read_key()
    try:
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.hazmat.primitives.serialization import load_pem_private_key
        key = load_pem_private_key(pem, password=None)
    except ImportError:
        raise SystemExit('缺 cryptography：先运行 update-027.sh，再用 /opt/agent-relay-027/.venv/bin/python 运行这个脚本')
    except ValueError:
        raise SystemExit('这不是一把能读的 .p8 密钥（要苹果网站上下载的那个文件），没有保存。')
    if not isinstance(key, ec.EllipticCurvePrivateKey):
        raise SystemExit('这不是苹果推送用的那种密钥（应为 P-256），没有保存。')
    key_id = input('Key ID（建密钥的页面上，10 位）：').strip().upper()
    if not re.fullmatch(r'[A-Z0-9]{10}', key_id):
        raise SystemExit('Key ID 应为 10 位字母和数字，没有保存。')
    team_id = input(f'Team ID [{TEAM}]：').strip().upper() or TEAM
    if not re.fullmatch(r'[A-Z0-9]{10}', team_id):
        raise SystemExit('Team ID 应为 10 位字母和数字，没有保存。')
    print('正在问苹果这把密钥能不能用（发给一部不存在的手机）…')
    try:
        status, reason = asyncio.run(ask_apple(pem, key_id, team_id))
    except Exception as exc:  # no route to Apple, a TLS problem
        raise SystemExit(f'连不上苹果的推送服务 api.push.apple.com（{type(exc).__name__}），没有保存。') from None
    if not (status == 400 and reason in TOOK):
        raise SystemExit((WHY.get(reason) or f'苹果的回答是 {status} {reason}，不像是收下了这把密钥。') + '没有保存。')
    print('苹果收下了这把密钥。')
    directory = Path('/etc/agent-relay')
    directory.mkdir(mode=0o700, exist_ok=True)
    os.umask(0o077)
    values = {'AR_APNS_KEY': base64.b64encode(pem).decode('ascii'), 'AR_APNS_KEY_ID': key_id, 'AR_APNS_TEAM_ID': team_id,
              'AR_APNS_TOPIC': relay_push.TOPIC}
    path = directory / 'push.env'
    temp = directory / 'push.env.new'
    temp.write_text(''.join(k + '=' + json.dumps(v) + '\n' for k, v in values.items()), encoding='utf-8')
    temp.chmod(0o600)
    temp.replace(path)
    DROP_IN.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
    DROP_IN.write_text('[Service]\nEnvironmentFile=-/etc/agent-relay/push.env\n', encoding='utf-8')
    DROP_IN.chmod(0o644)
    subprocess.run(['systemctl', 'daemon-reload'], check=True)
    subprocess.run(['systemctl', 'restart', SERVICE], check=True)
    if subprocess.run(['systemctl', 'is-active', '--quiet', SERVICE]).returncode != 0:
        raise SystemExit(f'已保存，但服务没起来：journalctl -u {SERVICE} -n 50')
    print('已开启：遥应通知。在 iPhone 上的遥应里：设置 → 手机通知 → 打开并试推一条。')
    if uploaded:
        print(f'上传的密钥文件已经用不着了，删掉它：rm {uploaded}')


if __name__ == '__main__':
    main()
