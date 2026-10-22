"""Local consent window: sign in, obtain a binding grant, enroll, then log out.

Never stores a password or prints authentication responses. No tunnel is started.
"""
import argparse
from http.cookiejar import CookieJar
import json
import os
from pathlib import Path
import queue
import threading
from types import SimpleNamespace
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener, ProxyHandler, HTTPCookieProcessor

from relay_device import DEFAULT_CONFIG, NoRedirect, enroll


def account_request(opener, origin, action, data):
    request = Request(origin+'/account/'+action, data=json.dumps(data).encode(),
        headers={'Content-Type':'application/json','Origin':origin}, method='POST')
    try:
        with opener.open(request, timeout=30) as response:
            return json.load(response)
    except HTTPError as exc:
        status = exc.code
        try:
            payload = json.loads(exc.read(8192))
            error = payload.get('error') if isinstance(payload, dict) else None
        except (ValueError, OSError):
            error = None
        finally:
            exc.close()
        allowed = {'账号或密码错误','尝试过于频繁，请稍后重试','密码已变化，请重新登录'}
        raise ValueError(error if error in allowed else f'账号服务请求失败（HTTP {status}），请把此提示告诉管理员。') from None


def login_and_bind(args, password):
    if args.config.exists():
        raise ValueError('这台电脑已有绑定配置，请先检查账号页，不要重复绑定。')
    if not args.certificate.is_file() or not args.frpc.is_file():
        raise ValueError('本机缺少隧道程序或服务器公开证书，请联系管理员。')
    cookies = CookieJar()
    opener = build_opener(ProxyHandler({}), NoRedirect(), HTTPCookieProcessor(cookies))
    logged_in = False
    try:
        account_request(opener, args.origin, 'login', {'name':args.account,'password':password})
        password = None
        logged_in = True
        grant = account_request(opener, args.origin, 'bind', {})
        return enroll(args, code=grant['code'], confirmed=True)
    finally:
        if logged_in:
            try:
                account_request(opener, args.origin, 'logout', {})
            except (ValueError, OSError):
                pass
        cookies.clear()


def build_window(account=''):
    import tkinter as tk
    from tkinter import ttk
    root = tk.Tk()
    root.title('Agent Remote · 绑定这台电脑')
    root.geometry('570x470')
    root.resizable(False, False)
    frame = ttk.Frame(root, padding=24)
    frame.pack(fill='both', expand=True)
    ttk.Label(frame, text='登录并绑定这台电脑', font=('Microsoft YaHei UI',16,'bold')).pack(anchor='w',pady=(0,10))
    ttk.Label(frame, text='服务器：https://8.166.15.235').pack(anchor='w')
    ttk.Label(frame, text='不需要复制绑定码。密码仅用于本次登录，不会保存。').pack(anchor='w',pady=(4,14))
    ttk.Label(frame, text='账号').pack(anchor='w')
    name = ttk.Entry(frame, font=('Microsoft YaHei UI',11))
    name.pack(fill='x',pady=(4,10)); name.insert(0,account)
    ttk.Label(frame, text='密码').pack(anchor='w')
    password = ttk.Entry(frame, show='●', font=('Microsoft YaHei UI',11))
    password.pack(fill='x',pady=(4,12))
    ttk.Label(frame, text='点击下方按钮，即确认允许此账号远程访问这台电脑。',wraplength=510).pack(anchor='w',pady=(0,12))
    status = tk.StringVar(value='绑定后还需启用专属隧道；现有连接不受影响。')
    messages = queue.Queue()
    def worker(args, secret):
        try:
            result = login_and_bind(args, secret)
            messages.put((True, '绑定成功！设备 ID：\n'+result['id']+'\n可以关闭窗口，继续启用专属隧道。'))
        except ValueError as exc:
            messages.put((False, str(exc)))
        except (URLError, TimeoutError):
            messages.put((False, '连接未完成。请先查看账号页是否已出现电脑，不要反复点击绑定。'))
        except Exception:
            messages.put((False, '本机绑定未完成，请联系管理员检查；不要重复绑定。'))
    def submit():
        username = name.get().strip().lower()
        secret = password.get()
        if not username or not secret:
            status.set('请填写账号和密码。'); return
        frp = Path(os.environ['LOCALAPPDATA'])/'AgentRemote'/'frp'
        args = SimpleNamespace(config=DEFAULT_CONFIG,origin='https://8.166.15.235',account=username,
            label='我的电脑',port=18768,code_from_clipboard=False,
            certificate=frp/'config'/'server.crt',frpc=frp/'frp_0.71.1_windows_amd64'/'frpc.exe')
        button.state(['disabled']); name.state(['disabled']); password.delete(0,'end'); password.state(['disabled'])
        root.protocol('WM_DELETE_WINDOW', lambda: status.set('正在完成绑定，请稍候；完成后即可关闭。'))
        status.set('正在登录并绑定，请稍候……')
        threading.Thread(target=worker,args=(args,secret),daemon=True).start()
    button = ttk.Button(frame, text='登录并绑定这台电脑',command=submit)
    button.pack(fill='x',ipady=8)
    ttk.Label(frame,textvariable=status,wraplength=510).pack(anchor='w',pady=(14,0))
    def poll():
        try:
            ok, message = messages.get_nowait()
        except queue.Empty:
            root.after(100,poll); return
        status.set(message)
        root.protocol('WM_DELETE_WINDOW',root.destroy)
        if not ok:
            button.state(['!disabled']); name.state(['!disabled']); password.state(['!disabled']); password.focus_set()
        root.after(100,poll)
    root.after(100,poll)
    password.focus_set() if account else name.focus_set()
    return root


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--account',default='')
    options = parser.parse_args()
    build_window(options.account).mainloop()
