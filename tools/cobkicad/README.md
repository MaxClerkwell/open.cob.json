# cobkicad

Generates a KiCad symbol library (`.kicad_sym`) and a footprint
(`.kicad_mod`) from a `.cob.json` file. Written for KiCad 9 and 10, which
share the s-expression formats used here.

```bash
cd tools/cobkicad
uv run cobkicad --file ../../examples/demo-chip/<uuid>.cob.json --out ./out
```

Produces `out/<name>.kicad_sym` and `out/<name>.pretty/COB_<name>.kicad_mod`.

Mapping:

| `.cob.json` | KiCad |
|---|---|
| `die` outline, notch, die pads | polygons on `F.SilkS` |
| `pcb.pads` copper polygon | custom SMD pad on `F.Cu`, pad number and name from the file |
| `pcb.pads` mask polygon | `fp_poly` on `F.Mask` (mask opening exactly as drawn) |
| `pcb.pads` with `paste` other than `none` | `F.Paste` added to the pad layers |
| `pcb.misc` with `kind: keepout` | rule area zone on the given `layers` |
| `pcb.misc` with `kind: cutout` | polygon on `Edge.Cuts` |
| `pcb.misc` any other kind | `fp_poly` on each of the given `layers` |
| `wires.items` | lines from die pad to bond target on `Dwgs.User` |
| die pads `electrical` | symbol pin type, default `passive` |

Every `pcb.misc` entry must carry a `layers` list with KiCad layer names.
Entries without it are rejected.

Options: `--out` output directory (default `.`), `--shapes` extra shape
catalog directories, `--lib` library nickname used in the symbol's
Footprint field (default `open_cob`).
