# cobedit

Small Tkinter editor for `.cob.json` files. Shows the same geometry as
`cobviz` on a canvas and lets you add PCB pads by picking a shape and
clicking on the canvas.

```bash
cd tools/cobedit
uv run cobedit --file ../../examples/demo-chip/<uuid>.cob.json
```

Layout: a view toolbar along the top, canvas below it on the left,
toolbox of fixed width on the right with collapsible sections File, Wire
and PCB pads. The PCB pads section holds the pad tool at the top and the
list of existing pads at the bottom.

The toolbar holds the die mode (solid, translucent, outline; also `D`),
toggles for grid, die pads, pad names, PCB pads, mask, misc features and
wires, and the two fit buttons. The grid uses the snap spacing from the
PCB pad section and coarsens itself when zoomed out, the current spacing
is printed in the canvas corner. All sections start collapsed;
click a heading to open it, which closes the other sections. Starting a tool with `W` or by its button
opens its section.

Adding a pad:

1. Click **Add PCB pad**.
2. Pick a shape. The list shows the aliases from `pcb.shapes` and every
   `<uuid>.shape.cob.json` found in the shape catalog directories next to
   the file, plus `examples/shapes/` of this repository as a default.
   `--shapes DIR` (repeatable) adds other directories. Set number, name,
   rotation and scale.
3. Move the mouse over the canvas: the shape follows as a preview.
   `R` rotates by 90 degrees, `Escape` cancels.
4. Click to place. The pad is appended to `pcb.pads`. If the shape came
   from the catalog and has no alias yet, an alias is created in
   `pcb.shapes`.

Adding a wire:

1. Click **Add wire** or press `W`. Type, material and diameter in the
   Wire box are taken for every wire placed from now on.
2. Click a die pad, then a PCB pad. The wire is appended to `wires.items`
   with `loop`, `bond` and `mechanical` left `"unspecified"`; a line
   follows the mouse in between. Clicking another die pad changes the
   start. The tool stays active for the next wire, `Escape` ends it.
3. Wires are listed in the Wire box; selecting one highlights it,
   **Delete wire** removes it.

**Export KiCad...** asks for a directory and writes `<name>.kicad_sym` and
`open_cob.pretty/COB_<name>.kicad_mod` from the current state, using the
same generator as `cobkicad`. It works on unsaved changes.

With no tool active, pressing on a PCB pad in the canvas selects it and
dragging moves it; the new position snaps to the grid and is written to
`at` on release. Dragging an edge or corner of the selected pad resizes
it: the edge follows the mouse and `scale.x` / `scale.y` change
accordingly, the cursor shows which direction is grabbed. `R` rotates the
selected pad by 90°, `Shift+R` back, as do the -90° / +90° buttons. Selecting a pad in the list highlights it. Double click, `Enter` or
**Edit pad...** opens a dialog with every parameter of the pad: id,
number, name, shape alias, position, rotation, scale, finish, paste and
role, plus any other keys such as `limits` or `bond_target` as JSON.
Renaming the id updates the wires that point at the pad. **Delete pad**
removes it.
**Save** writes the file in place, **Save as** asks for a path.

On load the die is centered and scaled to 40 % of the canvas (**Fit die**).
Mouse: wheel zooms around the cursor, right or middle drag pans, `F` or
**Fit all** fits die and all PCB pads into the view. Translucent or
outline die mode lets copper underneath the die such as an attach paddle
be seen and placed. Snap to grid is 0.05 mm by default and can be changed
in the toolbox.
