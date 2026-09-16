"""Per-PDK layer tables. Layer numbers are (layer, datatype)."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Pdk:
    name: str
    pad_layer: tuple[int, int]        # passivation opening
    label_layer: tuple[int, int]      # text labels naming the pads
    metal: str                        # pad metallization
    min_pad_um: float                 # smaller openings are not bond pads
    # substring of the I/O cell name -> symbol pin type
    cell_types: dict[str, str] = field(default_factory=dict)

    def electrical(self, cell_name: str | None) -> str | None:
        if not cell_name:
            return None
        n = cell_name.lower()
        for frag, typ in self.cell_types.items():
            if frag in n:
                return typ
        return None


PDKS: dict[str, Pdk] = {
    "gf180mcu": Pdk(
        name="gf180mcu",
        pad_layer=(37, 0),
        label_layer=(81, 10),
        metal="Al",
        min_pad_um=30.0,
        cell_types={
            "__bi_": "bidirectional",
            "__in_": "input",
            "__asig": "passive",
            "__dvdd": "power_in",
            "__dvss": "power_in",
            "__vdd": "power_in",
            "__vss": "power_in",
        },
    ),
    # untested: layer numbers from the sky130 PDK documentation
    "sky130": Pdk(
        name="sky130",
        pad_layer=(76, 20),
        label_layer=(72, 5),
        metal="Al",
        min_pad_um=30.0,
        cell_types={
            "gpiov2": "bidirectional",
            "gpio_ovt": "bidirectional",
            "xres": "input",
            "vddio": "power_in",
            "vssio": "power_in",
            "vdda": "power_in",
            "vssa": "power_in",
            "vccd": "power_in",
            "vssd": "power_in",
            "power": "power_in",
            "ground": "power_in",
        },
    ),
}
