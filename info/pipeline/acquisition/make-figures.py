#!/usr/bin/env python3
"""Regenerates every figure in this folder, each as .png (embedded in the overview) and .svg (source).
Needs python3 + Pillow for the plots and Graphviz `dot` for the two block diagrams. No matplotlib."""
import math, subprocess
from PIL import Image, ImageDraw, ImageFont

S = 3          # supersampling for the PNG
OUT = 1.5      # PNG output scale relative to the SVG coordinate space
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"; FONTB = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"

class Canvas:
    def __init__(self, w, h):
        self.w, self.h = w, h; self.svg = []
        self.im = Image.new("RGB", (int(w*S), int(h*S)), "white"); self.d = ImageDraw.Draw(self.im); self.fonts = {}
    def font(self, size, bold=False):
        k = (size, bold)
        if k not in self.fonts: self.fonts[k] = ImageFont.truetype(FONTB if bold else FONT, int(round(size*S)))
        return self.fonts[k]
    def txt(self, x, y, s, size=13, anchor="start", fill="#222", weight="normal"):
        self.svg.append(f'<text x="{x:.1f}" y="{y:.1f}" font-size="{size}" text-anchor="{anchor}" fill="{fill}" font-weight="{weight}">{s.replace("&","&amp;").replace("<","&lt;")}</text>')
        self.d.text((x*S, y*S), s, font=self.font(size, weight == "bold"), fill=fill, anchor={"start": "ls", "middle": "ms", "end": "rs"}[anchor])
    def _dashed(self, pts, stroke, w, dash):
        on, off = (float(v) for v in dash.split(",")); pattern = [on, off]
        for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
            L = math.hypot(x2-x1, y2-y1)
            if L == 0: continue
            ux, uy = (x2-x1)/L, (y2-y1)/L; t = 0.0; i = 0
            while t < L:
                seg = min(pattern[i % 2], L - t)
                if i % 2 == 0: self.d.line([(x1+ux*t)*S, (y1+uy*t)*S, (x1+ux*(t+seg))*S, (y1+uy*(t+seg))*S], fill=stroke, width=max(1, int(w*S)))
                t += seg; i += 1
    def line(self, x1, y1, x2, y2, stroke="#222", w=1.2, dash=None):
        self.svg.append(f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="{stroke}" stroke-width="{w}"' + (f' stroke-dasharray="{dash}"' if dash else '') + '/>')
        if dash: self._dashed([(x1, y1), (x2, y2)], stroke, w, dash)
        else: self.d.line([x1*S, y1*S, x2*S, y2*S], fill=stroke, width=max(1, int(w*S)))
    def path(self, pts, stroke="#222", w=1.6, dash=None):
        self.svg.append('<path d="M' + " L".join(f"{x:.1f},{y:.1f}" for x, y in pts) + f'" fill="none" stroke="{stroke}" stroke-width="{w}"' + (f' stroke-dasharray="{dash}"' if dash else '') + '/>')
        if dash: self._dashed(pts, stroke, w, dash)
        else: self.d.line([(x*S, y*S) for x, y in pts], fill=stroke, width=max(1, int(w*S)), joint="curve")
    def circ(self, x, y, r, fill, stroke="#222"):
        self.svg.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r}" fill="{fill}" stroke="{stroke}"/>')
        self.d.ellipse([(x-r)*S, (y-r)*S, (x+r)*S, (y+r)*S], fill=fill, outline=stroke, width=S)
    def rect(self, x, y, w, h, fill, stroke="#222", dash=None):
        self.svg.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" fill="{fill}" stroke="{stroke}" rx="3"' + (f' stroke-dasharray="{dash}"' if dash else '') + '/>')
        self.d.rounded_rectangle([x*S, y*S, (x+w)*S, (y+h)*S], radius=3*S, fill=fill, outline=None if dash else stroke, width=S)
        if dash: self._dashed([(x, y), (x+w, y), (x+w, y+h), (x, y+h), (x, y)], stroke, 1.2, dash)
    def polygon(self, pts, fill, stroke="#222", w=0.8):
        self.svg.append(f'<polygon points="{" ".join(f"{x:.1f},{y:.1f}" for x, y in pts)}" fill="{fill}" stroke="{stroke}" stroke-width="{w}"/>')
        self.d.polygon([(x*S, y*S) for x, y in pts], fill=fill, outline=stroke, width=max(1, int(w*S)))
    def wedge(self, cx, cy, r, a0, a1, fill):
        p0 = (cx+r*math.cos(math.radians(a0)), cy+r*math.sin(math.radians(a0))); p1 = (cx+r*math.cos(math.radians(a1)), cy+r*math.sin(math.radians(a1)))
        self.svg.append(f'<path d="M{cx},{cy} L{p0[0]:.1f},{p0[1]:.1f} A{r},{r} 0 0 1 {p1[0]:.1f},{p1[1]:.1f} Z" fill="{fill}" stroke="#222"/>')
        self.d.pieslice([(cx-r)*S, (cy-r)*S, (cx+r)*S, (cy+r)*S], a0, a1, fill=fill, outline="#222", width=S)
    def save(self, name):
        open(name + ".svg", "w").write(f'<svg xmlns="http://www.w3.org/2000/svg" width="{self.w}" height="{self.h}" viewBox="0 0 {self.w} {self.h}" font-family="DejaVu Sans, Helvetica, Arial, sans-serif" font-size="13">\n<rect width="{self.w}" height="{self.h}" fill="white"/>\n' + "\n".join(self.svg) + "\n</svg>\n")
        self.im.resize((int(self.w*OUT), int(self.h*OUT)), Image.LANCZOS).save(name + ".png", optimize=True); print("wrote", name + ".png/.svg")

