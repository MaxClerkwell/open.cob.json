"""SVG rendering of a Cob."""
from __future__ import annotations

from .model import Cob, nominal

COLORS = {
    "copper": ("#c8802a", 0.85),
    "mask": ("#2a7a4a", 0.25),
    "paste": ("#8a8a8a", 0.5),
    "cutout": ("#000000", 0.0),
    "keepout": ("#c02040", 0.0),
    "silk": ("#e8e8e8", 0.0),
    "fab": ("#7070c0", 0.0),
    "courtyard": ("#c040c0", 0.0),
}
MISC_STYLE = {
    "keepout": ("#c02040", "4 2"),
    "copper_required": ("#c8802a", "6 3"),
    "mask_opening": ("#2a7a4a", "3 3"),
    "cutout": ("#000000", "8 3"),
    "fiducial": ("#4060c0", ""),
    "silk": ("#e8e8e8", ""),
    "fab": ("#7070c0", "2 2"),
    "courtyard": ("#c040c0", "2 2"),
}


class Svg:
    def __init__(self, px_per_unit: float):
        self.k = px_per_unit
        self.parts: list[str] = []
        self.minx = self.miny = float("inf")
        self.maxx = self.maxy = float("-inf")

    def _pt(self, x: float, y: float) -> tuple[float, float]:
        self.minx, self.maxx = min(self.minx, x), max(self.maxx, x)
        self.miny, self.maxy = min(self.miny, y), max(self.maxy, y)
        return x * self.k, -y * self.k  # Y up -> SVG Y down

    def polygon(self, pts, fill, opacity, stroke, width=1.0, dash="", title=""):
        s = " ".join(f"{px:.2f},{py:.2f}" for px, py in (self._pt(x, y) for x, y in pts))
        t = f"<title>{esc(title)}</title>" if title else ""
        d = f' stroke-dasharray="{dash}"' if dash else ""
        self.parts.append(
            f'<polygon points="{s}" fill="{fill}" fill-opacity="{opacity}" stroke="{stroke}" '
            f'stroke-width="{width}"{d}>{t}</polygon>'
        )

    def line(self, a, b, stroke, width=1.5, title=""):
        (x1, y1), (x2, y2) = self._pt(*a), self._pt(*b)
        t = f"<title>{esc(title)}</title>" if title else ""
        self.parts.append(
            f'<line x1="{x1:.2f}" y1="{y1:.2f}" x2="{x2:.2f}" y2="{y2:.2f}" stroke="{stroke}" '
            f'stroke-width="{width}" stroke-linecap="round">{t}</line>'
        )

    def circle(self, c, r, stroke, fill="none", width=1.0):
        x, y = self._pt(*c)
        self.parts.append(
            f'<circle cx="{x:.2f}" cy="{y:.2f}" r="{r * self.k:.2f}" fill="{fill}" stroke="{stroke}" stroke-width="{width}"/>'
        )

    def text(self, p, s, size_px=9, fill="#222", anchor="middle", rotate=0.0):
        x, y = self._pt(*p)
        tr = f' transform="rotate({-rotate:.1f} {x:.2f} {y:.2f})"' if rotate else ""
        self.parts.append(
            f'<text x="{x:.2f}" y="{y:.2f}" font-size="{size_px}" font-family="monospace" fill="{fill}" '
            f'text-anchor="{anchor}" dominant-baseline="middle"{tr}>{esc(s)}</text>'
        )

    def render(self, margin_units: float = 0.5) -> str:
        x0, y0 = (self.minx - margin_units) * self.k, -(self.maxy + margin_units) * self.k
        w = (self.maxx - self.minx + 2 * margin_units) * self.k
        h = (self.maxy - self.miny + 2 * margin_units) * self.k
        body = "\n".join(self.parts)
        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{x0:.2f} {y0:.2f} {w:.2f} {h:.2f}" '
            f'width="{w:.0f}" height="{h:.0f}">\n<rect x="{x0:.2f}" y="{y0:.2f}" width="{w:.2f}" height="{h:.2f}" fill="#fafafa"/>\n'
            f"{body}\n</svg>\n"
        )


def esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def rect(cx, cy, w, h):
    return [(cx - w / 2, cy - h / 2), (cx + w / 2, cy - h / 2), (cx + w / 2, cy + h / 2), (cx - w / 2, cy + h / 2)]


