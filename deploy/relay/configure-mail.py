"""Switch on 邮箱注册 and 忘记密码 on the relay server: the mailbox that sends the codes.

    sudo python3 configure-mail.py

It asks for the sending address and its SMTP authorization code (never as arguments, never shown), fills in the
server for the usual mailboxes, sends a test mail with a code, and only the code typed back switches mail on
(/etc/agent-relay/smtp.env, root 0600; the service is restarted). Nothing is saved when anything fails.
"""
from email.message import EmailMessage
from email.utils import formataddr
import getpass
import json
import os
from pathlib import Path
import re
import secrets
import smtplib
import socket
import ssl
import subprocess

SERVICE = 'agent-relay-027.service'
# by the part after @: (server, port); 465 is SSL, 587 STARTTLS
PRESETS = {
    'qq.com': ('smtp.qq.com', 465), 'foxmail.com': ('smtp.qq.com', 465), 'vip.qq.com': ('smtp.qq.com', 465),
    '163.com': ('smtp.163.com', 465), '126.com': ('smtp.126.com', 465), 'yeah.net': ('smtp.yeah.net', 465),
    'sina.com': ('smtp.sina.com', 465), 'sohu.com': ('smtp.sohu.com', 465), 'aliyun.com': ('smtp.aliyun.com', 465),
    '139.com': ('smtp.139.com', 465), 'gmail.com': ('smtp.gmail.com', 465), 'outlook.com': ('smtp-mail.outlook.com', 587),
    'hotmail.com': ('smtp-mail.outlook.com', 587), 'live.com': ('smtp-mail.outlook.com', 587), 'icloud.com': ('smtp.mail.me.com', 587),
}
# where the authorization code is (it is not the mailbox password)
WHERE = {
    'smtp.qq.com': 'QQ 邮箱 → 设置 → 账号 → POP3/SMTP 服务 → 开启，生成授权码',
    'smtp.163.com': '163 邮箱 → 设置 → POP3/SMTP/IMAP → 开启 SMTP，新增授权密码',
    'smtp.126.com': '126 邮箱 → 设置 → POP3/SMTP/IMAP → 开启 SMTP，新增授权密码',
    'smtp.gmail.com': 'Google 账号 → 安全性 → 两步验证 → 应用专用密码',
}


def connect(host, port):
    context = ssl.create_default_context()
    if port == 465:
        return smtplib.SMTP_SSL(host, port, timeout=20, context=context)
    smtp = smtplib.SMTP(host, port, timeout=20)
    smtp.starttls(context=context)
    return smtp


def why(exc, host, port):
    """What went wrong, in a line someone can act on."""
    if isinstance(exc, smtplib.SMTPAuthenticationError):
        return '登录被拒：授权码不对，或这个邮箱还没开启 SMTP。'
    if isinstance(exc, (smtplib.SMTPSenderRefused, smtplib.SMTPRecipientsRefused)):
        return '邮件被拒收：发信地址要和登录的邮箱一致。'
    if isinstance(exc, ssl.SSLError):
        return f'加密握手失败：{port} 端口的加密方式不对（465 是 SSL，587 是 STARTTLS）。'
    if isinstance(exc, socket.gaierror):
        return f'找不到服务器 {host}。'
    if isinstance(exc, (TimeoutError, ConnectionError, OSError)) and not isinstance(exc, smtplib.SMTPException):
        return f'连不上 {host}:{port}：服务器出站端口可能被拦（云服务器常封 25，用 465 或 587）。'
    return '发送失败：' + type(exc).__name__


def main():
    if os.geteuid() != 0:
        raise SystemExit('用 sudo 运行')
    sender = input('发信邮箱：').strip()
    if not re.fullmatch(r'[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+', sender):
        raise SystemExit('邮箱地址不对')
    host, port = PRESETS.get(sender.split('@', 1)[1].lower(), ('', 465))
    given = input(f'SMTP 服务器 [{host}:{port}]：' if host else 'SMTP 服务器（如 smtp.example.com:465）：').strip()
    if given:
        host, _, number = given.partition(':')
        port = int(number or 465)
    if not host:
        raise SystemExit('需要 SMTP 服务器')
    if host in WHERE:
        print('授权码在：' + WHERE[host])
    password = getpass.getpass('授权码（不显示）：')
    recipient = input(f'测试邮件发到 [{sender}]：').strip() or sender
    if any('\r' in x or '\n' in x for x in (host, sender, password, recipient)):
        raise SystemExit('输入里有换行')
    challenge = f'{secrets.randbelow(10**6):06d}'
    message = EmailMessage()
    message['From'] = formataddr(('Agent Remote', sender))
    message['To'] = recipient
    message['Subject'] = f'测试 {challenge} · Agent Remote'
    message.set_content('测试代码：' + challenge)
    try:
        with connect(host, port) as smtp:
            smtp.login(sender, password)
            smtp.send_message(message)
    except (smtplib.SMTPException, OSError) as exc:
        raise SystemExit(why(exc, host, port) + ' 没有保存。') from None
    print(f'已发到 {recipient}（找不到就看垃圾邮件）。')
    if input('邮件里的测试代码：').strip() != challenge:
        raise SystemExit('代码不对，没有保存。')
    directory = Path('/etc/agent-relay')
    directory.mkdir(mode=0o700, exist_ok=True)
    os.umask(0o077)
    values = {'AR_SMTP_HOST': host, 'AR_SMTP_PORT': str(port), 'AR_SMTP_USER': sender, 'AR_SMTP_FROM': sender,
              'AR_SMTP_PASSWORD': password, 'AR_SMTP_VERIFIED': 'true'}
    # other settings in the same file (AR_ACCOUNT_LIMIT, AR_DEVICE_LIMIT) stay as they are
    path = directory / 'smtp.env'
    kept = [line for line in (path.read_text(encoding='utf-8').splitlines() if path.exists() else [])
            if line.split('=', 1)[0].strip() not in values]
    temp = directory / 'smtp.env.new'
    temp.write_text(''.join(line + '\n' for line in kept) + ''.join(k + '=' + json.dumps(v, ensure_ascii=False) + '\n' for k, v in values.items()), encoding='utf-8')
    temp.chmod(0o600)
    temp.replace(path)
    subprocess.run(['systemctl', 'restart', SERVICE], check=True)
    if subprocess.run(['systemctl', 'is-active', '--quiet', SERVICE]).returncode != 0:
        raise SystemExit(f'已保存，但服务没起来：journalctl -u {SERVICE} -n 50')
    print('已开启：邮箱注册和找回密码。')


if __name__ == '__main__':
    main()