# ---- 02 frame-rate limits (log-log) --------------------------------------------------------
H = [4096,2048,1024,512,256,128,64,32,8]
meas = [8.4,17.1,34.4,69.1,137.1,272.3,534.4,1036.0,3567.9]     # Renesas, acquire-only, 2026-08-26
vend = [9,19,38,75,150,297,583,1126,3726]                        # manual §6.3 / test report §3.1
c = Canvas(780, 500); W,Hh = 780,500; L,R_,T,B = 80,30,120,70
x0,x1 = math.log10(6), math.log10(6000); y0,y1 = math.log10(5), math.log10(30000)
X = lambda h: L + (math.log10(h)-x0)/(x1-x0)*(W-L-R_); Y = lambda f: Hh-B - (math.log10(f)-y0)/(y1-y0)*(Hh-T-B)
c.txt(L, 24, "Frame rate versus ROI height: what limits it", 15, weight="bold"); c.txt(L, 42, "frames per second, log-log", 12, fill="#555")
for h in [8,16,32,64,128,256,512,1024,2048,4096]: c.line(X(h),T,X(h),Hh-B,"#e6e6e6"); c.txt(X(h),Hh-B+18,str(h),anchor="middle")
for f in [10,100,1000,10000]: c.line(L,Y(f),W-R_,Y(f),"#e6e6e6"); c.txt(L-8,Y(f)+4,str(f),anchor="end")
c.line(L,Hh-B,W-R_,Hh-B); c.line(L,T,L,Hh-B); c.txt((L+W-R_)/2,Hh-28,"ROI height (rows, full 4096 width)",anchor="middle")
hs = sorted(set([8*1.15**i for i in range(60) if 8*1.15**i <= 4096] + [4096]))
c.path([(X(h), Y(1/(h*10.32e-6))) for h in hs], "#c0392b", 2, "7,4")
c.path([(X(h), Y(289.5e6/(h*8192))) for h in hs], "#2c6fbb", 2, "7,4")
c.path([(X(h),Y(f)) for h,f in zip(H,vend)], "#999999", 1.2)
for h,f in zip(H,vend): c.circ(X(h),Y(f),3.5,"white","#777777")
for h,f in zip(H,meas): c.circ(X(h),Y(f),4.5,"#1a7f37","#1a7f37")
lx,ly = L+10, 62
c.line(lx,ly,lx+30,ly,"#c0392b",2.5,"7,4"); c.txt(lx+38,ly+4,"sensor readout limit = 1 / (rows × 10.32 µs)  → 23.7 fps at full frame (manual §6.3)",12)
c.line(lx,ly+18,lx+30,ly+18,"#2c6fbb",2.5,"7,4"); c.txt(lx+38,ly+22,"USB 3 link limit = 289.5 MB/s / (rows × 8192 bytes)  → 8.6 fps at full frame",12)
c.circ(lx+15,ly+36,3.5,"white","#777777"); c.txt(lx+38,ly+40,"vendor table (manual §6.3, test report §3.1)",12)
c.circ(lx+15,ly+54,4.5,"#1a7f37","#1a7f37"); c.txt(lx+38,ly+58,"measured here, 2026-08-26 (Renesas controller, acquire-only)",12)
c.txt(X(8.5),Y(200),"the camera runs on the blue line: the USB link,",11,fill="#2c6fbb"); c.txt(X(8.5),Y(140),"not the sensor, sets the frame rate at every height",11,fill="#2c6fbb")
c.txt(X(8.5),Y(60),"below ~32 rows a fixed per-frame cost pulls it under the line",11,fill="#555")
c.save("02-frame-rate-limits")

