import requests
r = requests.get('http://localhost:5000/api/stock-chart/market-overview-akshare')
data = r.json()
print(f'tradingDate: {data.get("tradingDate")}')
print(f'totalAmount: {data.get("totalAmount")}')
print(f'mainNetInflow: {data.get("mainNetInflow")}')
print(f'source: {data.get("source")}')
print(f'dataStatus: {data.get("dataStatus")}')
