"""The only part of Ozzy TV that touches a screen.

It does two things: turn keypresses into Actions, and paint the Scene that
skin.py builds. It makes no decisions — anything resembling a rule about what a
child may do belongs in app.py, where a test can reach it.

Tk, on a Raspberry Pi 3, for two reasons: it is in the standard library, so there
is nothing to install on a machine whose job is to survive years of not being
maintained; and it costs about ten megabytes on a board that has a thousand and
needs the rest for decoding video. libVLC draws straight into one of its frames
through the X window id, so the picture appears inside the app rather than as a
second window a child can get behind.
"""
from __future__ import annotations

import logging
import tkinter as tk
import tkinter.font as tkfont

from . import scene as S
from . import skin
from .app import Action, OzzyApp, Screen

log = logging.getLogger(__name__)

TICK_MS = 250          # four times a second: smooth enough for a progress bar,
                       # idle enough to leave the CPU for decoding
POINTER_IDLE_MS = 3000 # how long the mouse pointer stays visible after it stops

# Font role -> (family, weight, size as a fraction of the screen height). Kept
# beside tools/mockup.py's copy of the same table; if they drift, a mockup stops
# being a picture of the television.
FONTS = {
    S.LOGO:  ("DejaVu Sans", "bold", 0.058),
    S.H1:    ("DejaVu Sans", "bold", 0.044),
    S.H2:    ("DejaVu Sans", "bold", 0.029),
    S.TILE:  ("DejaVu Sans", "bold", 0.025),
    S.BODY:  ("DejaVu Sans", "normal", 0.024),
    S.SMALL: ("DejaVu Sans", "normal", 0.019),
    S.GLYPH: ("DejaVu Sans", "bold", 0.040),
}

# Every key a cheap USB remote, a keyboard or a CEC bridge might send. Remotes
# present themselves as keyboards, which is why this list is longer than it looks
# like it needs to be.
KEYMAP = {
    "Up": Action.UP, "Down": Action.DOWN, "Left": Action.LEFT, "Right": Action.RIGHT,
    "KP_Up": Action.UP, "KP_Down": Action.DOWN, "KP_Left": Action.LEFT, "KP_Right": Action.RIGHT,
    "Return": Action.SELECT, "KP_Enter": Action.SELECT, "space": Action.PLAY_PAUSE,
    "BackSpace": Action.BACK, "Escape": Action.BACK,
    "XF86Back": Action.BACK, "XF86AudioPlay": Action.PLAY_PAUSE,
    "XF86AudioStop": Action.BACK,
    "XF86AudioRaiseVolume": Action.VOLUME_UP, "XF86AudioLowerVolume": Action.VOLUME_DOWN,
    "plus": Action.VOLUME_UP, "minus": Action.VOLUME_DOWN,
    "KP_Add": Action.VOLUME_UP, "KP_Subtract": Action.VOLUME_DOWN,
    "Delete": Action.CLEAR, "KP_Delete": Action.CLEAR,
}


