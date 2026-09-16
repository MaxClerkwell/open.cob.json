# cobgen

Reads a chip layout (GDSII or OASIS) and writes a `.cob.json` file whose
`die` block is filled in from the layout. Everything the layout cannot
know, `pcb`, `wires`, `assembly`, is written as `"unspecified"` so the file
is a valid, honest starting point for the PCB designer.

```bash
cd tools/cobgen
uv run cobgen --file chip_top.oas --pdk gf180mcu --out chip_top.cob.json
```

Tested with the
[wafer.space gf180mcu example layouts](https://github.com/wafer-space/gf180mcu-example-layouts)
(`3v3/0p5x0p5/chip_top.oas`: 56 pads, 52 of them labeled, four unlabeled
`dvdd`/`dvss` pads). Layout files are not part of this repository, fetch
them from the source.

What is extracted:

| `die` field | Source in the layout |
|---|---|
| `size` | bounding box of the top cell |
| `pads[].center`, `size`, `opening` | passivation opening polygons on the PDK's pad layer, filtered by minimum size |
| `pads[].name` | text label on the PDK's label layer that lies inside the opening, else `"unspecified"` |
| `pads[].electrical` | I/O cell type of the pad cell that contains the opening |
| `pads[].side` | nearest die edge |
| `pads[].metal` | from the PDK table |
| `pads[].source` | pad cell name and whether a label was found, for traceability |

Pads are numbered `D1..Dn` counter-clockwise starting at the bottom left
corner. All coordinates are relative to the die center, in mm, Y up.

Options: `--pdk` one of the built-in PDK tables (`gf180mcu`, `sky130`),
`--name` overrides the chip name (default: top cell name), `--top` picks a
top cell if the file has several, `--min-pad` minimum opening size in µm
(default from the PDK table).

The PDK table is small on purpose: pad layer, label layer, metal, minimum
pad size, and a mapping from I/O cell name fragments to pin types. Add a
PDK by extending `pdk.py`.
