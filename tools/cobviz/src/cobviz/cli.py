"""Command line entry point: cobviz --file x.cob.json --plot x.svg"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .model import Cob
from .render import render


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="cobviz", description="Render a .cob.json file as SVG.")
    ap.add_argument("--file", required=True, type=Path, help="input .cob.json")
    ap.add_argument("--plot", required=True, type=Path, help="output .svg")
    ap.add_argument("--shapes", action="append", type=Path, default=[], help="extra shape catalog directory")
    ap.add_argument("--scale", type=float, default=100.0, help="pixels per length unit (default 100)")
    ap.add_argument("--no-labels", action="store_true", help="omit pad labels")
    args = ap.parse_args(argv)

    try:
        cob = Cob.load(args.file, args.shapes)
        svg = render(cob, args.scale, labels=not args.no_labels)
    except (OSError, ValueError, KeyError) as e:
        print(f"cobviz: {e}", file=sys.stderr)
        return 1
    args.plot.write_text(svg)
    print(f"wrote {args.plot}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
