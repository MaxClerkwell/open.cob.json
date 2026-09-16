# Data model draft

Working notes for the `*.cob.json` format. Everything here is preliminary
and will be superseded by a JSON Schema once the structure settles.

## Guiding principles

1. **One file describes exactly one delivered die.** The file is identified
   by a `uuid`. Same design, different die: new file, new UUID.
2. **Separate physics, electrics and presentation.** Die, PCB and wires are
   the product. Symbol and footprint styling are derived and optional. EDA
   tools read geometry and nets; test and QA read electrical and mechanical
   specifications.
3. **Explicit over implicit.** A missing key is always invalid. An empty
   object or array is always invalid. Absence is stated with `"none"`,
   missing knowledge with `"unspecified"`.
4. **Declarative, not routed.** Pads are truth, wires may be `"auto"`.
   Explicit loop paths are for importing real bond maps, not for v1.
5. **Open for extension.** Wire bonding first. Flip-chip and others later,
   without breaking existing files.
6. **One origin.** All coordinates in a `.cob.json` file are measured from
   the center of the die. Land pattern shapes live in separate
   `.shape.cob.json` files with their own arbitrary origin and are placed,
   rotated and scaled into the die coordinate system.

## Tolerances

Any measured quantity may be written in one of three forms:

| Form | Example | Use |
|---|---|---|
| plain number | `0.25` | nominal only, tolerance unknown or irrelevant |
| nominal plus symmetric tolerance | `{ "nom": 0.25, "tol": 0.05 }` | dimensions from a drawing |
| range | `{ "min": 0.18, "typ": 0.22, "max": 0.28 }` | process windows, limits |

Tolerances that apply to a whole file rather than to a single value live in
a top-level `tolerances` block:

```json
"tolerances": {
  "die_placement": { "xy_mm": 0.05, "rotation_deg": 0.5 },
  "pcb_fab": { "copper_feature_mm": 0.02, "mask_registration_mm": 0.05 }
}
```

Die placement is the most important one: a die placed 50 to 100 µm off
changes every wire landing point, so bond targets and loop clearances must be
checked against it. A validator uses `die_placement` to widen every wire's
landing region and `pcb_fab` to shrink every land pattern's guaranteed copper.

## `none` vs. `unspecified`

| Value | Meaning | Examples |
|---|---|---|
| `"none"` | deliberately absent, a valid design decision | no cutout, no paste, no adhesive, no shear test |
| `"unspecified"` | expected information that this file does not provide | land patterns, electrical specs, loop shape, adhesive process |

A test system must not try to measure something marked `none`. It must flag
something marked `unspecified` as a missing spec. Electrical specifications
can never be `none`: a wire always has electrical properties, they are either
given or not documented.

## Top-level structure

```json
{
  "schema": "cob.v1",
  "uuid": "8f3c1a2e-4b9d-4e21-9c7a-0d5b6e1f2a44",
  "meta": { "name": "XYZ123", "revision": "A" },
  "units": { "length": "mm", "angle": "deg", "origin": "die_center", "axis": { "x": "right", "y": "up" } },
  "tolerances": { },

  "die": { },
  "pcb": { },
  "wires": { },
  "assembly": { }
}
```

| Block | Truth about | Typical contents |
|---|---|---|
| `die` | the chip | size, thickness, notch, die pads, pad metal, orientation |
| `pcb` | the board under and around the chip | local shapes, placed pads, misc features on any layer: mask openings, cutouts, keepouts, required copper |
| `wires` | the connection between both | from/to, type, loop, bond parameters, mechanical and electrical specs, differential pairs |
| `assembly` | the process | die attach, bonding, tempering, encapsulation, module mounting, sequence |

`die`, `pcb` and `wires` are mandatory objects. `assembly` is mandatory once
the file is a delivery artifact and may be `"unspecified"`.

A **die-only file** is the minimal valid delivery from a chip designer: the
`die` block is complete, and `pcb.pads`, `pcb.misc`, `wires.items`,
`wires.pairs`, `wires.electrical_specifications`, `tolerances` and
`assembly` are all `"unspecified"`. `pcb.shapes` is `"none"`. This is what
`tools/cobgen` produces from a layout.

