# -*- coding: utf-8 -*-
"""Crosshair & Brightness & HUD — v4.2 (AMD GPU support)"""
import tkinter as tk
from tkinter import ttk, colorchooser, messagebox, filedialog, simpledialog
import ctypes
from ctypes import wintypes
import json, os, sys, threading, queue, traceback, time, subprocess, re, math, colorsys

if sys.platform != 'win32':
    raise SystemExit("Windows only")
APP_VERSION = "4.2"
try: ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    try: ctypes.windll.user32.SetProcessDPIAware()
    except Exception: pass

LOG_PATH      = os.path.join(os.path.expanduser("~"), "crosshair_error.log")
SETTINGS_PATH = os.path.join(os.path.expanduser("~"), ".crosshair_settings.json")
PROFILES_DIR  = os.path.join(os.path.expanduser("~"), ".crosshair_profiles")
try: os.makedirs(PROFILES_DIR, exist_ok=True)
except Exception: pass

if "--reset" in sys.argv or "-r" in sys.argv:
    try:
        if os.path.exists(SETTINGS_PATH): os.remove(SETTINGS_PATH)
    except Exception: pass
    sys.exit(0)

# =============== WinAPI ===============
user32 = ctypes.WinDLL('user32', use_last_error=True)
gdi32  = ctypes.WinDLL('gdi32',  use_last_error=True)
for name, args, res in [
    ('GetWindowLongW',[wintypes.HWND, ctypes.c_int], ctypes.c_long),
    ('SetWindowLongW',[wintypes.HWND, ctypes.c_int, ctypes.c_long], ctypes.c_long),
    ('GetParent',[wintypes.HWND], wintypes.HWND),
    ('GetDesktopWindow',[], wintypes.HWND),
    ('GetDC',[wintypes.HWND], wintypes.HDC),
    ('ReleaseDC',[wintypes.HWND, wintypes.HDC], ctypes.c_int),
    ('SetLayeredWindowAttributes',[wintypes.HWND, wintypes.DWORD, ctypes.c_ubyte, wintypes.DWORD], wintypes.BOOL),
    ('SetWindowPos',[wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_uint], wintypes.BOOL),
    ('RegisterHotKey',[wintypes.HWND, ctypes.c_int, ctypes.c_uint, ctypes.c_uint], wintypes.BOOL),
    ('MessageBoxW',[wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR, ctypes.c_uint], ctypes.c_int),
]:
    try:
        fn = getattr(user32, name); fn.argtypes = args; fn.restype = res
    except Exception: pass

class POINT(ctypes.Structure):
    _fields_ = [('x', wintypes.LONG), ('y', wintypes.LONG)]
class RECT(ctypes.Structure):
    _fields_ = [('left', wintypes.LONG), ('top', wintypes.LONG),
                ('right', wintypes.LONG), ('bottom', wintypes.LONG)]

user32.GetCursorPos.argtypes = [ctypes.POINTER(POINT)]
user32.WindowFromPoint.argtypes = [POINT]; user32.WindowFromPoint.restype = wintypes.HWND
user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(RECT)]; user32.GetWindowRect.restype = wintypes.BOOL
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]; user32.GetWindowTextW.restype = ctypes.c_int
user32.IsWindow.argtypes = [wintypes.HWND]; user32.IsWindow.restype = wintypes.BOOL
user32.IsWindowVisible.argtypes = [wintypes.HWND]; user32.IsWindowVisible.restype = wintypes.BOOL
user32.IsIconic.argtypes = [wintypes.HWND]; user32.IsIconic.restype = wintypes.BOOL
user32.GetAncestor.argtypes = [wintypes.HWND, ctypes.c_uint]; user32.GetAncestor.restype = wintypes.HWND

GA_ROOT = 2
GWL_EXSTYLE       = -20
WS_EX_LAYERED     = 0x00080000
WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOOLWINDOW  = 0x00000080
WS_EX_TOPMOST     = 0x00000008
WS_EX_NOACTIVATE  = 0x08000000
LWA_COLORKEY      = 0x00000001
LWA_ALPHA         = 0x00000002
HWND_TOPMOST   = -1
SWP_NOMOVE     = 0x0002; SWP_NOSIZE = 0x0001; SWP_NOACTIVATE = 0x0010
SWP_SHOWWINDOW = 0x0040; SWP_NOOWNERZORDER = 0x0200
TRANSPARENT_COLOR = "#010203"
WM_HOTKEY = 0x0312
MOD = 0x0002 | 0x0001 | 0x4000

# =============== GAMMA ===============
class GAMMARAMP(ctypes.Structure):
    _fields_ = [('red', wintypes.WORD*256), ('green', wintypes.WORD*256), ('blue', wintypes.WORD*256)]
class MONITORINFOEXW(ctypes.Structure):
    _fields_ = [('cbSize', wintypes.DWORD), ('rcMonitor', RECT), ('rcWork', RECT),
                ('dwFlags', wintypes.DWORD), ('szDevice', wintypes.WCHAR*32)]
MONITORENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HMONITOR, wintypes.HDC,
                                     ctypes.POINTER(RECT), wintypes.LPARAM)
user32.EnumDisplayMonitors.argtypes = [wintypes.HDC, ctypes.c_void_p, MONITORENUMPROC, wintypes.LPARAM]
user32.GetMonitorInfoW.argtypes = [wintypes.HMONITOR, ctypes.c_void_p]
gdi32.CreateDCW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.LPCWSTR, ctypes.c_void_p]
gdi32.CreateDCW.restype = wintypes.HDC
gdi32.DeleteDC.argtypes = [wintypes.HDC]
gdi32.SetDeviceGammaRamp.argtypes = [wintypes.HDC, ctypes.c_void_p]

def hex_to_colorref(h):
    h = h.lstrip('#'); return int(h[0:2],16) | (int(h[2:4],16) << 8) | (int(h[4:6],16) << 16)

def _monitor_devices():
    devices = []
    def cb(hmon, hdc, lprect, lparam):
        mi = MONITORINFOEXW(); mi.cbSize = ctypes.sizeof(MONITORINFOEXW)
        if user32.GetMonitorInfoW(hmon, ctypes.byref(mi)): devices.append(mi.szDevice)
        return True
    try: user32.EnumDisplayMonitors(None, None, MONITORENUMPROC(cb), 0)
    except Exception: pass
    return devices

def _build_ramp(b):
    inv = 1.0 / max(0.05, b); ramp = GAMMARAMP()
    for i in range(256):
        v = int(round(65535 * ((i / 255.0) ** inv)))
        v = max(257, min(65278, v))
        ramp.red[i] = ramp.green[i] = ramp.blue[i] = v
    return ramp

def set_brightness(b):
    ramp = _build_ramp(b); applied = 0
    for dev in _monitor_devices():
        hdc = gdi32.CreateDCW(dev, dev, None, None)
        if not hdc: continue
        try:
            if gdi32.SetDeviceGammaRamp(hdc, ctypes.byref(ramp)): applied += 1
        finally: gdi32.DeleteDC(hdc)
    if applied == 0:
        hdc = user32.GetDC(None)
        try:
            if gdi32.SetDeviceGammaRamp(hdc, ctypes.byref(ramp)): applied = 1
        finally: user32.ReleaseDC(None, hdc)
    return applied

def get_toplevel_hwnd(window):
    hwnd = window.winfo_id(); parent = user32.GetParent(hwnd)
    if parent and parent != user32.GetDesktopWindow(): return parent
    return hwnd

def apply_alpha_style(hwnd, alpha, clickable=False):
    st = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
    st |= WS_EX_LAYERED | WS_EX_TOOLWINDOW | WS_EX_TOPMOST | WS_EX_NOACTIVATE
    if clickable: st &= ~WS_EX_TRANSPARENT
    else: st |= WS_EX_TRANSPARENT
    user32.SetWindowLongW(hwnd, GWL_EXSTYLE, st)
    user32.SetLayeredWindowAttributes(hwnd, 0, alpha, LWA_ALPHA)

def push_to_top(hwnd):
    try:
        user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0,
                            SWP_NOMOVE|SWP_NOSIZE|SWP_NOACTIVATE|SWP_SHOWWINDOW|SWP_NOOWNERZORDER)
    except Exception: pass

def window_title(hwnd):
    if not hwnd or not user32.IsWindow(hwnd): return ""
    buf = ctypes.create_unicode_buffer(256); user32.GetWindowTextW(hwnd, buf, 256)
    return buf.value

def root_window_at(x, y):
    hwnd = user32.WindowFromPoint(POINT(x, y))
    if not hwnd: return 0
    root = user32.GetAncestor(hwnd, GA_ROOT); return root or hwnd

def log_exception(t, v, tb):
    txt = "".join(traceback.format_exception(t, v, tb))
    try:
        with open(LOG_PATH, "w", encoding="utf-8") as f: f.write(txt)
        print(txt, file=sys.stderr)
    except Exception: pass
sys.excepthook = log_exception

def native_msg(title, text):
    try: user32.MessageBoxW(None, text, title, 0x10)
    except Exception: pass

# =============== Color helpers ===============
def hex_to_rgb(h):
    h = h.lstrip('#'); return int(h[0:2],16), int(h[2:4],16), int(h[4:6],16)
def rgb_to_hex(r,g,b):
    return f"#{int(max(0,min(255,r))):02X}{int(max(0,min(255,g))):02X}{int(max(0,min(255,b))):02X}"
def rainbow_color(t, sat=1.0, val=1.0):
    r,g,b = colorsys.hsv_to_rgb((t % 1.0), sat, val); return rgb_to_hex(r*255, g*255, b*255)
def lerp_color(c1, c2, t):
    r1,g1,b1 = hex_to_rgb(c1); r2,g2,b2 = hex_to_rgb(c2)
    return rgb_to_hex(r1+(r2-r1)*t, g1+(g2-g1)*t, b1+(b2-b1)*t)

try: import psutil; HAS_PSUTIL = True
except ImportError: HAS_PSUTIL = False
try: import GPUtil; HAS_GPUTIL = True
except ImportError: HAS_GPUTIL = False

# =============== GPU Reader (AMD + NVIDIA + Intel) ===============
class GPUReader:
    """Читает загрузку GPU в фоновом потоке. Работает для AMD/NVIDIA/Intel на Win10+."""
    def __init__(self):
        self.value = None
        self.enabled = False
        self._thread = None
        self._stop = threading.Event()

    def set_enabled(self, on):
        self.enabled = bool(on)
        if on and (self._thread is None or not self._thread.is_alive()):
            self._stop.clear()
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()

    def stop(self):
        self._stop.set()

    def _flags(self):
        return subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0

    def _query_nvidia(self):
        try:
            r = subprocess.run(['nvidia-smi', '--query-gpu=utilization.gpu',
                                '--format=csv,noheader,nounits'],
                               capture_output=True, text=True, timeout=2,
                               creationflags=self._flags())
            if r.returncode == 0 and r.stdout.strip():
                first = r.stdout.strip().split('\n')[0].strip()
                return f"{float(first.split()[0]):.0f}%"
        except Exception: pass
        return None

    def _query_windows_counter(self):
        """Универсальный счётчик Windows (AMD/Intel/NVIDIA)."""
        try:
            ps = (
                "try { "
                "$c = (Get-Counter '\\GPU Engine(*engtype_3D)\\Utilization Percentage' "
                "-EA Stop -SampleInterval 1 -MaxSamples 1).CounterSamples; "
                "$s = ($c | Measure-Object -Property CookedValue -Sum).Sum; "
                "if ($s -ne $null -and $s -gt 0) { [math]::Round([math]::Min(100,$s),0) } else { '' } "
                "} catch { '' }"
            )
            r = subprocess.run(
                ['powershell', '-NoProfile', '-NonInteractive', '-Command', ps],
                capture_output=True, text=True, timeout=8,
                creationflags=self._flags()
            )
            val = r.stdout.strip()
            if val and re.match(r'^\d+(\.\d+)?$', val):
                return f"{min(100, int(float(val.replace(',', '.'))))}%"
        except Exception: pass
        return None

    def _query_gputil(self):
        if not HAS_GPUTIL: return None
        try:
            gpus = GPUtil.getGPUs()
            if gpus:
                return f"{gpus[0].load*100:.0f}%"
        except Exception: pass
        return None

    def _run(self):
        while not self._stop.is_set():
            if not self.enabled:
                self._stop.wait(1.0); continue
            v = self._query_nvidia()
            if v is None: v = self._query_gputil()
            if v is None: v = self._query_windows_counter()
            self.value = v
            self._stop.wait(3.0)

GPU_READER = GPUReader()

# =============== Constants ===============
C_BG="#1e1f22"; C_BG_ALT="#2b2d31"; C_BG_DARK="#141518"; C_ACCENT="#5865f2"
C_ACCENT_H="#4752c4"; C_TEXT="#e6e6e8"; C_TEXT_DIM="#8a8d94"; C_BORDER="#3a3d44"
C_OK="#3ba55d"; C_OFF="#8a8d94"; C_WARN="#faa61a"

QUICK_COLORS = ["#00FF00","#33FF33","#FF0000","#FF4444","#00FFFF","#00CCFF",
                "#FF00FF","#FF66CC","#FFFF00","#FFAA00","#FFFFFF","#CCCCCC",
                "#0000FF","#8800FF","#FF0088","#00FF88"]

STYLE_NAMES = [
    ("dot","Точка"),("cross","Крест"),("dot_cross","Точка+\nкрест"),
    ("ring","Кольцо"),("ring_dot","Кольцо+\nточка"),("t_shape","T-обр."),
    ("chevron","Галочка"),("x_cross","X-крест"),("brackets","Скобки"),
    ("corners","Уголки"),("diamond","Ромб"),("square","Квадрат"),
    ("triangle","Треуг."),("triple_dot","3 точки"),("hash","Решётка"),
    ("arrow","Стрелка"),("brackets_square","[ ]"),("double_ring","2 кольца"),
    ("cross_ring","Крест+\nкольцо"),
    ("heart","Сердце"),("star_5","Звезда"),("hexagon","6-угольник"),
    ("chevron_down","Галка↓"),("arrow_up","Стрелка↑"),("arrow_down","Стрелка↓"),
    ("circle_dots","Точки по\nкругу"),("ticks","Тики"),
    ("segmented_ring","Пунктир"),("partial_ring","Дуга"),
]
STYLE_DICT = dict(STYLE_NAMES)

# =============== Scrollable Frame ===============
class ScrollableFrame(ttk.Frame):
    def __init__(self, parent, **kw):
        super().__init__(parent, **kw)
        self.canvas = tk.Canvas(self, bg=C_BG, highlightthickness=0, bd=0)
        self.vsb = ttk.Scrollbar(self, orient='vertical', command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.vsb.set)
        self.vsb.pack(side='right', fill='y')
        self.canvas.pack(side='left', fill='both', expand=True)
        self.inner = ttk.Frame(self.canvas, style="Card.TFrame")
        self.window = self.canvas.create_window((0, 0), window=self.inner, anchor='nw')
        self.inner.bind('<Configure>', self._update_scrollregion)
        self.canvas.bind('<Configure>', self._update_width)
        self.inner.bind_all('<MouseWheel>', self._on_wheel, add='+')

    def _update_scrollregion(self, e=None):
        try: self.canvas.configure(scrollregion=self.canvas.bbox('all'))
        except Exception: pass

    def _update_width(self, e):
        try: self.canvas.itemconfigure(self.window, width=e.width)
        except Exception: pass

    def _on_wheel(self, e):
        try:
            widget = self.winfo_containing(e.x_root, e.y_root)
            if widget is None: return
            w = widget
            while w is not None:
                if w is self.canvas:
                    self.canvas.yview_scroll(-int(e.delta/120), 'units')
                    return
                w = getattr(w, 'master', None)
        except Exception: pass

