import sys
sys.path.insert(0, '.')
from backend.services.stock.limit_emotion_service import get_limit_emotion, build_limit_emotion
import json

# 强制重建, 绕过 latest.json 缓存
result = build_limit_emotion(force=True)
print("tradeDate:", result.get("tradeDate"))
print("marketStatus:", result.get("marketStatus"))
print("streak.maxHeight:", result.get("streak", {}).get("maxHeight"))
print("streak.distribution:")
for d in result.get("streak", {}).get("distribution", []):
    print(f'  {d["streak"]}板: count={d["count"]}')
print("limitUp count:", result.get("limitUp", {}).get("count"))
print("dataStatus:", result.get("dataStatus"))
