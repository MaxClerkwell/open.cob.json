"""Command line entry point: cobgen --file chip.gds --pdk gf180mcu --out chip.cob.json"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .extract import build_cob, extract, pick_top, read_layout
from .pdk import PDKS


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="cobgen", description="Generate the die block of a .cob.json from GDSII/OASIS.")
    ap.add_argument("--file", required=True, type=Path, help="input .gds / .oas")
    ap.add_argument("--pdk", required=True, choices=sorted(PDKS), help="PDK layer table")
    ap.add_argument("--out", type=Path, help="output .cob.json (default: <input>.cob.json)")
    ap.add_argument("--top", help="top cell name if the layout has several")
    ap.add_argument("--name", help="chip name for meta.name (default: top cell name)")
    ap.add_argument("--min-pad", type=float, help="minimum pad opening in µm (default from PDK)")
    args = ap.parse_args(argv)

    pdk = PDKS[args.pdk]
    try:
        lib = read_layout(args.file)
        top = pick_top(lib, args.top)
        bbox, pads = extract(lib, top, pdk, args.min_pad or pdk.min_pad_um)
    except (OSError, ValueError, KeyError) as e:
        print(f"cobgen: {e}", file=sys.stderr)
        return 1
    if not pads:
        print("cobgen: no pad openings found, check --pdk and --min-pad", file=sys.stderr)
        return 1

    cob = build_cob(args.file, top.name, bbox, pads, pdk, args.name or top.name)
    out = args.out or args.file.with_suffix(".cob.json")
    out.write_text(json.dumps(cob, indent=2) + "\n")
    unlabeled = sum(1 for p in pads if p.name is None)
    print(f"wrote {out}: die {cob['die']['size'][0]} x {cob['die']['size'][1]} mm, {len(pads)} pads, {unlabeled} without label")
    return 0


if __name__ == "__main__":
    sys.exit(main())
