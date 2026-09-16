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
COL = {
    "bg": "#fafafa", "die": "#3a3a3a", "die_pad": "#e0c060", "copper": "#c8802a",
    "mask": "#7fb59a", "wire": "#2060d0", "misc": "#c02040", "preview": "#2060d0",
    "select": "#d02020", "origin": "#000",
}


def rect(cx, cy, w, h):
    return [(cx - w / 2, cy - h / 2), (cx + w / 2, cy - h / 2), (cx + w / 2, cy + h / 2), (cx - w / 2, cy + h / 2)]


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
    def __init__(self, root: tk.Tk, path: Path | None):
        self.root = root
        self.root.title("cobedit")
        self.cob: Cob | None = None
        self.path: Path | None = None
        self.view = View()
        self.tool = None          # None | "place"
        self.preview_items: list[int] = []
        self.pan_start = None
        self.selected: int | None = None
        self.dirty = False

        self._build_ui()
        self._bind()
        if path:
            self.load(path)

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        self.canvas = tk.Canvas(self.root, bg=COL["bg"], highlightthickness=0, cursor="crosshair")
        self.canvas.grid(row=0, column=0, sticky="nsew")

        tb = ttk.Frame(self.root, padding=8, width=300)
        tb.grid(row=0, column=1, sticky="ns")
        tb.grid_propagate(False)
        self.tb = tb

        f = ttk.LabelFrame(tb, text="File", padding=6)
        f.pack(fill="x", pady=(0, 8))
        ttk.Button(f, text="Open...", command=self.open_dialog).pack(fill="x")
        ttk.Button(f, text="Save", command=self.save).pack(fill="x", pady=2)
        ttk.Button(f, text="Save as...", command=self.save_as).pack(fill="x")
        ttk.Button(f, text="Export KiCad...", command=self.export_kicad).pack(fill="x", pady=(6, 0))
        self.lbl_file = ttk.Label(f, text="no file", wraplength=260, foreground="#666")
        self.lbl_file.pack(fill="x", pady=(4, 0))

        p = ttk.LabelFrame(tb, text="PCB pad", padding=6)
        p.pack(fill="x", pady=(0, 8))
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

        lst = ttk.LabelFrame(tb, text="PCB pads", padding=6)
        lst.pack(fill="both", expand=True)
        self.pad_list = tk.Listbox(lst, exportselection=False)
        self.pad_list.pack(fill="both", expand=True)
        self.pad_list.bind("<<ListboxSelect>>", self._on_select_pad)
        ttk.Button(lst, text="Delete pad", command=self.delete_pad).pack(fill="x", pady=(4, 0))

        self.status = ttk.Label(tb, text="", foreground="#666")
        self.status.pack(fill="x", pady=(6, 0))

    def _bind(self):
        c = self.canvas
        c.bind("<Configure>", lambda e: self.redraw())
        c.bind("<Motion>", self._on_motion)
        c.bind("<Button-1>", self._on_click)
        c.bind("<ButtonPress-2>", self._pan_start)
        c.bind("<ButtonPress-3>", self._pan_start)
        c.bind("<B2-Motion>", self._pan_move)
        c.bind("<B3-Motion>", self._pan_move)
        c.bind("<MouseWheel>", self._on_wheel)
        c.bind("<Button-4>", lambda e: self._zoom(e.x, e.y, 1.2))
        c.bind("<Button-5>", lambda e: self._zoom(e.x, e.y, 1 / 1.2))
        self.root.bind("<Escape>", lambda e: self.cancel_tool())
        self.root.bind("<Key-r>", lambda e: self._rotate_preview())
        self.root.bind("<Key-f>", lambda e: self.fit())
        self.root.bind("<Control-s>", lambda e: self.save())
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ------------------------------------------------------------- file ops
    def open_dialog(self):
        p = filedialog.askopenfilename(filetypes=[("cob.json", "*.cob.json"), ("JSON", "*.json")])
        if p:
            self.load(Path(p))

    def load(self, path: Path):
        try:
            self.cob = Cob.load(path)
        except Exception as e:  # noqa: BLE001 - show anything to the user
            messagebox.showerror("cobedit", f"Cannot load {path}:\n{e}")
            return
        self.path = path
        self.dirty = False
        self.lbl_file.config(text=path.name)
        self._ensure_pcb_lists()
        self._fill_shape_box()
        self._fill_pad_list()
        self.fit()

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

    def redraw(self):
        c = self.canvas
        c.delete("all")
        if not self.cob:
            return
        v = self.view
        # misc
        for m in self.cob.misc():
            try:
                polys = self.cob.placed_polygons(m)
            except Exception:  # noqa: BLE001
                continue
            for plist in polys.values():
                for poly in plist:
                    c.create_polygon(v.flat(poly), fill="", outline=COL["misc"], dash=(4, 2), tags="misc")
        # pcb pads
        for i, pad in enumerate(self.cob.pcb_pads()):
            try:
                polys = self.cob.placed_polygons(pad)
            except Exception as e:  # noqa: BLE001
                self.status.config(text=f"pad {pad.get('id')}: {e}")
                continue
            sel = i == self.selected
            for poly in polys.get("mask", []):
                c.create_polygon(v.flat(poly), fill=COL["mask"], outline="", stipple="gray50")
            for poly in polys.get("copper", []):
                c.create_polygon(v.flat(poly), fill=COL["copper"], outline=COL["select"] if sel else COL["copper"],
                                 width=3 if sel else 1)
            bt = self.cob.bond_target(pad)
            px, py = v.to_px(*bt)
            c.create_oval(px - 3, py - 3, px + 3, py + 3, fill="white", outline="black")
            c.create_text(px, py - 10, text=f"{pad.get('number')} {pad.get('name', '')}", font=("monospace", 8))
        # die
        die = self.cob.die
        w, h = nominal(die["size"][0]), nominal(die["size"][1])
        ox, oy = die.get("offset", [0, 0])
        c.create_polygon(v.flat(rect(ox, oy, w, h)), fill=COL["die"], outline="black")
        notch = die.get("notch")
        if isinstance(notch, dict):
            ns = notch.get("size", [0.1, 0.1])
            sx = -1 if "left" in notch.get("side", "") else 1
            sy = 1 if "top" in notch.get("side", "") else -1
            c.create_polygon(v.flat(rect(ox + sx * (w / 2 - ns[0] / 2), oy + sy * (h / 2 - ns[1] / 2), ns[0], ns[1])),
                             fill=COL["bg"], outline="")
        for dp in self.cob.die_pads():
            cx, cy = dp["center"]
            sz = dp.get("size", [0.08, 0.08])
            c.create_polygon(v.flat(rect(cx, cy, sz[0], sz[1])), fill=COL["die_pad"], outline="#806000")
            if v.k > 400:
                c.create_text(*v.to_px(cx, cy), text=dp.get("name", ""), font=("monospace", 7), fill="#f0f0f0",
                              anchor="w" if dp.get("side") == "left" else "e" if dp.get("side") == "right" else "center")
        # wires
        for wire in self.cob.wires():
            dp = self.cob.die_pad_by_id(wire.get("from", {}).get("die_pad", ""))
            pp = self.cob.pcb_pad_by_id(wire.get("to", {}).get("pcb_pad", ""))
            if dp and pp:
                try:
                    bt = self.cob.bond_target(pp)
                except Exception:  # noqa: BLE001
                    continue
                c.create_line(*v.to_px(*dp["center"]), *v.to_px(*bt), fill=COL["wire"], width=2)
        # origin
        px, py = v.to_px(0, 0)
        c.create_line(px - 8, py, px + 8, py, fill=COL["origin"])
        c.create_line(px, py - 8, px, py + 8, fill=COL["origin"])
        self.preview_items = []

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
            messagebox.showinfo("cobedit", "No shapes available. Put <uuid>.shape.cob.json files next to the file or in shapes/.")
            return
        self.tool = "place"
        n = len(self.cob.pcb_pads()) + 1
        if not self.v_number.get():
            self.v_number.set(str(n))
        self.lbl_hint.config(text="Move over the canvas and click to place. R rotates, Esc cancels.")
        self.status.config(text="placing pad")

    def cancel_tool(self):
        self.tool = None
        self._clear_preview()
        self.lbl_hint.config(text="")
        self.status.config(text="")

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
        else:
            wx, wy = self.view.to_world(e.x, e.y)
            self.status.config(text=f"{wx:.3f}, {wy:.3f} mm")

    def _on_click(self, e):
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


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="cobedit", description="Tkinter editor for .cob.json files.")
    ap.add_argument("--file", type=Path, help="file to open")
    args = ap.parse_args(argv)
    root = tk.Tk()
    root.geometry("1200x800")
    App(root, args.file)
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
