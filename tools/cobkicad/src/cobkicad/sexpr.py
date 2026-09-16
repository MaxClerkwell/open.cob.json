"""Tiny s-expression writer."""
from __future__ import annotations

import uuid as _uuid


def q(s: str) -> str:
    return '"' + str(s).replace("\\", "\\\\").replace('"', '\\"') + '"'


def num(v: float) -> str:
    s = f"{v:.4f}".rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


def xy(p) -> str:
    return f"(xy {num(p[0])} {num(p[1])})"


def pts(poly) -> str:
    return "(pts " + " ".join(xy(p) for p in poly) + ")"


def new_uuid() -> str:
    return f"(uuid {q(_uuid.uuid4())})"