# =============== Color Picker Panel ===============
class ColorPickerPanel(ttk.Frame):
    def __init__(self, parent, initial="#00FF00", on_change=None):
        super().__init__(parent, style="Card.TFrame")
        self.on_change = on_change
        self._updating = False
        self._wheel_size = 150
        self._parse_hex(initial)
        self._build_ui()
        self._draw_wheel()
        self._refresh_all()

    def _parse_hex(self, hex_color):
        try:
            h = hex_color.lstrip('#')
            r, g, b = int(h[0:2],16), int(h[2:4],16), int(h[4:6],16)
            self._h, self._s, self._v = colorsys.rgb_to_hsv(r/255, g/255, b/255)
        except Exception:
            self._h, self._s, self._v = 0.33, 1.0, 1.0

    def get_hex(self):
        r, g, b = colorsys.hsv_to_rgb(self._h, self._s, self._v)
        return rgb_to_hex(r*255, g*255, b*255)

    def set_hex(self, hex_color):
        self._parse_hex(hex_color); self._refresh_all()

    def _build_ui(self):
        size = self._wheel_size
        top = tk.Frame(self, bg=C_BG); top.pack(fill='x', pady=(4,6))
        wheel_wrap = tk.Frame(top, bg=C_BORDER); wheel_wrap.pack(side='left', padx=(0,10))
        self.wheel = tk.Canvas(wheel_wrap, width=size, height=size,
                                highlightthickness=0, bd=0, cursor="crosshair")
        self.wheel.pack(padx=1, pady=1)
        self.wheel.bind("<Button-1>", self._wheel_click)
        self.wheel.bind("<B1-Motion>", self._wheel_click)

        right = tk.Frame(top, bg=C_BG); right.pack(side='left', fill='both', expand=True)
        prv = tk.Frame(right, bg=C_BG); prv.pack(fill='x', pady=(0,6))
        self.preview = tk.Canvas(prv, width=60, height=60, bg=C_BG_DARK,
                                  highlightthickness=1, highlightbackground=C_BORDER)
        self.preview.pack(side='left')
        hx = tk.Frame(prv, bg=C_BG); hx.pack(side='left', padx=(8,0), fill='x', expand=True)
        tk.Label(hx, text="HEX:", bg=C_BG, fg=C_TEXT_DIM,
                 font=("Segoe UI", 8), anchor='w').pack(fill='x')
        self.hex_var = tk.StringVar()
        e = ttk.Entry(hx, textvariable=self.hex_var, width=10, style="Num.TEntry",
                      justify='center', font=("Consolas", 10))
        e.pack(anchor='w', pady=(2,0))
        e.bind("<Return>", self._hex_entered); e.bind("<FocusOut>", self._hex_entered)
        vf = tk.Frame(right, bg=C_BG); vf.pack(fill='x', pady=(6,0))
        tk.Label(vf, text="Яркость", bg=C_BG, fg=C_TEXT_DIM,
                 font=("Segoe UI", 8)).pack(anchor='w')
        self.v_var = tk.DoubleVar(value=self._v * 100)
        ttk.Scale(vf, from_=1, to=100, variable=self.v_var, orient='horizontal',
                  command=self._v_slider).pack(fill='x')

        rgb_frame = tk.Frame(self, bg=C_BG_ALT); rgb_frame.pack(fill='x', pady=(4,4), ipady=4)
        rgb_in = tk.Frame(rgb_frame, bg=C_BG_ALT); rgb_in.pack(fill='x', padx=8)
        self.r_var = tk.IntVar(); self.g_var = tk.IntVar(); self.b_var = tk.IntVar()
        for letter, var in [("R", self.r_var), ("G", self.g_var), ("B", self.b_var)]:
            tk.Label(rgb_in, text=letter, bg=C_BG_ALT, fg=C_TEXT,
                     font=("Segoe UI", 9, "bold"), width=2).pack(side='left')
            ttk.Scale(rgb_in, from_=0, to=255, variable=var, orient='horizontal',
                      command=lambda v, vv=var: self._rgb_slider(vv)).pack(
                        side='left', fill='x', expand=True, padx=(0,4))
            e2 = ttk.Entry(rgb_in, width=4, textvariable=var, style="Num.TEntry", justify='center')
            e2.pack(side='left', padx=(0,8))
            e2.bind("<Return>", lambda ev, vv=var: self._rgb_entry(vv))
            e2.bind("<FocusOut>", lambda ev, vv=var: self._rgb_entry(vv))

        hsv_frame = tk.Frame(self, bg=C_BG_ALT); hsv_frame.pack(fill='x', pady=(2,4), ipady=4)
        hsv_in = tk.Frame(hsv_frame, bg=C_BG_ALT); hsv_in.pack(fill='x', padx=8)
        tk.Label(hsv_in, text="H°", bg=C_BG_ALT, fg=C_TEXT,
                 font=("Segoe UI", 9, "bold"), width=3).pack(side='left')
        self.h_var = tk.DoubleVar(value=self._h * 360)
        ttk.Scale(hsv_in, from_=0, to=360, variable=self.h_var, orient='horizontal',
                  command=self._h_slider).pack(side='left', fill='x', expand=True, padx=(0,4))
        e3 = ttk.Entry(hsv_in, width=4, textvariable=self.h_var, style="Num.TEntry", justify='center')
        e3.pack(side='left', padx=(0,8))
        e3.bind("<Return>", self._h_entry); e3.bind("<FocusOut>", self._h_entry)
        tk.Label(hsv_in, text="S%", bg=C_BG_ALT, fg=C_TEXT,
                 font=("Segoe UI", 9, "bold"), width=3).pack(side='left', padx=(8,0))
        self.s_var = tk.DoubleVar(value=self._s * 100)
        ttk.Scale(hsv_in, from_=0, to=100, variable=self.s_var, orient='horizontal',
                  command=self._s_slider).pack(side='left', fill='x', expand=True, padx=(0,4))
        e4 = ttk.Entry(hsv_in, width=4, textvariable=self.s_var, style="Num.TEntry", justify='center')
        e4.pack(side='left')
        e4.bind("<Return>", self._s_entry); e4.bind("<FocusOut>", self._s_entry)

    def _draw_wheel(self):
        self.wheel.delete("all")
        size = self._wheel_size; cx, cy = size/2, size/2; r_max = size/2 - 2
        rings, segs = 18, 90
        for ring in range(rings, 0, -1):
            rr = r_max * ring / rings; sat = ring / rings
            for seg in range(segs):
                h = seg / segs
                r_, g_, b_ = colorsys.hsv_to_rgb(h, sat, 1.0)
                color = f"#{int(r_*255):02x}{int(g_*255):02x}{int(b_*255):02x}"
                start = seg * 360 / segs; ext = 360 / segs + 0.5
                self.wheel.create_arc(cx-rr, cy-rr, cx+rr, cy+rr,
                                       start=start, extent=ext, fill=color, outline=color)
        self._update_wheel_marker()

    def _update_wheel_marker(self):
        self.wheel.delete("marker")
        size = self._wheel_size; cx, cy = size/2, size/2; r_max = size/2 - 2
        px = cx + self._s * r_max * math.cos(self._h * 2 * math.pi)
        py = cy - self._s * r_max * math.sin(self._h * 2 * math.pi)
        self.wheel.create_oval(px-6, py-6, px+6, py+6, outline="#000", width=3, tags="marker")
        self.wheel.create_oval(px-4, py-4, px+4, py+4, outline="#fff", width=2, tags="marker")

    def _wheel_click(self, event):
        size = self._wheel_size; cx, cy = size/2, size/2; r_max = size/2 - 2
        dx = event.x - cx; dy = event.y - cy
        d = math.sqrt(dx*dx + dy*dy)
        if d < 1: return
        if d > r_max: d = r_max
        self._s = d / r_max
        self._h = (math.atan2(-dy, dx) / (2*math.pi)) % 1.0
        self._refresh_all()

    def _v_slider(self, _=None):
        if self._updating: return
        self._v = max(0.01, self.v_var.get() / 100.0); self._refresh_all()
    def _h_slider(self, _=None):
        if self._updating: return
        self._h = (float(self.h_var.get()) / 360.0) % 1.0; self._refresh_all()
    def _s_slider(self, _=None):
        if self._updating: return
        self._s = max(0.0, min(1.0, float(self.s_var.get()) / 100.0)); self._refresh_all()
    def _h_entry(self, _=None):
        try: self._h = (float(self.h_var.get()) / 360.0) % 1.0; self._refresh_all()
        except Exception: pass
    def _s_entry(self, _=None):
        try: self._s = max(0.0, min(1.0, float(self.s_var.get()) / 100.0)); self._refresh_all()
        except Exception: pass
    def _rgb_slider(self, var):
        if self._updating: return
        try:
            r = max(0, min(255, int(self.r_var.get())))
            g = max(0, min(255, int(self.g_var.get())))
            b = max(0, min(255, int(self.b_var.get())))
            self._h, self._s, self._v = colorsys.rgb_to_hsv(r/255, g/255, b/255)
            self._refresh_all(rgb=(r, g, b))
        except Exception: pass
    def _rgb_entry(self, var): self._rgb_slider(var)
    def _hex_entered(self, _=None):
        try:
            hex_to_rgb(self.hex_var.get().strip())
            self._parse_hex(self.hex_var.get().strip()); self._refresh_all()
        except Exception: pass

    def _refresh_all(self, rgb=None):
        self._updating = True
        try:
            if rgb is None:
                r_f, g_f, b_f = colorsys.hsv_to_rgb(self._h, self._s, self._v)
                rgb = (int(r_f*255), int(g_f*255), int(b_f*255))
            r, g, b = rgb
            hex_color = rgb_to_hex(r, g, b)
            self.r_var.set(r); self.g_var.set(g); self.b_var.set(b)
            self.h_var.set(round(self._h * 360))
            self.s_var.set(round(self._s * 100))
            self.v_var.set(round(self._v * 100))
            self.hex_var.set(hex_color)
            self.preview.delete("all")
            self.preview.create_rectangle(0, 0, 60, 60, fill=hex_color, outline="")
        finally:
            self._updating = False
        self._update_wheel_marker()
        if self.on_change:
            try: self.on_change(self.get_hex())
            except Exception: pass

# =============== HUD ===============
class HUDOverlay:
    def __init__(self, root, pos_x=20, pos_y=20, on_move=None):
        self.root = root; self.pos_x = pos_x; self.pos_y = pos_y; self.on_move = on_move
        self.win = tk.Toplevel(root); self.win.overrideredirect(True)
        self.win.attributes('-topmost', True); self.win.attributes('-alpha', 0.78)
        self.win.configure(bg="#000000"); self.win.geometry(f"+{pos_x}+{pos_y}")
        self.outer = tk.Frame(self.win, bg="#000000"); self.outer.pack(fill='both', expand=True)
        self.frame = tk.Frame(self.outer, bg="#000000"); self.frame.pack(padx=6, pady=4)
        self.label = tk.Label(self.frame, text="", bg="#000000", fg="#00FF00",
                              font=("Consolas", 10), justify='left'); self.label.pack()
        self._hwnd = None; self._last_update = 0
        self._visible = False; self._show_fps=False; self._show_cpu=False
        self._show_gpu=False
        self._app_fps = None
        self._drag_mode=False; self._drag_dx=0; self._drag_dy=0; self._drag_moved=False
        self._create_hwnd(); self._bind_drag()
    def _create_hwnd(self):
        self.win.update_idletasks()
        try:
            self._hwnd = get_toplevel_hwnd(self.win)
            apply_alpha_style(self._hwnd, 180, clickable=False)
        except Exception: pass
    def _bind_drag(self):
        for w in (self.win, self.outer, self.frame, self.label):
            w.bind("<Button-1>", self._drag_start); w.bind("<B1-Motion>", self._drag_move)
            w.bind("<ButtonRelease-1>", self._drag_end)
    def _drag_start(self, e):
        if not self._drag_mode: return
        self._drag_dx = e.x_root - self.win.winfo_x(); self._drag_dy = e.y_root - self.win.winfo_y()
        self._drag_moved = False
    def _drag_move(self, e):
        if not self._drag_mode: return
        self._drag_moved = True
        self.win.geometry(f"+{e.x_root-self._drag_dx}+{e.y_root-self._drag_dy}")
        self.pos_x = e.x_root-self._drag_dx; self.pos_y = e.y_root-self._drag_dy
    def _drag_end(self, e):
        if self._drag_moved and self.on_move: self.on_move(self.pos_x, self.pos_y)
    def set_drag_mode(self, on):
        self._drag_mode = on
        if self._hwnd:
            try: apply_alpha_style(self._hwnd, 180, clickable=on)
            except Exception: pass
        if on: self.outer.configure(bd=2, highlightthickness=2, highlightbackground="#ff4060")
        else:  self.outer.configure(bd=0, highlightthickness=0)
    def set_position(self, x, y):
        self.pos_x = x; self.pos_y = y
        try: self.win.geometry(f"+{x}+{y}")
        except Exception: pass
    def set_visible(self, v):
        self._visible = v
        if v:
            self.win.deiconify(); self.win.lift()
            if self._hwnd: push_to_top(self._hwnd)
        else: self.win.withdraw()
    def set_options(self, fps, cpu, gpu):
        self._show_fps=fps; self._show_cpu=cpu; self._show_gpu=gpu
        GPU_READER.set_enabled(gpu)
    def set_fps(self, fps):
        self._app_fps = fps
    def set_style(self, font_size, color):
        try: self.label.configure(font=("Consolas", font_size), fg=color)
        except Exception: pass
    def tick(self):
        now = time.time()
        if now - self._last_update >= 0.5:
            self._last_update = now; self._update_text()
            if self._visible and self._hwnd: push_to_top(self._hwnd)
    def _update_text(self):
        lines = []
        if self._show_fps and self._app_fps is not None:
            lines.append(f"FPS: {self._app_fps}")
        if self._show_cpu and HAS_PSUTIL:
            try: lines.append(f"CPU: {psutil.cpu_percent(interval=None):.0f}%")
            except Exception: lines.append("CPU: N/A")
        if self._show_gpu:
            v = GPU_READER.value
            lines.append(f"GPU: {v}" if v else "GPU: ...")
        self.label.configure(text="\n".join(lines) if lines else "HUD")

# =============== Notifications ===============
class NotificationOverlay:
    def __init__(self, root):
        self.root = root
        self.win = tk.Toplevel(root); self.win.overrideredirect(True)
        self.win.attributes('-topmost', True); self.win.attributes('-alpha', 0.0)
        self.win.configure(bg="#1e1f22")
        self.frame = tk.Frame(self.win, bg="#1e1f22"); self.frame.pack()
        self.label = tk.Label(self.frame, text="", bg="#1e1f22", fg="#e6e6e8",
                              font=("Segoe UI Semibold", 11), padx=22, pady=12); self.label.pack()
        self._hwnd = None; self._job = None
        self.win.update_idletasks()
        try:
            self._hwnd = get_toplevel_hwnd(self.win)
            st = user32.GetWindowLongW(self._hwnd, GWL_EXSTYLE)
            st |= WS_EX_LAYERED|WS_EX_TRANSPARENT|WS_EX_TOOLWINDOW|WS_EX_TOPMOST|WS_EX_NOACTIVATE
            user32.SetWindowLongW(self._hwnd, GWL_EXSTYLE, st)
        except Exception: pass
        self.win.withdraw()
    def show(self, text, duration=1.5, accent=None):
        try:
            self.label.configure(text=text)
            bg = accent or "#1e1f22"
            self.win.configure(bg=bg); self.frame.configure(bg=bg); self.label.configure(bg=bg)
            self.win.update_idletasks()
            w = self.win.winfo_width(); sw = self.win.winfo_screenwidth()
            self.win.geometry(f"+{(sw-w)//2}+80")
            self.win.deiconify(); self.win.lift(); self.win.attributes('-alpha', 0.92)
            if self._hwnd: push_to_top(self._hwnd)
            if self._job:
                try: self.root.after_cancel(self._job)
                except Exception: pass
            self._job = self.root.after(int(duration*1000), self._hide)
        except Exception: pass
    def _hide(self):
        try: self.win.attributes('-alpha', 0.0); self.win.withdraw()
        except Exception: pass
        self._job = None

# =============== Widgets ===============
class ColorSwatch(tk.Canvas):
    def __init__(self, parent, color, command, size=22, **kw):
        super().__init__(parent, width=size, height=size, bg="#1e1f22",
                         highlightthickness=0, bd=0, **kw)
        self._color = color; self._command = command; self._size = size
        self._selected = False; self._draw()
        self.bind("<Button-1>", lambda e: self._command(self._color))
        self.bind("<Enter>", lambda e: self.configure(cursor="hand2"))
        self.bind("<Leave>", lambda e: self.configure(cursor=""))
    def set_selected(self, s): self._selected = s; self._draw()
    def _draw(self):
        self.delete("all"); s = self._size
        if self._selected: self.create_oval(0,0,s,s, outline="#5865f2", width=2)
        self.create_oval(2,2,s-2,s-2, fill=self._color, outline="#3a3d44")

class NumberedSlider(ttk.Frame):
    def __init__(self, parent, label, var, frm, to, callback, reset_cb=None, fmt="{:.0f}"):
        super().__init__(parent, style="Card.TFrame")
        self.var = var; self.callback = callback; self.reset_cb = reset_cb; self.fmt = fmt
        self.columnconfigure(1, weight=1)
        if label:
            ttk.Label(self, text=label, style="FieldLabel.TLabel", width=15,
                      anchor='w').grid(row=0, column=0, sticky='w', padx=(0,6), pady=4)
        self.scale = ttk.Scale(self, from_=frm, to=to, variable=var, orient='horizontal',
                               command=self._move, style="Accent.Horizontal.TScale")
        self.scale.grid(row=0, column=1, sticky='ew', pady=4)
        self.entry_var = tk.StringVar(value=self.fmt.format(var.get()))
        e = ttk.Entry(self, textvariable=self.entry_var, width=6, justify='center', style="Num.TEntry")
        e.grid(row=0, column=2, padx=(6,0), pady=4)
        e.bind("<Return>", self._entry); e.bind("<FocusOut>", self._entry)
        self.scale.bind("<Button-3>", lambda ev: self._reset())
        var.trace_add('write', self._var_change)
    def _move(self, _=None):
        try: v = float(self.var.get()); self.entry_var.set(self.fmt.format(v))
        except Exception: return
        if self.callback: self.callback()
    def _var_change(self, *_):
        try: self.entry_var.set(self.fmt.format(float(self.var.get())))
        except Exception: pass
    def _entry(self, _=None):
        try: v = float(self.entry_var.get().replace(",", "."))
        except Exception: self._var_change(); return
        lo, hi = float(self.scale.cget("from")), float(self.scale.cget("to"))
        v = max(lo, min(hi, v)); self.var.set(v); self._var_change()
        if self.callback: self.callback()
    def _reset(self):
        if self.reset_cb: self.reset_cb()

class HotkeyRow(ttk.Frame):
    def __init__(self, parent, keys, desc):
        super().__init__(parent, style="Card.TFrame")
        for k in keys:
            tk.Label(self, text=k, bg="#2b2d31", fg="#e6e6e8",
                     font=("Segoe UI", 8, "bold"), padx=6, pady=2).pack(side='left', padx=(0,3))
        ttk.Label(self, text=desc, style="Dim.TLabel").pack(side='left', padx=(8,0))

