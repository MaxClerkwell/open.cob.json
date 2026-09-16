# open.cob.json

An open, canonical, machine-readable format for exchanging Chip-on-Board (COB)
wire-bonding information between chip designers and PCB designers.

> **Status: work in progress.** Nothing here is stable yet. Meaningful
> intermediate states will be frozen with git tags.

## The problem

When you design a chip, you send your GDS files to a manufacturer such as
[wafer.space](https://wafer.space). Some months later the bare dies come back,
and now you have to connect them to the outside world. Chip-on-Board wire
bonding is one way to do that: the die is glued directly onto the PCB and thin
wires are bonded from the chip pads to matching pads on the board.

I have done this many times myself and covered parts of the process in my
[KiCon talk](https://youtu.be/dNBwY7L6niI).

The hard question is not the bonding itself. It is: **how do you prepare the
PCB so that it can actually be bonded correctly?** Which chip pad goes to
which board pad? How long may a given wire become? What does the land pattern
look like, and where do cutouts and courtyards go? These questions are
surprisingly hard to answer, especially while the land pattern itself is still
undefined.

In every project I have worked on, this information existed, but it was
scattered across images, SVGs, PowerPoint slides, spreadsheets, electrical
specifications and geometric drawings. A typical bonding plan looks like this:

![A legacy bonding plan: chip photo with pad names, signal descriptions and colored wire lines, documented in a presentation slide](docs/legacy-bonding-plan-example.jpg)

It works, but it is not machine-readable, it drifts out of sync with the
design, and every project reinvents it.

## The observation

Designing the PCB, the bonding and the testing always follows the same
pattern. Each piece of information has one authoritative source:

| Information | Determined by |
|---|---|
| Where the chip pads are | the GDS files |
| Electrical properties of each pad (supply, I/O standard, bias, ESD, ...) | the chip designer's schematic |
| Pad metallization, and therefore wire material, bond force, temperature, ... | the manufacturing process |
| Wire length | the position of the matching pad on the PCB |
| Limits on wire length and loop shape | current load, EMC, differential vs. single-ended signalling |

From these inputs, a land pattern for the PCB, including cutouts and
courtyards, can be derived. So can bonding parameters and a test plan.

## The idea

A few years ago I started capturing this data for my own chips in JSON files.
This repository is an attempt to turn that into an open, canonical format,
`*.cob.json`, that:

- describes **chip pads**, **PCB pads** and **wire parameters** in one file,
  with reusable pad geometries in a catalog of `*.shape.cob.json` files,
- can be exchanged between chip designers, PCB designers and bonding services,
- is a sufficient input to **generate land patterns, bonding parameters and
  tests automatically**,
- is initially limited to **wire bonding**, but leaves room for other
  Chip-on-Board techniques such as flip-chip later on.

On 2026-09-15 I had a long conversation with Stuart Childs of wafer.space, who
encouraged me to write my thoughts on this down in an orderly way. This
repository is the result.

## Preliminary roadmap

This is a first sketch and will change.

1. **Write-up** of the problem, the data model and the design goals (this
   README and `docs/`).
2. **Draft data model**: define the entities (die, PCB, wires, assembly)
   and their relationships in prose. A first draft lives in
   [`docs/data-model-draft.md`](docs/data-model-draft.md).
3. **JSON Schema** for `*.cob.json`, versioned, with an explicit extension
   mechanism for future bonding techniques.
4. **Example files**. A fictional chip and three pad shapes live in
   [`examples/`](examples/). Files derived from real chips will follow.
5. **Visualizer**: [`tools/cobviz`](tools/cobviz/) renders a `*.cob.json`
   file as an SVG so a bonding plan can be checked by eye.
6. **Validator**: a small tool that checks a `*.cob.json` file against the
   schema and against physical constraints (wire length, pitch, angles).
7. **Land pattern generator**: derive PCB pads, cutouts and courtyards from a
   `*.cob.json` file.
8. **KiCad integration**: import a `*.cob.json` file directly as a footprint.
9. **Bonding parameter and test generation**.

Tags will mark the state after each step that is worth freezing.

## Tools

```bash
cd tools/cobviz
uv run cobviz --file ../../examples/demo-chip/<uuid>.cob.json --plot demo.svg
```

This is what the fictional demo chip in `examples/` looks like when
rendered by `cobviz`: die with notch and pads, die attach paddle, via
keepout, bond fingers with bond targets, two probe fingers, fiducials and
the wedge wires.

![cobviz rendering of the demo chip: a square die in the center, nine bond fingers around it, two of them with round probe areas, and blue bond wires](examples/demo-chip/demo.svg)

## Contributing

Ideas, questions and objections are welcome. Please open an issue or start a
discussion. Since the format is still being shaped, discussion is currently
more valuable than pull requests.

## License

This work, including the format specification, documentation, examples and
tools, is licensed under the
[Creative Commons Attribution 4.0 International License](https://creativecommons.org/licenses/by/4.0/)
(CC BY 4.0). See [`LICENSE`](LICENSE).

You may copy, modify, fork and use it commercially, as long as you credit
the original work and indicate if changes were made. Suggested attribution:

> open.cob.json by Stephan Bökelmann, https://github.com/MaxClerkwell/open.cob.json,
> licensed under CC BY 4.0.

## Author

Stephan Bökelmann, [maxclerkwell.tech](https://maxclerkwell.tech)
