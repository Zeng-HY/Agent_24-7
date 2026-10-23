"""Current-user-only single-instance notification. Carries no commands or secrets."""
import getpass
import threading


class Instance:
    def __init__(self,suffix=''):
        import win32api,win32con,win32event,win32security,pywintypes,winerror
        self.event_api=win32event
        token=win32security.OpenProcessToken(win32api.GetCurrentProcess(),win32con.TOKEN_QUERY)
        try:sid=win32security.ConvertSidToStringSid(win32security.GetTokenInformation(token,win32security.TokenUser)[0])
        finally:token.Close()
        sa=pywintypes.SECURITY_ATTRIBUTES()
        sa.SECURITY_DESCRIPTOR=win32security.ConvertStringSecurityDescriptorToSecurityDescriptor('D:P(A;;GA;;;'+sid+')',win32security.SDDL_REVISION_1)
        name='Local\\AgentRemote027-'+getpass.getuser()+suffix
        self.mutex=win32event.CreateMutex(sa,False,name)
        self.primary=win32api.GetLastError()!=winerror.ERROR_ALREADY_EXISTS
        self.show=None
        self.legacy=False
        if self.primary:self.show=win32event.CreateEvent(sa,False,False,name+'-show')
        else:
            try:
                self.show=win32event.OpenEvent(win32con.EVENT_MODIFY_STATE,False,name+'-show')
                win32event.SetEvent(self.show)
            except pywintypes.error:self.legacy=True

    def listen(self,stop,callback):
        while not stop.is_set():
            if self.event_api.WaitForSingleObject(self.show,500)==0:callback()

    def close(self):
        if self.show:self.show.Close()
        self.mutex.Close()
