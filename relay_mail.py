"""SMTP secrets stay in a private server environment file; never log messages."""
from email.message import EmailMessage
from email.utils import formataddr
import os
import smtplib
import ssl


class Mailer:
    def __init__(self, origin):
        self.origin=origin
        self.host=os.environ.get('AR_SMTP_HOST','')
        self.user=os.environ.get('AR_SMTP_USER','')
        self.password=os.environ.get('AR_SMTP_PASSWORD','')
        self.sender=os.environ.get('AR_SMTP_FROM',self.user)
        self.port=int(os.environ.get('AR_SMTP_PORT','465'))
        self.verified=os.environ.get('AR_SMTP_VERIFIED')=='true'

    @property
    def ready(self):
        return bool(self.host and self.sender and self.user and self.password and self.verified)

    def send(self, address, kind, code, pin=''):
        if not self.ready: raise ValueError('邮箱服务暂未启用')
        message=EmailMessage()
        message['From']=formataddr(('Agent Remote',self.sender));message['To']=address
        reset=kind=='reset'
        # the code first (typed on the page that asked for it), the link for another device; 30 minutes, once
        message['Subject']=(f'验证码 {pin} · ' if pin else '')+('重置密码' if reset else '验证邮箱')+' · Agent Remote'
        url=self.origin+'/account#'+('reset=' if reset else 'verify=')+code
        message.set_content((f'验证码：{pin}\n\n' if pin else '')+('或打开链接：' if pin else '打开链接：')+url+'\n\n30 分钟内有效。不是你本人操作，忽略即可。')
        try:
            if self.port==465:
                smtp=smtplib.SMTP_SSL(self.host,self.port,timeout=15,context=ssl.create_default_context())
            else:
                smtp=smtplib.SMTP(self.host,self.port,timeout=15)
                smtp.starttls(context=ssl.create_default_context())
            with smtp:
                smtp.login(self.user,self.password)
                smtp.send_message(message)
        except (OSError,smtplib.SMTPException):
            raise ValueError('邮件发送失败，请稍后重试') from None
