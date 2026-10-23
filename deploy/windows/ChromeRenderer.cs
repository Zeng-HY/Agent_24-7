using System;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Windows.Forms;
using System.Runtime.InteropServices;

namespace AgentRemoteChrome {
    // WebView2 owns child HWNDs on another input thread. WinForms' automatic
    // dismissal cannot reliably see their clicks. Poll only while this menu is
    // open; never intercept input or expose a page-to-host bridge.
    public sealed class MenuDismissal : IDisposable {
        readonly ContextMenuStrip menu;
        readonly Form owner;
        readonly Timer timer = new Timer();
        bool wasDown;
        [DllImport("user32.dll")] static extern short GetAsyncKeyState(int key);
        static bool PointerDown() { return (GetAsyncKeyState(1)&0x8000)!=0 || (GetAsyncKeyState(2)&0x8000)!=0 || (GetAsyncKeyState(4)&0x8000)!=0; }
        public MenuDismissal(ContextMenuStrip menu,Form owner) {
            this.menu=menu;this.owner=owner;menu.AutoClose=true;timer.Interval=25;
            menu.Opened+=Opened;menu.Closed+=Closed;owner.Deactivate+=Deactivated;timer.Tick+=Tick;
        }
        void Opened(object sender,EventArgs args) { wasDown=PointerDown();timer.Start(); }
        void Closed(object sender,ToolStripDropDownClosedEventArgs args) { timer.Stop(); }
        void Deactivated(object sender,EventArgs args) { if(menu.Visible)menu.Close(ToolStripDropDownCloseReason.AppFocusChange); }
        void Tick(object sender,EventArgs args) { ObservePointer(PointerDown(),Cursor.Position); }
        public void ObservePointer(bool down,Point screenPoint) {
            bool pressed=down&&!wasDown;wasDown=down;
            if(menu.Visible&&pressed&&!menu.Bounds.Contains(screenPoint))menu.Close(ToolStripDropDownCloseReason.AppClicked);
        }
        public void Dispose() {
            timer.Stop();timer.Tick-=Tick;menu.Opened-=Opened;menu.Closed-=Closed;owner.Deactivate-=Deactivated;timer.Dispose();
        }
    }
    public sealed class MenuRenderer : ToolStripProfessionalRenderer {
        readonly float scale;
        public MenuRenderer(float scale) { this.scale=scale; RoundedEdges=false; }
        int D(float n) { return (int)Math.Round(n*scale); }
        static GraphicsPath Round(RectangleF r,float radius) {
            var p=new GraphicsPath();float d=2*radius;
            p.AddArc(r.Left,r.Top,d,d,180,90);p.AddArc(r.Right-d,r.Top,d,d,270,90);
            p.AddArc(r.Right-d,r.Bottom-d,d,d,0,90);p.AddArc(r.Left,r.Bottom-d,d,d,90,90);p.CloseFigure();return p;
        }
        protected override void OnRenderToolStripBackground(ToolStripRenderEventArgs e) { e.Graphics.Clear(Color.White); }
        protected override void OnRenderImageMargin(ToolStripRenderEventArgs e) { using(var b=new SolidBrush(Color.White))e.Graphics.FillRectangle(b,e.AffectedBounds); }
        protected override void OnRenderToolStripBorder(ToolStripRenderEventArgs e) {
            e.Graphics.SmoothingMode=SmoothingMode.AntiAlias;
            using(var p=Round(new RectangleF(.5f,.5f,e.ToolStrip.Width-1,e.ToolStrip.Height-1),12*scale))
            using(var pen=new Pen(Color.FromArgb(229,231,235)))e.Graphics.DrawPath(pen,p);
        }
        protected override void OnRenderMenuItemBackground(ToolStripItemRenderEventArgs e) {
            e.Graphics.SmoothingMode=SmoothingMode.AntiAlias;
            using(var p=Round(new RectangleF(1,1,e.Item.Width-2,e.Item.Height-2),7*scale))
            using(var b=new SolidBrush(e.Item.Selected&&e.Item.Enabled?Color.FromArgb(243,244,246):Color.White))e.Graphics.FillPath(b,p);
        }
        protected override void OnRenderItemText(ToolStripItemTextRenderEventArgs e) {
            var color=e.Item.Enabled?Color.FromArgb(36,39,45):Color.FromArgb(156,160,168);
            TextRenderer.DrawText(e.Graphics,e.Text,e.TextFont,new Rectangle(D(32),0,e.Item.Width-D(42),e.Item.Height),color,
                TextFormatFlags.Left|TextFormatFlags.VerticalCenter|TextFormatFlags.SingleLine|TextFormatFlags.NoPrefix|TextFormatFlags.NoPadding);
        }
        protected override void OnRenderSeparator(ToolStripSeparatorRenderEventArgs e) {
            using(var pen=new Pen(Color.FromArgb(235,236,239)))e.Graphics.DrawLine(pen,D(10),e.Item.Height/2,e.Item.Width-D(10),e.Item.Height/2);
        }
    }
}