# =============== Layer ===============
class Layer:
    PARAMS = ["enabled","style","size","thickness","gap","dot","color",
              "outline","outline_color","outline_thickness",
              "offset_x","offset_y","opacity","scale",
              "rotate_enabled","rotate_speed","rotate_dir","rotate_orbit",
              "rainbow_enabled","rainbow_speed","rainbow_sat","rainbow_val",
              "pulse_enabled","pulse_period","pulse_min",
              "gradient_enabled","gradient_color","gradient_angle","gradient_animated",
              "glow_enabled","glow_color","glow_size",
              "shadow_enabled","shadow_color","shadow_offset_x","shadow_offset_y",
              "blink_enabled","blink_period","blink_duty",
              "breathe_enabled","breathe_period","breathe_amplitude",
              "wobble_enabled","wobble_amount","wobble_period",
              "trail_enabled","trail_length"]
    def __init__(self, d=None):
        d = d or {}
        self.enabled = tk.BooleanVar(value=d.get("enabled", True))
        self.style = tk.StringVar(value=d.get("style", "dot_cross"))
        self.size = tk.IntVar(value=d.get("size", 12))
        self.thickness = tk.IntVar(value=d.get("thickness", 2))
        self.gap = tk.IntVar(value=d.get("gap", 5))
        self.dot = tk.IntVar(value=d.get("dot", 3))
        self.color = tk.StringVar(value=d.get("color", "#00FF00"))
        self.outline = tk.BooleanVar(value=d.get("outline", False))
        self.outline_color = tk.StringVar(value=d.get("outline_color", "#000000"))
        self.outline_thickness = tk.IntVar(value=d.get("outline_thickness", 1))
        self.offset_x = tk.IntVar(value=d.get("offset_x", 0))
        self.offset_y = tk.IntVar(value=d.get("offset_y", 0))
        self.opacity = tk.IntVar(value=d.get("opacity", 100))
        self.scale = tk.IntVar(value=d.get("scale", 100))
        self.rotate_enabled = tk.BooleanVar(value=d.get("rotate_enabled", False))
        self.rotate_speed = tk.IntVar(value=d.get("rotate_speed", 45))
        self.rotate_dir = tk.IntVar(value=d.get("rotate_dir", 1))
        self.rotate_orbit = tk.BooleanVar(value=d.get("rotate_orbit", False))
        self.rainbow_enabled = tk.BooleanVar(value=d.get("rainbow_enabled", False))
        self.rainbow_speed = tk.IntVar(value=d.get("rainbow_speed", 60))
        self.rainbow_sat = tk.IntVar(value=d.get("rainbow_sat", 100))
        self.rainbow_val = tk.IntVar(value=d.get("rainbow_val", 100))
        self.pulse_enabled = tk.BooleanVar(value=d.get("pulse_enabled", False))
        self.pulse_period = tk.IntVar(value=d.get("pulse_period", 1000))
        self.pulse_min = tk.IntVar(value=d.get("pulse_min", 30))
        self.gradient_enabled = tk.BooleanVar(value=d.get("gradient_enabled", False))
        self.gradient_color = tk.StringVar(value=d.get("gradient_color", "#FF00FF"))
        self.gradient_angle = tk.IntVar(value=d.get("gradient_angle", 0))
        self.gradient_animated = tk.BooleanVar(value=d.get("gradient_animated", False))
        self.glow_enabled = tk.BooleanVar(value=d.get("glow_enabled", False))
        self.glow_color = tk.StringVar(value=d.get("glow_color", "#00FF00"))
        self.glow_size = tk.IntVar(value=d.get("glow_size", 2))
        self.shadow_enabled = tk.BooleanVar(value=d.get("shadow_enabled", False))
        self.shadow_color = tk.StringVar(value=d.get("shadow_color", "#000000"))
        self.shadow_offset_x = tk.IntVar(value=d.get("shadow_offset_x", 2))
        self.shadow_offset_y = tk.IntVar(value=d.get("shadow_offset_y", 2))
        self.blink_enabled = tk.BooleanVar(value=d.get("blink_enabled", False))
        self.blink_period = tk.IntVar(value=d.get("blink_period", 800))
        self.blink_duty = tk.IntVar(value=d.get("blink_duty", 50))
        self.breathe_enabled = tk.BooleanVar(value=d.get("breathe_enabled", False))
        self.breathe_period = tk.IntVar(value=d.get("breathe_period", 1500))
        self.breathe_amplitude = tk.IntVar(value=d.get("breathe_amplitude", 20))
        self.wobble_enabled = tk.BooleanVar(value=d.get("wobble_enabled", False))
        self.wobble_amount = tk.IntVar(value=d.get("wobble_amount", 3))
        self.wobble_period = tk.IntVar(value=d.get("wobble_period", 1200))
        self.trail_enabled = tk.BooleanVar(value=d.get("trail_enabled", False))
        self.trail_length = tk.IntVar(value=d.get("trail_length", 3))
        self.angle = 0.0
    def to_dict(self): return {k: getattr(self, k).get() for k in self.PARAMS}
    def copy(self): return Layer(self.to_dict())

