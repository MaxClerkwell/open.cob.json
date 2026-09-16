"""Footprint (.kicad_mod) generation."""
from __future__ import annotations

from cobviz.model import Cob, nominal

from .sexpr import new_uuid, num, pts, q

FP_VERSION = 20241229
SILK_W = 0.10
WIRE_LAYER = "Dwgs.User"


def flip(p):
    """die coordinates (Y up) -> KiCad footprint coordinates (Y down)."""
    return (p[0], -p[1])


def poly(layer: str, points, width=SILK_W, fill=True) -> str:
    return (
        f"  (fp_poly {pts(flip(p) for p in points)} (stroke (width {num(width)}) (type solid)) "
        f"(fill {'yes' if fill else 'no'}) (layer {q(layer)}) {new_uuid()})"
    )


def line(a, b, layer: str, width=SILK_W) -> str:
    a, b = flip(a), flip(b)
    return (
        f"  (fp_line (start {num(a[0])} {num(a[1])}) (end {num(b[0])} {num(b[1])}) "
        f"(stroke (width {num(width)}) (type solid)) (layer {q(layer)}) {new_uuid()})"
    )


def rect(cx, cy, w, h):
    return [(cx - w / 2, cy - h / 2), (cx + w / 2, cy - h / 2), (cx + w / 2, cy + h / 2), (cx - w / 2, cy + h / 2)]


def footprint_name(cob: Cob) -> str:
    return "COB_" + cob.data.get("meta", {}).get("name", "DIE").replace(" ", "_")


def build_footprint(cob: Cob) -> str:
    meta = cob.data.get("meta", {})
    name = footprint_name(cob)
    die = cob.die
    w, h = nominal(die["size"][0]), nominal(die["size"][1])
    ox, oy = die.get("offset", [0, 0])
    out: list[str] = []
    out.append(f"(footprint {q(name)} (version {FP_VERSION}) (generator \"cobkicad\") (generator_version \"0.1\") (layer \"F.Cu\")")
    out.append(f"  (descr {q(meta.get('description', 'Chip on board, generated from ' + cob.path.name))})")
    out.append(f"  (tags \"cob wirebond {meta.get('name', '')}\")")
    out.append(f"  (property \"Reference\" \"REF**\" (at 0 {num(-(h / 2 + 2.5))} 0) (layer \"F.SilkS\") {new_uuid()} (effects (font (size 1 1) (thickness 0.1))))")
    out.append(f"  (property \"Value\" {q(name)} (at 0 {num(h / 2 + 2.5)} 0) (layer \"F.Fab\") {new_uuid()} (effects (font (size 1 1) (thickness 0.15))))")
    for prop in ("Footprint", "Datasheet", "Description"):
        out.append(f"  (property {q(prop)} \"\" (at 0 0 0) (layer \"F.Fab\") hide {new_uuid()} (effects (font (size 1.27 1.27) (thickness 0.15))))")
    out.append(f"  (property \"cob_uuid\" {q(cob.data.get('uuid', ''))} (at 0 0 0) (layer \"F.Fab\") hide {new_uuid()} (effects (font (size 1.27 1.27) (thickness 0.15))))")
    out.append("  (attr smd)")

    # --- die on silkscreen ----------------------------------------------------
    out.append(poly("F.SilkS", rect(ox, oy, w, h), fill=False))
    notch = die.get("notch")
    if isinstance(notch, dict):
        ns = notch.get("size", [0.1, 0.1])
        sx = -1 if "left" in notch.get("side", "") else 1
        sy = 1 if "top" in notch.get("side", "") else -1
        cx, cy = ox + sx * (w / 2 - ns[0] / 2), oy + sy * (h / 2 - ns[1] / 2)
        out.append(poly("F.SilkS", rect(cx, cy, ns[0], ns[1]), fill=True))
    for dp in cob.die_pads():
        c, sz = dp["center"], dp.get("size", [0.08, 0.08])
        out.append(poly("F.SilkS", rect(c[0], c[1], sz[0], sz[1]), width=0.05, fill=False))

    # --- pcb pads on F.Cu -------------------------------------------------------
    for pad in cob.pcb_pads():
        polys = cob.placed_polygons(pad)
        at = flip(pad.get("at", [0, 0]))
        layers = ["F.Cu"]
        if pad.get("paste", "none") != "none":
            layers.append("F.Paste")
        if not polys.get("mask"):
            layers.append("F.Mask")  # no explicit mask polygon: let KiCad expand copper
        prims = " ".join(
            f"(gr_poly {pts(((x - at[0]), (y - at[1])) for x, y in (flip(p) for p in cu))} (width 0) (fill yes))"
            for cu in polys.get("copper", [])
        )
        out.append(
            f"  (pad {q(pad.get('number', pad['id']))} smd custom (at {num(at[0])} {num(at[1])}) (size 0.1 0.1) "
            f"(layers {' '.join(q(l) for l in layers)}) (pinfunction {q(pad.get('name', ''))}) "
            f"(options (clearance outline) (anchor rect)) (primitives {prims}) {new_uuid()})"
        )
        for m in polys.get("mask", []):
            out.append(poly("F.Mask", m, width=0, fill=True))

    # --- misc on explicit layers ------------------------------------------------
    for m in cob.misc():
        layers = m.get("layers")
        if not isinstance(layers, list) or not layers:
            raise ValueError(f"pcb.misc entry {m.get('id')!r} has no 'layers' list")
        polys = cob.placed_polygons(m)
        allp = [p for plist in polys.values() for p in plist]
        kind = m.get("kind", "")
        if kind == "keepout":
            forbids = set(m.get("forbids", []))
            zl = q("F&B.Cu") if layers == ["*.Cu"] else " ".join(q(l) for l in layers)
            for p in allp:
                out.append(
                    f"  (zone (net 0) (net_name \"\") (layers {zl}) {new_uuid()} (name {q(m.get('id', 'keepout'))}) "
                    f"(hatch edge 0.5) (connect_pads (clearance 0)) (min_thickness 0.25) "
                    f"(keepout (tracks {'not_allowed' if 'track' in forbids else 'allowed'}) "
                    f"(vias {'not_allowed' if forbids & {'via', 'microvia', 'pth'} else 'allowed'}) "
                    f"(pads {'not_allowed' if 'pad' in forbids else 'allowed'}) "
                    f"(copperpour {'not_allowed' if 'copper' in forbids else 'allowed'}) "
                    f"(footprints {'not_allowed' if 'footprint' in forbids else 'allowed'})) "
                    f"(fill (thermal_gap 0.5) (thermal_bridge_width 0.5)) (polygon {pts(flip(q_) for q_ in p)}))"
                )
        elif kind == "cutout":
            for p in allp:
                out.append(poly("Edge.Cuts", p, width=0.05, fill=False))
        elif kind == "copper_required" and m.get("satisfied_by"):
            continue  # the referenced pad already provides this copper
        else:
            for layer in layers:
                for p in allp:
                    out.append(poly(layer, p, width=0.1 if layer.endswith("SilkS") else 0, fill=True))

    # --- wires as documentation -----------------------------------------------
    for wire in cob.wires():
        dp = cob.die_pad_by_id(wire.get("from", {}).get("die_pad", ""))
        pp = cob.pcb_pad_by_id(wire.get("to", {}).get("pcb_pad", ""))
        if dp and pp:
            out.append(line(dp["center"], cob.bond_target(pp), WIRE_LAYER, 0.05))

    out.append(")")
    return "\n".join(out) + "\n"