class TkView:
    def __init__(self, app: OzzyApp, fullscreen: bool = True):
        self.app = app
        self.root = tk.Tk()
        self.root.title("Ozzy TV")
        self.root.configure(bg=skin.SKY_TOP)
        if fullscreen:
            self.root.attributes("-fullscreen", True)
            # ...and the same thing again the hard way. `-fullscreen` is a
            # request to the WINDOW MANAGER, and the kiosk session deliberately
            # runs without one — no window manager, no taskbar, nothing for a
            # child to reach. With nobody to honour the hint the window can come
            # up at Tk's default size on a black root window, which looks
            # exactly like a crash. An explicit geometry needs no WM.
            self.root.geometry(
                f"{self.root.winfo_screenwidth()}x{self.root.winfo_screenheight()}+0+0")
            # The pointer is hidden further down, once the widgets it has to be
            # set on actually exist.
            self._hide_the_pointer = True
        else:
            self._hide_the_pointer = False
            self.root.geometry("1280x720")

        # The frame libVLC paints into. It sits BEHIND everything and is raised
        # only while something is playing.
        self.video = tk.Frame(self.root, bg="black", highlightthickness=0, bd=0)
        self.video.place(x=0, y=0, relwidth=1, relheight=1)
        # The menus.
        self.canvas = tk.Canvas(self.root, bg=skin.SKY_TOP, highlightthickness=0, bd=0)
        self.canvas.place(x=0, y=0, relwidth=1, relheight=1)
        # The paused strip is its OWN canvas across the bottom. Tk widgets are
        # opaque, so a full-screen canvas raised over the video does not overlay
        # the picture — it replaces it with a rectangle of background colour.
        self.overlay = tk.Canvas(self.root, bg=skin.PANEL, highlightthickness=0, bd=0)
        self.overlay.place_forget()
        _raise(self.canvas)
        # A child will find the mouse pointer and leave it in the picture.
        if self._hide_the_pointer:
            self._cursor("none")

        self._fonts: dict[tuple, tkfont.Font] = {}
        self._attached = False
        self._last_screen = ""
        self.root.bind("<Key>", self._on_key)
        # A pointer is not how a child drives this — but it IS how the grown-up
        # setting it up drives it, and doing nothing at all when you click a tile
        # reads as broken rather than as deliberate.
        self.root.bind("<Button-1>", self._on_click)
        self.canvas.bind("<Button-1>", self._on_click)
        self.overlay.bind("<Button-1>", self._on_click)
        self.root.bind("<Motion>", self._on_motion)
        self._hide_pointer_after = None
        self._hits: list[tuple[float, float, float, float, str]] = []
        self.root.protocol("WM_DELETE_WINDOW", lambda: None)   # no way out but the PIN

    # ------------------------------------------------------------------ input
    def _on_motion(self, event) -> None:
        """Show the pointer while it is moving, and take it away again.

        Permanently hidden and it looks broken; permanently shown and there is
        an arrow parked in the middle of a programme, because a child will find
        the mouse and let go of it.
        """
        try:
            self._cursor("")
            if self._hide_pointer_after is not None:
                self.root.after_cancel(self._hide_pointer_after)
            self._hide_pointer_after = self.root.after(
                POINTER_IDLE_MS, lambda: self._cursor("none"))
        except Exception:
            log.debug("could not show the pointer", exc_info=True)

    def _cursor(self, shape: str) -> None:
        """Set the pointer on EVERY widget, not just the toplevel.

        A child window with no cursor of its own inherits its parent's, so
        setting it once ought to be enough — ought to. When it is not, what you
        get is X11's root-window pointer, the big black X, sitting on top of a
        perfectly good menu and looking exactly like a crash. Four calls is
        cheaper than finding out which of them was the one that mattered.
        """
        for widget in (self.root, self.video, self.canvas, self.overlay):
            try:
                widget.config(cursor=shape)
            except Exception:
                pass

    def _on_click(self, event) -> None:
        """Press whatever is under the pointer.

        Hit-tested against the rectangles the Scene was DRAWN from, topmost
        first, so this cannot drift away from what is on the screen the way a
        second copy of the layout would.
        """
        # Widget coordinates, not screen ones. The Scene is laid out relative to
        # the canvas it is painted on, and the paused strip is painted into its
        # own canvas parked at the bottom of the screen — so x_root/y_root are
        # off by wherever that canvas sits, and off by the window position in
        # --windowed. They happen to agree only for a fullscreen menu at 0,0.
        x, y = event.x, event.y
        for x0, y0, x1, y1, target in reversed(self._hits):
            if x0 <= x <= x1 and y0 <= y <= y1:
                self.app.click(target)
                self.render()
                return

    def _on_key(self, event) -> None:
        sym = event.keysym
        if sym in KEYMAP:
            self.app.handle(KEYMAP[sym])
        elif len(sym) == 1 and sym.isdigit():
            self.app.handle(Action.DIGIT, sym)
        elif sym in self.app.settings.parent_keys:
            self.app.handle(Action.PARENT)
        elif sym.lower() == "q":
            # Only the parent screen acts on this; everywhere else app.py drops it.
            self.app.handle(Action.QUIT)
        else:
            return
        self.render()

    # ------------------------------------------------------------------- loop
    def run(self) -> None:
        self.root.after(0, self._attach_video)
        self.root.after(0, self._take_the_keyboard)
        self.root.after(TICK_MS, self._tick)
        self.render()
        self.root.mainloop()

    def _take_the_keyboard(self) -> None:
        """Ask X for the keyboard, out loud.

        Assigning focus is the window manager's job, and this session has no
        window manager. X then leaves the input focus at PointerRoot, so
        keypresses go to whatever the pointer happens to be over — and the
        pointer is hidden and parked on the root window. The menus draw, the
        screen looks right, and not one button does anything.
        """
        try:
            self.root.focus_force()
        except Exception:
            log.debug("could not take the keyboard focus", exc_info=True)

    def _attach_video(self) -> None:
        """Hand libVLC the window to draw into. Must wait until Tk has actually
        created it — winfo_id() before that returns an id nothing can draw on."""
        if self._attached:
            return
        try:
            self.video.update_idletasks()
            self.app.player.attach(self.video.winfo_id())
            self._attached = True
        except Exception:
            log.exception("could not give VLC a window to draw in")

    def _tick(self) -> None:
        self.app.tick()
        if self.app.should_quit:
            self.root.destroy()
            return
        # Redraw on the tick ONLY when something moves by itself. Building a View
        # stats every tile on screen (to decide whether it shows a "resume" mark),
        # and doing that four times a second against an SD card is a steady drip
        # of I/O for a grid that is not changing. Keypresses redraw on their own.
        screen = self.app.screen.value
        if screen != self._last_screen or screen == Screen.PLAYING.value:
            self._last_screen = screen
            self.render()
        self.root.after(TICK_MS, self._tick)

    # ----------------------------------------------------------------- render
    def render(self) -> None:
        v = self.app.view()
        w = self.canvas.winfo_width() or 1280
        h = self.canvas.winfo_height() or 720
        sc = skin.build(v, w, h, columns=self.app.settings.columns,
                        rows=self.app.settings.rows)
        if v.screen == Screen.PLAYING.value:
            _raise(self.video)
            if not v.paused:
                self.overlay.place_forget()
                return
            # skin lays the strip out in full-screen coordinates; the strip itself
            # is the bottom slice, so it is drawn with everything shifted up by
            # where that slice starts.
            strip_h = int(h * 0.30)
            self.overlay.place(x=0, y=h - strip_h, relwidth=1, height=strip_h)
            _raise(self.overlay)
            self._paint(self.overlay, sc, dy=-(h - strip_h))
            return
        self.overlay.place_forget()
        _raise(self.canvas)
        self._paint(self.canvas, sc)

    def _font(self, role: str, h: int, size: float = 0) -> tkfont.Font:
        family, weight, frac = FONTS.get(role, FONTS[S.BODY])
        px = int(size) if size else int(h * frac)
        key = (family, weight, px)
        if key not in self._fonts:
            self._fonts[key] = tkfont.Font(family=family, size=-max(8, px), weight=weight)
        return self._fonts[key]

    def _paint(self, canvas: tk.Canvas, sc: S.Scene, dy: float = 0) -> None:
        canvas.delete("all")
        canvas.configure(bg=sc.bg)
        self._hits = [(i.x, i.y + dy, i.x + i.w, i.y + i.h + dy, i.hit)
                      for i in sc.items
                      if isinstance(i, S.RoundRect) and i.hit]
        for item in sc.items:
            try:
                self._draw(canvas, item, sc.h, dy)
            except tk.TclError:
                # One malformed shape must not take the television down with it.
                log.debug("could not draw %r", item, exc_info=True)

    def _draw(self, c: tk.Canvas, item, h: int, dy: float) -> None:
        if isinstance(item, S.Gradient):
            for i in range(item.bands):
                t = i / max(1, item.bands - 1)
                c.create_rectangle(
                    item.x, item.y + item.h * i / item.bands + dy,
                    item.x + item.w, item.y + item.h * (i + 1) / item.bands + 1 + dy,
                    fill=_mix(item.top, item.bottom, t), outline="")
        elif isinstance(item, S.RoundRect):
            c.create_polygon(_round_points(item.x, item.y + dy, item.w, item.h, item.r),
                             fill=item.fill or "", outline=item.outline or "",
                             width=item.width, smooth=True)
        elif isinstance(item, S.Oval):
            c.create_oval(item.cx - item.rx, item.cy - item.ry + dy,
                          item.cx + item.rx, item.cy + item.ry + dy,
                          fill=item.fill or "", outline=item.outline or "",
                          width=item.width or 1)
        elif isinstance(item, S.Poly):
            pts = [(x, y + dy) for x, y in item.points]
            if len(pts) == 2 or (item.outline and not item.fill):
                c.create_line([v for p in pts for v in p],
                              fill=item.outline or item.fill, width=item.width or 1,
                              capstyle="round")
            else:
                c.create_polygon([v for p in pts for v in p], fill=item.fill or "",
                                 outline=item.outline or "", width=item.width)
        elif isinstance(item, S.Text):
            c.create_text(item.x, item.y + dy, text=item.text,
                          font=self._font(item.font, h, item.size), fill=item.fill,
                          anchor=item.anchor, width=item.wrap or 0,
                          justify="center" if item.anchor in ("n", "center", "s") else "left")


