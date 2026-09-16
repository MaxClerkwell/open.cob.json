"""Command line entry point: cobkicad --file x.cob.json --out dir"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from cobviz.model import Cob

from .footprint import build_footprint, footprint_name
from .symbol import build_symbol


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="cobkicad", description="Generate KiCad symbol and footprint from a .cob.json file.")
    ap.add_argument("--file", required=True, type=Path, help="input .cob.json")
    ap.add_argument("--out", type=Path, default=Path("."), help="output directory")
    ap.add_argument("--shapes", action="append", type=Path, default=[], help="extra shape catalog directory")
    ap.add_argument("--lib", default="open_cob", help="library nickname for the Footprint field")
    args = ap.parse_args(argv)

    try:
        cob = Cob.load(args.file, args.shapes)
        sym = build_symbol(cob, args.lib)
        fp = build_footprint(cob)
    except (OSError, ValueError, KeyError) as e:
        print(f"cobkicad: {e}", file=sys.stderr)
        return 1

    name = cob.data.get("meta", {}).get("name", "DIE").replace(" ", "_")
    sym_path = args.out / f"{name}.kicad_sym"
    fp_dir = args.out / f"{args.lib}.pretty"
    fp_dir.mkdir(parents=True, exist_ok=True)
    fp_path = fp_dir / f"{footprint_name(cob)}.kicad_mod"
    sym_path.write_text(sym)
    fp_path.write_text(fp)
    print(f"wrote {sym_path}\nwrote {fp_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
