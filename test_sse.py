import requests
import json
import time

file_path = r"C:\Users\Cs7er\快抖下载器\我收藏的音乐_2026-05-25_20-05-11\2.mp4"

print("Uploading...")
resp = requests.post("http://localhost:5000/api/transcribe", files={"file": open(file_path, "rb")})
print(f"Status: {resp.status_code}, Body: {resp.text}")

if resp.status_code == 200:
    data = resp.json()
    task_id = data.get("task_id")
    print(f"Task ID: {task_id}")

    if task_id:
        time.sleep(2)
        print("Opening stream...")
        try:
            es = requests.get(f"http://localhost:5000/api/stream/{task_id}", stream=True, timeout=60)
            count = 0
            for line in es.iter_lines():
                if line:
                    try:
                        decoded = line.decode("utf-8")
                        if decoded.startswith("data:"):
                            json_str = decoded[5:].strip()
                            event = json.loads(json_str)
                            print(f"Event {count}: type={event.get('type')}, progress={event.get('progress')}, text_len={len(event.get('text',''))}")
                            count += 1
                    except Exception as e:
                        print(f"Parse error: {e}, line: {repr(line)}")
                if count >= 15:
                    print("Got 15 events, stopping")
                    break
        except Exception as e:
            print(f"Stream error: {e}")