def _raise(widget) -> None:
    """Raise a widget above its siblings.

    NOT `widget.tkraise()`, and NOT `widget.lift()`. tkinter's Canvas ends with

        lift = tkraise = tag_raise

    so on a Canvas BOTH names are the method that raises a canvas ITEM, and with
    no item named Tcl answers

        wrong # args: should be ".!canvas raise tagOrId ?aboveThis?"

    That is a TclError in TkView.__init__, which is to say a black screen on
    every boot. Only Misc's version raises the widget, and on a Canvas nothing
    reaches it — so call Tcl's `raise` directly, where there is no alias to land
    on. Frames are unaffected either way; one helper is one thing to remember
    instead of a rule per widget class.
    """
    widget.tk.call("raise", str(widget))


def _round_points(x: float, y: float, w: float, h: float, r: float) -> list[float]:
    """A rounded rectangle as a smoothed polygon.

    Tk has no rounded-rectangle primitive. Doubling each corner point and letting
    smooth=True spline between them is the standard trick and, unlike stitching
    four arcs to three lines, it leaves no seams where the fill shows through.
    """
    r = max(0.0, min(r, w / 2, h / 2))
    x2, y2 = x + w, y + h
    return [x + r, y, x + r, y, x2 - r, y, x2 - r, y, x2, y, x2, y + r,
            x2, y + r, x2, y2 - r, x2, y2 - r, x2, y2, x2 - r, y2, x2 - r, y2,
            x + r, y2, x + r, y2, x, y2, x, y2 - r, x, y2 - r, x, y + r,
            x, y + r, x, y]


def _mix(a: str, b: str, t: float) -> str:
    ar, ag, ab = (int(a[i:i + 2], 16) for i in (1, 3, 5))
    br, bg, bb = (int(b[i:i + 2], 16) for i in (1, 3, 5))
    return "#%02x%02x%02x" % (int(ar + (br - ar) * t), int(ag + (bg - ag) * t),
                              int(ab + (bb - ab) * t))
