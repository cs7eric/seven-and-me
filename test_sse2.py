import urllib.request, json, time

file_path = r"F:\dev-repo\mp4-to-word\uploads\bccbab3c-a480-4cb6-8edd-4793dc12f543_8_.mp4"

print("1. 上传文件...")
req_data, headers = urllib.request.quote, None
import multipart

# 用 requests 简单上传
import requests
resp = requests.post("http://localhost:5000/api/transcribe", files={"file": open(file_path, "rb")}, timeout=5)
print(f"   状态: {resp.status_code}, task_id: {resp.json().get('task_id')}")
tid = resp.json()["task_id"]

print("\n2. 监听 SSE (urllib)...")
time.sleep(0.5)
sse_url = f"http://localhost:5000/api/stream/{tid}"
req = urllib.request.Request(sse_url)
req.add_header("Accept", "text/event-stream")
req.add_header("Cache-Control", "no-cache")

try:
    with urllib.request.urlopen(req, timeout=30) as resp:
        print(f"   Stream 状态: {resp.status}")
        event_count = 0
        for line in resp:
            decoded = line.decode("utf-8", errors="replace").strip()
            if decoded.startswith("data:"):
                try:
                    ev = json.loads(decoded[5:])
                    t = ev.get("type")
                    txt = ev.get("text") or ev.get("polished_text") or ev.get("raw_text") or ev.get("summary_text") or ""
                    print(f"   [{t}] text_len={len(txt)}")
                    event_count += 1
                    if t == "done":
                        break
                except:
                    print(f"   解析失败: {decoded[:100]}")
except Exception as e:
    print(f"   SSE 错误: {e}")

print(f"\n3. 共收到 {event_count} 个事件")
