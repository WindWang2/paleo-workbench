"""Parser for SMI WellTops .dat files (井分层)."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class WellTop:
    well_name: str
    top_name: str
    md: float
    tvd: float | None = None


def parse_well_tops(path: str | Path) -> list[WellTop]:
    """Parse an SMI WellTops .dat file into WellTop rows.

    Format: ``#`` comment/header lines, then whitespace-separated columns
    ``WellName Name MD X Y Z TVD Time(ms)``. Tolerant of CRLF, blank lines
    and short/garbage rows (skipped).
    """
    tops: list[WellTop] = []
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        tokens = stripped.split()
        if len(tokens) < 3:
            continue
        try:
            md = float(tokens[2])
        except ValueError:
            continue
        tvd = None
        if len(tokens) >= 7:
            try:
                tvd = float(tokens[6])
            except ValueError:
                tvd = None
        tops.append(WellTop(well_name=tokens[0], top_name=tokens[1], md=md, tvd=tvd))
    return tops