Coordinates: `units` is declared once per file and applies to every value in
it. Origin is always the die center, Y up. Export to KiCad mirrors Y.

## `die`

Only the chip. No cutout, no vias, no land pattern here.

```json
"die": {
  "size": [{ "nom": 2.40, "tol": 0.02 }, { "nom": 1.80, "tol": 0.02 }],
  "thickness": { "nom": 0.30, "tol": 0.03 },
  "offset": [0, 0],
  "rotation": 0,
  "notch": { "side": "top-left", "size": [0.15, 0.15] },
  "pads": [
    {
      "id": "D1",
      "name": "VDD",
      "center": [-1.05, 0.70],
      "center_tol": 0.002,
      "size": [0.08, 0.08],
      "shape": "rect",
      "metal": "Al",
      "opening": [0.07, 0.07],
      "side": "top",
      "electrical": "power_in",
      "bond": { "allowed_types": ["wedge"], "min_pad_opening_um": 70 }
    }
  ]
}
```

Per pad mandatory: stable `id` (never just a number), `center`, `size`,
`shape`, `name`. `name` may be `"unspecified"` when the layout carries no
label for the pad. An optional `source` object records where the pad came
from, for example the I/O cell name and whether a label was found. `electrical` is the pin type for the schematic symbol:
`input | output | bidirectional | tri_state | passive | power_in |
power_out | open_collector | open_emitter | no_connect`. It defaults to
`passive`. `size` and `thickness` carry the dicing and wafer
tolerances. `center_tol` is the pad position tolerance from lithography and
is usually negligible against die placement. Useful: `metal`, passivation `opening`, `side` for
auto-routing, optional `polarity` for differential signals. Several pads may
share a name (ground bus). Unbonded pads are still documented.

## `pcb`

```json
"pcb": {
  "shapes": { },
  "pads": [ ],
  "misc": [ ]
}
```

All three keys are mandatory. `pads` and `misc` are `"unspecified"` or a
non-empty array. `shapes` may be `"none"` if every pad and misc entry
references the catalog by UUID directly.

### Shapes come from a catalog

Every pad and every misc item has a geometry. The geometry is a shape, and
shapes live in `<uuid>.shape.cob.json` files, the shape catalog. A
`.cob.json` file references them by UUID and places, rotates and scales
them into die coordinates.

`pcb.shapes` maps a local alias to either a catalog UUID or an inline
geometry. Inline geometries have exactly the structure of a shape file
minus `schema` and `uuid`.

```json
"shapes": {
  "FINGER":  "27c699bd-b041-4152-87ee-cbbbf485375b",
  "PADDLE":  "038fdaa7-78c0-4a06-8ae1-31ecf67957ea",
  "MASK_STRIP": {
    "name": "local mask opening",
    "units": "mm",
    "origin": { "at": [0, 0], "meaning": "center" },
    "anchors": { "center": [0, 0] },
    "polygons": { "mask": [ [[-1.0, -0.2], [1.0, -0.2], [1.0, 0.2], [-1.0, 0.2]] ] },
    "tolerances": { "vertex_mm": 0.02 }
  }
}
```

A `shape` field on a pad or misc item is then one of:

- a local alias from `pcb.shapes`,
- a catalog UUID directly.

An alias may not shadow a UUID, and an alias must not itself look like a
UUID. Inline geometries are for one-off local features. Anything reusable
belongs in the catalog.

### Shape files: `<uuid>.shape.cob.json`

A shape file contains geometry only, similar to an SVG: named polygons per
layer, an origin, anchors and a vertex tolerance. No electrical meaning, no
process, no net. The same shape can be used by any number of `.cob.json`
files.

```json
{
  "schema": "cob.shape.v1",
  "uuid": "27c699bd-b041-4152-87ee-cbbbf485375b",
  "name": "finger_wedge_narrow",
  "description": "Narrow bond finger. Origin is the bond target. Finger extends toward +x.",
  "units": "mm",
  "origin": { "at": [0, 0], "meaning": "bond_target" },
  "anchors": { "bond_target": [0, 0], "inner_end": [-0.15, 0], "outer_end": [0.85, 0] },
  "polygons": {
    "copper": [ [[x, y], [x, y], ...] ],
    "mask":   [ [[x, y], [x, y], ...] ]
  },
  "tolerances": { "vertex_mm": 0.02 }
}
```