# =============== Window picker ===============
class WindowPicker:
    def __init__(self, root, on_pick, on_cancel=None):
        self.root = root; self.on_pick = on_pick; self.on_cancel = on_cancel
        self.hwnd_under = 0; self._rect_id = None; self._picker_hwnd = None; self._closed = False
        self.win = tk.Toplevel(root); self.win.overrideredirect(True)
        self.win.attributes('-topmost', True); self.win.attributes('-alpha', 0.35)
        self.win.configure(bg="#000000")
        sw = self.win.winfo_screenwidth(); sh = self.win.winfo_screenheight()
        self.win.geometry(f"{sw}x{sh}+0+0")
        self.canvas = tk.Canvas(self.win, bg="#000000", highlightthickness=0, bd=0)
        self.canvas.pack(fill='both', expand=True)
        self.canvas.create_text(sw//2, 60, text="Кликните по окну", fill="#fff",
                                font=("Segoe UI", 16, "bold"))
        self.canvas.create_text(sw//2, 92, text="Esc — отмена", fill="#ccc", font=("Segoe UI", 10))
        self.canvas.bind("<Button-1>", self._on_click)
        self.win.bind("<Escape>", lambda e: self._cancel())
        self.win.focus_force(); self.win.update_idletasks()
        try: self._picker_hwnd = get_toplevel_hwnd(self.win)
        except Exception: self._picker_hwnd = self.win.winfo_id()
        self._tick()
    def _get_under(self, x, y):
        if not self._picker_hwnd: return root_window_at(x, y)
        try:
            st = user32.GetWindowLongW(self._picker_hwnd, GWL_EXSTYLE)
            user32.SetWindowLongW(self._picker_hwnd, GWL_EXSTYLE, st | WS_EX_TRANSPARENT)
            try: hwnd = root_window_at(x, y)
            finally: user32.SetWindowLongW(self._picker_hwnd, GWL_EXSTYLE, st)
            return hwnd
        except Exception: return root_window_at(x, y)
    def _tick(self):
        if self._closed: return
        try:
            pt = POINT(); user32.GetCursorPos(ctypes.byref(pt))
            hwnd = self._get_under(pt.x, pt.y); self.hwnd_under = hwnd
            if hwnd and hwnd != self._picker_hwnd and user32.IsWindow(hwnd):
                r = RECT()
                if user32.GetWindowRect(hwnd, ctypes.byref(r)):
                    coords = (r.left+3, r.top+3, r.right-3, r.bottom-3)
                    if self._rect_id is None:
                        self._rect_id = self.canvas.create_rectangle(*coords, outline="#ff4060", width=3)
                    else: self.canvas.coords(self._rect_id, *coords)
                else: self._hide_rect()
            else: self._hide_rect()
        except Exception: pass
        self.win.after(30, self._tick)
    def _hide_rect(self):
        if self._rect_id is not None:
            self.canvas.delete(self._rect_id); self._rect_id = None
    def _on_click(self, event):
        hwnd = self.hwnd_under
        if hwnd and hwnd != self._picker_hwnd:
            self._close()
            try: self.on_pick(hwnd)
            except Exception: pass
    def _cancel(self):
        self._close()
        if self.on_cancel:
            try: self.on_cancel()
            except Exception: pass
    def _close(self):
        self._closed = True
        try: self.win.destroy()
        except Exception: pass

# =============== Window brightness ===============
class WindowBrightnessOverlay:
    def __init__(self, root):
        self.root = root; self.target_hwnd = 0; self.brightness = 1.0; self.enabled = False
        self._hwnd = None; self._win = None; self._last_geom = None
        self._last_alpha = -1; self._last_color = None
        self._win = tk.Toplevel(root); self._win.overrideredirect(True)
        self._win.attributes('-topmost', True); self._win.configure(bg="#000000")
        self._win.geometry("1x1+0+0"); self._win.update_idletasks()
        try:
            self._hwnd = get_toplevel_hwnd(self._win)
            apply_alpha_style(self._hwnd, 0, clickable=False)
        except Exception: pass
        self._win.withdraw()
    def set_target(self, h): self.target_hwnd = h or 0
    def set_brightness(self, b): self.brightness = float(b); self._refresh()
    def set_enabled(self, e): self.enabled = bool(e); self._refresh()
    def _calc(self):
        b = self.brightness
        if abs(b - 1.0) < 0.01: return None, 0
        if b < 1.0:
            t = (1.0 - b) / 0.7; return "#000000", int(max(0, min(255, t * 230)))
        t = (b - 1.0) / 1.0; return "#FFFFFF", int(max(0, min(255, t * 130)))
    def _refresh(self):
        if not self._hwnd: return
        try:
            hwnd = self.target_hwnd
            show = self.enabled and hwnd and user32.IsWindow(hwnd) and \
                   user32.IsWindowVisible(hwnd) and not user32.IsIconic(hwnd)
            if not show: self._hide(); return
            color, alpha = self._calc()
            if alpha <= 0: self._hide(); return
            r = RECT()
            if not user32.GetWindowRect(hwnd, ctypes.byref(r)): self._hide(); return
            w = max(1, r.right-r.left); h = max(1, r.bottom-r.top)
            geom = (r.left, r.top, w, h)
            if color != self._last_color:
                self._win.configure(bg=color); self._last_color = color
            if geom != self._last_geom:
                self._win.geometry(f"{w}x{h}+{r.left}+{r.top}"); self._last_geom = geom
            try: self._win.deiconify(); self._win.lift()
            except Exception: pass
            if alpha != self._last_alpha:
                apply_alpha_style(self._hwnd, alpha, clickable=False); self._last_alpha = alpha
            push_to_top(self._hwnd)
        except Exception: pass
    def _hide(self):
        try: self._win.withdraw()
        except Exception: pass
        self._last_geom = None; self._last_alpha = -1; self._last_color = None
    def tick(self): self._refresh()

# =============== Mini mode ===============
class MiniMode:
    def __init__(self, root, app):
        self.root = root; self.app = app
        self.win = tk.Toplevel(root); self.win.overrideredirect(True)
        self.win.attributes('-topmost', True); self.win.configure(bg="#1e1f22")
        self.win.geometry("+50+50")
        f = tk.Frame(self.win, bg="#1e1f22", bd=1, relief='solid'); f.pack()
        t = tk.Label(f, text=f" CROSSHAIR v{APP_VERSION} ", bg="#2b2d31", fg="#e6e6e8",
                     font=("Segoe UI", 8, "bold"), padx=6, pady=3); t.pack(fill='x')
        t.bind("<Button-1>", self._start_drag); t.bind("<B1-Motion>", self._drag)
        bf = tk.Frame(f, bg="#1e1f22"); bf.pack(padx=4, pady=4)
        self.btn = tk.Button(bf, text="ВКЛ", bg="#3ba55d", fg="white",
                             font=("Segoe UI", 8, "bold"), width=5, command=self._toggle)
        self.btn.pack(side='left', padx=2)
        tk.Button(bf, text="+", bg="#2b2d31", fg="#e6e6e8", width=2,
                  command=lambda: self._adj(0.1)).pack(side='left', padx=1)
        self.lbl = tk.Label(bf, text="1.0", bg="#1e1f22", fg="#e6e6e8", width=4,
                            font=("Segoe UI", 9, "bold")); self.lbl.pack(side='left')
        tk.Button(bf, text="−", bg="#2b2d31", fg="#e6e6e8", width=2,
                  command=lambda: self._adj(-0.1)).pack(side='left', padx=1)
        tk.Button(bf, text="✕", bg="#c0392b", fg="white", width=2,
                  command=self.hide).pack(side='left', padx=(6,0))
        self._dx = 0; self._dy = 0; self.update()
    def _start_drag(self, e): self._dx = e.x; self._dy = e.y
    def _drag(self, e):
        self.win.geometry(f"+{self.win.winfo_x()+e.x-self._dx}+{self.win.winfo_y()+e.y-self._dy}")
    def _toggle(self):
        self.app.enabled_var.set(not self.app.enabled_var.get())
        self.app._toggle_crosshair(); self.update()
    def _adj(self, d):
        b = max(0.3, min(2.0, float(self.app.brightness_var.get()) + d))
        self.app._set_brightness(b); self.lbl.configure(text=f"{b:.1f}")
    def update(self):
        if self.app.enabled_var.get(): self.btn.configure(text="ВКЛ", bg="#3ba55d")
        else: self.btn.configure(text="ВЫКЛ", bg="#8a8d94")
        self.lbl.configure(text=f"{float(self.app.brightness_var.get()):.1f}")
    def show(self): self.win.deiconify(); self.win.lift()
    def hide(self): self.win.withdraw()
    def toggle(self):
        if self.win.state() == 'withdrawn': self.show()
        else: self.hide()

# =============== DEFAULTS ===============
DEFAULTS = {
    "version": 4, "enabled": True, "brightness": 1.0, "brightness_mode": "screen",
    "start_minimized": False, "notify_enabled": True,
    "hud_show_fps": False, "hud_show_cpu": False, "hud_show_gpu": False,
    "hud_pos_x": 20, "hud_pos_y": 20,
    "hud_font_size": 10, "hud_color": "#00FF00",
    "active_idx": 0,
    "layers": [{"enabled": True, "style": "dot_cross", "size": 12, "thickness": 2,
                "gap": 5, "dot": 3, "color": "#00FF00", "offset_x": 0, "offset_y": 0,
                "glow_enabled": False, "glow_color": "#00FF00", "glow_size": 2,
                "shadow_enabled": False, "shadow_color": "#000000",
                "shadow_offset_x": 2, "shadow_offset_y": 2,
                "blink_enabled": False, "blink_period": 800, "blink_duty": 50,
                "breathe_enabled": False, "breathe_period": 1500, "breathe_amplitude": 20,
                "wobble_enabled": False, "wobble_amount": 3, "wobble_period": 1200,
                "trail_enabled": False, "trail_length": 3,
                "gradient_animated": False}],
}

# ==================== App ====================
class CrosshairApp:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title(f"Crosshair & Brightness v{APP_VERSION}")
        self.root.geometry("700x1000")
        self.root.resizable(False, False); self.root.configure(bg=C_BG)
        self._setup_styles()

        self._loading = True; self._shutting_down = False
        self._overlay_hwnd = None; self._overlay_colorref = None
        self._pending_brightness = None; self._brightness_job = None
        self._last_applied = None; self._swatches = []
        self._color_history = []; self._custom_palette = []
        self._anim_time = 0.0; self._last_frame = time.time()
        self._app_fps = 0; self._app_fps_counter = 0; self._app_fps_time = time.time()
        self.live_color_var = tk.BooleanVar(value=True)

        self.target_hwnd = 0; self.target_name = ""
        self._picker = None; self.mini = None; self.hud = None
        self.notify = None; self.tray_icon = None; self._tray_thread = None
        self.layers = []; self.active_idx = 0
        self.color_picker = None

        self.enabled_var = tk.BooleanVar(value=True)
        self.brightness_var = tk.DoubleVar(value=1.0)
        self.br_mode_var = tk.StringVar(value="screen")
        self.start_min_var = tk.BooleanVar(value=False)
        self.notify_enabled_var = tk.BooleanVar(value=True)
        self.hud_fps_var = tk.BooleanVar(value=False)
        self.hud_cpu_var = tk.BooleanVar(value=False)
        self.hud_gpu_var = tk.BooleanVar(value=False)
        self.hud_font_size_var = tk.IntVar(value=10)
        self.hud_color_var = tk.StringVar(value="#00FF00")
        self.hud_pos_x = 20; self.hud_pos_y = 20
        self.hud_drag_var = tk.BooleanVar(value=False)
        self.profile_var = tk.StringVar(value="")

        self._build_ui()
        self.root.after(50, self._create_overlay)
        self.win_overlay = WindowBrightnessOverlay(self.root)
        self._load_settings()
        if not self.layers: self.layers = [Layer()]
        self.active_idx = max(0, min(self.active_idx, len(self.layers) - 1))
        self._loading = False
        self._rebuild_layer_list(); self._rebuild_params_tab()
        self._rebuild_color_tab(); self._rebuild_effects_tab()
        self._redraw(); self._update_status(); self._apply_mode()

        self.mini = MiniMode(self.root, self)
        self.hud = HUDOverlay(self.root, pos_x=self.hud_pos_x, pos_y=self.hud_pos_y,
                              on_move=self._on_hud_moved)
        self._update_hud_options()
        self.notify = NotificationOverlay(self.root)

        self._setup_tray()
        self._hk_queue = queue.Queue()
        self._start_hotkeys(); self._poll_hotkeys()
        self.root.after(300, self._keep_on_top)
        self.root.after(500, self._win_overlay_loop)
        self.root.after(1000, self._hud_loop)
        self.root.after(2000, self._reapply_brightness_loop)
        self.root.after(16, self._animation_loop)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        if self.start_min_var.get():
            self.root.after(500, lambda: self.root.withdraw())

    def _setup_styles(self):
        st = ttk.Style(self.root)
        try: st.theme_use('clam')
        except Exception: pass
        st.configure(".", background=C_BG, foreground=C_TEXT, fieldbackground=C_BG_ALT,
                     bordercolor=C_BORDER, font=("Segoe UI", 9))
        st.configure("TFrame", background=C_BG)
        st.configure("Card.TFrame", background=C_BG)
        st.configure("TLabel", background=C_BG, foreground=C_TEXT, font=("Segoe UI", 9))
        st.configure("Dim.TLabel", background=C_BG, foreground=C_TEXT_DIM, font=("Segoe UI", 8))
        st.configure("FieldLabel.TLabel", background=C_BG, foreground=C_TEXT)
        st.configure("SectionTitle.TLabel", background=C_BG, foreground=C_TEXT,
                     font=("Segoe UI Semibold", 10))
        st.configure("TNotebook", background=C_BG, borderwidth=0, tabmargins=(0,0,0,0))
        st.configure("TNotebook.Tab", background=C_BG_ALT, foreground=C_TEXT_DIM,
                     padding=(7,8), font=("Segoe UI", 9))
        st.map("TNotebook.Tab", background=[("selected", C_ACCENT)],
               foreground=[("selected", "#ffffff")])
        st.configure("Accent.Horizontal.TScale", background=C_BG, troughcolor=C_BG_ALT,
                     borderwidth=0, lightcolor=C_ACCENT, darkcolor=C_ACCENT)
        st.configure("Num.TEntry", fieldbackground=C_BG_ALT, foreground=C_TEXT,
                     insertcolor=C_TEXT, bordercolor=C_BORDER, padding=3)
        st.configure("TButton", background=C_BG_ALT, foreground=C_TEXT,
                     bordercolor=C_BORDER, focusthickness=0, padding=(10,6))
        st.map("TButton", background=[("active", C_ACCENT), ("pressed", C_ACCENT_H)],
               foreground=[("active", "#ffffff")])
        st.configure("Accent.TButton", background=C_ACCENT, foreground="#ffffff",
                     borderwidth=0, padding=(10,6), font=("Segoe UI Semibold", 9))
        st.map("Accent.TButton", background=[("active", C_ACCENT_H)])
        st.configure("TRadiobutton", background=C_BG, foreground=C_TEXT)
        st.configure("TCheckbutton", background=C_BG, foreground=C_TEXT)

    def _build_ui(self):
        header = tk.Frame(self.root, bg=C_BG); header.pack(fill='x', padx=14, pady=(12,4))
        tk.Label(header, text="Crosshair", bg=C_BG, fg=C_TEXT,
                 font=("Segoe UI Semibold", 15)).pack(side='left')
        tk.Label(header, text=f"  v{APP_VERSION}", bg=C_BG, fg=C_TEXT_DIM,
                 font=("Segoe UI", 15)).pack(side='left')
        nb = ttk.Notebook(self.root); nb.pack(fill='both', expand=True, padx=10, pady=(4,8))
        self._tab_layers(nb); self._tab_params(nb); self._tab_color(nb)
        self._tab_effects(nb); self._tab_brightness(nb); self._tab_hud(nb)
        self._tab_hotkeys(nb); self._tab_settings(nb)
        self._build_statusbar()

    def _build_statusbar(self):
        bar = tk.Frame(self.root, bg=C_BG_ALT, height=28); bar.pack(fill='x', side='bottom')
        bar.pack_propagate(False)
        self._status_cross = tk.Label(bar, text="● Прицел: вкл", bg=C_BG_ALT, fg=C_OK,
                                      font=("Segoe UI", 8), padx=10); self._status_cross.pack(side='left')
        self._status_layers = tk.Label(bar, text="Слоёв: 1", bg=C_BG_ALT, fg=C_TEXT_DIM,
                                       font=("Segoe UI", 8), padx=10); self._status_layers.pack(side='left')
        self._status_bright = tk.Label(bar, text="Яркость: 1.00", bg=C_BG_ALT,
                                       fg=C_TEXT_DIM, font=("Segoe UI", 8), padx=10)
        self._status_bright.pack(side='right')

    # ============ Слои ============
    def _tab_layers(self, nb):
        self.tab_layers_scroll = ScrollableFrame(nb)
        nb.add(self.tab_layers_scroll, text=" Слои ")
        tab = self.tab_layers_scroll.inner
        top = tk.Frame(tab, bg=C_BG); top.pack(fill='x', padx=14, pady=(12,6))
        ttk.Checkbutton(top, text="Показывать прицел на экране",
                        variable=self.enabled_var,
                        command=self._toggle_crosshair).pack(anchor='w')
        ttk.Label(tab, text="Слои прицела (клик — выбрать)",
                  style="SectionTitle.TLabel").pack(anchor='w', padx=14, pady=(8,4))
        tk.Label(tab, text="Наложи несколько фигур. У каждого — свой цвет, эффекты,\n"
                           "вращение, позиция.",
                 bg=C_BG, fg=C_TEXT_DIM, justify='left',
                 font=("Segoe UI", 8)).pack(anchor='w', padx=14, pady=(0,6))
        self.layers_container = tk.Frame(tab, bg=C_BG)
        self.layers_container.pack(fill='x', padx=14, pady=(4,6))
        btn_row = tk.Frame(tab, bg=C_BG); btn_row.pack(fill='x', padx=14, pady=(0,8))
        ttk.Button(btn_row, text="+ Добавить", command=self._add_layer).pack(side='left')
        ttk.Button(btn_row, text="⧉ Копия", command=self._duplicate_layer).pack(side='left', padx=(4,0))
        ttk.Button(btn_row, text="🗑 Удалить", command=self._delete_layer).pack(side='left', padx=(4,0))
        ttk.Button(btn_row, text="↑", width=3, command=lambda: self._move_layer(-1)).pack(side='left', padx=(4,0))
        ttk.Button(btn_row, text="↓", width=3, command=lambda: self._move_layer(1)).pack(side='left', padx=(2,0))
        tk.Frame(tab, bg=C_BG, height=20).pack(fill='x')

    def _rebuild_layer_list(self):
        for w in self.layers_container.winfo_children(): w.destroy()
        for i, layer in enumerate(self.layers):
            row = tk.Frame(self.layers_container, bg=C_BG); row.pack(fill='x', pady=2)
            canvas = tk.Canvas(row, width=70, height=50,
                               bg=C_BG_ALT if i != self.active_idx else C_ACCENT,
                               highlightthickness=2 if i == self.active_idx else 1,
                               highlightbackground=C_ACCENT if i == self.active_idx else C_BORDER)
            canvas.pack(side='left')
            canvas.bind("<Button-1>", lambda e, idx=i: self._select_layer(idx))
            self._draw_layer_preview(canvas, layer)
            info = tk.Frame(row, bg=C_BG); info.pack(side='left', padx=(8,0), fill='x', expand=True)
            name = f"▶ Слой {i+1} (активный)" if i == self.active_idx else f"Слой {i+1}"
            tk.Label(info, text=name, bg=C_BG,
                     fg=C_TEXT if i == self.active_idx else C_TEXT_DIM,
                     font=("Segoe UI", 9, "bold" if i == self.active_idx else "normal"),
                     anchor='w').pack(fill='x')
            style_name = STYLE_DICT.get(layer.style.get(), layer.style.get()).replace("\n", " ")
            extra = []
            if layer.rotate_enabled.get():
                d = "↻" if layer.rotate_dir.get() == 1 else "↺"
                extra.append(f"{d} {layer.rotate_speed.get()}°/с")
            if layer.rainbow_enabled.get(): extra.append("🌈")
            if layer.pulse_enabled.get(): extra.append("❤")
            if layer.glow_enabled.get(): extra.append("✨")
            if layer.shadow_enabled.get(): extra.append("🌑")
            if not layer.enabled.get(): extra.append("выкл")
            sub = style_name + ("  ·  " + " · ".join(extra) if extra else "")
            tk.Label(info, text=sub, bg=C_BG, fg=C_TEXT_DIM, font=("Segoe UI", 8),
                     anchor='w').pack(fill='x')
            try:
                sw = tk.Canvas(row, width=16, height=16, bg=C_BG, highlightthickness=0, bd=0)
                sw.create_oval(1,1,15,15, fill=layer.color.get(), outline=C_BORDER)
                sw.pack(side='right', padx=(4,0))
            except Exception: pass
            ttk.Checkbutton(row, variable=layer.enabled,
                            command=self._on_layer_enabled).pack(side='right', padx=(4,0))

    def _draw_layer_preview(self, canvas, layer):
        canvas.delete("all")
        if not layer.enabled.get():
            canvas.create_text(35, 25, text="—", fill=C_TEXT_DIM, font=("Segoe UI", 10)); return
        self._draw_layer_shape(canvas, layer, 35, 25, scale=0.8, skip_stipple=True)

    def _select_layer(self, idx):
        if idx < 0 or idx >= len(self.layers): return
        self.active_idx = idx
        self._rebuild_layer_list(); self._rebuild_params_tab()
        self._rebuild_color_tab(); self._rebuild_effects_tab(); self._redraw()

    def _add_layer(self):
        if len(self.layers) >= 5: self._notify("Максимум 5 слоёв"); return
        new_layer = Layer({"style": "ring", "size": 18,
                           "color": self.layers[self.active_idx].color.get() if self.layers else "#00FF00",
                           "rotate_enabled": True, "rotate_speed": 90, "rotate_dir": -1})
        self.layers.append(new_layer); self.active_idx = len(self.layers) - 1
        self._rebuild_layer_list(); self._rebuild_params_tab()
        self._rebuild_color_tab(); self._rebuild_effects_tab(); self._redraw(); self._update_status()

    def _duplicate_layer(self):
        if len(self.layers) >= 5: self._notify("Максимум 5 слоёв"); return
        if not self.layers: return
        dup = self.layers[self.active_idx].copy()
        self.layers.insert(self.active_idx + 1, dup); self.active_idx += 1
        self._rebuild_layer_list(); self._rebuild_params_tab()
        self._rebuild_color_tab(); self._rebuild_effects_tab(); self._redraw()

    def _delete_layer(self):
        if len(self.layers) <= 1: self._notify("Должен остаться хотя бы 1 слой"); return
        del self.layers[self.active_idx]
        self.active_idx = min(self.active_idx, len(self.layers) - 1)
        self._rebuild_layer_list(); self._rebuild_params_tab()
        self._rebuild_color_tab(); self._rebuild_effects_tab(); self._redraw(); self._update_status()

    def _move_layer(self, direction):
        i = self.active_idx; j = i + direction
        if j < 0 or j >= len(self.layers): return
        self.layers[i], self.layers[j] = self.layers[j], self.layers[i]
        self.active_idx = j
        self._rebuild_layer_list(); self._rebuild_params_tab()
        self._rebuild_color_tab(); self._rebuild_effects_tab(); self._redraw()

    def _on_layer_enabled(self):
        self._rebuild_layer_list(); self._redraw()

    # ============ Параметры ============
    def _tab_params(self, nb):
        self.tab_params_scroll = ScrollableFrame(nb)
        nb.add(self.tab_params_scroll, text=" Параметры ")
        self.tab_params = self.tab_params_scroll.inner

    def _rebuild_params_tab(self):
        for w in self.tab_params.winfo_children(): w.destroy()
        if not self.layers: return
        L = self.layers[self.active_idx]
        head = tk.Frame(self.tab_params, bg=C_BG); head.pack(fill='x', padx=14, pady=(12,4))
        tk.Label(head, text=f"Слой {self.active_idx + 1} из {len(self.layers)}",
                 bg=C_BG, fg=C_ACCENT, font=("Segoe UI Semibold", 12)).pack(anchor='w')
        tk.Label(head, text="Меняй настройки — видно сразу",
                 bg=C_BG, fg=C_TEXT_DIM, font=("Segoe UI", 8)).pack(anchor='w')
        prev_wrap = tk.Frame(self.tab_params, bg=C_BORDER); prev_wrap.pack(pady=(8,6))
        self.preview = tk.Canvas(prev_wrap, width=140, height=140, bg=C_BG_DARK,
                                 highlightthickness=0, bd=0); self.preview.pack(padx=1, pady=1)
        ttk.Label(self.tab_params, text="Стиль", style="SectionTitle.TLabel").pack(
            anchor='w', padx=14, pady=(6,4))
        style_grid = tk.Frame(self.tab_params, bg=C_BG); style_grid.pack(fill='x', padx=14, pady=(0,10))
        self._style_buttons = {}
        for i, (val, txt) in enumerate(STYLE_NAMES):
            r, c = i // 4, i % 4
            b = tk.Canvas(style_grid, width=90, height=52, bg=C_BG, highlightthickness=0, cursor="hand2")
            b.grid(row=r, column=c, padx=2, pady=2, sticky='nsew')
            style_grid.columnconfigure(c, weight=1)
            b.bind("<Button-1>", lambda e, v=val: self._choose_style(v, notify=True))
            self._style_buttons[val] = (b, txt)
        ttk.Label(self.tab_params, text="Геометрия", style="SectionTitle.TLabel").pack(
            anchor='w', padx=14, pady=(6,4))
        sl = tk.Frame(self.tab_params, bg=C_BG); sl.pack(fill='x', padx=14)
        NumberedSlider(sl, "Размер", L.size, 1, 80, self._redraw,
                       reset_cb=lambda: (L.size.set(12), self._redraw())).pack(fill='x')
        NumberedSlider(sl, "Толщина", L.thickness, 1, 12, self._redraw,
                       reset_cb=lambda: (L.thickness.set(2), self._redraw())).pack(fill='x')
        NumberedSlider(sl, "Отступ", L.gap, 0, 50, self._redraw,
                       reset_cb=lambda: (L.gap.set(5), self._redraw())).pack(fill='x')
        NumberedSlider(sl, "Радиус точки", L.dot, 1, 25, self._redraw,
                       reset_cb=lambda: (L.dot.set(3), self._redraw())).pack(fill='x')
        NumberedSlider(sl, "Масштаб %", L.scale, 30, 250, self._redraw,
                       reset_cb=lambda: (L.scale.set(100), self._redraw())).pack(fill='x')
        NumberedSlider(sl, "Прозрачность %", L.opacity, 20, 100, self._redraw,
                       reset_cb=lambda: (L.opacity.set(100), self._redraw())).pack(fill='x')
        of = tk.Frame(sl, bg=C_BG); of.pack(fill='x', pady=2)
        of.columnconfigure(0, weight=1); of.columnconfigure(1, weight=1)
        lx = tk.Frame(of, bg=C_BG); lx.grid(row=0, column=0, sticky='ew')
        NumberedSlider(lx, "Смещение X", L.offset_x, -500, 500, self._redraw,
                       reset_cb=lambda: (L.offset_x.set(0), self._redraw())).pack(fill='x')
        ly = tk.Frame(of, bg=C_BG); ly.grid(row=0, column=1, sticky='ew')
        NumberedSlider(ly, "Смещение Y", L.offset_y, -500, 500, self._redraw,
                       reset_cb=lambda: (L.offset_y.set(0), self._redraw())).pack(fill='x')
        ttk.Label(self.tab_params, text="Вращение", style="SectionTitle.TLabel").pack(
            anchor='w', padx=14, pady=(10,4))
        rot = tk.Frame(self.tab_params, bg=C_BG); rot.pack(fill='x', padx=14)
        ttk.Checkbutton(rot, text="Включить вращение", variable=L.rotate_enabled,
                        command=self._on_rotate_toggle).pack(anchor='w')
        ttk.Checkbutton(rot, text="Показывать орбиту", variable=L.rotate_orbit,
                        command=self._redraw).pack(anchor='w', pady=(2,0))
        dir_frame = tk.Frame(rot, bg=C_BG); dir_frame.pack(fill='x', pady=(4,2))
        ttk.Label(dir_frame, text="Направление:", style="FieldLabel.TLabel",
                  width=15, anchor='w').pack(side='left')
        ttk.Radiobutton(dir_frame, text="↻ По час.", variable=L.rotate_dir, value=1,
                        command=self._redraw).pack(side='left')
        ttk.Radiobutton(dir_frame, text="↺ Против", variable=L.rotate_dir, value=-1,
                        command=self._redraw).pack(side='left', padx=(6,0))
        NumberedSlider(rot, "Скорость (°/с)", L.rotate_speed, 5, 720, self._redraw,
                       reset_cb=lambda: (L.rotate_speed.set(45), self._redraw())).pack(fill='x', pady=(4,0))
        ttk.Label(self.tab_params, text="Обводка", style="SectionTitle.TLabel").pack(
            anchor='w', padx=14, pady=(10,4))
        o_row = tk.Frame(self.tab_params, bg=C_BG); o_row.pack(fill='x', padx=14)
        ttk.Checkbutton(o_row, text="Включить", variable=L.outline,
                        command=self._redraw).pack(side='left')
        tk.Label(o_row, text="цвет:", bg=C_BG, fg=C_TEXT_DIM,
                 font=("Segoe UI", 8)).pack(side='left', padx=(14,4))
        self.outline_btn = tk.Canvas(o_row, width=22, height=22, bg=C_BG,
                                     highlightthickness=0, cursor="hand2")
        self.outline_btn.pack(side='left')
        self.outline_btn.bind("<Button-1>", lambda e: self._pick_outline_color(L))
        self._draw_outline_btn(L.outline_color.get())
        NumberedSlider(self.tab_params, "Толщина обводки", L.outline_thickness, 1, 6, self._redraw,
                       reset_cb=lambda: (L.outline_thickness.set(1), self._redraw())
                       ).pack(fill='x', padx=14, pady=(4,20))
        self._refresh_style_buttons()

    def _on_rotate_toggle(self):
        L = self.layers[self.active_idx]
        if L.rotate_enabled.get(): L.angle = 0.0
        self._rebuild_layer_list(); self._redraw()

    def _refresh_style_buttons(self):
        if not self._style_buttons or not self.layers: return
        current = self.layers[self.active_idx].style.get()
        for val, (btn, txt) in self._style_buttons.items():
            self._draw_style_tile(btn, txt, val, selected=(val == current))

    def _draw_style_tile(self, canvas, text, val, selected=False):
        canvas.delete("all"); w, h = 90, 52
        bg = C_ACCENT if selected else C_BG_ALT
        outline = C_ACCENT if selected else C_BORDER
        canvas.create_rectangle(0, 0, w, h, fill=bg, outline=outline, width=1)
        cx, cy = w//2, 16; ic = "#ffffff" if selected else C_TEXT
        self._mini_icon(canvas, cx, cy, val, ic)
        canvas.create_text(w//2, h-10, text=text.replace("\n", " "),
                           fill=ic, font=("Segoe UI", 7), justify='center')

    def _mini_icon(self, canvas, cx, cy, val, ic):
        s = 9
        if val == "dot": canvas.create_oval(cx-3, cy-3, cx+3, cy+3, fill=ic, outline=ic)
        elif val == "cross":
            for a,b,c,d in [(cx-s,cy,cx-2,cy),(cx+2,cy,cx+s,cy),(cx,cy-s,cx,cy-2),(cx,cy+2,cx,cy+s)]:
                canvas.create_line(a,b,c,d, fill=ic, width=2)
        elif val == "dot_cross":
            for a,b,c,d in [(cx-s-2,cy,cx-4,cy),(cx+4,cy,cx+s+2,cy),(cx,cy-s-2,cx,cy-4),(cx,cy+4,cx,cy+s+2)]:
                canvas.create_line(a,b,c,d, fill=ic, width=2)
            canvas.create_oval(cx-2, cy-2, cx+2, cy+2, fill=ic, outline=ic)
        elif val == "ring": canvas.create_oval(cx-s, cy-s, cx+s, cy+s, outline=ic, width=2)
        elif val == "ring_dot":
            canvas.create_oval(cx-s, cy-s, cx+s, cy+s, outline=ic, width=2)
            canvas.create_oval(cx-2, cy-2, cx+2, cy+2, fill=ic, outline=ic)
        elif val == "t_shape":
            canvas.create_line(cx-s, cy, cx+s, cy, fill=ic, width=2)
            canvas.create_line(cx, cy, cx, cy+s, fill=ic, width=2)
        elif val == "chevron":
            canvas.create_line(cx-s, cy+4, cx, cy-4, fill=ic, width=2)
            canvas.create_line(cx, cy-4, cx+s, cy+4, fill=ic, width=2)
        elif val == "x_cross":
            canvas.create_line(cx-s, cy-s, cx+s, cy+s, fill=ic, width=2)
            canvas.create_line(cx-s, cy+s, cx+s, cy-s, fill=ic, width=2)
        elif val == "diamond":
            canvas.create_polygon(cx, cy-s, cx+s, cy, cx, cy+s, cx-s, cy, outline=ic, width=2, fill="")
        elif val == "square": canvas.create_rectangle(cx-s, cy-s, cx+s, cy+s, outline=ic, width=2)
        elif val == "triangle":
            canvas.create_polygon(cx, cy-s, cx+s, cy+s, cx-s, cy+s, outline=ic, width=2, fill="")
        elif val == "brackets_square":
            canvas.create_line(cx-s, cy-s, cx-s, cy+s, fill=ic, width=2)
            canvas.create_line(cx+s, cy-s, cx+s, cy+s, fill=ic, width=2)
        elif val == "double_ring":
            canvas.create_oval(cx-s, cy-s, cx+s, cy+s, outline=ic, width=2)
            canvas.create_oval(cx-s//2, cy-s//2, cx+s//2, cy+s//2, outline=ic, width=2)
        elif val == "cross_ring":
            canvas.create_oval(cx-s, cy-s, cx+s, cy+s, outline=ic, width=2)
            canvas.create_line(cx-s, cy, cx+s, cy, fill=ic, width=2)
            canvas.create_line(cx, cy-s, cx, cy+s, fill=ic, width=2)
        elif val == "heart":
            canvas.create_oval(cx-6, cy-3, cx, cy+3, fill=ic, outline=ic)
            canvas.create_oval(cx, cy-3, cx+6, cy+3, fill=ic, outline=ic)
            canvas.create_polygon(cx-6, cy, cx+6, cy, cx, cy+7, fill=ic, outline=ic)
        elif val == "star_5":
            pts = []
            for i in range(10):
                a = -math.pi/2 + i * math.pi/5
                r = s if i % 2 == 0 else s * 0.4
                pts.extend([cx + r*math.cos(a), cy + r*math.sin(a)])
            canvas.create_polygon(*pts, fill=ic, outline=ic)
        elif val == "hexagon":
            pts = []
            for i in range(6):
                a = i * math.pi/3 - math.pi/2
                pts.extend([cx + s*math.cos(a), cy + s*math.sin(a)])
            canvas.create_polygon(*pts, outline=ic, width=2, fill="")
        elif val == "chevron_down":
            canvas.create_line(cx-s, cy-3, cx, cy+4, fill=ic, width=2)
            canvas.create_line(cx, cy+4, cx+s, cy-3, fill=ic, width=2)
        elif val == "arrow_up":
            canvas.create_line(cx, cy+s, cx, cy-s, fill=ic, width=2)
            canvas.create_line(cx, cy-s, cx-4, cy-3, fill=ic, width=2)
            canvas.create_line(cx, cy-s, cx+4, cy-3, fill=ic, width=2)
        elif val == "arrow_down":
            canvas.create_line(cx, cy-s, cx, cy+s, fill=ic, width=2)
            canvas.create_line(cx, cy+s, cx-4, cy+3, fill=ic, width=2)
            canvas.create_line(cx, cy+s, cx+4, cy+3, fill=ic, width=2)
        elif val == "circle_dots":
            for i in range(8):
                a = i * 2*math.pi/8
                px = cx + s*math.cos(a); py = cy + s*math.sin(a)
                canvas.create_oval(px-1, py-1, px+1, py+1, fill=ic, outline=ic)
        elif val == "ticks":
            for i in range(4):
                a = i * 2*math.pi/4
                x1 = cx + (s-3)*math.cos(a); y1 = cy + (s-3)*math.sin(a)
                x2 = cx + s*math.cos(a); y2 = cy + s*math.sin(a)
                canvas.create_line(x1, y1, x2, y2, fill=ic, width=2)
        elif val == "segmented_ring":
            for i in range(8):
                st = i * 45 + 2
                canvas.create_arc(cx-s, cy-s, cx+s, cy+s, start=st, extent=20,
                                  outline=ic, style='arc', width=2)
        elif val == "partial_ring":
            canvas.create_arc(cx-s, cy-s, cx+s, cy+s, start=-45, extent=270,
                              outline=ic, style='arc', width=2)
        else: canvas.create_oval(cx-s, cy-s, cx+s, cy+s, outline=ic, width=2)

    def _choose_style(self, val, notify=False):
        if not self.layers: return
        self.layers[self.active_idx].style.set(val)
        self._refresh_style_buttons(); self._rebuild_layer_list(); self._redraw()
        if notify: self._notify(f"Стиль: {STYLE_DICT.get(val, val).replace(chr(10), ' ')}")

    # ============ Цвета ============
    def _tab_color(self, nb):
        self.tab_color_scroll = ScrollableFrame(nb)
        nb.add(self.tab_color_scroll, text=" 🎨 Цвета ")
        self.tab_color = self.tab_color_scroll.inner

    def _rebuild_color_tab(self):
        for w in self.tab_color.winfo_children(): w.destroy()
        if not self.layers: return
        L = self.layers[self.active_idx]
        head = tk.Frame(self.tab_color, bg=C_BG); head.pack(fill='x', padx=14, pady=(12,4))
        tk.Label(head, text=f"Цвет слоя {self.active_idx + 1}",
                 bg=C_BG, fg=C_ACCENT, font=("Segoe UI Semibold", 12)).pack(anchor='w')
        tk.Label(head, text="Колесо, слайдеры, HEX — всё меняется сразу",
                 bg=C_BG, fg=C_TEXT_DIM, font=("Segoe UI", 8)).pack(anchor='w')
        self.color_picker = ColorPickerPanel(self.tab_color, L.color.get(),
                                              on_change=self._on_live_color)
        self.color_picker.pack(fill='x', padx=14, pady=(8,4))
        arow = tk.Frame(self.tab_color, bg=C_BG); arow.pack(fill='x', padx=14, pady=(2,6))
        ttk.Checkbutton(arow, text="⚡ Live", variable=self.live_color_var).pack(side='left')
        ttk.Button(arow, text="⭐ В палитру",
                   command=lambda: self._save_color_to_palette(self.color_picker.get_hex())
                   ).pack(side='right', padx=(4,0))
        ttk.Button(arow, text="Применить", style="Accent.TButton",
                   command=lambda: self._apply_color_from_picker(L)
                   ).pack(side='right')
        ttk.Label(self.tab_color, text="Быстрые цвета",
                  style="SectionTitle.TLabel").pack(anchor='w', padx=14, pady=(8,4))
        grid = tk.Frame(self.tab_color, bg=C_BG); grid.pack(fill='x', padx=14, pady=(0,6))
        self._swatches.clear()
        for i, c in enumerate(QUICK_COLORS):
            r, col = i // 8, i % 8
            sw = ColorSwatch(grid, c, lambda col, l=L: self._set_color(l, col), size=26)
            sw.grid(row=r, column=col, padx=2, pady=2)
            self._swatches.append((sw, c))
            if c.lower() == L.color.get().lower(): sw.set_selected(True)
        if self._custom_palette:
            ttk.Label(self.tab_color, text="⭐ Моя палитра",
                      style="SectionTitle.TLabel").pack(anchor='w', padx=14, pady=(6,4))
            cg = tk.Frame(self.tab_color, bg=C_BG); cg.pack(fill='x', padx=14, pady=(0,6))
            for i, c in enumerate(self._custom_palette):
                r, col = i // 8, i % 8
                sw = ColorSwatch(cg, c, lambda col, l=L: self._set_color(l, col), size=26)
                sw.grid(row=r, column=col, padx=2, pady=2)
                if c.lower() == L.color.get().lower(): sw.set_selected(True)
        if self._color_history:
            ttk.Label(self.tab_color, text="История",
                      style="SectionTitle.TLabel").pack(anchor='w', padx=14, pady=(6,4))
            hg = tk.Frame(self.tab_color, bg=C_BG); hg.pack(fill='x', padx=14, pady=(0,6))
            for c in self._color_history[:12]:
                sw = ColorSwatch(hg, c, lambda col, l=L: self._set_color(l, col), size=22)
                sw.pack(side='left', padx=2)
        ttk.Label(self.tab_color, text="🌈 Радуга",
                  style="SectionTitle.TLabel").pack(anchor='w', padx=14, pady=(8,4))
        rb = tk.Frame(self.tab_color, bg=C_BG_ALT); rb.pack(fill='x', padx=14, pady=(0,8))
        ttk.Checkbutton(rb, text="Включить радугу", variable=L.rainbow_enabled,
                        command=self._redraw).pack(anchor='w', padx=10, pady=(6,2))
        NumberedSlider(rb, "Скорость", L.rainbow_speed, 5, 360, self._redraw,
                       reset_cb=lambda: (L.rainbow_speed.set(60), self._redraw())).pack(fill='x', padx=10)
        NumberedSlider(rb, "Насыщенность %", L.rainbow_sat, 10, 100, self._redraw,
                       reset_cb=lambda: (L.rainbow_sat.set(100), self._redraw())).pack(fill='x', padx=10)
        NumberedSlider(rb, "Яркость %", L.rainbow_val, 20, 100, self._redraw,
                       reset_cb=lambda: (L.rainbow_val.set(100), self._redraw())).pack(fill='x', padx=10, pady=(0,6))
        ttk.Label(self.tab_color, text="Градиент",
                  style="SectionTitle.TLabel").pack(anchor='w', padx=14, pady=(8,4))
        gr = tk.Frame(self.tab_color, bg=C_BG_ALT); gr.pack(fill='x', padx=14, pady=(0,8))
        row2 = tk.Frame(gr, bg=C_BG_ALT); row2.pack(fill='x', padx=10, pady=(6,2))
        ttk.Checkbutton(row2, text="Включить градиент", variable=L.gradient_enabled,
                        command=self._redraw).pack(side='left')
        tk.Label(row2, text="2-й цвет:", bg=C_BG_ALT, fg=C_TEXT_DIM,
                 font=("Segoe UI", 8)).pack(side='left', padx=(10,4))
        self.grad_btn = tk.Canvas(row2, width=22, height=22, bg=C_BG_ALT,
                                   highlightthickness=0, cursor="hand2"); self.grad_btn.pack(side='left')
        self.grad_btn.bind("<Button-1>", lambda e: self._pick_gradient_color(L))
        self._draw_grad_btn(L.gradient_color.get())
        NumberedSlider(gr, "Угол", L.gradient_angle, 0, 360, self._redraw,
                       reset_cb=lambda: (L.gradient_angle.set(0), self._redraw())).pack(fill='x', padx=10, pady=(2,2))
        ttk.Checkbutton(gr, text="Анимировать градиент", variable=L.gradient_animated,
                        command=self._redraw).pack(anchor='w', padx=10, pady=(0,6))
        ttk.Label(self.tab_color, text="❤ Пульсация",
                  style="SectionTitle.TLabel").pack(anchor='w', padx=14, pady=(8,4))
        pl = tk.Frame(self.tab_color, bg=C_BG_ALT); pl.pack(fill='x', padx=14, pady=(0,20))
        ttk.Checkbutton(pl, text="Включить пульсацию", variable=L.pulse_enabled,
                        command=self._redraw).pack(anchor='w', padx=10, pady=(6,2))
        NumberedSlider(pl, "Период (мс)", L.pulse_period, 200, 5000, self._redraw,
                       reset_cb=lambda: (L.pulse_period.set(1000), self._redraw())).pack(fill='x', padx=10)
        NumberedSlider(pl, "Мин. прозрачность %", L.pulse_min, 0, 100, self._redraw,
                       reset_cb=lambda: (L.pulse_min.set(30), self._redraw())).pack(fill='x', padx=10, pady=(0,6))

    def _on_live_color(self, hex_color):
        if not self.live_color_var.get() or not self.layers: return
        L = self.layers[self.active_idx]
        if L.color.get() == hex_color: return
        L.color.set(hex_color); self._redraw()
        for sw, c in self._swatches: sw.set_selected(c.lower() == hex_color.lower())

    def _apply_color_from_picker(self, layer):
        if not self.color_picker: return
        self._set_color(layer, self.color_picker.get_hex())
        self._notify(f"Цвет: {self.color_picker.get_hex()}")

    def _save_color_to_palette(self, hex_color):
        if hex_color.lower() in [x.lower() for x in self._custom_palette]:
            self._notify("Уже в палитре"); return
        self._custom_palette.append(hex_color)
        if len(self._custom_palette) > 24: self._custom_palette.pop(0)
        self._rebuild_color_tab(); self._notify(f"Добавлено: {hex_color}")

    def _set_color(self, layer, c):
        layer.color.set(c)
        if c.lower() not in [x.lower() for x in self._color_history]:
            self._color_history.insert(0, c)
            if len(self._color_history) > 12: self._color_history.pop()
        self._rebuild_layer_list(); self._redraw()
        if self.color_picker and self.color_picker.get_hex().lower() != c.lower():
            self.color_picker.set_hex(c)

    def _draw_grad_btn(self, color):
        try:
            c = self.grad_btn; c.delete("all")
            c.create_oval(0,0,21,21, fill=color, outline=C_BORDER, width=1)
        except Exception: pass

    def _draw_outline_btn(self, color):
        try:
            c = self.outline_btn; c.delete("all")
            c.create_oval(0,0,21,21, fill=color, outline=C_BORDER, width=1)
        except Exception: pass

    def _pick_outline_color(self, layer):
        c = colorchooser.askcolor(color=layer.outline_color.get(), title="Цвет обводки")[1]
        if c:
            layer.outline_color.set(c); self._draw_outline_btn(c); self._redraw()

    def _pick_gradient_color(self, layer):
        c = colorchooser.askcolor(color=layer.gradient_color.get(), title="2-й цвет градиента")[1]
        if c:
            layer.gradient_color.set(c); self._draw_grad_btn(c); self._redraw()

    # ============ Эффекты ============
    def _tab_effects(self, nb):
        self.tab_effects_scroll = ScrollableFrame(nb)
        nb.add(self.tab_effects_scroll, text=" ✨ Эффекты ")
        self.tab_effects = self.tab_effects_scroll.inner

    def _color_pick_row(self, parent, var, label, on_pick=None):
        f = tk.Frame(parent, bg=C_BG_ALT)
        f.pack(fill='x', padx=10, pady=(2,6))
        tk.Label(f, text=label, bg=C_BG_ALT, fg=C_TEXT_DIM,
                 font=("Segoe UI", 8)).pack(side='left')
        btn = tk.Canvas(f, width=22, height=22, bg=C_BG_ALT,
                        highlightthickness=0, cursor="hand2")
        btn.pack(side='left', padx=(6,0))
        def draw():
            try:
                btn.delete("all")
                btn.create_oval(0, 0, 21, 21, fill=var.get(), outline=C_BORDER, width=1)
            except Exception: pass
        draw()
        def click(e):
            c = colorchooser.askcolor(color=var.get(), title=label)[1]
            if c:
                var.set(c); draw()
                if on_pick: on_pick()
                self._redraw()
        btn.bind("<Button-1>", click)
        return f

    def _rebuild_effects_tab(self):
        for w in self.tab_effects.winfo_children(): w.destroy()
        if not self.layers: return
        L = self.layers[self.active_idx]
        head = tk.Frame(self.tab_effects, bg=C_BG); head.pack(fill='x', padx=14, pady=(12,4))
        tk.Label(head, text=f"Эффекты слоя {self.active_idx + 1}",
                 bg=C_BG, fg=C_ACCENT, font=("Segoe UI Semibold", 12)).pack(anchor='w')
        tk.Label(head, text="Каждый эффект работает независимо — комбинируй",
                 bg=C_BG, fg=C_TEXT_DIM, font=("Segoe UI", 8)).pack(anchor='w')

        ttk.Label(self.tab_effects, text="✨ Свечение (Glow)",
                  style="SectionTitle.TLabel").pack(anchor='w', padx=14, pady=(12,4))
        gf = tk.Frame(self.tab_effects, bg=C_BG_ALT); gf.pack(fill='x', padx=14, pady=(0,6))
        ttk.Checkbutton(gf, text="Включить свечение", variable=L.glow_enabled,
                        command=self._redraw).pack(anchor='w', padx=10, pady=(6,2))
        NumberedSlider(gf, "Размер", L.glow_size, 1, 6, self._redraw,
                       reset_cb=lambda: (L.glow_size.set(2), self._redraw())
                       ).pack(fill='x', padx=10)
        self._color_pick_row(gf, L.glow_color, "Цвет свечения:")

        ttk.Label(self.tab_effects, text="🌑 Тень (Shadow)",
                  style="SectionTitle.TLabel").pack(anchor='w', padx=14, pady=(10,4))
        sf = tk.Frame(self.tab_effects, bg=C_BG_ALT); sf.pack(fill='x', padx=14, pady=(0,6))
        ttk.Checkbutton(sf, text="Включить тень", variable=L.shadow_enabled,
                        command=self._redraw).pack(anchor='w', padx=10, pady=(6,2))
        NumberedSlider(sf, "Смещение X", L.shadow_offset_x, -15, 15, self._redraw,
                       reset_cb=lambda: (L.shadow_offset_x.set(2), self._redraw())
                       ).pack(fill='x', padx=10)
        NumberedSlider(sf, "Смещение Y", L.shadow_offset_y, -15, 15, self._redraw,
                       reset_cb=lambda: (L.shadow_offset_y.set(2), self._redraw())
                       ).pack(fill='x', padx=10)
        self._color_pick_row(sf, L.shadow_color, "Цвет тени:")

        ttk.Label(self.tab_effects, text="💡 Мерцание (Blink)",
                  style="SectionTitle.TLabel").pack(anchor='w', padx=14, pady=(10,4))
        bf = tk.Frame(self.tab_effects, bg=C_BG_ALT); bf.pack(fill='x', padx=14, pady=(0,6))
        ttk.Checkbutton(bf, text="Включить мерцание", variable=L.blink_enabled,
                        command=self._redraw).pack(anchor='w', padx=10, pady=(6,2))
        NumberedSlider(bf, "Период (мс)", L.blink_period, 100, 3000, self._redraw,
                       reset_cb=lambda: (L.blink_period.set(800), self._redraw())
                       ).pack(fill='x', padx=10)
        NumberedSlider(bf, "Скважность %", L.blink_duty, 5, 95, self._redraw,
                       reset_cb=lambda: (L.blink_duty.set(50), self._redraw())
                       ).pack(fill='x', padx=10, pady=(0,6))

        ttk.Label(self.tab_effects, text="🫁 Дыхание (Breathe)",
                  style="SectionTitle.TLabel").pack(anchor='w', padx=14, pady=(10,4))
        brf = tk.Frame(self.tab_effects, bg=C_BG_ALT); brf.pack(fill='x', padx=14, pady=(0,6))
        ttk.Checkbutton(brf, text="Включить дыхание", variable=L.breathe_enabled,
                        command=self._redraw).pack(anchor='w', padx=10, pady=(6,2))
        NumberedSlider(brf, "Период (мс)", L.breathe_period, 200, 5000, self._redraw,
                       reset_cb=lambda: (L.breathe_period.set(1500), self._redraw())
                       ).pack(fill='x', padx=10)
        NumberedSlider(brf, "Амплитуда %", L.breathe_amplitude, 1, 100, self._redraw,
                       reset_cb=lambda: (L.breathe_amplitude.set(20), self._redraw())
                       ).pack(fill='x', padx=10, pady=(0,6))

        ttk.Label(self.tab_effects, text="〰️ Покачивание (Wobble)",
                  style="SectionTitle.TLabel").pack(anchor='w', padx=14, pady=(10,4))
        wf = tk.Frame(self.tab_effects, bg=C_BG_ALT); wf.pack(fill='x', padx=14, pady=(0,6))
        ttk.Checkbutton(wf, text="Включить покачивание", variable=L.wobble_enabled,
                        command=self._redraw).pack(anchor='w', padx=10, pady=(6,2))
        NumberedSlider(wf, "Амплитуда (px)", L.wobble_amount, 1, 30, self._redraw,
                       reset_cb=lambda: (L.wobble_amount.set(3), self._redraw())
                       ).pack(fill='x', padx=10)
        NumberedSlider(wf, "Период (мс)", L.wobble_period, 200, 5000, self._redraw,
                       reset_cb=lambda: (L.wobble_period.set(1200), self._redraw())
                       ).pack(fill='x', padx=10, pady=(0,6))

        ttk.Label(self.tab_effects, text="💫 Шлейф (Trail)",
                  style="SectionTitle.TLabel").pack(anchor='w', padx=14, pady=(10,4))
        tf = tk.Frame(self.tab_effects, bg=C_BG_ALT); tf.pack(fill='x', padx=14, pady=(0,20))
        ttk.Checkbutton(tf, text="Включить шлейф", variable=L.trail_enabled,
                        command=self._redraw).pack(anchor='w', padx=10, pady=(6,2))
        tk.Label(tf, text="⚠ Требует включённого вращения",
                 bg=C_BG_ALT, fg=C_WARN, font=("Segoe UI", 8)).pack(anchor='w', padx=10)
        NumberedSlider(tf, "Длина шлейфа", L.trail_length, 1, 8, self._redraw,
                       reset_cb=lambda: (L.trail_length.set(3), self._redraw())
                       ).pack(fill='x', padx=10, pady=(2,6))

        hint = tk.Frame(self.tab_effects, bg=C_BG_ALT); hint.pack(fill='x', padx=14, pady=(0,20))
        tk.Label(hint, text="💡 Совет: Glow + Shadow + Rainbow = неоновый эффект.\n"
                            "Много эффектов одновременно = нагрузка на CPU.",
                 bg=C_BG_ALT, fg=C_TEXT_DIM, justify='left',
                 font=("Segoe UI", 8)).pack(padx=10, pady=8)

    # ============ Яркость ============
    def _tab_brightness(self, nb):
        self.tab_brightness_scroll = ScrollableFrame(nb)
        nb.add(self.tab_brightness_scroll, text=" Яркость ")
        tab = self.tab_brightness_scroll.inner
        ttk.Label(tab, text="Куда применять", style="SectionTitle.TLabel").pack(anchor='w', padx=14, pady=(14,6))
        mb = tk.Frame(tab, bg=C_BG_ALT); mb.pack(fill='x', padx=14, pady=(0,10))
        ttk.Radiobutton(mb, text="Ко всему экрану (гамма-коррекция)",
                        variable=self.br_mode_var, value="screen",
                        command=self._on_mode_change).pack(anchor='w', padx=10, pady=(6,2))
        ttk.Radiobutton(mb, text="К выбранному окну (оверлей поверх окна)",
                        variable=self.br_mode_var, value="window",
                        command=self._on_mode_change).pack(anchor='w', padx=10, pady=(2,6))
        pb = tk.Frame(tab, bg=C_BG); pb.pack(fill='x', padx=14, pady=(0,8))
        br = tk.Frame(pb, bg=C_BG); br.pack(fill='x')
        ttk.Button(br, text="Выбрать окно...", style="Accent.TButton",
                   command=self._start_pick).pack(side='left')
        ttk.Button(br, text="Сбросить", command=self._clear_target).pack(side='left', padx=(6,0))
        self.target_label = tk.Label(pb, text="Окно не выбрано", bg=C_BG, fg=C_TEXT_DIM,
                                     font=("Segoe UI", 8), anchor='w', wraplength=600, justify='left')
        self.target_label.pack(fill='x', pady=(6,0))
        ttk.Label(tab, text="Уровень яркости", style="SectionTitle.TLabel").pack(anchor='w', padx=14, pady=(10,6))
        box = tk.Frame(tab, bg=C_BG); box.pack(fill='x', padx=14)
        self.brightness_label = tk.Label(box, text="1.00", bg=C_BG, fg=C_ACCENT,
                                         font=("Segoe UI Semibold", 22)); self.brightness_label.pack(anchor='w')
        ttk.Scale(tab, from_=0.3, to=2.0, variable=self.brightness_var,
                  orient='horizontal', command=self._on_brightness,
                  style="Accent.Horizontal.TScale").pack(fill='x', padx=14, pady=(6,10))
        ttk.Label(tab, text="Быстрые пресеты", style="SectionTitle.TLabel").pack(anchor='w', padx=14, pady=(8,4))
        pf = tk.Frame(tab, bg=C_BG); pf.pack(fill='x', padx=14, pady=(0,10))
        for lbl, val in [("0.7\nТёмно",0.7),("1.0\nНорма",1.0),("1.3\nЯрче",1.3),("1.6\nМакс",1.6)]:
            ttk.Button(pf, text=lbl, width=8,
                       command=lambda v=val: self._preset_brightness(v)
                       ).pack(side='left', padx=(0,6), expand=True, fill='x')
        ttk.Button(tab, text="Сбросить яркость (1.0)", style="Accent.TButton",
                   command=self._reset_brightness).pack(fill='x', padx=14, pady=(0,20))

    def _preset_brightness(self, val):
        self._set_brightness(val); self._notify(f"Яркость: {val:.2f}")
    def _on_mode_change(self):
        self._apply_mode(); self._update_status()
        self._notify("Яркость: весь экран" if self.br_mode_var.get() == "screen" else "Яркость: окно")
    def _apply_mode(self):
        b = float(self.brightness_var.get())
        if self.br_mode_var.get() == "screen":
            self.win_overlay.set_enabled(False); self._schedule_brightness(b)
        else:
            try: set_brightness(1.0)
            except Exception: pass
            self.win_overlay.set_target(self.target_hwnd)
            self.win_overlay.set_brightness(b)
            self.win_overlay.set_enabled(self.target_hwnd != 0)
    def _start_pick(self):
        if self._picker is not None: return
        self.root.withdraw(); self.root.after(120, self._show_picker)
    def _show_picker(self):
        try: self._picker = WindowPicker(self.root, self._on_window_picked, self._on_pick_cancelled)
        except Exception: self.root.deiconify(); self._picker = None
    def _on_window_picked(self, hwnd):
        self._picker = None; self.target_hwnd = hwnd
        self.target_name = window_title(hwnd) or f"HWND {hwnd}"
        self.target_label.configure(text=f"Выбрано: {self.target_name}", fg=C_OK)
        self.root.deiconify(); self.br_mode_var.set("window")
        self._apply_mode(); self._update_status()
        self._notify(f"Окно: {self.target_name[:40]}")
    def _on_pick_cancelled(self):
        self._picker = None; self.root.deiconify()
    def _clear_target(self):
        self.target_hwnd = 0; self.target_name = ""
        self.target_label.configure(text="Окно не выбрано", fg=C_TEXT_DIM)
        self.win_overlay.set_target(0); self.win_overlay.set_enabled(False)
        self._update_status(); self._notify("Окно сброшено")

    # ============ HUD ============
    def _tab_hud(self, nb):
        self.tab_hud_scroll = ScrollableFrame(nb)
        nb.add(self.tab_hud_scroll, text=" HUD ")
        tab = self.tab_hud_scroll.inner
        ttk.Label(tab, text="Что показывать", style="SectionTitle.TLabel").pack(anchor='w', padx=14, pady=(14,6))
        opt = tk.Frame(tab, bg=C_BG_ALT); opt.pack(fill='x', padx=14, pady=(0,10))
        for var, txt in [(self.hud_fps_var,"FPS (частота отрисовки приложения)"),
                         (self.hud_cpu_var,"CPU"),
                         (self.hud_gpu_var,"GPU (AMD/NVIDIA/Intel на Win10+)")]:
            ttk.Checkbutton(opt, text=txt, variable=var,
                            command=self._update_hud_options).pack(anchor='w', padx=10, pady=3)
        ttk.Label(tab, text="Внешний вид", style="SectionTitle.TLabel").pack(
            anchor='w', padx=14, pady=(8,4))
        hc = tk.Frame(tab, bg=C_BG); hc.pack(fill='x', padx=14, pady=(0,10))
        tk.Label(hc, text="Цвет:", bg=C_BG, fg=C_TEXT_DIM,
                 font=("Segoe UI", 8)).pack(side='left')
        self.hud_color_btn = tk.Canvas(hc, width=22, height=22, bg=C_BG,
                                        highlightthickness=0, cursor="hand2")
        self.hud_color_btn.pack(side='left', padx=(4,10))
        self.hud_color_btn.bind("<Button-1>", lambda e: self._pick_hud_color())
        self._draw_hud_color_btn()
        tk.Label(hc, text="Размер:", bg=C_BG, fg=C_TEXT_DIM,
                 font=("Segoe UI", 8)).pack(side='left')
        NumberedSlider(hc, "", self.hud_font_size_var, 7, 22,
                       self._update_hud_style).pack(side='left', padx=(4,0), fill='x', expand=True)
        ttk.Label(tab, text="Позиция", style="SectionTitle.TLabel").pack(
            anchor='w', padx=14, pady=(8,4))
        self.hud_pos_label = tk.Label(tab, text=f"X: {self.hud_pos_x}   Y: {self.hud_pos_y}",
                                      bg=C_BG, fg=C_TEXT_DIM, font=("Segoe UI", 9), anchor='w')
        self.hud_pos_label.pack(fill='x', padx=14)
        pp = tk.Frame(tab, bg=C_BG); pp.pack(fill='x', padx=14, pady=(2,4))
        tk.Label(pp, text="Пресеты:", bg=C_BG, fg=C_TEXT_DIM,
                 font=("Segoe UI", 8)).pack(side='left', padx=(0,4))
        for lbl, (x, y) in [("ЛВ", (20,20)), ("ПВ", (None,20)),
                             ("ЛН", (20,None)), ("ПН", (None,None))]:
            ttk.Button(pp, text=lbl, width=3,
                       command=lambda x=x,y=y: self._set_hud_corner(x,y)).pack(side='left', padx=2)
        dr = tk.Frame(tab, bg=C_BG); dr.pack(fill='x', padx=14, pady=(4,10))
        self.hud_drag_btn = ttk.Button(dr, text="Перетащить HUD", style="Accent.TButton",
                                       command=self._toggle_hud_drag)
        self.hud_drag_btn.pack(side='left')
        ttk.Button(dr, text="Сброс", command=self._reset_hud_pos).pack(side='left', padx=(6,0))
        ttk.Button(tab, text="Показать / Скрыть HUD",
                   command=self._toggle_hud).pack(fill='x', padx=14, pady=(4,20))

    def _draw_hud_color_btn(self):
        try:
            c = self.hud_color_btn; c.delete("all")
            c.create_oval(0,0,21,21, fill=self.hud_color_var.get(), outline=C_BORDER)
        except Exception: pass
    def _pick_hud_color(self):
        c = colorchooser.askcolor(color=self.hud_color_var.get(), title="Цвет HUD")[1]
        if c:
            self.hud_color_var.set(c); self._draw_hud_color_btn(); self._update_hud_style()
    def _set_hud_corner(self, x, y):
        sw = self.root.winfo_screenwidth(); sh = self.root.winfo_screenheight()
        if x is None: x = sw - 200
        if y is None: y = sh - 120
        self.hud_pos_x = x; self.hud_pos_y = y
        if self.hud: self.hud.set_position(x, y)
        self._update_hud_pos_label()
    def _update_hud_options(self):
        if self.hud:
            self.hud.set_options(self.hud_fps_var.get(), self.hud_cpu_var.get(),
                                 self.hud_gpu_var.get())
            self.hud.set_style(int(self.hud_font_size_var.get()), self.hud_color_var.get())
            self.hud.set_fps(self._app_fps)
            any_on = (self.hud_fps_var.get() or self.hud_cpu_var.get() or
                      self.hud_gpu_var.get())
            self.hud.set_visible(any_on)
    def _update_hud_style(self):
        if self.hud: self.hud.set_style(int(self.hud_font_size_var.get()),
                                         self.hud_color_var.get())
    def _toggle_hud(self):
        if self.hud:
            if self.hud._visible: self.hud.set_visible(False); self._notify("HUD: выкл")
            else: self._update_hud_options(); self._notify("HUD: вкл")
    def _toggle_hud_drag(self):
        if not self.hud: return
        ns = not self.hud_drag_var.get(); self.hud_drag_var.set(ns); self.hud.set_drag_mode(ns)
        self.hud_drag_btn.configure(text="Готово" if ns else "Перетащить HUD")
        if ns and not self.hud._visible: self._update_hud_options()
    def _reset_hud_pos(self):
        self.hud_pos_x = 20; self.hud_pos_y = 20
        if self.hud: self.hud.set_position(20, 20)
        self._update_hud_pos_label()
    def _update_hud_pos_label(self):
        try: self.hud_pos_label.configure(text=f"X: {self.hud_pos_x}   Y: {self.hud_pos_y}")
        except Exception: pass
    def _on_hud_moved(self, x, y):
        self.hud_pos_x = x; self.hud_pos_y = y; self._update_hud_pos_label()

    # ============ Хоткеи ============
    def _tab_hotkeys(self, nb):
        self.tab_hotkeys_scroll = ScrollableFrame(nb)
        nb.add(self.tab_hotkeys_scroll, text=" Хоткеи ")
        tab = self.tab_hotkeys_scroll.inner
        ttk.Label(tab, text="Глобальные горячие клавиши",
                  style="SectionTitle.TLabel").pack(anchor='w', padx=14, pady=(14,4))
        ttk.Label(tab, text="Работают в любой программе",
                  style="Dim.TLabel").pack(anchor='w', padx=14, pady=(0,10))
        rows = [
            (["Ctrl","Alt","H"],"Вкл/выкл прицел"),
            (["Ctrl","Alt","S"],"Сменить стиль активного слоя"),
            (["Ctrl","Alt","C"],"Следующий цвет (из палитры)"),
            (["Ctrl","Alt","↑"],"Яркость +0.1"),
            (["Ctrl","Alt","↓"],"Яркость −0.1"),
            (["Ctrl","Alt","R"],"Сбросить яркость"),
            (["Ctrl","Alt","T"],"Вращение активного слоя"),
            (["Ctrl","Alt","M"],"Мини-режим"),
            (["Ctrl","Alt","F"],"HUD вкл/выкл"),
        ]
        box = tk.Frame(tab, bg=C_BG); box.pack(fill='x', padx=14, pady=(0,20))
        for k, d in rows: HotkeyRow(box, k, d).pack(fill='x', pady=3)

    # ============ Ещё ============
    def _tab_settings(self, nb):
        self.tab_settings_scroll = ScrollableFrame(nb)
        nb.add(self.tab_settings_scroll, text=" Ещё ")
        tab = self.tab_settings_scroll.inner
        ttk.Label(tab, text="Поведение", style="SectionTitle.TLabel").pack(anchor='w', padx=14, pady=(14,6))
        o = tk.Frame(tab, bg=C_BG_ALT); o.pack(fill='x', padx=14, pady=(0,10))
        ttk.Checkbutton(o, text="Запускать свёрнутым в трей",
                        variable=self.start_min_var).pack(anchor='w', padx=10, pady=6)
        ttk.Label(tab, text="Уведомления", style="SectionTitle.TLabel").pack(anchor='w', padx=14, pady=(10,6))
        nf = tk.Frame(tab, bg=C_BG_ALT); nf.pack(fill='x', padx=14, pady=(0,10))
        ttk.Checkbutton(nf, text="Показывать уведомления",
                        variable=self.notify_enabled_var).pack(anchor='w', padx=10, pady=6)
        ttk.Button(nf, text="Тест уведомления",
                   command=lambda: self._notify("Тестовое уведомление")).pack(anchor='w', padx=10, pady=(0,6))
        ttk.Label(tab, text="Профиль", style="SectionTitle.TLabel").pack(anchor='w', padx=14, pady=(10,6))
        pf = tk.Frame(tab, bg=C_BG); pf.pack(fill='x', padx=14, pady=(0,6))
        self.profile_combo = ttk.Combobox(pf, textvariable=self.profile_var, width=24)
        self.profile_combo.pack(side='left')
        ttk.Button(pf, text="↻", width=3, command=self._refresh_profile_list).pack(side='left', padx=(4,0))
        pfr = tk.Frame(tab, bg=C_BG); pfr.pack(fill='x', padx=14, pady=(0,6))
        ttk.Button(pfr, text="Сохранить как…", command=self._save_profile_as).pack(side='left')
        ttk.Button(pfr, text="Загрузить", command=self._load_profile).pack(side='left', padx=(4,0))
        ttk.Button(pfr, text="Удалить", command=self._delete_profile).pack(side='left', padx=(4,0))
        ttk.Label(tab, text="Настройки", style="SectionTitle.TLabel").pack(anchor='w', padx=14, pady=(10,6))
        ttk.Button(tab, text="Сохранить", command=self._save_settings).pack(fill='x', padx=14, pady=3)
        ttk.Button(tab, text="Загрузить", command=self._load_settings).pack(fill='x', padx=14, pady=3)
        ttk.Button(tab, text="Экспорт…", command=self._export_settings).pack(fill='x', padx=14, pady=3)
        ttk.Button(tab, text="Импорт…", command=self._import_settings).pack(fill='x', padx=14, pady=3)
        ttk.Button(tab, text="Сброс к умолчанию", command=self._reset_all).pack(fill='x', padx=14, pady=3)
        ttk.Button(tab, text="Сбросить ВСЁ и закрыть", command=self._hard_reset).pack(fill='x', padx=14, pady=3)
        ttk.Button(tab, text="Пересоздать оверлей", command=self._recreate_overlay).pack(fill='x', padx=14, pady=(3,20))
        self._refresh_profile_list()

    def _refresh_profile_list(self):
        try:
            files = [f[:-5] for f in os.listdir(PROFILES_DIR) if f.endswith('.json')]
            self.profile_combo['values'] = sorted(files)
        except Exception: pass
    def _save_profile_as(self):
        name = simpledialog.askstring("Профиль", "Имя профиля:", parent=self.root)
        if not name: return
        name = re.sub(r'[^\w\-а-яА-ЯёЁ]', '_', name)
        try:
            path = os.path.join(PROFILES_DIR, f"{name}.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self._collect(), f, indent=2, ensure_ascii=False)
            self.profile_var.set(name); self._refresh_profile_list()
            self._notify(f"Профиль «{name}» сохранён")
        except Exception as e: messagebox.showerror("Ошибка", str(e))
    def _load_profile(self):
        name = self.profile_var.get()
        if not name: return
        try:
            path = os.path.join(PROFILES_DIR, f"{name}.json")
            if not os.path.exists(path): self._notify("Профиль не найден"); return
            with open(path, "r", encoding="utf-8") as f: data = json.load(f)
            self._apply(data)
            self._rebuild_layer_list(); self._rebuild_params_tab()
            self._rebuild_color_tab(); self._rebuild_effects_tab()
            self._redraw(); self._update_status()
            self._notify(f"Профиль «{name}» загружен")
        except Exception as e: messagebox.showerror("Ошибка", str(e))
    def _delete_profile(self):
        name = self.profile_var.get()
        if not name: return
        if not messagebox.askyesno("Удалить", f"Удалить профиль «{name}»?"): return
        try:
            os.remove(os.path.join(PROFILES_DIR, f"{name}.json"))
            self._refresh_profile_list(); self.profile_var.set("")
        except Exception: pass
    def _export_settings(self):
        path = filedialog.asksaveasfilename(defaultextension=".json",
                                             filetypes=[("JSON","*.json")],
                                             initialfile="crosshair_settings.json")
        if not path: return
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self._collect(), f, indent=2, ensure_ascii=False)
            self._notify(f"Экспортировано: {os.path.basename(path)}")
        except Exception as e: messagebox.showerror("Ошибка", str(e))
    def _import_settings(self):
        path = filedialog.askopenfilename(filetypes=[("JSON","*.json")])
        if not path: return
        try:
            with open(path, "r", encoding="utf-8") as f: data = json.load(f)
            self._apply(data)
            self._rebuild_layer_list(); self._rebuild_params_tab()
            self._rebuild_color_tab(); self._rebuild_effects_tab()
            self._redraw(); self._update_status()
            self._notify("Импортировано")
        except Exception as e: messagebox.showerror("Ошибка", str(e))
    def _hard_reset(self):
        if not messagebox.askyesno("Внимание", "Сбросить всё и закрыть?"): return
        try:
            if os.path.exists(SETTINGS_PATH): os.remove(SETTINGS_PATH)
        except Exception: pass
        try: set_brightness(1.0)
        except Exception: pass
        try:
            if self.tray_icon: self.tray_icon.stop()
        except Exception: pass
        self._shutting_down = True
        try: self.root.destroy()
        except Exception: pass
    def _recreate_overlay(self):
        try:
            if hasattr(self, "overlay"): self.overlay.destroy()
        except Exception: pass
        self._overlay_hwnd = None
        self.root.after(200, self._create_overlay)
        self.root.after(400, self._redraw)
        self._notify("Оверлей пересоздан")
    def _update_status(self):
        if self.enabled_var.get():
            self._status_cross.configure(text="● Прицел: вкл", fg=C_OK)
        else:
            self._status_cross.configure(text="● Прицел: выкл", fg=C_OFF)
        self._status_layers.configure(text=f"Слоёв: {len(self.layers)}")
        b = float(self.brightness_var.get())
        if self.br_mode_var.get() == "screen":
            self._status_bright.configure(text=f"Яркость: {b:.2f} (экран)")
        else:
            nm = (self.target_name or "—")[:18]
            self._status_bright.configure(text=f"Яркость: {b:.2f} · {nm}")

    def _create_overlay(self):
        self.overlay = tk.Toplevel(self.root)
        self.overlay.overrideredirect(True); self.overlay.attributes('-topmost', True)
        try: self.overlay.attributes('-transparentcolor', TRANSPARENT_COLOR)
        except Exception: pass
        self.overlay.configure(bg=TRANSPARENT_COLOR)
        self.sw = self.overlay.winfo_screenwidth(); self.sh = self.overlay.winfo_screenheight()
        self.overlay.geometry(f"{self.sw}x{self.sh}+0+0")
        self.canvas = tk.Canvas(self.overlay, bg=TRANSPARENT_COLOR, highlightthickness=0, bd=0)
        self.canvas.pack(fill='both', expand=True)
        self.overlay.update_idletasks(); self.overlay.update(); self.root.update()
        self.root.after(150, self._apply_overlay_transparency)
        self.root.after(1200, self._apply_overlay_transparency)
    def _apply_overlay_transparency(self):
        if self._shutting_down: return
        try:
            hwnd = get_toplevel_hwnd(self.overlay)
            if not hwnd: return
            self._overlay_hwnd = hwnd
            colorref = hex_to_colorref(TRANSPARENT_COLOR); self._overlay_colorref = colorref
            st = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            st |= WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW | WS_EX_TOPMOST
            user32.SetWindowLongW(hwnd, GWL_EXSTYLE, st)
            user32.SetLayeredWindowAttributes(hwnd, colorref, 0, LWA_COLORKEY)
            push_to_top(hwnd)
        except Exception: pass
    def _keep_on_top(self):
        if self._shutting_down: return
        try:
            if self._overlay_hwnd: push_to_top(self._overlay_hwnd)
        except Exception: pass
        self.root.after(300, self._keep_on_top)
    def _win_overlay_loop(self):
        if self._shutting_down: return
        try: self.win_overlay.tick()
        except Exception: pass
        self.root.after(200, self._win_overlay_loop)
    def _hud_loop(self):
        if self._shutting_down: return
        try:
            if self.hud: self.hud.tick()
        except Exception: pass
        self.root.after(100, self._hud_loop)

    def _animation_loop(self):
        if self._shutting_down: return
        try:
            self._app_fps_counter += 1
            t_now = time.time()
            if t_now - self._app_fps_time >= 1.0:
                self._app_fps = self._app_fps_counter
                self._app_fps_counter = 0
                self._app_fps_time = t_now
                if self.hud: self.hud.set_fps(self._app_fps)
            if not self._loading:
                now = time.time(); dt = now - self._last_frame; self._last_frame = now
                if dt > 0.2: dt = 0.016
                self._anim_time += dt
                need_redraw = False
                minimized = self.root.state() == 'withdrawn'
                if minimized: dt *= 0.2
                for L in self.layers:
                    if not L.enabled.get(): continue
                    if L.rotate_enabled.get():
                        spd = float(L.rotate_speed.get()) * int(L.rotate_dir.get())
                        L.angle = (L.angle + spd * dt) % 360.0
                        need_redraw = True
                    if L.rainbow_enabled.get() or L.pulse_enabled.get() or \
                       L.blink_enabled.get() or L.breathe_enabled.get() or \
                       L.wobble_enabled.get() or \
                       (L.trail_enabled.get() and L.rotate_enabled.get()) or \
                       (L.gradient_enabled.get() and L.gradient_animated.get()):
                        need_redraw = True
                if need_redraw: self._redraw()
        except Exception: pass
        self.root.after(16, self._animation_loop)

    def _get_stipple(self, layer):
        op = layer.opacity.get()
        if layer.pulse_enabled.get():
            period = max(200, layer.pulse_period.get()) / 1000.0
            phase = (math.sin(self._anim_time * 2 * math.pi / period) + 1) / 2
            pmin = max(0, layer.pulse_min.get())
            op = op * (pmin/100.0 + (1.0 - pmin/100.0) * phase)
        if op >= 95: return ""
        if op >= 80: return "gray75"
        if op >= 65: return "gray50"
        if op >= 50: return "gray25"
        return "gray12"

    def _resolve_color(self, layer):
        if not layer.rainbow_enabled.get(): return layer.color.get()
        speed = max(1, layer.rainbow_speed.get())
        phase = (self._anim_time * speed / 360.0) % 1.0
        sat = max(0.1, min(1.0, layer.rainbow_sat.get()/100.0))
        val = max(0.2, min(1.0, layer.rainbow_val.get()/100.0))
        return rainbow_color(phase, sat, val)

    def _draw_shape_raw(self, canvas, layer, cx, cy, scale=1.0, color=None,
                        extra_thickness=0, stipple=None, angle_override=None,
                        use_gradient=True):
        base_color = color if color is not None else self._resolve_color(layer)
        style = layer.style.get()
        us = layer.scale.get() / 100.0
        size = max(1, int(layer.size.get() * scale * us))
        thick = max(1, int(layer.thickness.get() * scale * us)) + extra_thickness
        gap = max(0, int(layer.gap.get() * scale * us))
        dot = max(1, int(layer.dot.get() * scale * us))
        if stipple is None:
            stipple = self._get_stipple(layer)
        angle = angle_override if angle_override is not None else (
            layer.angle if layer.rotate_enabled.get() else 0.0)
        rad = math.radians(angle); cos_a = math.cos(rad); sin_a = math.sin(rad)

        def rot(x, y):
            dx = x - cx; dy = y - cy
            return (cx + dx*cos_a - dy*sin_a, cy + dx*sin_a + dy*cos_a)

        def col_at(px, py):
            if not use_gradient or not layer.gradient_enabled.get():
                return base_color
            ang = math.radians(layer.gradient_angle.get())
            t = (math.cos(ang)*(px-cx) + math.sin(ang)*(py-cy)) / max(1.0, size*2)
            if layer.gradient_animated.get():
                t += self._anim_time * 0.5
            t = max(0.0, min(1.0, (t + 1.0) / 2.0))
            return lerp_color(base_color, layer.gradient_color.get(), t)

        def line(x1, y1, x2, y2, col, t):
            p1 = rot(x1, y1); p2 = rot(x2, y2)
            c = col if not use_gradient else col_at(x1, y1)
            canvas.create_line(p1[0], p1[1], p2[0], p2[1], fill=c, width=t, stipple=stipple)

        def oval(x1, y1, x2, y2, col, fill=True, width=1):
            c = col if not use_gradient else col_at((x1+x2)/2, (y1+y2)/2)
            canvas.create_oval(x1, y1, x2, y2, fill=c if fill else "",
                               outline=c, width=width, stipple=stipple)

        def polygon(pts, col, width=2, fill=False):
            r = []
            for px, py in pts: r.extend(rot(px, py))
            c = col if not use_gradient else col_at(cx, cy)
            canvas.create_polygon(*r, outline=c, width=width,
                                  fill=c if fill else "", stipple=stipple)

        def arc(x1, y1, x2, y2, start, extent, col, t):
            canvas.create_arc(x1, y1, x2, y2, start=start, extent=extent,
                              outline=col, style='arc', width=t, stipple=stipple)

        if style == "dot":
            oval(cx-dot, cy-dot, cx+dot, cy+dot, base_color)
        elif style == "cross":
            line(cx-gap-size, cy, cx-gap, cy, base_color, thick)
            line(cx+gap, cy, cx+gap+size, cy, base_color, thick)
            line(cx, cy-gap-size, cx, cy-gap, base_color, thick)
            line(cx, cy+gap, cx, cy+gap+size, base_color, thick)
        elif style == "dot_cross":
            line(cx-gap-size, cy, cx-gap, cy, base_color, thick)
            line(cx+gap, cy, cx+gap+size, cy, base_color, thick)
            line(cx, cy-gap-size, cx, cy-gap, base_color, thick)
            line(cx, cy+gap, cx, cy+gap+size, base_color, thick)
            oval(cx-dot, cy-dot, cx+dot, cy+dot, base_color)
        elif style == "ring":
            oval(cx-size, cy-size, cx+size, cy+size, base_color, fill=False, width=thick)
        elif style == "ring_dot":
            oval(cx-size, cy-size, cx+size, cy+size, base_color, fill=False, width=thick)
            oval(cx-dot, cy-dot, cx+dot, cy+dot, base_color)
        elif style == "t_shape":
            line(cx-size, cy, cx+size, cy, base_color, thick)
            line(cx, cy, cx, cy+size, base_color, thick)
        elif style == "chevron":
            line(cx-size, cy+size//2, cx, cy-size, base_color, thick)
            line(cx, cy-size, cx+size, cy+size//2, base_color, thick)
        elif style == "x_cross":
            line(cx-size, cy-size, cx+size, cy+size, base_color, thick)
            line(cx-size, cy+size, cx+size, cy-size, base_color, thick)
        elif style == "brackets":
            half = size; arm = max(3, half//2)
            line(cx-half, cy-half, cx-half, cy+half, base_color, thick)
            line(cx-half, cy-half, cx-half+arm, cy-half, base_color, thick)
            line(cx-half, cy+half, cx-half+arm, cy+half, base_color, thick)
            line(cx+half, cy-half, cx+half, cy+half, base_color, thick)
            line(cx+half, cy-half, cx+half-arm, cy-half, base_color, thick)
            line(cx+half, cy+half, cx+half-arm, cy+half, base_color, thick)
        elif style == "corners":
            arm = max(3, size//2)
            for sx, sy in [(-1,-1),(1,-1),(-1,1),(1,1)]:
                px, py = cx+sx*size, cy+sy*size
                line(px, py, px-sx*arm, py, base_color, thick)
                line(px, py, px, py-sy*arm, base_color, thick)
        elif style == "diamond":
            polygon([(cx,cy-size),(cx+size,cy),(cx,cy+size),(cx-size,cy)], base_color, thick)
        elif style == "square":
            polygon([(cx-size,cy-size),(cx+size,cy-size),(cx+size,cy+size),(cx-size,cy+size)], base_color, thick)
        elif style == "triangle":
            polygon([(cx,cy-size),(cx+size,cy+size),(cx-size,cy+size)], base_color, thick)
        elif style == "triple_dot":
            d = max(2, dot); g2 = max(d*2+1, gap+dot)
            oval(cx-g2-d, cy-d, cx-g2+d, cy+d, base_color)
            oval(cx-d, cy-d, cx+d, cy+d, base_color)
            oval(cx+g2-d, cy-d, cx+g2+d, cy+d, base_color)
        elif style == "hash":
            line(cx-size, cy, cx+size, cy, base_color, thick)
            line(cx, cy-size, cx, cy+size, base_color, thick)
            off = size//2
            line(cx-size, cy-off, cx+size, cy-off, base_color, thick)
            line(cx-size, cy+off, cx+size, cy+off, base_color, thick)
            line(cx-off, cy-size, cx-off, cy+size, base_color, thick)
            line(cx+off, cy-size, cx+off, cy+size, base_color, thick)
        elif style == "arrow":
            line(cx, cy-size, cx, cy+size, base_color, thick)
            line(cx, cy-size, cx-size//2, cy-size//2, base_color, thick)
            line(cx, cy-size, cx+size//2, cy-size//2, base_color, thick)
        elif style == "brackets_square":
            half = size; arm = max(3, half//2)
            line(cx-half, cy-half, cx-half, cy+half, base_color, thick)
            line(cx-half, cy-half, cx-half+arm, cy-half, base_color, thick)
            line(cx-half, cy+half, cx-half+arm, cy+half, base_color, thick)
            line(cx+half, cy-half, cx+half, cy+half, base_color, thick)
            line(cx+half, cy-half, cx+half-arm, cy-half, base_color, thick)
            line(cx+half, cy+half, cx+half-arm, cy+half, base_color, thick)
        elif style == "double_ring":
            oval(cx-size, cy-size, cx+size, cy+size, base_color, fill=False, width=thick)
            r2 = max(2, size*2//3)
            oval(cx-r2, cy-r2, cx+r2, cy+r2, base_color, fill=False, width=thick)
        elif style == "cross_ring":
            oval(cx-size, cy-size, cx+size, cy+size, base_color, fill=False, width=thick)
            line(cx-size, cy, cx+size, cy, base_color, thick)
            line(cx, cy-size, cx, cy+size, base_color, thick)
        elif style == "heart":
            r = max(3, size)
            oval(cx-r, cy-r//2, cx, cy+r//2, base_color, fill=True, width=thick)
            oval(cx, cy-r//2, cx+r, cy+r//2, base_color, fill=True, width=thick)
            polygon([(cx-r+1, cy), (cx+r-1, cy), (cx, cy+int(r*1.3))],
                    base_color, thick, fill=True)
        elif style == "star_5":
            pts = []
            for i in range(10):
                a = -math.pi/2 + i * math.pi/5
                r = size if i % 2 == 0 else size * 0.4
                pts.append((cx + r*math.cos(a), cy + r*math.sin(a)))
            polygon(pts, base_color, thick, fill=True)
        elif style == "hexagon":
            pts = []
            for i in range(6):
                a = i * math.pi/3 - math.pi/2
                pts.append((cx + size*math.cos(a), cy + size*math.sin(a)))
            polygon(pts, base_color, thick)
        elif style == "chevron_down":
            line(cx-size, cy-size//2, cx, cy+size//2, base_color, thick)
            line(cx, cy+size//2, cx+size, cy-size//2, base_color, thick)
        elif style == "arrow_up":
            line(cx, cy+size, cx, cy-size, base_color, thick)
            line(cx, cy-size, cx-size//2, cy-size//2, base_color, thick)
            line(cx, cy-size, cx+size//2, cy-size//2, base_color, thick)
        elif style == "arrow_down":
            line(cx, cy-size, cx, cy+size, base_color, thick)
            line(cx, cy+size, cx-size//2, cy+size//2, base_color, thick)
            line(cx, cy+size, cx+size//2, cy+size//2, base_color, thick)
        elif style == "circle_dots":
            n = 8
            d = max(2, dot)
            for i in range(n):
                a = i * 2*math.pi/n
                px = cx + size*math.cos(a); py = cy + size*math.sin(a)
                oval(px-d, py-d, px+d, py+d, base_color)
        elif style == "ticks":
            n = 4
            for i in range(n):
                a = i * 2*math.pi/n
                x1 = cx + (size - max(3, size//3))*math.cos(a)
                y1 = cy + (size - max(3, size//3))*math.sin(a)
                x2 = cx + size*math.cos(a); y2 = cy + size*math.sin(a)
                line(x1, y1, x2, y2, base_color, thick)
        elif style == "segmented_ring":
            n = 12
            x1, y1 = cx-size, cy-size
            x2, y2 = cx+size, cy+size
            seg_extent = 360.0/n * 0.6
            for i in range(n):
                start = i * 360.0/n - angle
                arc(x1, y1, x2, y2, start, seg_extent, base_color, thick)
        elif style == "partial_ring":
            x1, y1 = cx-size, cy-size
            x2, y2 = cx+size, cy+size
            arc(x1, y1, x2, y2, -angle - 45, 270, base_color, thick)
        else:
            oval(cx-size, cy-size, cx+size, cy+size, base_color, fill=False, width=thick)

        if layer.rotate_enabled.get() and layer.rotate_orbit.get():
            orb_r = max(size+8, 18)
            ox = cx + orb_r*math.cos(rad); oy = cy + orb_r*math.sin(rad)
            ob = max(2, thick+1)
            oval(ox-ob, oy-ob, ox+ob, oy+ob, base_color)

    def _draw_layer_shape(self, canvas, layer, cx, cy, scale=1.0, skip_stipple=False):
        if layer.blink_enabled.get() and not skip_stipple:
            period = max(100, layer.blink_period.get()) / 1000.0
            duty = max(0.05, min(0.95, layer.blink_duty.get() / 100.0))
            phase = (self._anim_time / period) % 1.0
            if phase > duty: return
        if layer.wobble_enabled.get() and not skip_stipple:
            amt = layer.wobble_amount.get()
            period = max(200, layer.wobble_period.get()) / 1000.0
            cx += amt * math.sin(2*math.pi*self._anim_time/period)
            cy += amt * math.cos(2*math.pi*self._anim_time/period)
        if layer.breathe_enabled.get() and not skip_stipple:
            period = max(200, layer.breathe_period.get()) / 1000.0
            amp = layer.breathe_amplitude.get() / 100.0
            scale *= 1.0 + amp * math.sin(2*math.pi*self._anim_time/period)
        base_color = self._resolve_color(layer)
        stipple = "" if skip_stipple else self._get_stipple(layer)
        simple_mode = skip_stipple
        if layer.shadow_enabled.get() and not simple_mode:
            sx = layer.shadow_offset_x.get()
            sy = layer.shadow_offset_y.get()
            self._draw_shape_raw(canvas, layer, cx+sx, cy+sy, scale,
                                  layer.shadow_color.get(),
                                  stipple="gray50",
                                  use_gradient=False)
        if layer.glow_enabled.get() and not simple_mode:
            glow = max(1, layer.glow_size.get())
            for i in range(glow, 0, -1):
                self._draw_shape_raw(canvas, layer, cx, cy,
                                      scale * (1 + i * 0.04),
                                      layer.glow_color.get(),
                                      stipple="gray50",
                                      use_gradient=False)
        if layer.trail_enabled.get() and layer.rotate_enabled.get() and not simple_mode:
            n = max(1, layer.trail_length.get())
            for i in range(n, 0, -1):
                old_angle = (layer.angle - i * 12) % 360
                self._draw_shape_raw(canvas, layer, cx, cy, scale,
                                      base_color,
                                      stipple="gray25",
                                      angle_override=old_angle,
                                      use_gradient=False)
        if layer.outline.get():
            self._draw_shape_raw(canvas, layer, cx, cy, scale,
                                  layer.outline_color.get(),
                                  extra_thickness=int(layer.outline_thickness.get()),
                                  stipple=stipple,
                                  use_gradient=False)
        self._draw_shape_raw(canvas, layer, cx, cy, scale, base_color, stipple=stipple)

    def _redraw(self):
        if self._loading or self._shutting_down: return
        try:
            if hasattr(self, "preview") and self.preview.winfo_exists():
                self.preview.delete("all")
                if self.enabled_var.get() and self.layers:
                    self._draw_layer_shape(self.preview, self.layers[self.active_idx],
                                           70, 70, scale=1.4, skip_stipple=True)
            if not hasattr(self, "canvas"): return
            self.canvas.delete("all")
            if not self.enabled_var.get(): return
            base_x = self.sw // 2; base_y = self.sh // 2
            for L in self.layers:
                if not L.enabled.get(): continue
                ox = base_x + int(L.offset_x.get()); oy = base_y + int(L.offset_y.get())
                self._draw_layer_shape(self.canvas, L, ox, oy, scale=1.0)
        except Exception as e:
            print("redraw error:", e, file=sys.stderr)

    def _notify(self, text, accent=None):
        if not self.notify_enabled_var.get(): return
        if self.notify:
            try: self.notify.show(text, 1.5, accent)
            except Exception: pass
    def _toggle_crosshair(self):
        self._redraw(); self._update_status()
        if self.mini: self.mini.update()
        self._notify("Прицел: вкл" if self.enabled_var.get() else "Прицел: выкл",
                     "#3ba55d" if self.enabled_var.get() else "#8a8d94")
    def _on_brightness(self, _=None):
        b = float(self.brightness_var.get())
        try: self.brightness_label.configure(text=f"{b:.2f}")
        except Exception: pass
        self._update_status()
        if self.mini: self.mini.lbl.configure(text=f"{b:.1f}")
        if self.br_mode_var.get() == "screen": self._schedule_brightness(b)
        else: self.win_overlay.set_brightness(b)
    def _schedule_brightness(self, val):
        self._pending_brightness = val
        if self._brightness_job is None:
            self._brightness_job = self.root.after(40, self._apply_brightness_now)
    def _apply_brightness_now(self):
        self._brightness_job = None
        v = self._pending_brightness; self._pending_brightness = None
        if v is None: return
        try: set_brightness(v); self._last_applied = v
        except Exception: pass
    def _set_brightness(self, val):
        self.brightness_var.set(val)
        try: self.brightness_label.configure(text=f"{float(val):.2f}")
        except Exception: pass
        self._update_status()
        if self.mini: self.mini.lbl.configure(text=f"{float(val):.1f}")
        if self.br_mode_var.get() == "screen":
            self._pending_brightness = float(val)
            if self._brightness_job is not None:
                try: self.root.after_cancel(self._brightness_job)
                except Exception: pass
                self._brightness_job = None
            self._apply_brightness_now()
        else: self.win_overlay.set_brightness(float(val))
    def _reset_brightness(self):
        self._set_brightness(1.0); self._notify("Яркость: 1.00")
    def _reapply_brightness_loop(self):
        if self._shutting_down: return
        try:
            if self.br_mode_var.get() == "screen":
                b = float(self.brightness_var.get())
                if abs(b - 1.0) > 0.01:
                    if self._last_applied is None or abs(self._last_applied - b) > 0.005:
                        set_brightness(b); self._last_applied = b
        except Exception: pass
        self.root.after(2000, self._reapply_brightness_loop)

    def _setup_tray(self):
        try:
            import pystray
            from PIL import Image, ImageDraw
        except ImportError: return
        def make_img():
            img = Image.new('RGB', (64,64), (30,31,34))
            d = ImageDraw.Draw(img)
            d.ellipse((16,16,48,48), fill=(0,255,0))
            d.line((32,8,32,24), fill=(0,255,0), width=4)
            d.line((32,40,32,56), fill=(0,255,0), width=4)
            d.line((8,32,24,32), fill=(0,255,0), width=4)
            d.line((40,32,56,32), fill=(0,255,0), width=4)
            return img
        def on_show(i, it): self.root.after(0, self._show_from_tray)
        def on_toggle(i, it): self.root.after(0, self._toggle_crosshair)
        def on_mini(i, it): self.root.after(0, lambda: self.mini.toggle() if self.mini else None)
        def on_hud(i, it): self.root.after(0, self._toggle_hud)
        def on_quit(i, it):
            i.stop(); self.root.after(0, self.on_close)
        menu = pystray.Menu(
            pystray.MenuItem('Показать окно', on_show, default=True),
            pystray.MenuItem('Вкл/выкл прицел', on_toggle),
            pystray.MenuItem('Мини-режим', on_mini),
            pystray.MenuItem('HUD вкл/выкл', on_hud),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem('Выход', on_quit),
        )
        self.tray_icon = pystray.Icon("crosshair", make_img(), "Crosshair", menu)
        def run():
            try: self.tray_icon.run()
            except Exception: pass
        self._tray_thread = threading.Thread(target=run, daemon=True); self._tray_thread.start()

    def _show_from_tray(self):
        self.root.deiconify(); self.root.lift(); self.root.focus_force()

    def _collect(self):
        return {
            "version": 4, "enabled": self.enabled_var.get(),
            "brightness": float(self.brightness_var.get()),
            "brightness_mode": self.br_mode_var.get(),
            "start_minimized": bool(self.start_min_var.get()),
            "notify_enabled": bool(self.notify_enabled_var.get()),
            "hud_show_fps": bool(self.hud_fps_var.get()),
            "hud_show_cpu": bool(self.hud_cpu_var.get()),
            "hud_show_gpu": bool(self.hud_gpu_var.get()),
            "hud_font_size": int(self.hud_font_size_var.get()),
            "hud_color": self.hud_color_var.get(),
            "hud_pos_x": int(self.hud_pos_x), "hud_pos_y": int(self.hud_pos_y),
            "active_idx": int(self.active_idx),
            "layers": [L.to_dict() for L in self.layers],
            "color_history": self._color_history[:12],
            "custom_palette": self._custom_palette[:24],
        }

    def _apply(self, d):
        for k, v in [("enabled", True), ("brightness", 1.0),
                     ("brightness_mode", "screen"), ("start_minimized", False),
                     ("notify_enabled", True), ("hud_show_fps", False),
                     ("hud_show_cpu", False), ("hud_show_gpu", False),
                     ("hud_font_size", 10), ("hud_color", "#00FF00")]:
            try:
                var = getattr(self, k + "_var", None)
                if var: var.set(d.get(k, v))
            except Exception: pass
        try: self.hud_pos_x = int(d.get("hud_pos_x", 20))
        except Exception: pass
        try: self.hud_pos_y = int(d.get("hud_pos_y", 20))
        except Exception: pass
        try: self._color_history = list(d.get("color_history", []))[:12]
        except Exception: pass
        try: self._custom_palette = list(d.get("custom_palette", []))[:24]
        except Exception: pass
        try: self.active_idx = int(d.get("active_idx", 0))
        except Exception: pass
        layers_data = d.get("layers")
        if layers_data is None:
            old = {k: d.get(k) for k in ["style","size","thickness","gap","dot","color",
                                          "outline","outline_color","outline_thickness",
                                          "offset_x","offset_y","opacity","scale",
                                          "rotate_enabled","rotate_speed","rotate_orbit"]
                   if k in d}
            layers_data = [old] if old else [{}]
        self.layers = [Layer(ld) for ld in layers_data[:5]]
        if not self.layers: self.layers = [Layer()]
        self.active_idx = max(0, min(self.active_idx, len(self.layers) - 1))
        self._update_hud_options()

    def _save_settings(self):
        try:
            with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
                json.dump(self._collect(), f, indent=2, ensure_ascii=False)
            messagebox.showinfo("Готово", f"Сохранено в:\n{SETTINGS_PATH}")
        except Exception as e: messagebox.showerror("Ошибка", str(e))
    def _load_settings(self):
        if not os.path.exists(SETTINGS_PATH): return
        try:
            with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
                self._apply(json.load(f))
        except Exception as e: print("load error:", e, file=sys.stderr)
    def _reset_all(self):
        if messagebox.askyesno("Сброс", "Сбросить все настройки?"):
            self._apply(DEFAULTS)
            self._rebuild_layer_list(); self._rebuild_params_tab()
            self._rebuild_color_tab(); self._rebuild_effects_tab(); self._redraw()

    HOTKEYS = [(1,0x48),(2,0x53),(3,0x43),(4,0x26),(5,0x28),(6,0x52),(7,0x4D),(8,0x46),(9,0x54)]
    def _start_hotkeys(self):
        def worker():
            try:
                for hid, vk in self.HOTKEYS:
                    try: user32.RegisterHotKey(None, hid, MOD, vk)
                    except Exception: pass
                msg = wintypes.MSG()
                while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                    if msg.message == WM_HOTKEY: self._hk_queue.put(msg.wParam)
            except Exception: pass
        threading.Thread(target=worker, daemon=True).start()
    def _poll_hotkeys(self):
        if self._shutting_down: return
        try:
            while True:
                hid = self._hk_queue.get_nowait(); self._handle_hotkey(hid)
        except queue.Empty: pass
        except Exception: pass
        self.root.after(60, self._poll_hotkeys)
    def _handle_hotkey(self, hid):
        try:
            if hid == 1:
                self.enabled_var.set(not self.enabled_var.get())
                self._redraw(); self._update_status()
                if self.mini: self.mini.update()
                self._notify("Прицел: вкл" if self.enabled_var.get() else "Прицел: выкл",
                             "#3ba55d" if self.enabled_var.get() else "#8a8d94")
            elif hid == 2:
                order = [s[0] for s in STYLE_NAMES]
                L = self.layers[self.active_idx]; cur = L.style.get()
                nxt = order[(order.index(cur)+1) % len(order)] if cur in order else order[0]
                L.style.set(nxt); self._refresh_style_buttons()
                self._rebuild_layer_list(); self._redraw()
                self._notify(f"Стиль: {STYLE_DICT.get(nxt, nxt).replace(chr(10),' ')}")
            elif hid == 3:
                L = self.layers[self.active_idx]
                cur = L.color.get().upper()
                try: idx = [c.upper() for c in QUICK_COLORS].index(cur)
                except ValueError: idx = -1
                nxt = QUICK_COLORS[(idx+1) % len(QUICK_COLORS)]
                self._set_color(L, nxt); self._notify(f"Цвет: {nxt}")
            elif hid == 4:
                v = min(2.0, self.brightness_var.get()+0.1); self._set_brightness(v)
                self._notify(f"Яркость: {v:.2f}")
            elif hid == 5:
                v = max(0.3, self.brightness_var.get()-0.1); self._set_brightness(v)
                self._notify(f"Яркость: {v:.2f}")
            elif hid == 6: self._reset_brightness()
            elif hid == 7:
                if self.mini: self.mini.toggle()
            elif hid == 8: self._toggle_hud()
            elif hid == 9:
                L = self.layers[self.active_idx]
                L.rotate_enabled.set(not L.rotate_enabled.get())
                if L.rotate_enabled.get(): L.angle = 0.0
                self._rebuild_layer_list(); self._rebuild_params_tab(); self._redraw()
                self._notify("Вращение: вкл" if L.rotate_enabled.get() else "Вращение: выкл")
        except Exception as e: print("hotkey error:", e, file=sys.stderr)

    def on_close(self):
        self._shutting_down = True
        try: GPU_READER.stop()
        except Exception: pass
        try: set_brightness(1.0)
        except Exception: pass
        try:
            if self.tray_icon: self.tray_icon.stop()
        except Exception: pass
        try:
            with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
                json.dump(self._collect(), f, indent=2, ensure_ascii=False)
        except Exception: pass
        try: self.root.destroy()
        except Exception: pass

    def run(self): self.root.mainloop()


def main():
    try:
        CrosshairApp().run()
    except Exception as e:
        log_exception(type(e), e, e.__traceback__)
        native_msg("Ошибка", f"{type(e).__name__}: {e}\n\nЛог: {LOG_PATH}")
        raise

if __name__ == "__main__":
    main()
