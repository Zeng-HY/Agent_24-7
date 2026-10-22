"""Interactive server-only SMTP setup. Never pass credentials as arguments."""
from email.message import EmailMessage
import getpass
import json
import os
from pathlib import Path
import secrets
import smtplib
import ssl
import subprocess


def main():
    if os.geteuid()!=0:raise SystemExit('Run with sudo')
    host=input('SMTP 主机 [smtp.qq.com]：').strip() or 'smtp.qq.com'
    port=int(input('端口 [465]：').strip() or '465')
    user=input('发信账号：').strip()
    sender=input('发信地址 [同账号]：').strip() or user
    password=getpass.getpass('SMTP 授权码（不显示）：')
    recipient=input('用于收取验证邮件的邮箱：').strip()
    if any('\r' in x or '\n' in x for x in (host,user,sender,password,recipient)):raise ValueError('Invalid input')
    challenge=secrets.token_hex(3).upper()
    message=EmailMessage();message['From']=sender;message['To']=recipient
    message['Subject']='Agent Remote 发信验证';message.set_content('验证代码：'+challenge)
    try:
        smtp=smtplib.SMTP_SSL(host,port,timeout=20,context=ssl.create_default_context()) if port==465 else smtplib.SMTP(host,port,timeout=20)
        with smtp:
            if port!=465:smtp.starttls(context=ssl.create_default_context())
            smtp.login(user,password);smtp.send_message(message)
    except (smtplib.SMTPException,OSError):raise SystemExit('发送失败，未保存配置。请检查邮箱服务设置。') from None
    if getpass.getpass('请输入邮件中的验证代码（不显示）：').strip().upper()!=challenge:
        raise SystemExit('未确认收到邮件，未启用注册。')
    directory=Path('/etc/agent-relay');directory.mkdir(mode=0o700,exist_ok=True)
    os.umask(0o077)
    values={'AR_SMTP_HOST':host,'AR_SMTP_PORT':str(port),'AR_SMTP_USER':user,'AR_SMTP_FROM':sender,
            'AR_SMTP_PASSWORD':password,'AR_SMTP_VERIFIED':'true'}
    temp=directory/'smtp.env.new';temp.write_text(''.join(k+'='+json.dumps(v,ensure_ascii=False)+'\n' for k,v in values.items()))
    temp.chmod(0o600);temp.replace(directory/'smtp.env')
    subprocess.run(['systemctl','restart','agent-relay-027.service'],check=True)
    print('投递已验证，邮箱注册和找回密码已启用。')


if __name__=='__main__':main()
