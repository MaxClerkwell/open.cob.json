"""Tkinter editor: canvas on the left, toolbox on the right."""
from __future__ import annotations

import argparse
import json
import math
import sys
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from cobkicad.footprint import build_footprint, footprint_name
from cobkicad.symbol import build_symbol
from cobviz.model import UUID_RE, Cob, nominal

GRID_DEFAULT = 0.05
SIDEBAR_WIDTH = 300
REPO_SHAPES = Path(__file__).resolve().parents[4] / "examples" / "shapes"
COL = {
    "bg": "#fafafa", "die": "#3a3a3a", "die_pad": "#e0c060", "copper": "#c8802a",
    "mask": "#7fb59a", "wire": "#2060d0", "misc": "#c02040", "preview": "#2060d0",
    "select": "#d02020", "origin": "#000",
}


def _point_in_poly(x, y, poly) -> bool:
    inside = False
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        if (y1 > y) != (y2 > y):
            xi = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
            if x < xi:
                inside = not inside
    return inside


def rect(cx, cy, w, h):
    return [(cx - w / 2, cy - h / 2), (cx + w / 2, cy - h / 2), (cx + w / 2, cy + h / 2), (cx - w / 2, cy + h / 2)]


class Section(ttk.Frame):
    """Collapsible toolbox section: a header row that shows or hides a body frame."""

    def __init__(self, master, title: str, open_: bool = False, expand: bool = False, on_open=None, **kw):
        super().__init__(master, **kw)
        self.title = title
        self._open = open_
        self._expand = expand
        self.on_open = on_open  # called with this section when it opens
        self.header = ttk.Label(self, text="", cursor="hand2", font=("TkDefaultFont", 10, "bold"))
        self.header.pack(fill="x")
        self.header.bind("<Button-1>", lambda e: self.toggle())
        self.body = ttk.Frame(self, padding=(6, 4, 0, 4))
        self._update()

    def _update(self):
        self.header.config(text=f"{'▾' if self._open else '▸'} {self.title}")
        if self._open:
            self.body.pack(fill="both" if self._expand else "x", expand=self._expand)
        else:
            self.body.pack_forget()
        # an expanded section may claim the leftover height, a collapsed one must not
        self.pack_configure(expand=self._open and self._expand, fill="both" if self._open and self._expand else "x")

    def toggle(self):
        if self._open:
            self.close()
        else:
            self.open()

    def open(self):
        if not self._open:
            self._open = True
            self._update()
            if self.on_open:
                self.on_open(self)

    def close(self):
        if self._open:
            self._open = False
            self._update()


class View:
    """World (mm, Y up) <-> canvas pixels."""

    def __init__(self):
        self.k = 100.0  # px per mm
        self.ox = 0.0   # canvas x of world origin
        self.oy = 0.0

    def to_px(self, x, y):
        return self.ox + x * self.k, self.oy - y * self.k

    def to_world(self, px, py):
        return (px - self.ox) / self.k, (self.oy - py) / self.k

    def flat(self, pts):
        out = []
        for x, y in pts:
            out.extend(self.to_px(x, y))
        return out


