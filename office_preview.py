"""Word, Excel and PowerPoint files shown as PDF on the phones and the web (10-27).

This computer's own Office converts each version of a file (path, size, modification time) once, into the data
folder. Office opens it read-only with macros off, in an instance of its own that is closed afterwards (PowerPoint, a
single instance, is never closed when the user had it open); one conversion runs at a time and is stopped after
DEADLINE. Without the Office program a file needs, nothing is offered and the file pages stay as they were.
"""
import ctypes
from ctypes import wintypes
import hashlib
import os
from pathlib import Path
import signal
import threading
import time

import app_paths
from chat_history import HistoryError

PROGRAMS={'word':('Word.Application','WINWORD.EXE','Word'),'excel':('Excel.Application','EXCEL.EXE','Excel'),
          'powerpoint':('PowerPoint.Application','POWERPNT.EXE','PowerPoint')}
EXTENSIONS={**dict.fromkeys(('.doc','.docx','.docm','.dot','.dotx','.dotm','.rtf','.odt'),'word'),
            **dict.fromkeys(('.xls','.xlsx','.xlsm','.xlsb','.ods'),'excel'),
            **dict.fromkeys(('.ppt','.pptx','.pptm','.pps','.ppsx','.ppsm','.odp'),'powerpoint')}
DEADLINE=60                    # seconds a conversion may take; the web waits 120 s, the phones longer
# These are ZIP files; one with a password to open is an OLE file instead, and Excel waits on a password box for it
# whatever password Open is given (10-27). It is turned away before Office sees it.
ZIPPED=('.docx','.docm','.dotx','.dotm','.xlsx','.xlsm','.xlsb','.pptx','.pptm','.ppsx','.ppsm')
OLE=bytes.fromhex('d0cf11e0a1b11ae1')
MAX_SOURCE=100<<20             # the computer files route refuses larger files too (pc_files.download_meta)
CACHE_FILES=200;CACHE_BYTES=300<<20
# Given to Open so that a password-protected file fails at once instead of asking on the computer's screen.
PASSWORD='teleply-no-password'

class PreviewError(HistoryError):pass

_installed={}

def installed(program):
    """Whether this computer has the Office program, by its COM registration; looked at again after 10 minutes."""
    now=time.monotonic();seen=_installed.get(program)
    if seen and now-seen[1]<600:return seen[0]
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT,PROGRAMS[program][0]+'\\CLSID'):found=True
    except (ImportError,OSError):found=False
    _installed[program]=(found,now)
    return found

def program_of(path):
    return EXTENSIONS.get(Path(path).suffix.lower())

def offers(path):
    """'pdf' when this computer can show the file as a PDF, otherwise None."""
    program=program_of(path)
    return 'pdf' if program and installed(program) else None

class _Entry(ctypes.Structure):
    _fields_=[('dwSize',wintypes.DWORD),('cntUsage',wintypes.DWORD),('th32ProcessID',wintypes.DWORD),
              ('th32DefaultHeapID',ctypes.c_size_t),('th32ModuleID',wintypes.DWORD),('cntThreads',wintypes.DWORD),
              ('th32ParentProcessID',wintypes.DWORD),('pcPriClassBase',ctypes.c_long),('dwFlags',wintypes.DWORD),
              ('szExeFile',ctypes.c_wchar*260)]

def _pids(image):
    """The processes running an Office program (WINWORD.EXE…): the ones a conversion starts are told apart by this."""
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.CreateToolhelp32Snapshot.restype=wintypes.HANDLE
    kernel.CreateToolhelp32Snapshot.argtypes=[wintypes.DWORD,wintypes.DWORD]
    kernel.Process32FirstW.argtypes=kernel.Process32NextW.argtypes=[wintypes.HANDLE,ctypes.POINTER(_Entry)]
    kernel.CloseHandle.argtypes=[wintypes.HANDLE]
    snapshot=kernel.CreateToolhelp32Snapshot(2,0)  # TH32CS_SNAPPROCESS
    if not snapshot or snapshot==wintypes.HANDLE(-1).value:return set()
    found=set();entry=_Entry();entry.dwSize=ctypes.sizeof(_Entry)
    try:
        more=kernel.Process32FirstW(snapshot,ctypes.byref(entry))
        while more:
            if entry.szExeFile.upper()==image:found.add(entry.th32ProcessID)
            more=kernel.Process32NextW(snapshot,ctypes.byref(entry))
    finally:kernel.CloseHandle(snapshot)
    return found

class _Job:
    def __init__(self,program,source,target):
        self.program=program;self.source=source;self.target=target
        self.started=set();self.error=None;self.done=threading.Event()

def _start(job):
    """A new instance of the job's Office program (PowerPoint: the user's own when it is open), with what it started."""
    from win32com.client import DispatchEx
    progid,image,_=PROGRAMS[job.program]
    before=_pids(image)
    app=DispatchEx(progid)
    job.started=_pids(image)-before
    return app

def _word(job):
    app=_start(job)
    try:
        app.Visible=False;app.DisplayAlerts=0;app.AutomationSecurity=3  # wdAlertsNone, msoAutomationSecurityForceDisable
        document=app.Documents.Open(FileName=str(job.source),ConfirmConversions=False,ReadOnly=True,AddToRecentFiles=False,
                                    PasswordDocument=PASSWORD,PasswordTemplate=PASSWORD,Visible=False,OpenAndRepair=False,
                                    NoEncodingDialog=True)
        try:document.ExportAsFixedFormat(OutputFileName=str(job.target),ExportFormat=17,OpenAfterExport=False)  # PDF
        finally:document.Close(SaveChanges=0)
    finally:app.Quit(SaveChanges=0)

