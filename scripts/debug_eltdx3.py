"""Debug: _extract_rows_from_response 为什么 0."""
import sys
sys.path.insert(0, '.')
from datetime import date
from eltdx import TdxClient

with TdxClient() as c:
    r = c.get_history_minute('sh000001', date(2026, 5, 25))
    print('type:', type(r).__name__)
    print('isinstance(list):', isinstance(r, list))
    print('hasattr items:', hasattr(r, 'items'))
    print('hasattr rows:', hasattr(r, 'rows'))
    print('hasattr points:', hasattr(r, 'points'))
    rows = getattr(r, 'points')
    print('rows type:', type(rows).__name__)
    print('rows[0] type:', type(rows[0]).__name__)