class App:
    def __init__(self, root: tk.Tk, path: Path | None, shape_dirs: list[Path] | None = None):
        self.root = root
        self.root.title("cobedit")
        self.shape_dirs = list(shape_dirs or [])
        self.cob: Cob | None = None
        self.path: Path | None = None
        self.view = View()
        self.tool = None          # None | "place" | "wire"
        self.wire_from: str | None = None   # die pad id picked as wire start
        self.drag = None                    # dict while a pad is being moved or resized
        self.selected_wire: int | None = None
        self.preview_items: list[int] = []
        self.pan_start = None
        self.selected: int | None = None
        self.dirty = False
        self._needs_fit = False

        self._build_ui()
        self._bind()
        if path:
            self.load(path)

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(1, weight=1)
        self._build_toolbar()
        self.canvas = tk.Canvas(self.root, bg=COL["bg"], highlightthickness=0, cursor="crosshair")
        self.canvas.grid(row=1, column=0, sticky="nsew")

        tb = ttk.Frame(self.root, padding=8, width=SIDEBAR_WIDTH)
        tb.grid(row=1, column=1, sticky="ns")
        tb.grid_propagate(False)  # children never change the width
        tb.pack_propagate(False)
        self.root.columnconfigure(1, weight=0, minsize=SIDEBAR_WIDTH)
        # packed first so it keeps its place at the bottom when the sections
        # above need more height than the window has
        self.status = ttk.Label(tb, text="", foreground="#666")
        self.status.pack(side="bottom", fill="x", pady=(6, 0))
        self.tb = tb

        self.sec_file = Section(tb, "File", on_open=self._collapse_others)
        self.sec_file.pack(fill="x", pady=(0, 6))
        f = self.sec_file.body
        ttk.Button(f, text="Open...", command=self.open_dialog).pack(fill="x")
        ttk.Button(f, text="Save", command=self.save).pack(fill="x", pady=2)
        ttk.Button(f, text="Save as...", command=self.save_as).pack(fill="x")
        ttk.Button(f, text="Export KiCad...", command=self.export_kicad).pack(fill="x", pady=(6, 0))
        self.lbl_file = ttk.Label(f, text="no file", wraplength=260, foreground="#666")
        self.lbl_file.pack(fill="x", pady=(4, 0))

        self.sec_wire = Section(tb, "Wire", on_open=self._collapse_others)
        self.sec_wire.pack(fill="x", pady=(0, 6))
        wf = self.sec_wire.body
        self.btn_wire = ttk.Button(wf, text="Add wire (W)", command=self.start_add_wire)
        self.btn_wire.pack(fill="x")
        wg = ttk.Frame(wf)
        wg.pack(fill="x", pady=(6, 0))
        self.v_wtype = tk.StringVar(value="wedge")
        self.v_wmat = tk.StringVar(value="Al")
        self.v_wdia = tk.StringVar(value="25")
        for r, (label, var, values) in enumerate([("Type", self.v_wtype, ("wedge", "ball", "ribbon")),
                                                  ("Material", self.v_wmat, ("Al", "Au", "Cu", "Ag")),
                                                  ("Diameter µm", self.v_wdia, ("17", "20", "25", "32", "50"))]):
            ttk.Label(wg, text=label).grid(row=r, column=0, sticky="w")
            ttk.Combobox(wg, textvariable=var, values=values, width=12).grid(row=r, column=1, sticky="ew", pady=1)
        wg.columnconfigure(1, weight=1)
        self.lbl_whint = ttk.Label(wf, text="", wraplength=260, foreground="#2060d0")
        self.lbl_whint.pack(fill="x", pady=(6, 0))
        self.wire_list = tk.Listbox(wf, exportselection=False, height=5)
        self.wire_list.pack(fill="x", pady=(6, 0))
        self.wire_list.bind("<<ListboxSelect>>", self._on_select_wire)
        ttk.Button(wf, text="Delete wire", command=self.delete_wire).pack(fill="x", pady=(4, 0))

        self.sec_pad = Section(tb, "PCB pads", expand=True, on_open=self._collapse_others)
        self.sec_pad.pack(fill="x", pady=(0, 6))
        # pack order is priority when space is short: tool controls first,
        # then the button row, the list last takes whatever height is left
        p = ttk.Frame(self.sec_pad.body)
        p.pack(side="top", fill="x")
        pad_btns = ttk.Frame(self.sec_pad.body)
        pad_btns.pack(side="bottom", fill="x", pady=(4, 0))
        self.pad_list = tk.Listbox(self.sec_pad.body, exportselection=False, height=3)
        self.pad_list.pack(side="bottom", fill="both", expand=True, pady=(8, 0))
        self.pad_list.bind("<<ListboxSelect>>", self._on_select_pad)
        self.pad_list.bind("<Double-Button-1>", lambda e: self.edit_pad())
        self.pad_list.bind("<Return>", lambda e: self.edit_pad())
        ttk.Button(pad_btns, text="-90°", width=5, command=lambda: self.rotate_pad(-90)).pack(side="left")
        ttk.Button(pad_btns, text="+90°", width=5, command=lambda: self.rotate_pad(90)).pack(side="left", padx=(2, 4))
        ttk.Button(pad_btns, text="Edit...", command=self.edit_pad).pack(side="left", fill="x", expand=True)
        ttk.Button(pad_btns, text="Delete", command=self.delete_pad).pack(side="left", fill="x", expand=True, padx=(4, 0))
        self.btn_add = ttk.Button(p, text="Add PCB pad", command=self.start_add_pad)
        self.btn_add.pack(fill="x")
        ttk.Label(p, text="Shape").pack(anchor="w", pady=(6, 0))
        self.shape_var = tk.StringVar()
        self.shape_box = ttk.Combobox(p, textvariable=self.shape_var, state="readonly", width=30)
        self.shape_box.pack(fill="x")
        self.shape_box.bind("<<ComboboxSelected>>", lambda e: self._refresh_preview())

        grid = ttk.Frame(p)
        grid.pack(fill="x", pady=(6, 0))
        self.v_number = tk.StringVar()
        self.v_name = tk.StringVar()
        self.v_rot = tk.StringVar(value="0")
        self.v_sx = tk.StringVar(value="1.0")
        self.v_sy = tk.StringVar(value="1.0")
        self.v_grid = tk.StringVar(value=str(GRID_DEFAULT))
        for r, (label, var) in enumerate([("Number", self.v_number), ("Name", self.v_name),
                                          ("Rotation", self.v_rot), ("Scale X", self.v_sx),
                                          ("Scale Y", self.v_sy), ("Grid mm", self.v_grid)]):
            ttk.Label(grid, text=label).grid(row=r, column=0, sticky="w")
            e = ttk.Entry(grid, textvariable=var, width=14)
            e.grid(row=r, column=1, sticky="ew", pady=1)
            e.bind("<KeyRelease>", lambda ev: self._refresh_preview())
        grid.columnconfigure(1, weight=1)
        self.lbl_hint = ttk.Label(p, text="", wraplength=260, foreground="#2060d0")
        self.lbl_hint.pack(fill="x", pady=(6, 0))
        ttk.Button(p, text="Cancel (Esc)", command=self.cancel_tool).pack(fill="x", pady=(4, 0))


    def _collapse_others(self, opened: "Section"):
        for sec in (self.sec_file, self.sec_wire, self.sec_pad):
            if sec is not opened:
                sec.close()

    def _build_toolbar(self):
        bar = ttk.Frame(self.root, padding=(8, 4))
        bar.grid(row=0, column=0, columnspan=2, sticky="ew")
        ttk.Label(bar, text="View").pack(side="left", padx=(0, 8))
        self.die_mode = "solid"  # solid | translucent | outline
        self.btn_die = ttk.Button(bar, command=self.cycle_die_mode, width=18)
        self.btn_die.pack(side="left", padx=(0, 12))
        self._update_die_button()
        self.show = {}
        for key, label, default in (("grid", "Grid", False), ("die_pads", "Die pads", True),
                                    ("labels", "Pad names", True), ("pcb", "PCB pads", True),
                                    ("mask", "Mask", True), ("misc", "Misc", True), ("wires", "Wires", True)):
            var = tk.BooleanVar(value=default)
            self.show[key] = var
            ttk.Checkbutton(bar, text=label, variable=var, command=self.redraw).pack(side="left", padx=(0, 8))
        ttk.Separator(bar, orient="vertical").pack(side="left", fill="y", padx=8)
        ttk.Button(bar, text="Fit die", command=self.fit_die).pack(side="left")
        ttk.Button(bar, text="Fit all (F)", command=self.fit).pack(side="left", padx=(4, 0))
        ttk.Separator(self.root, orient="horizontal").grid(row=0, column=0, columnspan=2, sticky="sew")

    def _bind(self):
        c = self.canvas
        c.bind("<Configure>", self._on_configure)
        c.bind("<Motion>", self._on_motion)
        c.bind("<Button-1>", self._on_click)
        c.bind("<B1-Motion>", self._drag_move)
        c.bind("<ButtonRelease-1>", self._drag_end)
        c.bind("<ButtonPress-2>", self._pan_start)
        c.bind("<ButtonPress-3>", self._pan_start)
        c.bind("<B2-Motion>", self._pan_move)
        c.bind("<B3-Motion>", self._pan_move)
        c.bind("<MouseWheel>", self._on_wheel)
        c.bind("<Button-4>", lambda e: self._zoom(e.x, e.y, 1.2))
        c.bind("<Button-5>", lambda e: self._zoom(e.x, e.y, 1 / 1.2))
        self.root.bind("<Escape>", lambda e: self.cancel_tool())
        self.root.bind("<Key-r>", lambda e: self._on_rotate_key(90))
        self.root.bind("<Key-R>", lambda e: self._on_rotate_key(-90))
        self.root.bind("<Key-f>", lambda e: self.fit())
        self.root.bind("<Key-d>", lambda e: self.cycle_die_mode())
        self.root.bind("<Key-w>", lambda e: self.start_add_wire())
        self.root.bind("<Control-s>", lambda e: self.save())
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _on_configure(self, e):
        if getattr(self, "_needs_fit", False):
            self._fit_when_ready()
        else:
            self.redraw()

    # ------------------------------------------------------------- file ops
    def open_dialog(self):
        p = filedialog.askopenfilename(filetypes=[("cob.json", "*.cob.json"), ("JSON", "*.json")])
        if p:
            self.load(Path(p))

    def load(self, path: Path):
        try:
            self.cob = Cob.load(path, self.shape_dirs)
        except Exception as e:  # noqa: BLE001 - show anything to the user
            messagebox.showerror("cobedit", f"Cannot load {path}:\n{e}")
            return
        self.path = path
        self.dirty = False
        self.lbl_file.config(text=path.name)
        self._ensure_pcb_lists()
        self._ensure_wire_lists()
        self._fill_wire_list()
        self._fill_shape_box()
        self._fill_pad_list()
        self._needs_fit = True
        self.root.after_idle(self._fit_when_ready)

    def _fit_when_ready(self):
        """fit_die needs the real canvas size; at startup Tk reports 1x1 until the
        first layout pass. Wait for that, then fit once."""
        if not self._needs_fit:
            return
        self.root.update_idletasks()
        if self.canvas.winfo_width() > 50 and self.canvas.winfo_height() > 50:
            self._needs_fit = False
            self.fit_die()
        else:
            self.root.after(50, self._fit_when_ready)

    def _ensure_wire_lists(self):
        wires = self.cob.data.get("wires")
        if not isinstance(wires, dict):
            wires = self.cob.data["wires"] = {}
        if not isinstance(wires.get("items"), list):
            wires["items"] = []
        for k in ("pairs", "electrical_specifications"):
            wires.setdefault(k, "unspecified")

    def _ensure_pcb_lists(self):
        pcb = self.cob.data.setdefault("pcb", {})
        if not isinstance(pcb.get("pads"), list):
            pcb["pads"] = []
        if not isinstance(pcb.get("shapes"), dict):
            pcb["shapes"] = {}

    def save(self):
        if not self.cob:
            return
        if not self.path:
            return self.save_as()
        self._write(self.path)

    def save_as(self):
        if not self.cob:
            return
        p = filedialog.asksaveasfilename(defaultextension=".cob.json", initialfile=self.path.name if self.path else "")
        if p:
            self.path = Path(p)
            self._write(self.path)

    def _write(self, path: Path):
        data = json.loads(json.dumps(self.cob.data))
        pcb = data["pcb"]
        if not pcb["pads"]:
            pcb["pads"] = "unspecified"
        if not pcb["shapes"]:
            pcb["shapes"] = "none"
        if isinstance(data.get("wires"), dict) and data["wires"].get("items") == []:
            data["wires"]["items"] = "unspecified"
        path.write_text(json.dumps(data, indent=2) + "\n")
        self.dirty = False
        self.lbl_file.config(text=path.name)
        self.status.config(text=f"saved {path.name}")

    def export_kicad(self):
        """Write symbol library and footprint from the current in-memory state."""
        if not self.cob:
            return
        if not self.cob.pcb_pads():
            messagebox.showinfo("cobedit", "No PCB pads yet. Place at least one pad before exporting.")
            return
        out = filedialog.askdirectory(title="Export KiCad symbol and footprint to", mustexist=True)
        if not out:
            return
        out = Path(out)
        try:
            sym = build_symbol(self.cob, "open_cob")
            fp = build_footprint(self.cob)
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("cobedit", f"KiCad export failed:\n{e}")
            return
        name = self.cob.data.get("meta", {}).get("name", "DIE").replace(" ", "_")
        sym_path = out / f"{name}.kicad_sym"
        fp_dir = out / "open_cob.pretty"
        fp_dir.mkdir(parents=True, exist_ok=True)
        fp_path = fp_dir / f"{footprint_name(self.cob)}.kicad_mod"
        sym_path.write_text(sym)
        fp_path.write_text(fp)
        self.status.config(text=f"exported {sym_path.name}, {fp_path.name}")
        messagebox.showinfo("cobedit", f"Written:\n{sym_path}\n{fp_path}")

    def _on_close(self):
        if self.dirty and not messagebox.askyesno("cobedit", "Unsaved changes. Quit anyway?"):
            return
        self.root.destroy()

    # ------------------------------------------------------------- shapes
    def _catalog_uuids(self) -> list[str]:
        found = []
        for d in self.cob.search_dirs:
            for f in sorted(d.glob("*.shape.cob.json")):
                u = f.name.split(".")[0]
                if UUID_RE.match(u):
                    found.append(u)
        return found

    def _fill_shape_box(self):
        aliases = list(self.cob.data["pcb"]["shapes"].keys())
        aliased_uuids = {v for v in self.cob.data["pcb"]["shapes"].values() if isinstance(v, str)}
        entries = [f"{a}  (alias)" for a in aliases]
        for u in self._catalog_uuids():
            if u not in aliased_uuids:
                try:
                    name = self.cob.resolve(u).name
                except Exception:  # noqa: BLE001
                    name = "?"
                entries.append(f"{u}  ({name})")
        self.shape_box["values"] = entries
        if entries and not self.shape_var.get():
            self.shape_box.current(0)

    def _selected_shape_ref(self) -> str | None:
        v = self.shape_var.get()
        return v.split("  ")[0] if v else None

    # ------------------------------------------------------------- drawing
    def _draw_grid(self):
        c, v = self.canvas, self.view
        try:
            g = float(self.v_grid.get())
        except ValueError:
            g = GRID_DEFAULT
        if g <= 0:
            return
        step, m = g, 1
        while step * v.k < 12:  # too dense to read: 2x, 5x, 10x, 20x, ...
            m = m * 2 if str(m)[0] in "15" else int(m * 2.5)
            step = g * m
        cw, ch = c.winfo_width(), c.winfo_height()
        x0, y1 = v.to_world(0, 0)
        x1, y0 = v.to_world(cw, ch)
        major = step * 10
        x = math.floor(x0 / step) * step
        while x <= x1:
            px = v.to_px(x, 0)[0]
            big = abs(x / major - round(x / major)) < 1e-6
            c.create_line(px, 0, px, ch, fill="#d8d8d8" if big else "#ececec", tags="grid")
            x += step
        y = math.floor(y0 / step) * step
        while y <= y1:
            py = v.to_px(0, y)[1]
            big = abs(y / major - round(y / major)) < 1e-6
            c.create_line(0, py, cw, py, fill="#d8d8d8" if big else "#ececec", tags="grid")
            y += step
        c.create_text(cw - 6, ch - 6, text=f"grid {step:g} mm", anchor="se", fill="#999", font=("monospace", 8))

    DIE_FILL = 0.4  # fraction of the canvas the die spans after loading

    def fit_die(self):
        """Center the die and scale it to DIE_FILL of the smaller canvas dimension."""
        if not self.cob:
            return
        die = self.cob.die
        w, h = nominal(die["size"][0]), nominal(die["size"][1])
        ox, oy = die.get("offset", [0, 0])
        cw, ch = max(self.canvas.winfo_width(), 50), max(self.canvas.winfo_height(), 50)
        self.view.k = min(cw / (w or 1), ch / (h or 1)) * self.DIE_FILL
        self.view.ox = cw / 2 - ox * self.view.k
        self.view.oy = ch / 2 + oy * self.view.k
        self.redraw()

    def fit(self):
        if not self.cob:
            return
        xs, ys = [], []
        die = self.cob.die
        w, h = nominal(die["size"][0]), nominal(die["size"][1])
        xs += [-w / 2, w / 2]
        ys += [-h / 2, h / 2]
        for pad in self.cob.pcb_pads():
            try:
                for plist in self.cob.placed_polygons(pad).values():
                    for poly in plist:
                        xs += [p[0] for p in poly]
                        ys += [p[1] for p in poly]
            except Exception:  # noqa: BLE001
                pass
        cw, ch = max(self.canvas.winfo_width(), 50), max(self.canvas.winfo_height(), 50)
        span_x, span_y = (max(xs) - min(xs)) or 1, (max(ys) - min(ys)) or 1
        self.view.k = min(cw / span_x, ch / span_y) * 0.8
        cx, cy = (max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2
        self.view.ox = cw / 2 - cx * self.view.k
        self.view.oy = ch / 2 + cy * self.view.k
        self.redraw()

    DIE_MODES = ("solid", "translucent", "outline")
    DIE_LABELS = {"solid": "Die: solid  (D)", "translucent": "Die: translucent  (D)", "outline": "Die: outline  (D)"}

    def cycle_die_mode(self):
        i = self.DIE_MODES.index(self.die_mode)
        self.die_mode = self.DIE_MODES[(i + 1) % len(self.DIE_MODES)]
        self._update_die_button()
        self.redraw()

    def _update_die_button(self):
        self.btn_die.config(text=self.DIE_LABELS[self.die_mode])

    def redraw(self):
        c = self.canvas
        c.delete("all")
        if not self.cob:
            return
        v = self.view
        show = {k: var.get() for k, var in self.show.items()}
        if show["grid"]:
            self._draw_grid()
        # misc
        for m in self.cob.misc() if show["misc"] else []:
            try:
                polys = self.cob.placed_polygons(m)
            except Exception:  # noqa: BLE001
                continue
            for plist in polys.values():
                for poly in plist:
                    c.create_polygon(v.flat(poly), fill="", outline=COL["misc"], dash=(4, 2), tags="misc")
        # pcb pads
        for i, pad in enumerate(self.cob.pcb_pads() if show["pcb"] else []):
            try:
                polys = self.cob.placed_polygons(pad)
            except Exception as e:  # noqa: BLE001
                self.status.config(text=f"pad {pad.get('id')}: {e}")
                continue
            sel = i == self.selected
            for poly in polys.get("mask", []) if show["mask"] else []:
                c.create_polygon(v.flat(poly), fill=COL["mask"], outline="", stipple="gray50")
            for poly in polys.get("copper", []):
                c.create_polygon(v.flat(poly), fill=COL["copper"], outline=COL["select"] if sel else COL["copper"],
                                 width=3 if sel else 1)
            bt = self.cob.bond_target(pad)
            px, py = v.to_px(*bt)
            c.create_oval(px - 3, py - 3, px + 3, py + 3, fill="white", outline="black")
            if show["labels"]:
                c.create_text(px, py - 10, text=f"{pad.get('number')} {pad.get('name', '')}", font=("monospace", 8))
        # die
        die = self.cob.die
        w, h = nominal(die["size"][0]), nominal(die["size"][1])
        ox, oy = die.get("offset", [0, 0])
        mode = self.die_mode
        if mode == "solid":
            c.create_polygon(v.flat(rect(ox, oy, w, h)), fill=COL["die"], outline="black")
        elif mode == "translucent":
            c.create_polygon(v.flat(rect(ox, oy, w, h)), fill=COL["die"], outline="black", stipple="gray25")
        else:
            c.create_polygon(v.flat(rect(ox, oy, w, h)), fill="", outline="black", dash=(6, 3))
        notch = die.get("notch")
        if isinstance(notch, dict):
            ns = notch.get("size", [0.1, 0.1])
            sx = -1 if "left" in notch.get("side", "") else 1
            sy = 1 if "top" in notch.get("side", "") else -1
            c.create_polygon(v.flat(rect(ox + sx * (w / 2 - ns[0] / 2), oy + sy * (h / 2 - ns[1] / 2), ns[0], ns[1])),
                             fill=COL["bg"] if mode == "solid" else "", outline="black" if mode != "solid" else "")
        for dp in self.cob.die_pads() if show["die_pads"] else []:
            cx, cy = dp["center"]
            sz = dp.get("size", [0.08, 0.08])
            c.create_polygon(v.flat(rect(cx, cy, sz[0], sz[1])),
                             fill=COL["die_pad"] if mode == "solid" else "", outline="#806000")
            if v.k > 400 and mode == "solid" and show["labels"]:
                c.create_text(*v.to_px(cx, cy), text=dp.get("name", ""), font=("monospace", 7), fill="#f0f0f0",
                              anchor="w" if dp.get("side") == "left" else "e" if dp.get("side") == "right" else "center")
        # wires
        for i, wire in enumerate(self.cob.wires() if show["wires"] else []):
            dp = self.cob.die_pad_by_id(wire.get("from", {}).get("die_pad", ""))
            pp = self.cob.pcb_pad_by_id(wire.get("to", {}).get("pcb_pad", ""))
            if dp and pp:
                try:
                    bt = self.cob.bond_target(pp)
                except Exception:  # noqa: BLE001
                    continue
                sel = i == self.selected_wire
                c.create_line(*v.to_px(*dp["center"]), *v.to_px(*bt),
                              fill=COL["select"] if sel else COL["wire"], width=4 if sel else 2)
        if self.wire_from:
            dp = self.cob.die_pad_by_id(self.wire_from)
            if dp:
                sz = dp.get("size", [0.08, 0.08])
                c.create_polygon(v.flat(rect(dp["center"][0], dp["center"][1], sz[0] * 1.6, sz[1] * 1.6)),
                                 fill="", outline=COL["select"], width=2)
        # origin
        px, py = v.to_px(0, 0)
        c.create_line(px - 8, py, px + 8, py, fill=COL["origin"])
        c.create_line(px, py - 8, px, py + 8, fill=COL["origin"])
        self.preview_items = []

    # ------------------------------------------------------------- move, resize, rotate pads
    def rotate_pad(self, deg: float):
        if self.selected is None or not self.cob:
            return
        pad = self.cob.pcb_pads()[self.selected]
        r = (float(pad.get("rotation", 0)) + deg) % 360
        pad["rotation"] = int(r) if r == int(r) else r
        self.dirty = True
        self.status.config(text=f"{pad.get('id')} rotation {pad['rotation']}°")
        self.redraw()

    def _on_rotate_key(self, deg: float):
        if self.tool == "place":
            self._rotate_preview()
        elif self.tool is None:
            self.rotate_pad(deg)

    def _pad_local(self, pad: dict):
        """Scaled, unrotated copper bounding box of a pad in its own frame, origin at `at`."""
        shape = self.cob.resolve(pad["shape"])
        f = shape.unit_factor(self.cob.units)
        from cobviz.model import scale_xy
        sx, sy = scale_xy(pad.get("scale"))
        xs, ys = [], []
        for poly in shape.polygons.get("copper", []):
            for px, py in poly:
                xs.append((px - shape.origin[0]) * f * sx)
                ys.append((py - shape.origin[1]) * f * sy)
        if not xs:
            return None
        return min(xs), min(ys), max(xs), max(ys)

    def _to_local(self, pad: dict, wx: float, wy: float) -> tuple[float, float]:
        at = pad.get("at", [0, 0])
        a = -math.radians(float(pad.get("rotation", 0)))
        dx, dy = wx - at[0], wy - at[1]
        return dx * math.cos(a) - dy * math.sin(a), dx * math.sin(a) + dy * math.cos(a)

    def _edge_hit(self, pad: dict, wx: float, wy: float):
        """Which edge of the pad's box is under the point: (ex, ey) in -1/0/1, or None."""
        try:
            box = self._pad_local(pad)
        except Exception:  # noqa: BLE001
            return None
        if not box:
            return None
        x0, y0, x1, y1 = box
        lx, ly = self._to_local(pad, wx, wy)
        tol = 6 / self.view.k
        if not (x0 - tol <= lx <= x1 + tol and y0 - tol <= ly <= y1 + tol):
            return None
        ex = -1 if abs(lx - x0) <= tol else 1 if abs(lx - x1) <= tol else 0
        ey = -1 if abs(ly - y0) <= tol else 1 if abs(ly - y1) <= tol else 0
        return (ex, ey) if ex or ey else None

    @staticmethod
    def _edge_cursor(pad: dict, hit) -> str:
        ex, ey = hit
        # map the local edge to a screen direction, good enough for 90° steps
        r = round(float(pad.get("rotation", 0)) / 90) % 4
        for _ in range(r):
            ex, ey = -ey, ex
        if ex and ey:
            return "sizing"
        return "sb_h_double_arrow" if ex else "sb_v_double_arrow"

    def _drag_start(self, e):
        """No tool active: a press on a PCB pad selects it and starts moving it;
        a press on the edge of the selected pad starts resizing it."""
        wx, wy = self.view.to_world(e.x, e.y)
        if self.selected is not None:
            pad = self.cob.pcb_pads()[self.selected]
            hit = self._edge_hit(pad, wx, wy)
            if hit:
                from cobviz.model import scale_xy
                self.drag = {"kind": "resize", "idx": self.selected, "edge": hit,
                             "box": self._pad_local(pad), "scale0": scale_xy(pad.get("scale"))}
                self.canvas.config(cursor=self._edge_cursor(pad, hit))
                self.status.config(text=f"resizing {pad.get('id')}")
                return
        pad = self._hit_pcb_pad(wx, wy)
        if not pad:
            return
        idx = self.cob.pcb_pads().index(pad)
        at = pad.get("at", [0, 0])
        self.drag = {"kind": "move", "idx": idx, "dx": at[0] - wx, "dy": at[1] - wy}  # keep the grab offset
        self.selected = idx
        self.pad_list.selection_clear(0, "end")
        self.pad_list.selection_set(idx)
        self.pad_list.see(idx)
        self.canvas.config(cursor="fleur")
        self.status.config(text=f"moving {pad.get('id')}")
        self.redraw()

    def _drag_move(self, e):
        if not self.drag or not self.cob:
            return
        d = self.drag
        pad = self.cob.pcb_pads()[d["idx"]]
        wx, wy = self.view.to_world(e.x, e.y)
        if d["kind"] == "move":
            x, y = self._snap(wx + d["dx"], wy + d["dy"])
            if pad.get("at") != [round(x, 4), round(y, 4)]:
                pad["at"] = [round(x, 4), round(y, 4)]
                self.dirty = True
                self.redraw()
            self.status.config(text=f"{pad.get('id')} at {x:.3f}, {y:.3f} mm")
            return
        # resize: the grabbed edge follows the mouse, scale about the pad origin
        lx, ly = self._to_local(pad, wx, wy)
        x0, y0, x1, y1 = d["box"]
        ex, ey = d["edge"]
        sx, sy = d["scale0"]
        if ex:
            edge = x1 if ex > 0 else x0
            if abs(edge) > 1e-9 and lx * edge > 0:
                sx = max(0.05, round(sx * lx / edge, 3))
        if ey:
            edge = y1 if ey > 0 else y0
            if abs(edge) > 1e-9 and ly * edge > 0:
                sy = max(0.05, round(sy * ly / edge, 3))
        if pad.get("scale") != {"x": sx, "y": sy}:
            pad["scale"] = {"x": sx, "y": sy}
            self.dirty = True
            self.redraw()
        self.status.config(text=f"{pad.get('id')} scale {sx:g} × {sy:g}")

    def _drag_end(self, e):
        if not self.drag:
            return
        pad = self.cob.pcb_pads()[self.drag["idx"]]
        self.drag = None
        self.canvas.config(cursor="crosshair")
        sc = pad.get("scale", {})
        self.status.config(text=f"{pad.get('id')} at {pad['at'][0]:.3f}, {pad['at'][1]:.3f} mm, "
                                f"scale {sc.get('x', 1):g} × {sc.get('y', 1):g}, rotation {pad.get('rotation', 0)}°")

    def _idle_cursor(self, e):
        """Show a resize cursor when hovering the selected pad's edge."""
        cur = "crosshair"
        if self.selected is not None and self.cob and self.selected < len(self.cob.pcb_pads()):
            pad = self.cob.pcb_pads()[self.selected]
            hit = self._edge_hit(pad, *self.view.to_world(e.x, e.y))
            if hit:
                cur = self._edge_cursor(pad, hit)
        if self.canvas.cget("cursor") != cur:
            self.canvas.config(cursor=cur)

    # ------------------------------------------------------------- wires
    def start_add_wire(self):
        if not self.cob:
            return
        if not self.cob.pcb_pads():
            messagebox.showinfo("cobedit", "No PCB pads yet. Place PCB pads first, then connect them with wires.")
            return
        self.sec_wire.open()
        self._clear_preview()
        self.tool = "wire"
        self.wire_from = None
        self.lbl_hint.config(text="")
        self.lbl_whint.config(text="Click a die pad, then a PCB pad. Repeat for more wires, Esc ends.")
        self.status.config(text="wire: pick die pad")
        self.redraw()

    def _hit_die_pad(self, wx: float, wy: float) -> dict | None:
        tol = 4 / self.view.k  # 4 px slack so small pads are easy to hit
        best, best_d = None, None
        for dp in self.cob.die_pads():
            cx, cy = dp["center"]
            sz = dp.get("size", [0.08, 0.08])
            if abs(wx - cx) <= sz[0] / 2 + tol and abs(wy - cy) <= sz[1] / 2 + tol:
                d = (wx - cx) ** 2 + (wy - cy) ** 2
                if best is None or d < best_d:
                    best, best_d = dp, d
        return best

    def _hit_pcb_pad(self, wx: float, wy: float) -> dict | None:
        tol = 6 / self.view.k
        for pad in self.cob.pcb_pads():
            try:
                bt = self.cob.bond_target(pad)
                polys = self.cob.placed_polygons(pad).get("copper", [])
            except Exception:  # noqa: BLE001
                continue
            if (wx - bt[0]) ** 2 + (wy - bt[1]) ** 2 <= tol * tol:
                return pad
            if any(_point_in_poly(wx, wy, poly) for poly in polys):
                return pad
        return None

    def _wire_click(self, e):
        wx, wy = self.view.to_world(e.x, e.y)
        dp = self._hit_die_pad(wx, wy)
        if dp:  # first click, or re-pick the start
            self.wire_from = dp["id"]
            self.status.config(text=f"wire: from {dp['id']} {dp.get('name', '')}, pick PCB pad")
            self.redraw()
            return
        if not self.wire_from:
            self.status.config(text="wire: no die pad here")
            return
        pp = self._hit_pcb_pad(wx, wy)
        if not pp:
            self.status.config(text="wire: no PCB pad here")
            return
        self._add_wire(self.wire_from, pp["id"])
        self.wire_from = None
        self._clear_preview()
        self.status.config(text="wire: pick die pad")
        self.redraw()

    def _add_wire(self, die_pad: str, pcb_pad: str):
        items = self.cob.wires()
        used = {w.get("id") for w in items}
        n = len(items) + 1
        while f"W{n}" in used:
            n += 1
        try:
            dia = float(self.v_wdia.get())
            dia = int(dia) if dia == int(dia) else dia
        except ValueError:
            dia = "unspecified"
        items.append({
            "id": f"W{n}",
            "from": {"die_pad": die_pad},
            "to": {"pcb_pad": pcb_pad},
            "type": self.v_wtype.get().strip() or "unspecified",
            "material": self.v_wmat.get().strip() or "unspecified",
            "diameter_um": dia,
            "loop": "unspecified",
            "bond": "unspecified",
            "mechanical": "unspecified",
        })
        self.dirty = True
        self._fill_wire_list()
        self.lbl_whint.config(text=f"W{n}: {die_pad} → {pcb_pad}. Next die pad, or Esc.")

    def _draw_wire_preview(self, px, py):
        self._clear_preview()
        wx, wy = self.view.to_world(px, py)
        if self.wire_from:
            dp = self.cob.die_pad_by_id(self.wire_from)
            if dp:
                end = self._hit_pcb_pad(wx, wy)
                try:
                    ex, ey = self.cob.bond_target(end) if end else (wx, wy)
                except Exception:  # noqa: BLE001
                    ex, ey = wx, wy
                self.preview_items.append(self.canvas.create_line(
                    *self.view.to_px(*dp["center"]), *self.view.to_px(ex, ey),
                    fill=COL["preview"], width=2, dash=None if end else (4, 3)))
        else:
            hit = self._hit_die_pad(wx, wy)
            if hit:
                sz = hit.get("size", [0.08, 0.08])
                self.preview_items.append(self.canvas.create_polygon(
                    self.view.flat(rect(hit["center"][0], hit["center"][1], sz[0] * 1.6, sz[1] * 1.6)),
                    fill="", outline=COL["preview"], width=2))

    def _fill_wire_list(self):
        self.wire_list.delete(0, "end")
        for w in self.cob.wires():
            self.wire_list.insert("end", f"{w.get('id')}  {w.get('from', {}).get('die_pad')} → {w.get('to', {}).get('pcb_pad')}")

    def _on_select_wire(self, e):
        sel = self.wire_list.curselection()
        self.selected_wire = sel[0] if sel else None
        self.redraw()

    def delete_wire(self):
        if self.selected_wire is None or not self.cob:
            return
        del self.cob.wires()[self.selected_wire]
        self.selected_wire = None
        self.dirty = True
        self._fill_wire_list()
        self.redraw()

    # ------------------------------------------------------------- navigation
    def _pan_start(self, e):
        self.pan_start = (e.x, e.y, self.view.ox, self.view.oy)

    def _pan_move(self, e):
        if self.pan_start:
            x0, y0, ox, oy = self.pan_start
            self.view.ox, self.view.oy = ox + e.x - x0, oy + e.y - y0
            self.redraw()

    def _on_wheel(self, e):
        self._zoom(e.x, e.y, 1.2 if e.delta > 0 else 1 / 1.2)

    def _zoom(self, px, py, f):
        wx, wy = self.view.to_world(px, py)
        self.view.k *= f
        self.view.ox = px - wx * self.view.k
        self.view.oy = py + wy * self.view.k
        self.redraw()

    # ------------------------------------------------------------- pad tool
    def start_add_pad(self):
        if not self.cob:
            return
        if not self.shape_box["values"]:
            messagebox.showinfo("cobedit", "No shapes available. Put <uuid>.shape.cob.json files next to the file or in shapes/, or start cobedit with --shapes DIR.")
            return
        self.sec_pad.open()
        self.tool = "place"
        n = len(self.cob.pcb_pads()) + 1
        if not self.v_number.get():
            self.v_number.set(str(n))
        self.lbl_hint.config(text="Move over the canvas and click to place. R rotates, Esc cancels.")
        self.status.config(text="placing pad")

    def cancel_tool(self):
        self.tool = None
        self.wire_from = None
        self._clear_preview()
        self.lbl_hint.config(text="")
        self.lbl_whint.config(text="")
        self.status.config(text="")
        self.redraw()

    def _rotate_preview(self):
        try:
            r = (float(self.v_rot.get()) + 90) % 360
        except ValueError:
            r = 0
        self.v_rot.set(str(int(r)))
        self._refresh_preview()

    def _snap(self, x, y):
        try:
            g = float(self.v_grid.get())
        except ValueError:
            g = 0
        if g <= 0:
            return x, y
        return round(x / g) * g, round(y / g) * g

    def _pad_from_form(self, x, y) -> dict | None:
        ref = self._selected_shape_ref()
        if not ref:
            return None
        try:
            rot = float(self.v_rot.get())
            sx, sy = float(self.v_sx.get()), float(self.v_sy.get())
        except ValueError:
            return None
        return {"shape": ref, "at": [round(x, 4), round(y, 4)], "rotation": rot, "scale": {"x": sx, "y": sy}}

    def _clear_preview(self):
        for i in self.preview_items:
            self.canvas.delete(i)
        self.preview_items = []

    def _refresh_preview(self):
        if self.tool == "place" and hasattr(self, "_last_mouse"):
            self._draw_preview(*self._last_mouse)

    def _draw_preview(self, px, py):
        self._clear_preview()
        x, y = self._snap(*self.view.to_world(px, py))
        pad = self._pad_from_form(x, y)
        if not pad:
            return
        try:
            polys = self.cob.placed_polygons(pad)
        except Exception as e:  # noqa: BLE001
            self.status.config(text=str(e))
            return
        for poly in polys.get("copper", []):
            self.preview_items.append(
                self.canvas.create_polygon(self.view.flat(poly), fill="", outline=COL["preview"], width=2, dash=(3, 2)))
        self.status.config(text=f"at {x:.3f}, {y:.3f} mm")

    def _on_motion(self, e):
        self._last_mouse = (e.x, e.y)
        if self.tool == "place":
            self._draw_preview(e.x, e.y)
        elif self.tool == "wire":
            self._draw_wire_preview(e.x, e.y)
        else:
            if not self.drag:
                self._idle_cursor(e)
            wx, wy = self.view.to_world(e.x, e.y)
            self.status.config(text=f"{wx:.3f}, {wy:.3f} mm")

    def _on_click(self, e):
        if self.tool == "wire" and self.cob:
            return self._wire_click(e)
        if self.tool is None and self.cob:
            return self._drag_start(e)
        if self.tool != "place" or not self.cob:
            return
        x, y = self._snap(*self.view.to_world(e.x, e.y))
        pad = self._pad_from_form(x, y)
        if not pad:
            return
        ref = pad["shape"]
        shapes = self.cob.data["pcb"]["shapes"]
        if UUID_RE.match(ref) and ref not in shapes.values():
            alias = self.cob.resolve(ref).name.upper().replace(" ", "_")
            base, n = alias, 2
            while alias in shapes:
                alias, n = f"{base}_{n}", n + 1
            shapes[alias] = ref
            self.cob.shapes[alias] = self.cob.resolve(ref)  # make the alias resolvable right away
            pad["shape"] = alias
            self._fill_shape_box()
            self.shape_var.set(f"{alias}  (alias)")
        elif UUID_RE.match(ref):
            pad["shape"] = next(a for a, u in shapes.items() if u == ref)
        pads = self.cob.data["pcb"]["pads"]
        pid = f"P{len(pads) + 1}"
        while any(p["id"] == pid for p in pads):
            pid = pid + "_"
        number = self.v_number.get() or str(len(pads) + 1)
        pads.append({"id": pid, "number": number, "name": self.v_name.get() or "unspecified",
                     **pad, "finish": "unspecified", "paste": "none", "role": "bond_finger"})
        self.dirty = True
        try:
            self.v_number.set(str(int(number) + 1))
        except ValueError:
            pass
        self._fill_pad_list()
        self.redraw()
        self._draw_preview(e.x, e.y)

    # ------------------------------------------------------------- pad list
    def _fill_pad_list(self):
        self.pad_list.delete(0, "end")
        for p in self.cob.pcb_pads():
            self.pad_list.insert("end", f"{p['id']}  #{p.get('number')}  {p.get('name')}  [{p.get('shape')}]")

    def _on_select_pad(self, e):
        sel = self.pad_list.curselection()
        self.selected = sel[0] if sel else None
        self.redraw()

    def delete_pad(self):
        if self.selected is None or not self.cob:
            return
        del self.cob.data["pcb"]["pads"][self.selected]
        self.selected = None
        self.dirty = True
        self._fill_pad_list()
        self.redraw()

    def edit_pad(self):
        if self.selected is None or not self.cob:
            return
        pad = self.cob.data["pcb"]["pads"][self.selected]
        shapes = list(self.cob.data["pcb"]["shapes"].keys()) if isinstance(self.cob.data["pcb"].get("shapes"), dict) else []
        other_ids = {p["id"] for i, p in enumerate(self.cob.pcb_pads()) if i != self.selected}
        dlg = PadDialog(self.root, pad, shapes, other_ids)
        self.root.wait_window(dlg.top)
        if dlg.result is None:
            self.status.config(text=f"pad {pad.get('id')}: edit cancelled")
            return
        old_id = pad["id"]
        pad.clear()
        pad.update(dlg.result)
        self.status.config(text=f"pad {pad['id']}: updated")
        if pad["id"] != old_id:  # keep wires pointing at this pad
            for w in self.cob.wires():
                to = w.get("to")
                if isinstance(to, dict) and to.get("pcb_pad") == old_id:
                    to["pcb_pad"] = pad["id"]
        self.dirty = True
        self._fill_pad_list()
        self.pad_list.selection_set(self.selected)
        self.redraw()


PAD_FIELDS = ("id", "number", "name", "shape", "at", "rotation", "scale", "finish", "paste", "role")
ROLES = ("bond_finger", "die_attach", "probe", "test_point", "unspecified")
FINISHES = ("ENIG", "ENEPIG", "soft_gold", "HASL", "immersion_silver", "unspecified")
PASTES = ("none", "full", "windowed", "unspecified")


class PadDialog:
    """Modal editor for one PCB pad. Known keys get a field each, everything
    else (limits, bond_target, ...) is edited as JSON so no data is lost."""

    def __init__(self, parent: tk.Tk, pad: dict, shapes: list[str], other_ids: set[str]):
        self.result: dict | None = None
        self.other_ids = other_ids
        t = self.top = tk.Toplevel(parent)
        t.title(f"PCB pad {pad.get('id', '')}")
        t.transient(parent)
        t.resizable(False, True)
        body = ttk.Frame(t, padding=10)
        body.pack(fill="both", expand=True)

        self.v = {k: tk.StringVar(value=str(pad.get(k, ""))) for k in ("id", "number", "name", "finish", "paste", "role")}
        at = pad.get("at", [0, 0])
        sc = pad.get("scale", {}) if isinstance(pad.get("scale"), dict) else {}
        self.v.update({
            "x": tk.StringVar(value=str(at[0])), "y": tk.StringVar(value=str(at[1])),
            "rotation": tk.StringVar(value=str(pad.get("rotation", 0))),
            "sx": tk.StringVar(value=str(sc.get("x", 1.0))), "sy": tk.StringVar(value=str(sc.get("y", 1.0))),
            "shape": tk.StringVar(value=str(pad.get("shape", ""))),
        })

        r = 0
        def row(label, widget_fn):
            nonlocal r
            ttk.Label(body, text=label).grid(row=r, column=0, sticky="w", pady=2, padx=(0, 8))
            w = widget_fn()
            w.grid(row=r, column=1, columnspan=3, sticky="ew", pady=2)
            r += 1
            return w
        def entry(var, width=24):
            return lambda: ttk.Entry(body, textvariable=var, width=width)
        def combo(var, values):
            return lambda: ttk.Combobox(body, textvariable=var, values=values, width=22)

        e_id = row("ID", entry(self.v["id"]))
        row("Number", entry(self.v["number"]))
        row("Name", entry(self.v["name"]))
        row("Shape alias", combo(self.v["shape"], shapes))
        ttk.Label(body, text="At x / y [mm]").grid(row=r, column=0, sticky="w", pady=2)
        ttk.Entry(body, textvariable=self.v["x"], width=10).grid(row=r, column=1, sticky="ew", pady=2)
        ttk.Entry(body, textvariable=self.v["y"], width=10).grid(row=r, column=2, sticky="ew", pady=2, padx=(4, 0))
        r += 1
        row("Rotation [deg]", entry(self.v["rotation"]))
        ttk.Label(body, text="Scale x / y").grid(row=r, column=0, sticky="w", pady=2)
        ttk.Entry(body, textvariable=self.v["sx"], width=10).grid(row=r, column=1, sticky="ew", pady=2)
        ttk.Entry(body, textvariable=self.v["sy"], width=10).grid(row=r, column=2, sticky="ew", pady=2, padx=(4, 0))
        r += 1
        row("Finish", combo(self.v["finish"], FINISHES))
        row("Paste", combo(self.v["paste"], PASTES))
        row("Role", combo(self.v["role"], ROLES))

        extra = {k: v for k, v in pad.items() if k not in PAD_FIELDS}
        ttk.Label(body, text="Other keys (JSON)").grid(row=r, column=0, columnspan=4, sticky="w", pady=(8, 2))
        r += 1
        self.extra = tk.Text(body, width=40, height=6, font=("monospace", 9))
        self.extra.grid(row=r, column=0, columnspan=4, sticky="nsew")
        self.extra.insert("1.0", json.dumps(extra, indent=1) if extra else "{}")
        body.rowconfigure(r, weight=1)
        r += 1
        self.lbl_err = ttk.Label(body, text="", foreground="#d02020", wraplength=320)
        self.lbl_err.grid(row=r, column=0, columnspan=4, sticky="w", pady=(4, 0))
        r += 1
        btns = ttk.Frame(body)
        btns.grid(row=r, column=0, columnspan=4, sticky="e", pady=(8, 0))
        ttk.Button(btns, text="Cancel", command=self.cancel).pack(side="right")
        ttk.Button(btns, text="OK", command=self.ok).pack(side="right", padx=(0, 6))
        body.columnconfigure(1, weight=1)
        body.columnconfigure(2, weight=1)

        t.bind("<Escape>", lambda e: self.cancel())
        t.bind("<Control-Return>", lambda e: self.ok())
        t.bind("<Return>", lambda e: None if isinstance(e.widget, tk.Text) else self.ok())
        t.protocol("WM_DELETE_WINDOW", self.cancel)
        e_id.focus_set()
        # the grab needs a mapped window; on some window managers the
        # Toplevel is not viewable yet when __init__ runs
        try:
            t.wait_visibility()
            t.grab_set()
        except tk.TclError:
            pass  # no modal grab, the dialog still works

    def _num(self, key: str, label: str) -> float:
        try:
            return float(self.v[key].get().strip())
        except ValueError:
            raise ValueError(f"{label} must be a number") from None

    def ok(self):
        try:
            pid = self.v["id"].get().strip()
            if not pid:
                raise ValueError("ID must not be empty")
            if pid in self.other_ids:
                raise ValueError(f"ID {pid!r} is already used by another pad")
            if not self.v["shape"].get().strip():
                raise ValueError("Shape alias must not be empty")
            extra_text = self.extra.get("1.0", "end").strip() or "{}"
            extra = json.loads(extra_text)
            if not isinstance(extra, dict):
                raise ValueError("Other keys must be a JSON object")
            clash = [k for k in extra if k in PAD_FIELDS]
            if clash:
                raise ValueError(f"{clash} belong in the fields above, not in Other keys")
            rot = self._num("rotation", "Rotation")
            res = {
                "id": pid,
                "number": self.v["number"].get().strip() or "unspecified",
                "name": self.v["name"].get().strip() or "unspecified",
                "shape": self.v["shape"].get().strip(),
                "scale": {"x": self._num("sx", "Scale x"), "y": self._num("sy", "Scale y")},
                "at": [round(self._num("x", "At x"), 4), round(self._num("y", "At y"), 4)],
                "rotation": int(rot) if rot == int(rot) else rot,
                "finish": self.v["finish"].get().strip() or "unspecified",
                "paste": self.v["paste"].get().strip() or "none",
                "role": self.v["role"].get().strip() or "unspecified",
            }
            res.update(extra)
        except Exception as e:  # noqa: BLE001 - show anything, the dialog must not swallow it
            self.lbl_err.config(text=f"{type(e).__name__}: {e}")
            return
        self.result = res
        self.top.destroy()

    def cancel(self):
        self.result = None
        self.top.destroy()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="cobedit", description="Tkinter editor for .cob.json files.")
    ap.add_argument("--file", type=Path, help="file to open")
    ap.add_argument("--shapes", action="append", type=Path, default=[],
                    help="extra shape catalog directory, repeatable (default: examples/shapes of this repository)")
    args = ap.parse_args(argv)
    shape_dirs = list(args.shapes) or ([REPO_SHAPES] if REPO_SHAPES.is_dir() else [])
    root = tk.Tk()
    root.geometry("1200x800")
    App(root, args.file, shape_dirs)
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
