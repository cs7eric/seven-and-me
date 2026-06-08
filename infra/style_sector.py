def compute_sector_change_pct(
    last_caps: list[float], prev_caps: list[float]
) -> float | None:
    if not last_caps or not prev_caps or len(last_caps) != len(prev_caps):
        return None
    last_total = sum(last_caps)
    prev_total = sum(prev_caps)
    if prev_total == 0:
        return None
    return (last_total - prev_total) / prev_total * 100.0
