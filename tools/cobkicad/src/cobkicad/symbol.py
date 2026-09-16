"""Symbol library (.kicad_sym) generation."""
from __future__ import annotations

from cobviz.model import Cob

from .footprint import footprint_name
from .sexpr import num, q

SYM_VERSION = 20241209
PIN_LEN = 2.54
PITCH = 2.54
POWER_NAMES = ("VDD", "VCC", "VSS", "GND", "AVDD", "DVDD", "AGND", "DGND")


def pin_type(dp: dict | None, name: str) -> str:
    if dp and dp.get("electrical"):
        return dp["electrical"]
    if name.upper().startswith(POWER_NAMES) or name.upper() in POWER_NAMES:
        return "power_in"
    return "passive"


def build_symbol(cob: Cob, lib_nick: str) -> str:
    meta = cob.data.get("meta", {})
    name = meta.get("name", "DIE").replace(" ", "_")
    fp = f"{lib_nick}:{footprint_name(cob)}"

    # pins: one per pcb pad, source die pad via wires for side and type
    die_for_pad = {}
    for w in cob.wires():
        die_for_pad.setdefault(w.get("to", {}).get("pcb_pad"), w.get("from", {}).get("die_pad"))
    pins = []
    for pad in cob.pcb_pads():
        dp = cob.die_pad_by_id(die_for_pad.get(pad["id"], ""))
        pname = pad.get("name", pad["id"])
        pins.append({"number": str(pad.get("number", pad["id"])), "name": pname,
                     "type": pin_type(dp, pname), "side": (dp or {}).get("side", "left")})

    top = [p for p in pins if p["type"] == "power_in" and p["name"].upper().startswith(("VDD", "VCC", "AVDD", "DVDD"))]
    bottom = [p for p in pins if p["type"] == "power_in" and p not in top]
    rest = [p for p in pins if p not in top and p not in bottom]
    left = [p for p in rest if p["side"] in ("left", "top")]
    right = [p for p in rest if p not in left]

    # body size: room for the pins on each side and for the longest names,
    # everything snapped to the 2.54 mm grid so pin ends land on grid points
    char_w = 1.1  # approx. width of one character at 1.27 mm font
    name_lr = max([len(p["name"]) for p in left + right] + [0])
    name_tb = max([len(p["name"]) for p in top + bottom] + [0])
    n_lr = max(len(left), len(right), 1)
    n_tb = max(len(top), len(bottom), 1)

    def snap(v):
        return PITCH * max(2, -(-v // PITCH))

    body_w = snap(max((n_tb + 1) * PITCH, 2 * name_lr * char_w + 2 * PITCH))
    body_h = snap(max((n_lr + 1) * PITCH, 2 * name_tb * char_w + 2 * PITCH))
    hw, hh = body_w / 2, body_h / 2

    def spread(n):
        return [(i - (n - 1) / 2) * PITCH for i in range(n)]

    def pin(p, x, y, angle):
        return (f"      (pin {p['type']} line (at {num(x)} {num(y)} {angle}) (length {num(PIN_LEN)}) "
                f"(name {q(p['name'])} (effects (font (size 1.27 1.27)))) "
                f"(number {q(p['number'])} (effects (font (size 1.27 1.27)))))")

    lines = []
    for i, p in enumerate(left):
        lines.append(pin(p, -hw - PIN_LEN, hh - (i + 1) * PITCH, 0))
    for i, p in enumerate(right):
        lines.append(pin(p, hw + PIN_LEN, hh - (i + 1) * PITCH, 180))
    for x, p in zip(spread(len(top)), top):
        lines.append(pin(p, x, hh + PIN_LEN, 270))
    for x, p in zip(spread(len(bottom)), bottom):
        lines.append(pin(p, x, -hh - PIN_LEN, 90))

    def prop(k, v, x, y, hide=False):
        return (f"    (property {q(k)} {q(v)} (at {num(x)} {num(y)} 0) "
                f"(effects (font (size 1.27 1.27)){' (hide yes)' if hide else ''}))")

    return "\n".join([
        f"(kicad_symbol_lib (version {SYM_VERSION}) (generator \"cobkicad\") (generator_version \"0.1\")",
        f"  (symbol {q(name)} (pin_names (offset 1.016)) (exclude_from_sim no) (in_bom yes) (on_board yes)",
        prop("Reference", "U", -hw, hh + 1.27),
        prop("Value", name, hw, hh + 1.27),
        prop("Footprint", fp, 0, -hh - 3.81, hide=True),
        prop("Datasheet", meta.get("datasheet", ""), 0, -hh - 5.08, hide=True),
        prop("Description", meta.get("description", ""), 0, -hh - 6.35, hide=True),
        prop("cob_uuid", cob.data.get("uuid", ""), 0, -hh - 7.62, hide=True),
        f"    (symbol {q(name + '_0_1')}",
        f"      (rectangle (start {num(-hw)} {num(hh)}) (end {num(hw)} {num(-hh)}) (stroke (width 0.254) (type default)) (fill (type background)))",
        "    )",
        f"    (symbol {q(name + '_1_1')}",
        *lines,
        "    )",
        "  )",
        ")",
    ]) + "\n"
