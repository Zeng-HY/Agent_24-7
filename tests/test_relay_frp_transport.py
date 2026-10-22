"""Opt-in local frp 0.71.1 transport test; no cloud or live gateway changes.

Set RELAY_FRP_DIR and RELAY_OPENSSL to installed binaries. All listeners use
loopback and disposable random ports; all credentials are generated for this test.
"""
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import tempfile
import threading
import time
import unittest


def port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0))
        return sock.getsockname()[1]


class Echo(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def do_GET(self):
        self.send_response(200);self.end_headers();self.wfile.write(b'isolated-device')


@unittest.skipUnless(os.environ.get('RELAY_FRP_DIR') and os.environ.get('RELAY_OPENSSL'), 'explicit local frp binaries required')
class FrpTests(unittest.TestCase):
    def test_dedicated_token_port_allowlist_tls_and_reconnect(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)
            processes=[]
            extra = {'creationflags':subprocess.CREATE_NO_WINDOW} if os.name=='nt' else {}
            def spawn(args):
                p=subprocess.Popen(args,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,**extra)
                processes.append(p)
                return p
            def stop(p):
                if p.poll() is None:p.terminate()
                p.wait(timeout=10)
            def get(remote):
                try:
                    c=http.client.HTTPConnection('127.0.0.1',remote,timeout=.5)
                    c.request('GET','/');r=c.getresponse();body=r.read();c.close()
                    return body==b'isolated-device'
                except OSError:return False
            def wait(remote):
                end=time.monotonic()+15
                while time.monotonic()<end:
                    if get(remote):return True
                    time.sleep(.1)
                return False
            binary=Path(os.environ['RELAY_FRP_DIR'])
            subprocess.run([os.environ['RELAY_OPENSSL'],'req','-x509','-newkey','rsa:2048','-nodes',
                '-keyout',str(folder/'key.pem'),'-out',str(folder/'cert.pem'),'-days','1',
                '-subj','/CN=127.0.0.1','-addext','subjectAltName=IP:127.0.0.1'],
                check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,**extra)
            echo=ThreadingHTTPServer(('127.0.0.1',0),Echo)
            threading.Thread(target=echo.serve_forever,daemon=True).start()
            ingress,remote,forbidden=port(),port(),port()
            token=secrets.token_urlsafe(32)
            (folder/'token').write_text(token)
            server=folder/'frps.toml'
            server.write_text(f'''bindAddr="127.0.0.1"
bindPort={ingress}
proxyBindAddr="127.0.0.1"
allowPorts=[{{single={remote}}}]
maxPortsPerClient=1
auth.method="token"
auth.additionalScopes=["HeartBeats","NewWorkConns"]
auth.tokenSource.type="file"
auth.tokenSource.file.path={json.dumps(str(folder/'token'))}
transport.tls.force=true
transport.tls.certFile={json.dumps(str(folder/'cert.pem'))}
transport.tls.keyFile={json.dumps(str(folder/'key.pem'))}
''')
            def client(name,credential,target):
                config=folder/(name+'.toml')
                config.write_text(f'''serverAddr="127.0.0.1"
serverPort={ingress}
loginFailExit=false
auth.method="token"
auth.token={json.dumps(credential)}
auth.additionalScopes=["HeartBeats","NewWorkConns"]
transport.tls.enable=true
transport.tls.trustedCaFile={json.dumps(str(folder/'cert.pem'))}
transport.tls.serverName="127.0.0.1"
[[proxies]]
name={json.dumps(name)}
type="tcp"
localIP="127.0.0.1"
localPort={echo.server_port}
remotePort={target}
''')
                return spawn([str(binary/'frpc.exe'),'-c',str(config)])
            try:
                server_process=spawn([str(binary/'frps.exe'),'-c',str(server)])
                bad=client('wrong-account',secrets.token_urlsafe(32),remote)
                time.sleep(2)
                self.assertFalse(get(remote))
                stop(bad)
                bad=client('wrong-route',token,forbidden)
                time.sleep(2)
                self.assertFalse(get(forbidden))
                stop(bad)
                good=client('own-device',token,remote)
                self.assertTrue(wait(remote),'authorized tunnel failed')
                stop(server_process)
                self.assertFalse(get(remote))
                server_process=spawn([str(binary/'frps.exe'),'-c',str(server)])
                self.assertTrue(wait(remote),'frpc did not reconnect after server restart')
                self.assertIsNone(good.poll())
            finally:
                for p in processes:stop(p)
                echo.shutdown();echo.server_close()


if __name__=='__main__':unittest.main()
