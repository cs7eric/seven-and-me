"""Smoke test: verify isLimitDown fix produces sensible values."""
import sys
sys.path.insert(0, ".")

from backend.repositories.market.limit_repo import calc_limit_emotion_summary

dates = [
    "2026-06-17", "2026-06-16", "2026-06-15",
    "2026-06-12", "2026-06-11", "2026-06-10",
    "2026-06-09", "2026-06-08",
]

print(f'{"date":<12} {"up":>5} {"down":>5} {"ratio":>8} {"upDownScore":>11} {"bbScore":>8} {"yestScore":>10} {"comp":>7} {"level"}')
for d in dates:
    p = calc_limit_emotion_summary(d)
    if not p:
        print(f"{d}  NO DATA")
        continue
    c = p["components"]
    print(
        f'{d:<12} {p["limitUpCount"]:>5} {p["limitDownCount"]:>5} '
        f'{p["limitUpDownRatio"]:>8.2f} {c["upDownScore"]:>11.2f} '
        f'{c["breakBoardScore"]:>8.2f} {c["yesterdayReturnScore"]:>10.2f} '
        f'{p["compositeScore"]:>7.2f}  {p["level"]}'
    )