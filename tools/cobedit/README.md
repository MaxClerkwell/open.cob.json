# cobedit

Small Tkinter editor for `.cob.json` files. Shows the same geometry as
`cobviz` on a canvas and lets you add PCB pads by picking a shape and
clicking on the canvas.

```bash
cd tools/cobedit
uv run cobedit --file ../../examples/demo-chip/<uuid>.cob.json
```

Layout: canvas on the left, full height. Toolbox on the right with file
actions, the pad tool and the list of existing PCB pads.

Adding a pad:

1. Click **Add PCB pad**.
2. Pick a shape. The list shows the aliases from `pcb.shapes` and every
   `<uuid>.shape.cob.json` found in the shape catalog directories next to
   the file. Set number, name, rotation and scale.
3. Move the mouse over the canvas: the shape follows as a preview.
   `R` rotates by 90 degrees, `Escape` cancels.
4. Click to place. The pad is appended to `pcb.pads`. If the shape came
   from the catalog and has no alias yet, an alias is created in
   `pcb.shapes`.

**Export KiCad...** asks for a directory and writes `<name>.kicad_sym` and
`open_cob.pretty/COB_<name>.kicad_mod` from the current state, using the
same generator as `cobkicad`. It works on unsaved changes.

Selecting a pad in the list highlights it. **Delete pad** removes it.
**Save** writes the file in place, **Save as** asks for a path.

Mouse: wheel zooms around the cursor, right or middle drag pans,
`F` fits the view. Snap to grid is 0.05 mm by default and can be changed
in the toolbox.