- `units` is declared once per shape file and applies to every coordinate
  in it, exactly like `units` in a `.cob.json` file. The importer converts
  to the `.cob.json` unit before scaling and placing. Mixed units inside one
  file are not allowed.
- The origin is arbitrary and chosen by the shape author. It is the point
  that is placed at the item's `at` position in the `.cob.json` file and the
  center of rotation and scaling. For fingers the bond target is the natural
  choice, for paddles the center.
- `anchors` are named points in shape coordinates. `bond_target` is
  mandatory for shapes used by bonded pads. A `.cob.json` file may reference
  anchors, for example to place a probe needle or to derive the wire landing
  point.
- `polygons` is keyed by layer role: `copper`, `mask`, `paste`, `cutout`,
  `keepout`, `silk`, `fab`, `courtyard`. Each role holds a list of closed
  polygons, vertices in order, first vertex not repeated. Curves are
  approximated as vertices, the shape author picks the resolution. A pad
  shape needs `copper`; if `mask` is absent, mask follows copper by the
  fab's default expansion.
- Convention for fingers: +x points away from the die. The `.cob.json`
  rotation then makes fingers on all four sides point outward.
- `tolerances.vertex_mm` is the accuracy the polygon claims. A validator
  adds it to `pcb_fab.copper_feature_mm` when checking clearances.

### Pads

Pads are the electrically relevant copper features: bond fingers, the die
attach paddle, probe pads. Each pad places a shape.

```json
{
  "id": "P1",
  "number": "1",
  "name": "VDD",
  "shape": "FINGER",
  "scale": { "x": 1.0, "y": 1.2 },
  "at": [-2.4, 2.1],
  "rotation": 90,
  "finish": "ENIG",
  "paste": "none",
  "role": "bond_finger",
  "limits": { "min_pitch": 0.40, "min_copper_clearance": 0.15 }
}
```

- `shape`: alias or UUID. `scale` scales the shape about its origin, X and
  Y may differ, anchors scale along. Default `{ "x": 1, "y": 1 }`.
- `at` is where the shape origin lands in die coordinates, `rotation` turns
  the shape about that origin.
- `role`: `bond_finger | die_attach | probe | other`. `paste`: `none |
  expand | defined`, bond fingers are `none`.
- `limits` are optional and stated in die coordinates, they do not scale.
- `bond_target` on the pad is optional and otherwise taken from the shape's
  anchor after scaling and rotation.

Three things must not be confused: the die pad (metal on the chip), the
bond target (where the wire lands) and the PCB pad (copper, mask, paste,
drill).

### Misc

Everything on the PCB that is not a pad but must be there, or must not be
there, for the COB to work: mask openings, cutouts, via keepouts, required
copper, fiducials, silk. Each entry places a shape on one or more layers
and says what it means. `layers` is mandatory for every misc entry and
uses KiCad layer names (`F.Cu`, `F.Mask`, `F.SilkS`, `Edge.Cuts`,
`Dwgs.User`, `*.Cu`, ...). Pads do not carry a layer: their copper is
always on `F.Cu`, their mask polygon on `F.Mask`. The die itself is
rendered on `F.SilkS`.

```json
"misc": [
  {
    "id": "NO_VIA_UNDER_DIE",
    "kind": "keepout",
    "forbids": ["via", "microvia", "pth"],
    "layers": ["*.Cu"],
    "shape": "PADDLE",
    "scale": { "x": 1.05, "y": 1.05 },
    "at": [0, 0],
    "rotation": 0
  },
  {
    "id": "CU_UNDER_DIE",
    "kind": "copper_required",
    "net": "GND",
    "layers": ["F.Cu"],
    "satisfied_by": "EP",
    "shape": "PADDLE",
    "at": [0, 0]
  },
  {
    "id": "MASK_OPEN_BOND_ROW",
    "kind": "mask_opening",
    "layers": ["F.Mask"],
    "shape": "MASK_STRIP",
    "at": [0, 1.6],
    "rotation": 0
  },
  {
    "id": "CAVITY",
    "kind": "cutout",
    "implementation": "npth_slot",
    "shape": "PADDLE",
    "scale": { "x": 0.9, "y": 0.9 },
    "at": [0, 0]
  }
]
```

