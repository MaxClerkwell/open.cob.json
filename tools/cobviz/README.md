# cobviz

Renders a `.cob.json` file as an SVG: die outline and pads, PCB pads and
misc features from the shape catalog, and the bond wires between them.

```bash
cd tools/cobviz
uv run cobviz --file ../../examples/demo-chip/<uuid>.cob.json --plot demo.svg
```

Options:

- `--file` input `.cob.json` (required)
- `--plot` output SVG path (required)
- `--shapes` extra directory to search for `<uuid>.shape.cob.json` files.
  By default the input file's directory, `shapes/` and `../shapes/` next to
  it are searched.
- `--scale` pixels per unit, default 100
- `--no-labels` omit pad names

Y is up in the file and mirrored for SVG. The origin (die center) is marked
with a small cross.
