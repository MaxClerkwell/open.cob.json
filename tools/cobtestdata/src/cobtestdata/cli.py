"""initialize_testdata: fetch the wafer.space shuttle reticles into the local testdata cache.

The run repositories ship one OASIS per shuttle, split into <100 MB parts
for GitHub, plus a manifest that names every project on it. This tool
downloads the parts, verifies the MD5 the run repo publishes, joins them
and stores reticle and manifest under testdata/cache/. Picking single
chips out of a reticle is the job of extract_die.

Layouts are never committed to this repository; everything lands under
testdata/, which is gitignored.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import sys
import time
import urllib.request
from pathlib import Path

import gdstk

from .runs import RUNS, Run

# wirebonding plans published in the wafer.space COB repository (Apache-2.0)
COB_REPO_RAW = "https://raw.githubusercontent.com/wafer-space/chip-on-board-wire-bonded-pcbs/main"
COB_PDFS = {"1": ("BTAP", "MOLE", "TTP2", "TTPG")}


def log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


# ---------------------------------------------------------------- download

def download(url: str, dest: Path) -> None:
    if dest.exists() and dest.stat().st_size > 0:
        log(f"  cached  {dest.name}")
        return
    log(f"  fetch   {url}")
    tmp = dest.with_suffix(dest.suffix + ".part")
    with urllib.request.urlopen(url) as r, open(tmp, "wb") as f:
        while chunk := r.read(1 << 20):
            f.write(chunk)
    tmp.replace(dest)


def md5_of(path: Path) -> str:
    h = hashlib.md5()
    with open(path, "rb") as f:
        while chunk := f.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()


def fetch_reticle(run: Run, cache: Path) -> Path:
    cache.mkdir(parents=True, exist_ok=True)
    oas = cache / f"{run.shuttle}.oas"
    if oas.exists() and md5_of(oas) == run.md5:
        log(f"  ok      {oas.name} (md5 verified)")
        return oas
    parts = []
    for p in run.parts:
        name = f"{run.shuttle}-part-{p}"
        download(f"{run.raw}/layout/{name}", cache / name)
        parts.append(cache / name)
    log(f"  join    {oas.name}")
    with open(oas, "wb") as out:
        for p in parts:
            out.write(p.read_bytes())
    got = md5_of(oas)
    if got != run.md5:
        oas.unlink()
        raise SystemExit(f"md5 mismatch for {oas.name}: expected {run.md5}, got {got}")
    log(f"  ok      {oas.name} (md5 verified)")
    for p in parts:
        p.unlink()
    return oas


def fetch_manifest(run: Run, cache: Path) -> list[dict[str, str]]:
    dest = cache / "manifest.csv"
    download(f"{run.raw}/{run.manifest}", dest)
    with open(dest, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


# ---------------------------------------------------------------- split

def find_cell(lib: gdstk.Library, code: str, top: str) -> list[gdstk.Cell]:
    """Locate a project's cell(s) inside the reticle.

    The reticle names project cells ``<CODE>_<TOP>_<x>_<y>``, where x, y is
    the slot position. A project submitted to several slots appears several
    times with identical content. All placements are returned, slot order.
    Private projects are obfuscated and have no cell at all.
    """
    hits = [c for c in lib.cells if c.name.startswith(f"{code}_{top}_")]
    if not hits:
        hits = [c for c in lib.cells if c.name.startswith(f"{code}_")]
    return sorted(hits, key=lambda c: c.name)


def slot_of(cell_name: str) -> str | None:
    tail = cell_name.rsplit("_", 2)
    return f"{tail[1]}_{tail[2]}" if len(tail) == 3 and tail[1].isdigit() and tail[2].isdigit() else None


def write_chip(lib: gdstk.Library, cell: gdstk.Cell, dest: Path) -> int:
    out = gdstk.Library(name=cell.name, unit=lib.unit, precision=lib.precision)
    out.add(cell, *cell.dependencies(True))
    dest.parent.mkdir(parents=True, exist_ok=True)
    out.write_oas(str(dest))
    return len(out.cells)


def load_reticle(oas: Path, cache: Path | None = None) -> gdstk.Library:
    log(f"  load    {oas.name} ({oas.stat().st_size / 1e6:.0f} MB), this takes a while")
    t0 = time.time()
    lib = gdstk.read_oas(str(oas))
    log(f"  loaded  {len(lib.cells)} cells in {time.time() - t0:.0f} s")
    if cache is not None:
        tops = lib.top_level()
        kids = sorted({r.cell.name for t in tops for r in t.references}) if len(tops) == 1 else [t.name for t in tops]
        (cache / "cells.json").write_text(json.dumps(kids, indent=1))
    return lib


def manifest_entry(row: dict[str, str]) -> dict:
    top = row.get("TOP", "").strip() or "chip_top"
    return {
        "code": row["CODE"].strip(),
        "project": row.get("PROJECT", ""),
        "slot_size": row.get("SLOT_SIZE", ""),
        "visibility": row.get("VISIBILITY", ""),
        "repository": row.get("REPOSITORY", ""),
        "manifest_top": top,
        "manifest_sha256": row.get("SHA256", ""),
    }


def export_chip(lib: gdstk.Library, row: dict[str, str], out: Path) -> dict:
    """Write one project's cell to out/<CODE>/<top>.oas and return its index entry."""
    entry = manifest_entry(row)
    code, top = entry["code"], entry["manifest_top"]
    cells = find_cell(lib, code, top)
    if not cells:
        log(f"  miss    {code}: no cell {code}_{top}_x_y ({entry['visibility'].lower() or 'unknown'})")
        entry.update({"cell": None, "layout": None, "placements": []})
        return entry
    cell = cells[0]
    dest = out / code / f"{top}.oas"
    n = write_chip(lib, cell, dest)
    bb = cell.bounding_box()
    size = None
    if bb:
        s = lib.unit / 1e-3
        size = [round((bb[1][0] - bb[0][0]) * s, 4), round((bb[1][1] - bb[0][1]) * s, 4)]
    entry.update({"cell": cell.name, "layout": str(dest.relative_to(out)), "cells_written": n,
                  "size_mm": size, "placements": [slot_of(c.name) for c in cells],
                  "labels_on_top": len(cell.labels)})
    log(f"  wrote   {dest.relative_to(out)}  {cell.name}  {n} cells  {size} mm  labels {len(cell.labels)}")
    return entry