`kind` values so far:

| kind | meaning | extra fields |
|---|---|---|
| `mask_opening` | solder mask removed here | |
| `cutout` | hole or slot in the board | `implementation`: `npth_slot \| edge_cuts` |
| `keepout` | items forbidden inside | `forbids`: `via \| microvia \| pth \| copper \| footprint` |
| `copper_required` | copper must exist here | `net`, `min_coverage`, optional `satisfied_by` pad id |
| `fiducial` | optical alignment mark | |
| `silk`, `fab`, `courtyard` | documentation graphics | |

Rules: a `cutout` and a `copper_required` on the same layer may not
overlap. A conductive die attach in `assembly` requires a `copper_required`
or a `die_attach` pad on its net under the die. Which layer a shape's
polygons apply to is fixed by the misc entry's `layers`, not by the polygon
role, so a plain `copper` polygon can serve as a mask opening or a keepout.

## `wires`

An object, not a bare array: items plus specs plus pairs plus defaults.

```json
"wires": {
  "defaults": { "by_combination": [ ] },
  "items": [ ],
  "pairs": "none",
  "electrical_specifications": "unspecified"
}
```

### Wire item

```json
{
  "id": "W1",
  "from": { "die_pad": "D1" },
  "to": { "pcb_pad": "P1" },
  "type": "wedge",
  "material": "Al",
  "diameter_um": 25,
  "loop": {
    "shape": "standard",
    "height": { "nom": 0.25, "tol": 0.05 },
    "max_height": 0.35,
    "length": { "max": 2.0 },
    "clearance_to_die": 0.05
  },
  "bond": {
    "first":  { "site": "die", "process": "ultrasonic_wedge",
                "force_n": { "min": 0.18, "typ": 0.22, "max": 0.28 },
                "time_ms": { "typ": 20 }, "ultrasonic": { "power": 0.35, "unit": "relative" }, "tool": "wedge_30" },
    "second": { "site": "pcb", "process": "ultrasonic_wedge",
                "force_n": { "typ": 0.26 }, "time_ms": { "typ": 25 } }
  },
  "mechanical": {
    "pull": { "required": true, "method": "destructive_pull", "sample": "lot", "min_force_n": 0.03,
              "break_mode_allowed": ["neck"], "break_mode_forbidden": ["pad_lift", "interface", "cratering"] },
    "shear": "none"
  },
  "process_ref": "assembly.wire_bond"
}
```

- `from` and `to` reference `die.pads[].id` and `pcb.pads[].id`. 1:n and
  n:1 are allowed (double bonds, ground stars).
- `type`: `ball | wedge | ribbon`.
- `loop`: object or `"unspecified"`, always present. Everything about the
  wire's geometry in space lives here and nowhere else: `shape`, `height`,
  `max_height`, `length`, `clearance_to_die`, `span`, `kink`, `path`.
  `height` carries a tolerance because bonders do not hit it exactly.
  `max_height` is the hard ceiling from encapsulation, lids or neighbors.
  `length` is the allowed wire length as a range. The actual length follows
  from die pad, bond target, loop and die placement tolerance. A validator
  checks the worst case, not the nominal. Shapes: `standard`
  (first bond on die), `reverse` (first bond on PCB), `low`, `high`,
  `squared`, `stitched`, `custom` (explicit `path` of xyz points, mandatory
  for custom only).
- `bond`: object or `"unspecified"`. `first` always refers to `from`,
  `second` to `to`. Bond parameters look like machine setup but are part of
  the wire specification.
- `mechanical`: object or `"unspecified"`. `pull` is an object or `"none"`.
  Methods: `destructive_pull | non_destructive_pull | tweezer_pull |
  ball_shear | wedge_shear`. `sample`: `each | lot | setup`.

### Defaults by material combination

