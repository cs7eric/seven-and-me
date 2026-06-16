"""TDX .day file loader for the market-data warehouse.

The TDX installation stores per-stock daily bars under
``<vipdoc>/<market>/lday/<market><code>.day``.  ``vipdoc`` may contain
three market subtrees: ``sh``, ``sz``, ``bj``.  This module enumerates them
and yields ``DayFile`` records; it does NOT itself parse (that's
``tdx_parser``) or download from the network (mootdx hooks live elsewhere).

For a one-shot backfill this is enough: point ``HSJDAY_ROOT`` at the
user's local TDX installation and walk it.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

# Repo-relative default; override with constructor arg.
_HSJDAY_ROOT = Path(__file__).resolve().parents[1] / "reference" / "tdx" / "day" / "hsjday"


@dataclass(frozen=True)
class DayFile:
    code: str          # 6-digit, no market prefix (e.g. "000001")
    market: str        # "sh" | "sz" | "bj"
    path: Path
    size: int          # bytes on disk

    @property
    def filename(self) -> str:
        return self.path.name

    @property
    def record_count(self) -> int:
        """Approximate record count assuming 32-byte records."""
        return self.size // 32


def set_default_root(path: Path | str) -> None:
    global _HSJDAY_ROOT
    _HSJDAY_ROOT = Path(path)


def get_default_root() -> Path:
    return _HSJDAY_ROOT


def _market_to_prefix(market: str) -> str:
    m = market.lower()
    if m not in {"sh", "sz", "bj"}:
        raise ValueError(f"unsupported market: {market}")
    return m


def iter_day_files(root: Path | str | None = None,
                   markets: tuple[str, ...] = ("sh", "sz", "bj"),
                   skip_zero_byte: bool = True) -> Iterator[DayFile]:
    """Yield every .day file under ``root/{market}/lday/*.day``."""
    root = Path(root) if root else _HSJDAY_ROOT
    for market in markets:
        lday = root / market / "lday"
        if not lday.is_dir():
            continue
        prefix = _market_to_prefix(market)
        for p in sorted(lday.glob(f"{prefix}*.day")):
            size = p.stat().st_size
            if skip_zero_byte and size == 0:
                continue
            code = p.stem[len(prefix):]
            yield DayFile(code=code, market=market, path=p, size=size)


def list_codes(root: Path | str | None = None,
               markets: tuple[str, ...] = ("sh", "sz", "bj")) -> list[DayFile]:
    """Materialize the iterator into a list (use only for small enumerations)."""
    return list(iter_day_files(root=root, markets=markets))


# ----- CLI ----------------------------------------------------------------

if __name__ == "__main__":
    import sys
    from collections import Counter

    files = list(iter_day_files())
    by_market = Counter(f.market for f in files)
    total_bytes = sum(f.size for f in files)
    total_records = sum(f.record_count for f in files)
    print(f"root: {get_default_root()}")
    print(f"files: {len(files)}")
    for m in ("sh", "sz", "bj"):
        if m in by_market:
            sub = [f for f in files if f.market == m]
            mb = sum(f.size for f in sub) / 1024 / 1024
            print(f"  {m}: {len(sub):>5d} files, {mb:>7.1f} MB")
    print(f"  TOTAL: {total_bytes/1024/1024:>7.1f} MB, ~{total_records:,} records")
    print()
    print("largest 5:")
    for f in sorted(files, key=lambda x: -x.size)[:5]:
        print(f"  {f.filename}  {f.size:>9d} bytes  ~{f.record_count:>6d} days")
    print("smallest 5 (excluding zero):")
    nonempty = [f for f in files if f.size > 0]
    for f in sorted(nonempty, key=lambda x: x.size)[:5]:
        print(f"  {f.filename}  {f.size:>9d} bytes  ~{f.record_count:>6d} days")