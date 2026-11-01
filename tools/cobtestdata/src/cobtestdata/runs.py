"""Known wafer.space shuttle runs: where the reticle parts live and how to verify them."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Run:
    key: str
    repo: str          # GitHub owner/name
    shuttle: str       # reticle file stem, e.g. G802
    parts: tuple[str, ...]
    md5: str           # from layout/create-reticle-oas.sh in the run repo
    manifest: str = "data/manifest.csv"

    @property
    def raw(self) -> str:
        return f"https://raw.githubusercontent.com/{self.repo}/main"


RUNS: dict[str, Run] = {
    "1": Run(
        key="1",
        repo="wafer-space/ws-run1",
        shuttle="G801",
        parts=("aa", "ab", "ac", "ad"),
        md5="3ae7349e205f60d9f997cf7d3a688500",
    ),
    "2": Run(
        key="2",
        repo="wafer-space/ws-run2",
        shuttle="G802",
        parts=("aa", "ab"),
        md5="57fa57f52eac82835a051f2a353e5a30",
    ),
}
