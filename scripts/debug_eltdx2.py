"""Debug: 检查 _extract_rows_from_response 在 MinutePoint 上为什么返回空."""
import sys
sys.path.insert(0, '.')
from dataclasses import asdict
from datetime import date
from eltdx import TdxClient
from backend.adapters.market.eltdx_adapter import _sanitize_jsonable

with TdxClient() as c:
    r = c.get_history_minute('sh000001', date(2026, 5, 25))
    points = r.points
    print('points type:', type(points).__name__)
    print('points[0] type:', type(points[0]).__name__)
    p0 = points[0]
    print('has __dataclass_fields__:', hasattr(p0, '__dataclass_fields__'))
    d = asdict(p0)
    print('asdict type:', type(d).__name__)
    print('asdict sample:', {k: type(v).__name__ for k, v in d.items()})
    s = _sanitize_jsonable(d)
    print('sanitize type:', type(s).__name__)
    print('sanitize sample:', s)