# ---------------------------------------------------------------- pdfs

def fetch_pdfs(run: Run, cache: Path) -> None:
    for code in COB_PDFS.get(run.key, ()):
        dest = cache / "wirebonding" / f"{code}.pdf"
        dest.parent.mkdir(parents=True, exist_ok=True)
        download(f"{COB_REPO_RAW}/run-{run.key}/wirebonding/{code}.pdf", dest)


# ---------------------------------------------------------------- main

def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="initialize_testdata", description=__doc__.split("\n\n")[0])
    ap.add_argument("--run", choices=sorted(RUNS), action="append", help="shuttle run(s) to fetch, default: all")
    ap.add_argument("--testdata", type=Path, default=None, help="testdata root (default: <repo>/testdata)")
    ap.add_argument("--scan", action="store_true",
                    help="also load each reticle once and cache its cell list, so extract_die can mark projects")
    ap.add_argument("--no-pdfs", action="store_true", help="skip the wirebonding PDFs from the COB repo")
    args = ap.parse_args(argv)

    repo_root = Path(__file__).resolve().parents[4]
    testdata = args.testdata or repo_root / "testdata"

    for key in args.run or sorted(RUNS):
        run = RUNS[key]
        cache = testdata / "cache" / run.repo.split("/")[1]
        log(f"run {run.key}: {run.repo}")
        oas = fetch_reticle(run, cache)
        manifest = fetch_manifest(run, cache)
        public = sum(1 for r in manifest if r.get("VISIBILITY", "").lower() != "private")
        log(f"  ok      manifest.csv: {len(manifest)} projects, {public} public")
        if not args.no_pdfs:
            fetch_pdfs(run, cache)
        if args.scan:
            load_reticle(oas, cache)
            log(f"  ok      cells.json")
        log(f"  ready   {cache}")
    log("next: uv run extract_die --run <n>")


if __name__ == "__main__":
    main()
