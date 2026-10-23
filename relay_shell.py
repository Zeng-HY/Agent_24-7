"""Native chrome and an isolated account WebView inside the existing desktop window."""
import threading
from urllib.parse import urlsplit


class Shell:
    def __init__(self,controller):
        from System import Action,Uri
        from System.Drawing import Color,ContentAlignment,Font,FontStyle,Point,Size
        from System.Windows.Forms import Panel,TableLayoutPanel,RowStyle,SizeType,DockStyle,Label,Button,CheckBox,FlatStyle,ContextMenuStrip,ToolStripMenuItem
        from Microsoft.Web.WebView2.WinForms import WebView2,CoreWebView2CreationProperties
        self.c=controller;self.form=controller.window.native;self.local=self.form.webview
        D=lambda n:round(n*self.form.DeviceDpi/96)
        self.remote_ready=threading.Event();self.pending_url=None;self.remote_showing=False;self.last_remote=False;self.synchronizing=False
        self.Action=Action;self.Uri=Uri;self.disposed=False
        root=TableLayoutPanel();root.Dock=DockStyle.Fill;root.BackColor=Color.White;root.RowCount=3;root.ColumnCount=1
        root.RowStyles.Add(RowStyle(SizeType.Absolute,D(48)));root.RowStyles.Add(RowStyle(SizeType.Percent,100));root.RowStyles.Add(RowStyle(SizeType.Absolute,D(44)))
        top=Panel();top.Dock=DockStyle.Fill;top.BackColor=Color.White
        self.gear=Button();self.gear.Text='⚙';self.gear.AccessibleName='设置';self.gear.Size=Size(D(40),D(40));self.gear.Location=Point(D(12),D(4));self.gear.BackColor=Color.White;self.gear.FlatStyle=FlatStyle.Flat;self.gear.FlatAppearance.BorderSize=0;self.gear.Font=Font('Segoe UI Symbol',15)
        title=Label();title.Text='Agent Remote';title.Font=Font('Segoe UI',11,FontStyle.Bold);title.Dock=DockStyle.Fill;title.TextAlign=ContentAlignment.MiddleCenter
        top.Controls.Add(title);top.Controls.Add(self.gear);self.gear.BringToFront()
        self.back_button=Button();self.back_button.Text='‹';self.back_button.AccessibleName='返回';self.back_button.Size=Size(D(40),D(40));self.back_button.FlatStyle=FlatStyle.Flat;self.back_button.FlatAppearance.BorderSize=0;self.back_button.BackColor=Color.White;self.back_button.Font=Font('Segoe UI',16);self.back_button.Visible=False
        top.Controls.Add(self.back_button);self.back_button.BringToFront()
        top.SizeChanged+=lambda sender,args:setattr(self.back_button,'Location',Point(top.Width-D(52),D(4)))
        self.back_button.Click+=lambda sender,args:self.dispatch('back')
        bottom=Panel();bottom.Dock=DockStyle.Fill;bottom.BackColor=Color.White
        self.startup=CheckBox();self.startup.Text='登录时启动';self.startup.AccessibleName='登录时启动';self.startup.AutoSize=True;self.startup.Font=Font('Microsoft YaHei UI',9);self.startup.Location=Point(D(16),D(12));self.startup.Checked=controller.startup;self.startup.BackColor=Color.White
        self.version=Label();self.version.Text=controller.version;self.version.Font=Font('Segoe UI',9);self.version.ForeColor=Color.Gray;self.version.Dock=DockStyle.Right;self.version.Width=D(150);self.version.TextAlign=ContentAlignment.MiddleRight;self.version.Padding=__import__('System.Windows.Forms',fromlist=['Padding']).Padding(0,0,D(16),0)
        bottom.Controls.Add(self.startup);bottom.Controls.Add(self.version)
        self.center=Panel();self.center.Dock=DockStyle.Fill;self.center.BackColor=Color.White
        self.local.Parent.Controls.Remove(self.local);self.local.Dock=DockStyle.Fill;self.center.Controls.Add(self.local)
        self.remote=WebView2();self.remote.Dock=DockStyle.Fill;self.remote.Visible=False
        self.remote.CreationProperties=self.local.CreationProperties
        self.center.Controls.Add(self.remote)
        root.Controls.Add(top,0,0);root.Controls.Add(self.center,0,1);root.Controls.Add(bottom,0,2)
        self.form.Controls.Add(root);root.BringToFront();self.root=root
        self.menu=ContextMenuStrip();self.items={}
        for label,action in [('账号与电脑','account'),('检查更新','check-update'),('迁移旧版','legacy'),('迁移详情','migration-info'),('重新绑定','rebind'),('退出','quit')]:
            item=ToolStripMenuItem(label);item.Click+=lambda sender,args,a=action:self.dispatch(a);self.menu.Items.Add(item);self.items[action]=item
        self.gear.Click+=lambda sender,args:self.open_menu()
        self.startup.CheckedChanged+=self.toggle_startup
        self.remote.CoreWebView2InitializationCompleted+=self.initialized
        self.remote.EnsureCoreWebView2Async(None)

    def invoke(self,fn):
        if not self.disposed and not self.form.IsDisposed:self.form.Invoke(self.Action(fn))

    def dispatch(self,action):threading.Thread(target=self.c.dispatch,args=(action,),daemon=True).start()

    def open_menu(self):
        from System.Drawing import Point
        self.items['legacy'].Enabled=not self.c.binding.get('device')
        self.items['migration-info'].Enabled=bool(self.c.migration)
        self.menu.Show(self.gear,Point(0,self.gear.Height))

    def toggle_startup(self,sender,args):
        if self.synchronizing:return
        self.startup.Enabled=False;self.dispatch('startup')

    def sync(self):
        def update():
            self.synchronizing=True
            try:
                self.startup.Checked=self.c.startup;self.startup.Enabled=not getattr(self.c,'startup_busy',False)
                self.back_button.Visible=getattr(self.c,'settings_open',False) or (bool(self.c.binding.get('device')) and self.remote_showing)
            finally:self.synchronizing=False
        self.invoke(update)

    def initialized(self,sender,args):
        if not args.IsSuccess:
            self.c.detail='登录页面启动失败，请重试。';return
        core=self.remote.CoreWebView2
        core.Settings.IsWebMessageEnabled=False;core.Settings.AreHostObjectsAllowed=False
        core.Settings.AreDevToolsEnabled=False;core.Settings.IsPasswordAutosaveEnabled=False
        core.NavigationStarting+=self.navigation
        core.NavigationCompleted+=self.fit_login
        core.NewWindowRequested+=lambda sender,args:setattr(args,'Handled',True)
        core.DownloadStarting+=lambda sender,args:setattr(args,'Cancel',True)
        self.remote_ready.set()
        if self.pending_url:core.Navigate(self.pending_url)

    def fit_login(self,sender,args):
        # Host layout only: the server still owns form styling and authentication.
        # No field values are read and no host API is exposed to remote JavaScript.
        p=urlsplit(str(self.remote.CoreWebView2.Source))
        if p.scheme+'://'+p.netloc!=self.c.binding['origin']:return
        self.remote.CoreWebView2.ExecuteScriptAsync("(()=>{document.body.style.padding='24px 24px 16px';const brand=document.querySelector('.brand');if(brand)brand.style.display='none';const main=document.querySelector('main');if(main){main.style.maxWidth='380px';main.style.margin='0 auto';}const h=document.querySelector('h1');if(h){h.style.fontSize='27px';h.style.marginBottom='24px';}})()")

    def navigation(self,sender,args):
        uri=str(args.Uri);p=urlsplit(uri)
        if uri!='about:blank' and (p.scheme+'://'+p.netloc!=self.c.binding['origin']):args.Cancel=True

    def load_account(self,url):
        def load():
            self.pending_url=url
            if self.remote_ready.is_set():self.remote.CoreWebView2.Navigate(url)
            self.local.Visible=False;self.remote.Visible=True;self.remote.BringToFront();self.remote.Focus();self.remote_showing=True
        self.invoke(load)

    def show_account(self):
        self.invoke(lambda:(setattr(self.local,'Visible',False),setattr(self.remote,'Visible',True),self.remote.BringToFront(),self.remote.Focus(),setattr(self,'remote_showing',True)))

    def local_view(self,returnable=False):
        def show():
            if not returnable:self.last_remote=False
            elif self.remote_showing:self.last_remote=True
            self.remote.Visible=False;self.local.Visible=True;self.local.BringToFront();self.remote_showing=False
        self.invoke(show)

    def back(self):
        if self.last_remote:
            self.invoke(lambda:(setattr(self.local,'Visible',False),setattr(self.remote,'Visible',True),self.remote.BringToFront(),self.remote.Focus(),setattr(self,'remote_showing',True)))

    def clear_account(self):
        self.pending_url=None
        self.invoke(lambda:self.remote.CoreWebView2.Navigate('about:blank') if self.remote_ready.is_set() else None)

    def close(self):
        self.invoke(lambda:(self.remote.Dispose(),self.menu.Dispose()))
        self.disposed=True