Bond parameters follow from die pad metal, PCB finish and wire. Describe the
combination once, wires inherit and may override.

```json
"defaults": {
  "by_combination": [
    {
      "id": "AL25_WEDGE_ALPAD_ENIG",
      "when": { "wire": { "type": "wedge", "material": "Al", "diameter_um": 25 },
                "die_pad": { "metal": "Al" }, "pcb_pad": { "finish": "ENIG" } },
      "bond": { "first": { "force_n": { "typ": 0.22 } }, "second": { "force_n": { "typ": 0.26 } } },
      "mechanical": { "pull": { "method": "destructive_pull", "min_force_n": 0.03 } }
    }
  ]
}
```

Resolution: pick the matching combination, merge the wire's own `bond` and
`mechanical` on top. If nothing matches and the wire has no override, `bond`
must be `"unspecified"`, never silently empty.

### Electrical specifications

Either `"unspecified"` globally, or an array with exactly one entry per wire
(plus optional entries per pair). Per-wire entries are either a full spec or
`{ "wire": "W3", "specification": "unspecified" }`. A missing wire in the
array is invalid.

```json
{
  "wire": "W1",
  "net": "VDD",
  "measure": { "high": { "pad": "P1" }, "low": { "die_pad": "D1" } },
  "test": {
    "continuity": { "required": true, "max_resistance_ohm": 0.35, "method": "4wire" },
    "isolation":  { "required": true, "against": ["OUT", "GND"], "min_resistance_ohm": 1e8, "voltage_v": 50 }
  },
  "limits": { "max_current_a": 0.25, "max_voltage_v": 5.5, "max_dc_resistance_ohm": 0.35 }
}
```

### Differential pairs

`+`/`-` in names is fine for humans and symbols, but never the source of
truth. A pair is an explicit relation between two wires. `pairs` is
`"none"`, `"unspecified"` or a non-empty array.

```json
{
  "id": "DP_OUT",
  "kind": "differential",
  "positive": { "wire": "W4" },
  "negative": { "wire": "W5" },
  "matched": { "loop_shape": true, "loop_height": true, "wire_type": true, "diameter_um": true, "mechanical": true },
  "electrical": { "zdiff_ohm": { "min": 90, "typ": 100, "max": 110 }, "skew_ps": { "max": 5 },
                  "length_match_mm": { "max": 0.10 }, "common_mode_net": "GND" }
}
```

DC tests stay on the individual wire. Differential quantities and matching
live on the pair. Optional `polarity` on pads must agree with the pair.

## `assembly`

Attachment and tempering are process, not geometry. `assembly` is the
manufacturing sequence that turns die, pcb and wires into a COB.

```json
"assembly": {
  "die_attach": {
    "method": "conductive_epoxy",
    "product": "Ablebond 84-1LMI",
    "conductive": true,
    "net": "GND",
    "dispense": { "pattern": "cross", "dots": 5, "volume_ul": 0.08, "keepout_from_die_edge": 0.10 },
    "bondline_um": { "min": 20, "typ": 40, "max": 80 },
    "surface": { "needs_copper": true, "finish": ["ENIG", "bare_cu"] },
    "cure": { "temperature_c": { "min": 140, "typ": 150, "max": 160 }, "time_min": { "min": 55, "typ": 60, "max": 90 }, "atmosphere": "air" },
    "temper": "none"
  },
  "wire_bond": {
    "method": "al_wedge",
    "atmosphere": "air",
    "plasma_clean": { "required": true, "when": "before_bond", "gas": "Ar/O2", "time_s": 30 },
    "temper": { "required": true, "when": "after_bond", "temperature_c": 150, "time_min": 60,
                "atmosphere": "N2", "purpose": "stress_relief" }
  },
  "post": {
    "encapsulate": { "method": "glob_top", "product": "Dam-and-Fill epoxy",
                     "cure": { "temperature_c": 125, "time_min": 90 }, "temper": "none" }
  },
  "module_mount": "none",
  "sequence": ["pcb_clean", "die_attach", "die_attach.cure", "plasma_clean", "wire_bond", "wire_bond.temper", "encapsulate"]
}
```

