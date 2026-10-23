"""Draw the trusted native chrome with consistent geometry, independent of icon fonts."""
import math


def rounded(rect,radius):
    from System.Drawing.Drawing2D import GraphicsPath
    path=GraphicsPath();x,y,w,h=float(rect.X),float(rect.Y),float(rect.Width),float(rect.Height)
    d=float(radius*2)
    for a,b,angle in [(x,y,180),(x+w-d,y,270),(x+w-d,y+h-d,0),(x,y+h-d,90)]:path.AddArc(a,b,d,d,float(angle),90.)
    path.CloseFigure();return path


def icon(name,size):
    from System.Drawing import Bitmap,Graphics,Color,Pen,PointF
    from System.Drawing.Drawing2D import SmoothingMode,LineCap,LineJoin
    from System import Array
    bitmap=Bitmap(size,size);g=Graphics.FromImage(bitmap);g.Clear(Color.Transparent);g.SmoothingMode=SmoothingMode.AntiAlias
    g.ScaleTransform(size/24.,size/24.)
    pen=Pen(Color.FromArgb(48,52,59),1.6);pen.StartCap=LineCap.Round;pen.EndCap=LineCap.Round;pen.LineJoin=LineJoin.Round
    def lines(points,closed=False):
        pts=Array[PointF]([PointF(float(x),float(y)) for x,y in points])
        if closed:g.DrawPolygon(pen,pts)
        else:g.DrawLines(pen,pts)
    if name=='gear':
        points=[]
        for i in range(48):
            angle=math.pi*2*i/48-math.pi/2;r=8.6 if i%6 in (1,2,3,4) else 7.2
            points.append((12+math.cos(angle)*r,12+math.sin(angle)*r))
        lines(points,True);g.DrawEllipse(pen,8.7,8.7,6.6,6.6)
    elif name=='back':lines([(14,6),(8,12),(14,18)])
    elif name=='account':
        g.DrawEllipse(pen,8.,4.,8.,8.);g.DrawArc(pen,5.,13.,14.,12.,180.,180.)
    elif name=='check-update':
        lines([(12,4),(12,15),(8,11)]);lines([(12,15),(16,11)]);lines([(5,16),(5,20),(19,20),(19,16)])
    elif name=='legacy':lines([(3,7),(3,19),(21,19),(21,7),(12,7),(10,4),(3,4),(3,7)],True)
    elif name=='migration-info':
        g.DrawEllipse(pen,3.,3.,18.,18.);lines([(12,11),(12,17)]);g.DrawEllipse(pen,11.5,6.5,1.,1.)
    elif name=='rebind':
        g.DrawArc(pen,4.,4.,16.,16.,35.,290.);lines([(20,4),(20,10),(14,10)])
    elif name=='quit':
        lines([(10,4),(4,4),(4,20),(10,20)]);lines([(9,12),(21,12),(17,8)]);lines([(21,12),(17,16)])
    pen.Dispose();g.Dispose();return bitmap


def button(control,bitmap):
    from System.Drawing import Color,SolidBrush,Pen,RectangleF
    from System.Drawing.Drawing2D import SmoothingMode
    from System.Windows.Forms import Cursors
    hover={'on':False};control.Text='';control.Cursor=Cursors.Hand
    def paint(sender,event):
        g=event.Graphics;g.SmoothingMode=SmoothingMode.AntiAlias;g.Clear(Color.White)
        scale=bitmap.Width/20.;rect=RectangleF(1.,1.,float(control.Width-2),float(control.Height-2));path=rounded(rect,9*scale)
        if hover['on']:
            brush=SolidBrush(Color.FromArgb(244,245,247));g.FillPath(brush,path);brush.Dispose()
        if control.Focused:
            pen=Pen(Color.FromArgb(180,186,196),1.);g.DrawPath(pen,path);pen.Dispose()
        g.DrawImageUnscaled(bitmap,(control.Width-bitmap.Width)//2,(control.Height-bitmap.Height)//2);path.Dispose()
    def enter(sender,args):hover['on']=True;control.Invalidate()
    def leave(sender,args):hover['on']=False;control.Invalidate()
    control.MouseEnter+=enter;control.MouseLeave+=leave;control.GotFocus+=lambda s,e:control.Invalidate();control.LostFocus+=lambda s,e:control.Invalidate();control.Paint+=paint


def menu_style(menu,scale):
    from System.Drawing import Color,Pen,SolidBrush,Rectangle,RectangleF,Region,Font,Size,StringFormat,StringAlignment,StringFormatFlags
    from System.Drawing.Drawing2D import SmoothingMode
    from System.Windows.Forms import Padding,ToolStripProfessionalRenderer,TextRenderer,TextFormatFlags
    D=lambda n:round(n*scale)
    menu.BackColor=Color.White;menu.ForeColor=Color.FromArgb(32,35,41);menu.Font=Font('Microsoft YaHei UI',10.)
    menu.ShowImageMargin=True;menu.ShowCheckMargin=False;menu.ImageScalingSize=Size(D(18),D(18));menu.Padding=Padding(D(6));menu.DropShadowEnabled=True
    menu.MinimumSize=Size(D(232),0)
    import clr,sys
    from pathlib import Path
    from app_paths import ASSETS
    dll=ASSETS/'AgentRemote.Chrome.dll' if getattr(sys,'frozen',False) else ASSETS/'build/AgentRemote.Chrome.dll'
    clr.AddReference(str(dll))
    from AgentRemoteChrome import MenuRenderer
    renderer=MenuRenderer(float(scale));menu.Renderer=renderer
    def clip(sender,args):
        path=rounded(RectangleF(0.,0.,float(menu.Width),float(menu.Height)),12*scale);old=menu.Region;menu.Region=Region(path);path.Dispose()
        if old:old.Dispose()
    menu.Opened+=clip
    return renderer
