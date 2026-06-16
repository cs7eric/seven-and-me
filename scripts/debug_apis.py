"""
直接请求后端 API 看实际返回, 找问题.
"""
import requests

print("=" * 60)
print("market-overview-akshare")
r = requests.get("http://localhost:5000/api/stock-chart/market-overview-akshare")
data = r.json()
print(f"  tradingDate: {data.get('tradingDate')}")
print(f"  totalAmount: {data.get('totalAmount')}")
print(f"  mainNetInflow: {data.get('mainNetInflow')}")
print(f"  source: {data.get('source')}")
print(f"  prevDayTradingDate: {data.get('prevDayTradingDate')}")
print(f"  prevDayFlow: {data.get('prevDayFlow')}")
print()

print("=" * 60)
print("market-overview-eltdx")
r = requests.get("http://localhost:5000/api/stock-chart/market-overview-eltdx")
data = r.json()
print(f"  tradingDate: {data.get('tradingDate')}")
print(f"  totalAmount: {data.get('totalAmount')}")
print(f"  limitUpCount: {data.get('limitUpCount')}")
print(f"  limitDownCount: {data.get('limitDownCount')}")
print(f"  prevDayTradingDate: {data.get('prevDayTradingDate')}")
print(f"  prevDayTotalAmount: {data.get('prevDayTotalAmount')}")
print()

print("=" * 60)
print("intraday 000001 06-16")
r = requests.get("http://localhost:5000/api/stock-chart/intraday?target_type=index&symbol=000001&adjust=none&trade_date=2026-06-16&periods=1m")
data = r.json()
print(f"  ok: {data.get('ok')}")
print(f"  error: {data.get('error')}")
print(f"  trade_date: {data.get('trade_date')}")
ts = data.get('timeshare') or []
print(f"  timeshare bars: {len(ts)}")