- Two different attachments, never mixed: die to PCB (`die_attach`) and
  finished COB to carrier (`module_mount`: adhesive, screws, socket, none).
- `die_attach.method`: `none | nonconductive_epoxy | conductive_epoxy |
  sinter_silver | eutectic | solder | unspecified`.
- Tempering always belongs to a step, never as a loose top-level flag.
  `purpose`: `cure | post_cure | stress_relief | anneal | none`. `when`:
  `before_attach | after_attach | before_bond | after_bond | after_encapsulate`.
- `sequence` is the only place that defines order. Every token must point to
  a specified step. A step marked `"none"` may not appear in the sequence.
- A conductive adhesive on a net requires copper under the die on that net.
- Cure and temper temperatures and times are process windows, so they are
  written as ranges. `bondline_um` is a range for the same reason.

## What the generators derive

| From | KiCad symbol | KiCad footprint | Test / production |
|---|---|---|---|
| `pcb.pads` number, shape, position | one pin per PCB pad | custom pad on F.Cu, mask polygon on F.Mask | |
| `die` outline, notch, die pads | | polygons on F.SilkS | |
| `die.pads[].electrical` | pin type | | |
| `die` outline and pads | | graphics on Fab/User layers | |
| `wires.items` | | lines on a user layer, courtyard incl. loop overhang, optional pad die_length | bonder program after merging defaults |
| `pcb.misc` keepout | | rule area | DRC |
| `pcb.misc` cutout | | NPTH slot or Edge.Cuts graphic | milling |
| `pcb.misc` mask opening, silk, fab | | graphics on the named layers | |
| `wires.electrical_specifications`, `pairs` | pin names, differential net classes | | continuity, isolation, skew tests |
| `wires.items[].mechanical` | | | pull and shear tests |
| `assembly` | | at most Fab text | oven, plasma, adhesive, order |

## Validation rules collected so far

- `uuid` mandatory, UUID v4.
- `die`, `pcb`, `wires` mandatory, none of them `{}` or `[]`.
- `die.pads` non-empty. IDs unique across the file.
- `pcb.shapes`, `pcb.pads`, `pcb.misc` present. Every `shape` reference
  resolves to an alias or a catalog UUID. Aliases never look like UUIDs.
- A shape used by a bonded pad has a `bond_target` anchor. Finger pitch
  must respect `limits.min_pitch`. Paste `none` on bond fingers.
- `wires.items` non-empty or `"unspecified"`. Every item has `loop`, `bond` and `mechanical`
  as objects or `"unspecified"`. `custom` loops need a `path`.
- `electrical_specifications`: `"unspecified"` or exactly one entry per
  wire. `[]` and `{}` invalid.
- Pair members must exist; matched fields must actually match; pad polarity
  must agree with the pair.
- Cutout and required copper on the same layer exclude each other.
  Conductive adhesive requires copper on its net under the die.
- `sequence` tokens must reference specified steps.
- Every catalog UUID must resolve to a shape file whose `uuid` matches.
  `scale.x` and `scale.y` must be positive.
- Bond target of every placed finger, widened by `die_placement.xy_mm`,
  must lie on the guaranteed copper, i.e. the scaled copper polygon shrunk
  by `pcb_fab.copper_feature_mm` plus the shape's `vertex_mm`.
- Worst-case wire length (nominal plus die placement offset) must respect
  `loop.length.max`. Worst-case loop height (`height.nom + height.tol`)
  must not exceed `loop.max_height`.

## Examples

- `examples/demo-chip/` holds a complete `.cob.json` for a fictional 9-pad
  chip, `OCJ-DEMO1`, with a differential output, two ground pads and a
  conductive die attach.
- `examples/shapes/` holds three shape files: a narrow wedge finger, a
  finger with a round probe area at the outer end, and a square die attach
  paddle. The demo chip stretches the probe finger by 1.2 in Y, shrinks the
  paddle to 0.95 for the attach pad and reuses it enlarged as via keepout.

## Open questions

- Face-up vs. face-down orientation and how flip-chip would extend
  `wires` or replace it.
- Whether shape files should allow arcs instead of only polygon vertices.
- Extension mechanism: reserved `x-` keys, or a `extensions` object per
  block.