# ---- 03 exposure vs period ------------------------------------------------------------------
c = Canvas(720, 420); W,Hh = 720,420; L,R_,T,B = 80,30,70,60
ex = [20.64e-6,0.05,0.1,0.2,0.5]; per = [114.3,114.3,114.3,200,500]                 # measured 2026-08-26, full frame
x0,x1 = math.log10(1e-5), math.log10(1.0); X = lambda e: L+(math.log10(e)-x0)/(x1-x0)*(W-L-R_)
YMAX = 1050; Y = lambda p: Hh-B-(p/YMAX)*(Hh-T-B)
c.txt(L,24,"Frame period versus exposure time — full frame, free run",15,weight="bold"); c.txt(L,42,"frame period in ms (measured 2026-08-26)",12,fill="#555")
for e,lab in [(1e-5,"10 µs"),(1e-4,"100 µs"),(1e-3,"1 ms"),(1e-2,"10 ms"),(1e-1,"100 ms"),(1,"1 s")]: c.line(X(e),T,X(e),Hh-B,"#e6e6e6"); c.txt(X(e),Hh-B+18,lab,anchor="middle")
for p in range(0,1001,200): c.line(L,Y(p),W-R_,Y(p),"#e6e6e6"); c.txt(L-8,Y(p)+4,str(p),anchor="end")
c.line(L,Hh-B,W-R_,Hh-B); c.line(L,T,L,Hh-B); c.txt((L+W-R_)/2,Hh-22,"exposure time (log scale)",anchor="middle")
c.path([(X(e), Y(max(114.3, e*1000))) for e in [10**(x0+(x1-x0)*i/300) for i in range(301)]], "#2c6fbb", 2)
for e,p in zip(ex,per): c.circ(X(e),Y(p),5,"#1a7f37","#1a7f37")
c.txt(X(1.2e-5),Y(114.3)-28,"flat at 114 ms: the time to move one 32 MiB frame over USB 3;",11,fill="#2c6fbb")
c.txt(X(1.2e-5),Y(114.3)-14,"shorter exposures overlap the previous frame's transfer and cost nothing",11,fill="#2c6fbb")
c.txt(X(0.42),Y(720),"beyond 114 ms the period equals the exposure",11,anchor="end",fill="#2c6fbb")
c.save("03-exposure-vs-period")

