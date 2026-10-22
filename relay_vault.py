"""DPAPI-bound device secret, never a user's password. Atomic private files."""
import json
import os
from pathlib import Path
import secrets
from app_paths import DATA
from relay_device import private_directory


def load(path=None):
    import win32crypt
    path=Path(path or DATA/'device-v2.bin')
    if not path.exists(): return None
    raw=win32crypt.CryptUnprotectData(path.read_bytes(),None,None,None,0)[1]
    return json.loads(raw.decode('utf-8'))


def save(value,path=None):
    import win32crypt
    path=Path(path or DATA/'device-v2.bin')
    private_directory(path.parent)
    encrypted=win32crypt.CryptProtectData(json.dumps(value).encode('utf-8'),'Agent Remote device',None,None,None,0)
    temporary=path.with_name(path.name+'.'+secrets.token_hex(4)+'.tmp')
    temporary.write_bytes(encrypted)
    os.replace(temporary,path)
