"""cobclean: remove generated test data so a run starts from scratch.

By default only the exported dies and the files generated from them are
removed. The downloaded reticles stay, since fetching them again costs
hundreds of MB; pass --cache or --all to drop them too.
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path


def log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def size_of(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


def remove(path: Path, dry: bool) -> int:
    if not path.exists():
        return 0
    n = size_of(path)
    log(f"  {'would remove' if dry else 'remove'}  {path}  ({n / 1e6:.1f} MB)")
    if not dry:
        shutil.rmtree(path) if path.is_dir() else path.unlink()
    return n


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="cobclean", description=__doc__.split("\n\n")[0])
    ap.add_argument("--cache", action="store_true", help="also remove the downloaded reticles (testdata/cache)")
    ap.add_argument("--pycache", action="store_true", help="also remove __pycache__ directories under tools/")
    ap.add_argument("--all", action="store_true", help="everything above, leaving only testdata/ itself gone")
    ap.add_argument("--testdata", type=Path, default=None, help="testdata root (default: <repo>/testdata)")
    ap.add_argument("-n", "--dry-run", action="store_true", help="only show what would be removed")
    args = ap.parse_args(argv)

    repo_root = Path(__file__).resolve().parents[4]
    testdata = args.testdata or repo_root / "testdata"
    total = 0

    log("dies and generated files")
    total += remove(testdata / "dies", args.dry_run)
    if args.cache or args.all:
        log("downloaded reticles")
        total += remove(testdata / "cache", args.dry_run)
    if args.all and testdata.exists() and not any(testdata.iterdir()):
        remove(testdata, args.dry_run)
    if args.pycache or args.all:
        log("python caches")
        for d in sorted((repo_root / "tools").rglob("__pycache__")):
            if ".venv" not in d.parts:
                total += remove(d, args.dry_run)
    log(f"{'would free' if args.dry_run else 'freed'} {total / 1e6:.1f} MB")
    if not (args.cache or args.all):
        log("reticles kept in testdata/cache, pass --cache to drop them")


if __name__ == "__main__":
    main()