# ---- 04 rolling shutter ---------------------------------------------------------------------
c = Canvas(840, 460); W,Hh = 840,460; L,R_,T,B = 110,30,110,60
tmax = 300.0; X = lambda t: L+t/tmax*(W-L-R_); rows = 4096; Y = lambda r: T+r/rows*(Hh-T-B)
c.txt(L,24,"Rolling shutter: each row starts 10.32 µs after the one above",15,weight="bold")
c.txt(L,42,"the test report §3.2 case: external trigger at t = 0, exposure 100 ms, full frame — every row exposes for 100 ms",12,fill="#555")
c.txt(L,60,"yellow: rows exposing.  red edge: readout, one row every 10.32 µs, so the last row is read 42.3 ms after the first.",12,fill="#c0392b")
c.txt(L,78,"row 4095 starts exposing 42.3 ms after row 0 — the top and bottom of a frame do not see the same instant.",12,fill="#7a5a00")
for t in range(0,301,50): c.line(X(t),T,X(t),Hh-B,"#e6e6e6"); c.txt(X(t),Hh-B+18,f"{t} ms",anchor="middle")
for r,lab in [(0,"row 0"),(1024,"row 1024"),(2048,"row 2048"),(3072,"row 3072"),(4095,"row 4095")]: c.line(L,Y(r),W-R_,Y(r),"#eeeeee"); c.txt(L-8,Y(r)+4,lab,anchor="end")
c.line(L,Hh-B,W-R_,Hh-B); c.line(L,T,L,Hh-B); c.txt((L+W-R_)/2,Hh-22,"time after trigger",anchor="middle")
skew = 4096*0.01032
def band(t0, exp, label):
    c.polygon([(X(t0),Y(0)),(X(t0+exp),Y(0)),(X(t0+exp+skew),Y(4095)),(X(t0+skew),Y(4095))],"#f6d55c"); c.txt(X(t0+exp/2+skew/2),Y(2048)+4,label,12,anchor="middle")
band(0,100,"frame 1 exposing"); band(142.3,100,"frame 2 exposing")
for t0 in (100, 242.3): c.polygon([(X(t0),Y(0)),(X(t0+0.8),Y(0)),(X(t0+skew+0.8),Y(4095)),(X(t0+skew),Y(4095))],"#c0392b","#c0392b",1.5)
c.line(X(0),T-6,X(0),Hh-B,"#555",1,"3,3"); c.txt(X(0)+4,T-10,"trigger (t = 0): EXPOSURE START on Out1",11,fill="#555")
c.line(X(142.3),T-6,X(142.3),Hh-B,"#555",1,"3,3"); c.txt(X(142.3)+4,T-10,"142 ms: READOUT END on Out3; row 0 is already exposing frame 2",11,fill="#555")
c.save("04-rolling-shutter")

# ---- 05 ring buffer --------------------------------------------------------------------------
c = Canvas(840, 360); c.txt(30,24,"The SDK ring buffer: two slots, used in turn",15,weight="bold")
def ring(cx, cy, title, slots, note):
    c.txt(cx,cy-100,title,13,anchor="middle",weight="bold"); r=70
    for i,(l1,l2,fill) in enumerate(slots):
        a0=-90+i*180; a1=a0+180; c.wedge(cx,cy,r,a0,a1,fill)
        am=math.radians((a0+a1)/2); tx=cx+r*0.5*math.cos(am); ty=cy+r*0.5*math.sin(am)
        c.txt(tx,ty-2,l1,12,anchor="middle",weight="bold"); c.txt(tx,ty+13,l2,(9 if len(l2)>8 else 11),anchor="middle")
    c.txt(cx,cy+r+24,note[0],11,anchor="middle",fill="#555"); c.txt(cx,cy+r+38,note[1],11,anchor="middle",fill="#555")
