# cobtestdata

Gets the chips that wafer.space actually manufactured onto your disk as
cobgen input. Two commands, run in this order:

```bash
uv run initialize_testdata --run 2     # fetch the reticle and manifest, once
uv run extract_die --run 2             # pick chips from a menu, one folder each
```

Nothing either command downloads is committed. Everything lands in
`testdata/` at the repository root, which is gitignored.

## initialize_testdata

Downloads the shuttle reticle from the run repository
([ws-run1](https://github.com/wafer-space/ws-run1),
[ws-run2](https://github.com/wafer-space/ws-run2)) in its <100 MB parts,
joins them, checks the MD5 that `layout/create-reticle-oas.sh` in that
repo states, and stores the result together with the project manifest:

```
testdata/cache/ws-run2/
├── G802.oas            the joined reticle, MD5 verified (187 MB)
├── manifest.csv        every project: code, name, slot size, top cell, repo
├── cells.json          reticle cell list, only with --scan or after an extract
└── wirebonding/*.pdf   bond plans from the wafer.space COB repo (run 1 only)
```

Options: `--run 1|2` (repeatable, default all), `--scan` loads each
reticle once so `extract_die` can mark which projects are really present,
`--no-pdfs`, `--testdata DIR`. Re-running is cheap: a verified reticle is
not fetched again.

Run 1 is about 350 MB, run 2 about 190 MB. Loading a reticle with gdstk
takes about a minute and several GB of RAM, which is why `--scan` is
optional and why `extract_die` loads only after you have chosen.

## extract_die

Lists every project of a run and asks which to export. If the reticle is
not cached yet it is fetched first.

```
wafer.space run 2: 40 projects on the reticle

    1  + 0000   1x0p5    ICELab Test Chip
    2  + AMM1   1x0p5    raybox-zero wafer.space run 2 half height
    ...
    7  + CAFE   0p5x0p5  Expresso Ethernet Chip: 100Mbps Ethernet switch ...

  + in reticle   x private, not exportable   ? not scanned yet
  select by number, range, code or 'all', e.g.  3,5-8,KIAN   (empty to quit)

export> 7,KIAN
```

Each chosen chip gets its own folder:

```
testdata/dies/
├── CAFE/
│   ├── chip_top.oas   the project cell CAFE_chip_top_<x>_<y> and its sub-cells
│   └── die.json       code, project, slot size, cell name, size in mm, repository
└── KIAN/
    ├── chip_top.oas
    └── die.json
```

Private projects are obfuscated on the published reticle and have no cell;
they are listed but cannot be exported. Projects placed in several slots
appear once, with all placements noted in `die.json`.

Options: `--run 1|2` (default 2), `--select 7,KIAN` or `--select all`
skips the prompt, `--out DIR` changes the die directory, `--testdata DIR`
the cache location.

## cobclean

Removes what the two commands produced, so a trial starts clean:

```bash
uv run cobclean            # exported dies only, reticles stay cached
uv run cobclean --cache    # also the downloaded reticles
uv run cobclean --all      # everything, plus __pycache__ under tools/
uv run cobclean -n         # dry run, show what would go
```

## Then

```bash
uv run cobgen  --file testdata/dies/CAFE/chip_top.oas --pdk gf180mcu --out testdata/dies/CAFE/CAFE.cob.json
uv run cobedit --file testdata/dies/CAFE/CAFE.cob.json
uv run cobkicad --file testdata/dies/CAFE/CAFE.cob.json --out testdata/dies/CAFE/kicad
```

Known runs are a table in `runs.py`. A new run needs its repo, shuttle
name, part suffixes and MD5.

Licensing: the run repositories do not state a license for the layouts,
which is one more reason not to copy them into this repository. Use them
as test input only.
