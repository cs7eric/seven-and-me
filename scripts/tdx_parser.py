"""TDX .day file parser for the market-data warehouse.

Format (32 bytes / record, little-endian):
    0-3    uint32   date              YYYYMMDD
    4-7    uint32   open              actual * 1000
    8-11   uint32   high              actual * 1000
   12-15   uint32   low               actual * 1000
   16-19   uint32   close             actual * 1000
   20-23   float32  amount (yuan)
   24-27   uint32   volume (lots)
   28-31   uint32   prev_close        actual * 1000 (often a sentinel; see below)

Sentinel values for prev_close (treated as missing):
    0
    0x00010000 == 65536 (observed in sz302132.day; not in the spec guide)

Unit scale bug (TDX side, observed in sz302132.day):
    On some stocks TDX writes prices as (actual_price / 10) * 1000 instead of
    actual_price * 1000. The .day file's open/high/low/close raw values are
    therefore 1/10 of what they should be in 元. We detect this by comparing
    a sample close against an authoritative API source (East Money / Tencent).
"""
from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator

import pandas as pd

_RECORD_FMT = '<IIIIIfII'   # 8 fields × 4 bytes = 32 bytes
_RECORD_SIZE = 32

# prev_close sentinels seen in real TDX .day files.
PREV_CLOSE_SENTINELS: set[int] = {0, 0x00010000}

# Candidate unit scales tested during self-healing. 10 corresponds to the
# observed sz302132 bug; 1 is the normal case. 100 is paranoia.
_UNIT_SCALE_CANDIDATES: tuple[int, ...] = (1, 10, 100)


@dataclass
class DayParseResult:
    """Parsed + healed daily bars for one TDX .day file."""
    code: str
    df: pd.DataFrame                  # OHLCV in 元 (post unit-scale correction)
    unit_scale: int                   # 1 / 10 / 100, applied to OHLC
    prev_close_raw_kept: pd.Series    # original prev_close field (rarely populated)


def _parse_raw(buffer: bytes) -> pd.DataFrame:
    if len(buffer) % _RECORD_SIZE != 0:
        raise ValueError(f"file size {len(buffer)} is not a multiple of {_RECORD_SIZE}")

    rows = []
    for off in range(0, len(buffer), _RECORD_SIZE):
        date_int, o, h, l, c, amount, volume, prev = struct.unpack(
            _RECORD_FMT, buffer[off:off + _RECORD_SIZE]
        )
        rows.append((date_int, o, h, l, c, amount, volume, prev))
    df = pd.DataFrame(rows, columns=[
        'date_int', 'open_raw', 'high_raw', 'low_raw', 'close_raw',
        'amount', 'volume', 'prev_raw',
    ])
    df['date'] = pd.to_datetime(df['date_int'].astype(str), format='%Y%m%d')
    return df


def apply_unit_scale(df: pd.DataFrame, scale: int) -> pd.DataFrame:
    """Divide OHLC raw values by `scale` to get 元."""
    for col in ('open_raw', 'high_raw', 'low_raw', 'close_raw'):
        df[col] = df[col] / scale
    return df


def detect_unit_scale(close_raw_series: pd.Series, api_close: float | None) -> int:
    """Pick the unit_scale that best matches an external authoritative close.

    `close_raw_series` is the raw uint32 column from the .day file (still
    needs to be divided by 1000 to get the on-disk unit, whatever that unit
    is). `api_close` is the real, unadjusted close in 元 from the network.

    Returns 1, 10, or 100. If `api_close` is missing or zero, returns 1 (the
    spec default) so we don't accidentally over-correct.
    """
    if api_close is None or api_close <= 0 or len(close_raw_series) == 0:
        return 1
    last_raw = float(close_raw_series.iloc[-1])
    last_on_disk = last_raw / 1000.0
    ratio = api_close / last_on_disk if last_on_disk > 0 else 0
    for s in _UNIT_SCALE_CANDIDATES:
        # if ratio ≈ s (within 5%), this is the right scale
        if abs(ratio - s) / max(s, 1e-9) < 0.05:
            return s
    return 1


def parse_day_file(file_path: Path, api_close: float | None = None) -> DayParseResult:
    """Parse a single TDX .day file. If api_close is given, auto-correct
    unit_scale and return the OHLC in 元. Otherwise returns OHLC in the file's
    native unit (÷ 1000).
    """
    buf = file_path.read_bytes()
    raw = _parse_raw(buf)

    unit_scale = detect_unit_scale(raw['close_raw'], api_close)

    df = pd.DataFrame({
        'code': file_path.stem[2:],          # strip 'sz'/'sh' prefix
        'trade_date': raw['date'].dt.date,
        # File spec: raw = actual_price * 1000.  unit_scale=N (e.g. 10) means the
        # file actually stores raw = actual_price * (1000 / N), so to recover the
        # real 元 we multiply the spec value by N (i.e. divide by 1000 then × N).
        'open':   raw['open_raw']  / 1000.0 * unit_scale,
        'high':   raw['high_raw']  / 1000.0 * unit_scale,
        'low':    raw['low_raw']   / 1000.0 * unit_scale,
        'close':  raw['close_raw'] / 1000.0 * unit_scale,
        'volume': raw['volume'].astype('int64'),
        'amount': raw['amount'].astype('float64'),
        'unit_scale': unit_scale,
        'source': 'tdx_day',
    })
    prev_kept = raw['prev_raw'].copy()
    prev_kept[prev_kept.isin(PREV_CLOSE_SENTINELS)] = None

    return DayParseResult(
        code=df['code'].iloc[0],
        df=df,
        unit_scale=unit_scale,
        prev_close_raw_kept=prev_kept,
    )


def parse_day_files(files: Iterable[Path], api_close_lookup=None) -> Iterator[DayParseResult]:
    """Generator over multiple .day files. `api_close_lookup(code) -> float|None`
    is optional; pass None to skip auto-scaling.
    """
    for fp in files:
        api = api_close_lookup(fp.stem[2:]) if api_close_lookup else None
        yield parse_day_file(fp, api_close=api)


# ----- DuckDB write helper ------------------------------------------------

def to_duckdb_rows(result: DayParseResult) -> list[tuple]:
    """Convert a DayParseResult into tuples ready for executemany() into daily_raw."""
    df = result.df
    return list(df.itertuples(index=False, name=None))


# ----- CLI ----------------------------------------------------------------

if __name__ == '__main__':
    import sys
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent.parent / 'reference' / 'tdx' / 'day' / 'sz302132.day'
    r = parse_day_file(target)
    print(f"code={r.code} unit_scale={r.unit_scale} rows={len(r.df)}")
    print(f"date range: {r.df['trade_date'].min()} -> {r.df['trade_date'].max()}")
    print(r.df[['trade_date', 'open', 'high', 'low', 'close', 'volume']].tail().to_string(index=False))