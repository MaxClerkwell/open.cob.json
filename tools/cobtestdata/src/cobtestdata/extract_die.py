"""extract_die: pick chips from a cached wafer.space reticle and export each into its own die folder.

Reads the manifest of a run from testdata/cache (fetching the reticle
first if initialize_testdata has not run yet), shows a numbered list of
all projects, asks which to export, loads the reticle once and writes
testdata/dies/<CODE>/<top>.oas plus a die.json beside it.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .cli import RUNS, export_chip, fetch_manifest, fetch_reticle, load_reticle, log, manifest_entry


def parse_selection(text: str, entries: list[dict]) -> list[int]:
    """'all' | '1,3,5-8' | 'CAFE,KIAN' | mixed. Returns 0-based indices, in order, deduplicated."""
    text = text.strip()
    if not text:
        return []
    if text.lower() in ("all", "a", "*"):
        return list(range(len(entries)))
    by_code = {e["code"].upper(): i for i, e in enumerate(entries)}
    picked: list[int] = []
    for tok in text.replace(";", ",").split(","):
        tok = tok.strip()
        if not tok:
            continue
        if tok.upper() in by_code:  # codes first: "0000" is a project, not a number
            picked.append(by_code[tok.upper()])
        elif "-" in tok and all(x.strip().isdigit() for x in tok.split("-", 1)):
            a, b = (int(x) for x in tok.split("-", 1))
            rng = range(a, b + 1) if a <= b else range(a, b - 1, -1)
            picked.extend(i - 1 for i in rng)
        elif tok.isdigit():
            picked.append(int(tok) - 1)
        else:
            raise ValueError(f"unknown selection {tok!r}")
    seen, out = set(), []
    for i in picked:
        if not 0 <= i < len(entries):
            raise ValueError(f"number {i + 1} is out of range 1..{len(entries)}")
        if i not in seen:
            seen.add(i)
            out.append(i)
    return out


def show_menu(run_key: str, entries: list[dict], present: set[str] | None) -> None:
    print(f"\nwafer.space run {run_key}: {len(entries)} projects on the reticle\n")
    w = max(len(e["project"]) for e in entries)
    w = min(w, 60)
    for i, e in enumerate(entries, 1):
        proj = e["project"] if len(e["project"]) <= 60 else e["project"][:57] + "..."
        if e["visibility"].lower() == "private":
            mark = "x"  # obfuscated, no cell in the reticle
        elif present is None:
            mark = "?"  # reticle never loaded yet
        else:
            mark = "+" if any(c.startswith(e["code"] + "_") for c in present) else "x"
        print(f"  {i:3d}  {mark} {e['code']:<6} {e['slot_size']:<8} {proj:<{w}}")
    print("\n  + in reticle   x not in reticle (private)   ? not scanned yet")
    print("  select by number, range, code or 'all', e.g.  3,5-8,KIAN   (empty to quit)\n")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="extract_die", description=__doc__.split("\n\n")[0])
    ap.add_argument("--run", choices=sorted(RUNS), default="2", help="shuttle run, default 2")
    ap.add_argument("--select", help="non-interactive selection, same syntax as the prompt")
    ap.add_argument("--out", type=Path, default=None, help="die directory (default: <repo>/testdata/dies)")
    ap.add_argument("--testdata", type=Path, default=None, help="testdata root (default: <repo>/testdata)")
    args = ap.parse_args(argv)

    repo_root = Path(__file__).resolve().parents[4]
    testdata = args.testdata or repo_root / "testdata"
    out = args.out or testdata / "dies"
    run = RUNS[args.run]
    cache = testdata / "cache" / run.repo.split("/")[1]

    log(f"run {run.key}: {run.repo}")
    oas = fetch_reticle(run, cache)
    manifest = fetch_manifest(run, cache)
    entries = [manifest_entry(r) for r in manifest]
    cells_file = cache / "cells.json"
    present = set(json.loads(cells_file.read_text())) if cells_file.exists() else None

    if args.select is not None:
        chosen = parse_selection(args.select, entries)
    else:
        if not sys.stdin.isatty():
            raise SystemExit("no terminal: pass --select instead")
        show_menu(run.key, entries, present)
        while True:
            try:
                text = input("export> ")
            except EOFError:
                text = ""
            if not text.strip():
                log("nothing selected")
                return
            try:
                chosen = parse_selection(text, entries)
                break
            except ValueError as e:
                print(f"  {e}")
    if not chosen:
        log("nothing selected")
        return

    lib = load_reticle(oas, cache)
    written = 0
    for i in chosen:
        entry = export_chip(lib, manifest[i], out)
        if entry["cell"]:
            entry["run"] = run.key
            entry["shuttle"] = run.shuttle
            (out / entry["code"] / "die.json").write_text(json.dumps(entry, indent=2))
            written += 1
    log(f"  done    {written}/{len(chosen)} dies in {out}")
    rel = out.relative_to(Path.cwd()) if out.is_relative_to(Path.cwd()) else out
    for i in chosen:
        code = manifest[i]["CODE"].strip()
        d = out / code
        if (d / "die.json").exists():
            top = json.loads((d / "die.json").read_text())["manifest_top"]
            log(f"next:    uv run cobgen --file {rel / code / (top + '.oas')} --pdk gf180mcu --out {rel / code / (code + '.cob.json')}")


if __name__ == "__main__":
    main()
