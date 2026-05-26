import requests
import json
import time

file_path = r"F:\dev-repo\mp4-to-word\uploads\bccbab3c-a480-4cb6-8edd-4793dc12f543_8_.mp4"

print("1. 上传文件...")
resp = requests.post("http://localhost:5000/api/transcribe", files={"file": open(file_path, "rb")})
print(f"   状态: {resp.status_code}, 返回: {resp.text}")
if resp.status_code != 200:
    print("上传失败!")
    exit(1)

task_id = resp.json().get("task_id")
print(f"   Task ID: {task_id}")

print("\n2. 监听 SSE 流...")
time.sleep(1)
events = []
try:
    es = requests.get(f"http://localhost:5000/api/stream/{task_id}", stream=True, timeout=180)
    for line in es.iter_lines():
        if line:
            decoded = line.decode("utf-8", errors="replace")
            if decoded.startswith("data:"):
                try:
                    event = json.loads(decoded[5:].strip())
                    etype = event.get("type")
                    txt = event.get("text") or event.get("polished_text") or event.get("raw_text") or ""
                    print(f"   [{etype}] text_len={len(txt)}")
                    events.append(event)
                except:
                    print(f"   解析失败: {decoded[:100]}")
    print(f"\n3. 共收到 {len(events)} 个事件")
    if events:
        last = events[-1]
        if last.get("type") == "done":
            rt = last.get("raw_text", "")
            pt = last.get("polished_text", "")
            st = last.get("summary_text", "")
            print(f"   转写: {len(rt)} 字")
            print(f"   润色: {len(pt)} 字")
            print(f"   摘要: {st}")
except Exception as e:
    print(f"   SSE 错误: {e}")