ring(150,175,"now",[("slot 0","filling","#cfe3f7"),("slot 1","ready","#d5f0d5")],("the SDK's USB thread fills one slot while","the driver's grab thread copies the other out"))
ring(420,175,"one frame period later",[("slot 0","ready","#d5f0d5"),("slot 1","filling","#cfe3f7")],("the two indices advance and wrap;","no allocation, memory fixed at Buf_Alloc"))
ring(690,175,"grab thread late by 2 frames",[("slot 0","overwritten","#f3b7b7"),("slot 1","filling","#cfe3f7")],("the producer wraps onto an unread slot:","frame gone — no counter, no message"))
c.txt(420,325,"N fixed slots used circularly: fast and allocation-free; the price is a silent overwrite when the reader falls N frames behind.",12,anchor="middle")
c.txt(420,343,"Here N = 2 (pinned by SDK 2.0.7.0), so each frame must be collected within one frame period: 114 ms at full frame, 0.28 ms at 8 rows.",12,anchor="middle",fill="#555")
c.save("05-ring-buffer")

# ---- 07 capture timeline ---------------------------------------------------------------------
c = Canvas(840, 320); W,Hh = 840,320; L,R_ = 90,30; tmax=7.5; X=lambda t:L+t/tmax*(W-L-R_)
c.txt(L,24,"One write-mode capture on the wall clock",15,weight="bold"); c.txt(L,42,"2048 rows, 100 frames, Multiple mode — Renesas, 2026-08-26: wall clock 6.3 s, camera time 5.73 s",12,fill="#555")
for t in range(0,8): c.line(X(t),60,X(t),250,"#e6e6e6"); c.txt(X(t),268,f"{t} s",anchor="middle")
def bar(y,t0,t1,fill,label): c.rect(X(t0),y,X(t1)-X(t0),26,fill); c.txt((X(t0)+X(t1))/2,y+18,label,12,anchor="middle")
c.txt(L-8,83,"camera",anchor="end"); bar(65,0,0.35,"#eeeeee","start"); bar(65,0.35,6.08,"#f6d55c","100 frames at 17.3 fps  (5.73 s of camera time)")
c.txt(L-8,128,"driver",anchor="end"); bar(110,0.35,6.08,"#d5f0d5","grab thread: WaitForFrame → memcpy → callbacks, one frame at a time")
c.txt(L-8,173,"HDF1",anchor="end"); bar(155,0,0.35,"#eeeeee","open"); bar(155,0.4,6.1,"#cfe3f7","H5Dwrite each frame into the page cache, 1–2 frames behind the camera"); c.rect(X(6.1),155,X(6.3)-X(6.1),26,"#f3b7b7"); c.txt(X(6.35),155+18,"close (0.2 s)",11,fill="#c0392b")
c.txt(L-8,218,"kernel",anchor="end"); c.rect(X(0.6),200,X(7.3)-X(0.6),26,"#f4f4f4","#999999","5,3"); c.txt((X(0.6)+X(7.3))/2,218,"background writeback of dirty pages to the virtual disk — continues after Capture = Done",12,anchor="middle",fill="#555")
c.line(X(6.3),58,X(6.3),252,"#c0392b",1.2,"4,3"); c.txt(X(6.3)-5,72,"6.3 s: Capture_RBV = Done",11,anchor="end",fill="#c0392b")
c.txt((L+W-R_)/2,300,"end-to-end fps = 100 / 6.3 s = 15.8 against a camera rate of 17.3: the 0.5 s of start-up + close is the same for a 3 s and a 10 s capture",11,anchor="middle",fill="#555")
c.save("07-capture-timeline")

# ---- 01, 06: Graphviz (dot sources kept beside the outputs) -------------------------------------
for name in ("01-system-path", "06-software-pipeline"):
    subprocess.run(["dot", "-Tsvg", name + ".dot", "-o", name + ".svg"], check=True)
    subprocess.run(["dot", "-Tpng", "-Gdpi=110", name + ".dot", "-o", name + ".png"], check=True); print("wrote", name + ".png/.svg (dot)")