def _excel(job):
    app=_start(job)
    try:
        app.Visible=False;app.DisplayAlerts=False;app.ScreenUpdating=False;app.EnableEvents=False
        app.AskToUpdateLinks=False;app.AutomationSecurity=3
        book=app.Workbooks.Open(Filename=str(job.source),UpdateLinks=0,ReadOnly=True,Password=PASSWORD,
                                WriteResPassword=PASSWORD,IgnoreReadOnlyRecommended=True,Notify=False,AddToMru=False)
        try:book.ExportAsFixedFormat(Type=0,Filename=str(job.target),OpenAfterPublish=False)  # xlTypePDF
        finally:book.Close(SaveChanges=False)
    finally:app.Quit()

def _powerpoint(job):
    app=_start(job);mine=bool(job.started)
    try:
        if mine:app.DisplayAlerts=1;app.AutomationSecurity=3  # ppAlertsNone; the user's own instance keeps its settings
        # PowerPoint takes a password after the name ("file::password::"); a protected file then fails at once
        presentation=app.Presentations.Open(FileName=str(job.source)+'::'+PASSWORD+'::',ReadOnly=-1,Untitled=0,WithWindow=0)
        try:presentation.SaveAs(str(job.target),32)  # ppSaveAsPDF
        finally:presentation.Close()
    finally:
        if mine:app.Quit()

_CONVERT={'word':_word,'excel':_excel,'powerpoint':_powerpoint}

def _reason(exc):
    """What Office said, short; COM errors carry it in their exception information."""
    info=exc.args[2] if len(exc.args)>2 and isinstance(exc.args[2],tuple) and len(exc.args[2])>2 else None
    text=(info[2] if info and info[2] else exc.args[1] if len(exc.args)>1 and isinstance(exc.args[1],str) else str(exc)) or type(exc).__name__
    return ' '.join(str(text).split())[:160]

def _run(job):
    try:
        import pythoncom
        pythoncom.CoInitialize()
        try:_CONVERT[job.program](job)
        finally:pythoncom.CoUninitialize()
    except Exception as exc:
        job.error=exc if isinstance(exc,PreviewError) else PreviewError('电脑上的 '+PROGRAMS[job.program][2]+' 没能转换这个文件：'+_reason(exc))
    finally:job.done.set()

def _convert(program,source,target):
    """One conversion on a thread of its own; past DEADLINE the Office it started is stopped and the thread left."""
    job=_Job(program,source,target)
    threading.Thread(target=_run,args=(job,),name='office-preview',daemon=True).start()
    if not job.done.wait(DEADLINE):
        for pid in job.started:
            try:os.kill(pid,signal.SIGTERM)  # TerminateProcess
            except OSError:pass
        job.done.wait(10)
        raise PreviewError('电脑上的 '+PROGRAMS[program][2]+' 转换超过 '+str(DEADLINE)+' 秒，已停下。可以保存原文件，用手机上的应用打开。',503)
    if job.error:raise job.error

_one=threading.Lock()

def folder():
    return app_paths.DATA/'previews'

def pdf(source):
    """The PDF of the file as it is now: from the cache, or converted now (one conversion at a time)."""
    source=Path(source);program=program_of(source)
    if not program:raise PreviewError('这类文件不能转成 PDF 预览')
    if not installed(program):raise PreviewError('这台电脑没有装 '+PROGRAMS[program][2]+'，不能预览这个文件')
    st=source.stat()
    if st.st_size>MAX_SOURCE:raise PreviewError('文件超过 100 MB，不转换；可以保存原文件后打开',413)
    if source.suffix.lower() in ZIPPED:
        with source.open('rb') as f:
            if f.read(8)==OLE:raise PreviewError('这个文件设了打开密码，电脑不转换；可以保存原文件后在手机上打开')
    key=hashlib.sha256('\n'.join((str(source.absolute()),str(st.st_size),str(st.st_mtime_ns))).encode('utf-8','surrogatepass')).hexdigest()[:40]
    place=folder();target=place/(key+'.pdf')
    if not target.is_file():
        if not _one.acquire(timeout=DEADLINE+15):raise PreviewError('电脑正在转换别的文件，请稍后再打开',503)
        try:
            if not target.is_file():
                place.mkdir(parents=True,exist_ok=True)
                partial=place/(key+'.partial.pdf');partial.unlink(missing_ok=True)
                try:
                    _convert(program,source,partial)
                    with partial.open('rb') as f:made=f.read(5)==b'%PDF-'
                except OSError:made=False
                if not made:
                    partial.unlink(missing_ok=True)
                    raise PreviewError('电脑上的 '+PROGRAMS[program][2]+' 没有转出 PDF')
                os.replace(partial,target)
                _prune(place,target)
        finally:_one.release()
    else:
        try:os.utime(target)  # the newest are kept longest
        except OSError:pass
    return target

def _prune(place,keep):
    """At most CACHE_FILES PDFs and CACHE_BYTES, newest first; leftovers of stopped conversions go too."""
    now=time.time();files=[]
    for p in place.glob('*.pdf'):
        try:st=p.stat()
        except OSError:continue
        if p.name.endswith('.partial.pdf'):
            if now-st.st_mtime>3600:p.unlink(missing_ok=True)
            continue
        files.append((st.st_mtime,st.st_size,p))
    files.sort(reverse=True);total=0
    for index,(_,size,p) in enumerate(files):
        total+=size
        if p!=keep and (index>=CACHE_FILES or total>CACHE_BYTES):
            try:p.unlink()
            except OSError:pass