def render(cob: Cob, px_per_unit: float = 100.0, labels: bool = True) -> str:
    svg = Svg(px_per_unit)

    # --- misc features (below everything else) ------------------------------
    for m in cob.misc():
        color, dash = MISC_STYLE.get(m.get("kind", ""), ("#888", "2 2"))
        try:
            polys = cob.placed_polygons(m)
        except (KeyError, FileNotFoundError) as e:
            print(f"warning: misc {m.get('id')}: {e}")
            continue
        for role, plist in polys.items():
            for poly in plist:
                svg.polygon(poly, color, 0.08 if m.get("kind") == "copper_required" else 0.0, color, 1.2, dash,
                            title=f"{m.get('id')} [{m.get('kind')}] layers={m.get('layers')}")

    # --- pcb pads ------------------------------------------------------------
    for pad in cob.pcb_pads():
        try:
            polys = cob.placed_polygons(pad)
        except (KeyError, FileNotFoundError) as e:
            print(f"warning: pad {pad.get('id')}: {e}")
            continue
        title = f"{pad.get('id')} #{pad.get('number')} {pad.get('name')} shape={pad.get('shape')}"
        for role in ("mask", "paste", "copper"):
            fill, op = COLORS.get(role, ("#888", 0.3))
            for poly in polys.get(role, []):
                svg.polygon(poly, fill, op, fill if role == "copper" else "none", 0.8, title=title)
        if labels and pad.get("role") != "die_attach":
            bt = cob.bond_target(pad)
            svg.circle(bt, 0.03, "#000", "#fff", 0.8)
            # label at the centroid of the copper, rotated with the pad
            cu = [pt for poly in polys.get("copper", []) for pt in poly]
            if cu:
                lp = (sum(x for x, _ in cu) / len(cu), sum(y for _, y in cu) / len(cu))
                svg.text(lp, f"{pad.get('number')} {pad.get('name')}", 9, "#222", "middle",
                         rotate=float(pad.get("rotation", 0)) % 180)

    # --- die -----------------------------------------------------------------
    die = cob.die
    w, h = nominal(die["size"][0]), nominal(die["size"][1])
    ox, oy = die.get("offset", [0, 0])
    svg.polygon(rect(ox, oy, w, h), "#3a3a3a", 0.9, "#000", 1.0, title=f"die {w}x{h}")
    notch = die.get("notch")
    if isinstance(notch, dict):
        ns = notch.get("size", [0.1, 0.1])
        sx = -1 if "left" in notch.get("side", "") else 1
        sy = 1 if "top" in notch.get("side", "") else -1
        cx, cy = ox + sx * (w / 2 - ns[0] / 2), oy + sy * (h / 2 - ns[1] / 2)
        svg.polygon(rect(cx, cy, ns[0], ns[1]), "#fafafa", 1.0, "none")

    for dp in die_pads_sorted(cob):
        c = dp["center"]
        sz = dp.get("size", [0.08, 0.08])
        svg.polygon(rect(c[0], c[1], sz[0], sz[1]), "#e0c060", 1.0, "#806000", 0.6,
                    title=f"{dp['id']} {dp.get('name')} metal={dp.get('metal')}")
        if labels:
            side = dp.get("side", "")
            inward = {"top": (0, -0.12), "bottom": (0, 0.12), "left": (0.12, 0), "right": (-0.12, 0)}.get(side, (0, -0.12))
            anchor = {"left": "start", "right": "end"}.get(side, "middle")
            rot = 90 if side in ("top", "bottom") else 0
            svg.text((c[0] + inward[0], c[1] + inward[1]), dp.get("name", dp["id"]), 6, "#f0f0f0", anchor, rot)

    # --- wires ---------------------------------------------------------------
    for wire in cob.wires():
        dp = cob.die_pad_by_id(wire.get("from", {}).get("die_pad", ""))
        pp = cob.pcb_pad_by_id(wire.get("to", {}).get("pcb_pad", ""))
        if not dp or not pp:
            print(f"warning: wire {wire.get('id')}: unresolved endpoint")
            continue
        try:
            bt = cob.bond_target(pp)
        except (KeyError, FileNotFoundError):
            continue
        a = (dp["center"][0], dp["center"][1])
        color = "#d02020" if wire.get("type") == "ball" else "#2060d0"
        svg.line(a, bt, color, 1.5, title=f"{wire.get('id')} {wire.get('type')} {wire.get('material')} {wire.get('diameter_um')}um")

    # origin cross
    svg.line((-0.1, 0), (0.1, 0), "#000", 0.8)
    svg.line((0, -0.1), (0, 0.1), "#000", 0.8)

    meta = cob.data.get("meta", {})
    title = f"{meta.get('name', '?')} rev {meta.get('revision', '?')}  uuid {cob.data.get('uuid', '?')}"
    svg.text((svg.minx, svg.maxy + 0.25), title, 10, "#222", "start")
    return svg.render()


def die_pads_sorted(cob: Cob) -> list[dict]:
    return sorted(cob.die_pads(), key=lambda p: p["id"])
