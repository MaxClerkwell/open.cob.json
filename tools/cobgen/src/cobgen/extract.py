"""Extract die geometry and pads from a layout."""
from __future__ import annotations

import math
import uuid
from dataclasses import dataclass
from pathlib import Path

import gdstk

from .pdk import Pdk


@dataclass
class Pad:
    center_um: tuple[float, float]
    size_um: tuple[float, float]
    name: str | None
    cell: str | None


def read_layout(path: Path) -> gdstk.Library:
    if path.suffix.lower() in (".oas", ".oasis"):
        return gdstk.read_oas(str(path))
    return gdstk.read_gds(str(path))


def pick_top(lib: gdstk.Library, name: str | None) -> gdstk.Cell:
    tops = lib.top_level()
    if name:
        for c in lib.cells:
            if c.name == name:
                return c
        raise KeyError(f"no cell named {name!r}")
    if len(tops) != 1:
        raise ValueError(f"layout has {len(tops)} top cells, pick one with --top: {[c.name for c in tops]}")
    return tops[0]


def extract(lib: gdstk.Library, top: gdstk.Cell, pdk: Pdk, min_pad_um: float) -> tuple[tuple[float, float, float, float], list[Pad]]:
    """Return (bbox_um as x0,y0,x1,y1) and the pads in µm, absolute layout coordinates."""
    scale = lib.unit / 1e-6  # library units -> µm
    (x0, y0), (x1, y1) = top.bounding_box()
    bbox = (x0 * scale, y0 * scale, x1 * scale, y1 * scale)

    flat = top.copy("__cobgen_flat").flatten()
    openings = [p for p in flat.polygons if (p.layer, p.datatype) == pdk.pad_layer]

    # pad names are top-level labels. Sub-cells carry thousands of internal
    # pin labels on the same layer, so they are deliberately not searched.
    labels = [(l.text, (l.origin[0] * scale, l.origin[1] * scale))
              for l in top.labels if (l.layer, l.texttype) == pdk.label_layer]

    # references whose bounding box contains an opening tell us the pad cell.
    # Only cells that actually contain a pad opening qualify, otherwise fill
    # cells spanning the whole die would win. Smallest bounding box wins.
    def has_pad_layer(cell: gdstk.Cell) -> bool:
        if any((p.layer, p.datatype) == pdk.pad_layer for p in cell.polygons):
            return True
        return any(has_pad_layer(d) for d in cell.dependencies(False) if isinstance(d, gdstk.Cell))

    pad_cells = {c.name for c in lib.cells if has_pad_layer(c)}
    refs = []
    for r in top.references:
        bb = r.bounding_box()
        cname = r.cell.name if isinstance(r.cell, gdstk.Cell) else str(r.cell)
        if bb is None or cname not in pad_cells:
            continue
        area = (bb[1][0] - bb[0][0]) * (bb[1][1] - bb[0][1])
        refs.append((area, cname, (bb[0][0] * scale, bb[0][1] * scale, bb[1][0] * scale, bb[1][1] * scale)))
    refs.sort()

    pads: list[Pad] = []
    for poly in openings:
        (bx0, by0), (bx1, by1) = poly.bounding_box()
        w, h = (bx1 - bx0) * scale, (by1 - by0) * scale
        if w < min_pad_um or h < min_pad_um:
            continue  # seal ring strips, corner marks
        if max(w, h) / min(w, h) > 4:
            continue  # long strips are not bond pads
        cx, cy = (bx0 + bx1) / 2 * scale, (by0 + by1) / 2 * scale
        inside = [t for t, (lx, ly) in labels if poly.contain((lx / scale, ly / scale))]
        name = inside[0] if len(inside) == 1 else None
        cell = next((c for _, c, (rx0, ry0, rx1, ry1) in refs if rx0 <= cx <= rx1 and ry0 <= cy <= ry1), None)
        pads.append(Pad((cx, cy), (w, h), name, cell))
    return bbox, pads


def side_of(cx: float, cy: float, w: float, h: float) -> str:
    """Nearest die edge for a pad at (cx, cy) relative to die center."""
    d = {"left": cx + w / 2, "right": w / 2 - cx, "bottom": cy + h / 2, "top": h / 2 - cy}
    return min(d, key=d.get)


def build_cob(path: Path, top_name: str, bbox, pads: list[Pad], pdk: Pdk, chip_name: str) -> dict:
    x0, y0, x1, y1 = bbox
    w_um, h_um = x1 - x0, y1 - y0
    ccx, ccy = (x0 + x1) / 2, (y0 + y1) / 2
    um = 0.001  # µm -> mm

    # order counter-clockwise starting at the bottom-left corner
    def angle(p: Pad) -> float:
        a = math.atan2(p.center_um[1] - ccy, p.center_um[0] - ccx)
        return (a + math.pi * 5 / 4) % (2 * math.pi)

    die_pads = []
    for i, p in enumerate(sorted(pads, key=angle), start=1):
        cx, cy = (p.center_um[0] - ccx) * um, (p.center_um[1] - ccy) * um
        entry = {
            "id": f"D{i}",
            "name": p.name if p.name else "unspecified",
            "center": [round(cx, 4), round(cy, 4)],
            "size": [round(p.size_um[0] * um, 4), round(p.size_um[1] * um, 4)],
            "shape": "rect",
            "metal": pdk.metal,
            "opening": [round(p.size_um[0] * um, 4), round(p.size_um[1] * um, 4)],
            "side": side_of(cx, cy, w_um * um, h_um * um),
            "electrical": pdk.electrical(p.cell) or "unspecified",
            "bond": "unspecified",
            "source": {"cell": p.cell or "unspecified", "labeled": p.name is not None},
        }
        die_pads.append(entry)

    return {
        "schema": "cob.v1",
        "uuid": str(uuid.uuid4()),
        "meta": {
            "name": chip_name,
            "revision": "unspecified",
            "description": f"Generated by cobgen from {path.name}, top cell {top_name}, PDK {pdk.name}",
            "gds": path.name,
            "pdk": pdk.name,
        },
        "units": {"length": "mm", "angle": "deg", "origin": "die_center", "axis": {"x": "right", "y": "up"}},
        "tolerances": "unspecified",
        "die": {
            "size": [round(w_um * um, 4), round(h_um * um, 4)],
            "thickness": "unspecified",
            "offset": [0, 0],
            "rotation": 0,
            "notch": "unspecified",
            "pads": die_pads,
        },
        "pcb": {"shapes": "none", "pads": "unspecified", "misc": "unspecified"},
        "wires": {"items": "unspecified", "pairs": "unspecified", "electrical_specifications": "unspecified"},
        "assembly": "unspecified",
    }
