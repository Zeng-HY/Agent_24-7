using System;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Windows.Forms;

namespace AgentRemoteChrome {
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
