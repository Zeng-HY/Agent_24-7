"""Program assets are immutable; frozen builds write only to per-user data."""
import os
from pathlib import Path
import sys

ASSETS=Path(getattr(sys,'_MEIPASS',Path(__file__).resolve().parent))
DATA=Path(os.environ['AR_DATA_DIR']).resolve() if os.environ.get('AR_DATA_DIR') else (
    Path(os.environ['LOCALAPPDATA'])/'AgentRemote'/'Data' if getattr(sys,'frozen',False) else ASSETS)


def command(mode):
    if getattr(sys,'frozen',False): return [sys.executable,mode]
    return [str(ASSETS/'.venv/Scripts/pythonw.exe'),str(ASSETS/'relay_desktop.py'),mode]
