"""Loading of .cob.json files and shape resolution."""
from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path

UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)

UNIT_TO_MM = {"mm": 1.0, "um": 0.001, "µm": 0.001, "mil": 0.0254, "in": 25.4}


def nominal(v) -> float:
    """Return the nominal value of a plain number, {nom,tol} or {min,typ,max}."""
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, dict):
        for k in ("nom", "typ", "max", "min"):
            if k in v:
                return float(v[k])
    raise ValueError(f"not a measurable value: {v!r}")


def scale_xy(v) -> tuple[float, float]:
    if v is None:
        return 1.0, 1.0
    return float(v.get("x", 1.0)), float(v.get("y", 1.0))


@dataclass
class Shape:
    name: str
    units: str
    origin: tuple[float, float]
    anchors: dict[str, tuple[float, float]]
    polygons: dict[str, list[list[tuple[float, float]]]]
    uuid: str | None = None

    @classmethod
    def from_dict(cls, d: dict) -> "Shape":
        origin = d.get("origin", {}).get("at", [0, 0])
        return cls(
            name=d.get("name", d.get("uuid", "?")),
            units=d.get("units", "mm"),
            origin=(float(origin[0]), float(origin[1])),
            anchors={k: (float(v[0]), float(v[1])) for k, v in d.get("anchors", {}).items()},
            polygons={
                role: [[(float(x), float(y)) for x, y in poly] for poly in polys]
                for role, polys in d.get("polygons", {}).items()
            },
            uuid=d.get("uuid"),
        )

    def unit_factor(self, target_units: str) -> float:
        return UNIT_TO_MM[self.units] / UNIT_TO_MM[target_units]


@dataclass
class Placement:
    at: tuple[float, float]
    rotation_deg: float = 0.0
    scale: tuple[float, float] = (1.0, 1.0)

    def apply(self, p: tuple[float, float], shape: Shape, target_units: str) -> tuple[float, float]:
        """Shape coordinates -> die coordinates."""
        f = shape.unit_factor(target_units)
        x = (p[0] - shape.origin[0]) * f * self.scale[0]
        y = (p[1] - shape.origin[1]) * f * self.scale[1]
        a = math.radians(self.rotation_deg)
        xr = x * math.cos(a) - y * math.sin(a)
        yr = x * math.sin(a) + y * math.cos(a)
        return self.at[0] + xr, self.at[1] + yr

    @classmethod
    def from_item(cls, item: dict) -> "Placement":
        at = item.get("at", [0, 0])
        return cls((float(at[0]), float(at[1])), float(item.get("rotation", 0)), scale_xy(item.get("scale")))


@dataclass
class Cob:
    path: Path
    data: dict
    units: str
    shapes: dict[str, Shape] = field(default_factory=dict)
    search_dirs: list[Path] = field(default_factory=list)

    @classmethod
    def load(cls, path: Path, extra_shape_dirs: list[Path] | None = None) -> "Cob":
        data = json.loads(path.read_text())
        units = data.get("units", {}).get("length", "mm")
        dirs = [path.parent, path.parent / "shapes", path.parent.parent / "shapes"]
        dirs += extra_shape_dirs or []
        cob = cls(path=path, data=data, units=units, search_dirs=[d for d in dirs if d.is_dir()])
        cob._load_local_shapes()
        return cob

    def _load_local_shapes(self) -> None:
        local = self.data.get("pcb", {}).get("shapes", {})
        if local in ("none", "unspecified", None):
            return
        for alias, ref in local.items():
            if isinstance(ref, str):
                self.shapes[alias] = self._load_catalog(ref)
            else:
                self.shapes[alias] = Shape.from_dict(ref)

    def _load_catalog(self, uuid: str) -> Shape:
        if uuid in self.shapes:
            return self.shapes[uuid]
        for d in self.search_dirs:
            f = d / f"{uuid}.shape.cob.json"
            if f.is_file():
                s = Shape.from_dict(json.loads(f.read_text()))
                if s.uuid and s.uuid.lower() != uuid.lower():
                    raise ValueError(f"{f}: uuid inside file does not match filename")
                self.shapes[uuid] = s
                return s
        raise FileNotFoundError(f"shape {uuid} not found in {[str(d) for d in self.search_dirs]}")

    def resolve(self, ref: str) -> Shape:
        if ref in self.shapes:
            return self.shapes[ref]
        if UUID_RE.match(ref):
            return self._load_catalog(ref)
        raise KeyError(f"unknown shape alias {ref!r}")

    # --- convenience accessors -------------------------------------------
    @property
    def die(self) -> dict:
        return self.data["die"]

    def die_pads(self) -> list[dict]:
        return self.die.get("pads", [])

    def pcb_pads(self) -> list[dict]:
        p = self.data.get("pcb", {}).get("pads", [])
        return p if isinstance(p, list) else []

    def misc(self) -> list[dict]:
        m = self.data.get("pcb", {}).get("misc", [])
        return m if isinstance(m, list) else []

    def wires(self) -> list[dict]:
        w = self.data.get("wires", {})
        items = w.get("items", []) if isinstance(w, dict) else []
        return items if isinstance(items, list) else []

    def die_pad_by_id(self, pid: str) -> dict | None:
        return next((p for p in self.die_pads() if p["id"] == pid), None)

    def pcb_pad_by_id(self, pid: str) -> dict | None:
        return next((p for p in self.pcb_pads() if p["id"] == pid), None)

    def placed_polygons(self, item: dict) -> dict[str, list[list[tuple[float, float]]]]:
        shape = self.resolve(item["shape"])
        pl = Placement.from_item(item)
        return {
            role: [[pl.apply(p, shape, self.units) for p in poly] for poly in polys]
            for role, polys in shape.polygons.items()
        }

    def bond_target(self, pad: dict) -> tuple[float, float]:
        if "bond_target" in pad:
            bt = pad["bond_target"]
            return float(bt[0]), float(bt[1])
        shape = self.resolve(pad["shape"])
        pl = Placement.from_item(pad)
        anchor = shape.anchors.get("bond_target", shape.anchors.get("center", shape.origin))
        return pl.apply(anchor, shape, self.units)
