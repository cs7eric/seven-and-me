import os
import sys
import uuid
import subprocess
import imageio_ffmpeg
import json
import time
from datetime import datetime
from urllib.parse import quote
from flask import Flask, render_template, request, jsonify, Response, send_from_directory
from werkzeug.utils import secure_filename
from pathlib import Path
from dotenv import load_dotenv
from concurrent.futures import ThreadPoolExecutor

load_dotenv()

app = Flask(__name__, static_folder='static')
app.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024 * 1024
UPLOAD_FOLDER = Path(__file__).parent / 'uploads'
OUTPUT_FOLDER = Path(__file__).parent / 'outputs'
UPLOAD_FOLDER.mkdir(exist_ok=True)
OUTPUT_FOLDER.mkdir(exist_ok=True)

_executor = ThreadPoolExecutor(max_workers=2)
_tasks = {}

API_KEY = os.getenv("MINIMAX_API_KEY")
GROUP_ID = os.getenv("MINIMAX_GROUP_ID")

from transcribe import Transcriber
from polisher import TextPolisher

_transcriber = None
_polisher = None


def sanitize_filename(name: str) -> str:
    safe = "".join(ch for ch in name if ch.isprintable() and ch not in ('<', '>', ':', '"', '/', '\\', '|', '?', '*')).strip()
    safe = safe.replace(" ", "-")
    return safe[:80] or "untitled"


def build_export_filename(task: dict, task_id: str) -> str:
    metadata = task.get("metadata") or {}
    title = str(metadata.get("title") or "").strip()
    original_name = Path(str(task.get("file_name") or "")).stem

    base_name = sanitize_filename(title)
    if not base_name or base_name == "untitled":
        base_name = sanitize_filename(original_name)

    if not base_name or base_name == "untitled":
        base_name = "untitled"

    return f"{base_name}.md"


def build_markdown_document(task: dict) -> str:
    metadata = task.get("metadata") or {}
    title = str(metadata.get("title") or "Untitled Note").strip()
    categories = metadata.get("categories") or ["Uncategorized"]
    tags = metadata.get("tags") or ["待整理"]
    polished = (task.get("polished") or "").strip()
    summary = (task.get("summary") or "").strip()
    date_str = datetime.now().strftime("%Y/%m/%d %H:%M:%S")

    frontmatter = "\n".join([
        "---",
        f"title: {title}",
        "",
        f"categories: {','.join(categories)}",
        "",
        f"tags: {','.join(tags)}",
        "",
        f"date: {date_str}",
        "---",
    ])

    sections = [frontmatter, polished, summary]
    return "\n\n".join(section for section in sections if section)

def get_transcriber():
    global _transcriber
    if _transcriber is None:
        print("[App] 初始化 Whisper 模型")
        sys.stdout.flush()
        _transcriber = Transcriber()
    return _transcriber

def get_polisher():
    global _polisher
    if _polisher is None:
        print("[App] 初始化 MiniMax AI")
        sys.stdout.flush()
        _polisher = TextPolisher()
    return _polisher

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/status')
def status():
    return jsonify({
        "api_configured": bool(API_KEY and GROUP_ID),
        "gpu_available": False,
        "model_loaded": _transcriber is not None,
        "status": "running"
    })

@app.route('/api/transcribe', methods=['POST'])
def transcribe():
    if 'file' not in request.files:
        return jsonify({"error": "没有文件"}), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "文件名为空"}), 400

    task_id = str(uuid.uuid4())
    file_path = UPLOAD_FOLDER / f"{task_id}_{secure_filename(file.filename)}"
    wav_path = UPLOAD_FOLDER / f"{task_id}_audio.wav"

    try:
        file.save(str(file_path))
    except Exception as e:
        return jsonify({"error": f"文件保存失败: {e}"}), 500

    # 转换为 WAV
    try:
        ffmpeg_cmd = [
            imageio_ffmpeg.get_ffmpeg_exe(),
            "-y", "-i", str(file_path),
            "-ar", "16000", "-ac", "1", "-acodec", "pcm_s16le",
            str(wav_path)
        ]
        result = subprocess.run(ffmpeg_cmd, capture_output=True, timeout=300)
        if result.returncode != 0:
            return jsonify({"error": f"ffmpeg 转换失败"}), 500
    except Exception as e:
        return jsonify({"error": f"转换音频失败: {e}"}), 500

    # 初始化任务状态
    _tasks[task_id] = {
        "status": "transcribing",
        "transcript": "",
        "polished": "",
        "summary": "",
        "metadata": {},
        "file_name": file.filename,
        "polish_progress": 0,
        "summary_progress": 0,
        "error": None,
    }

    def on_chunk(chunk_idx, text, is_final):
        _tasks[task_id]["transcript"] = text

    def run():
        try:
            print(f"[run] 开始转写 task_id={task_id}")
            transcriber = get_transcriber()
            audio_path = str(wav_path)
            print(f"[run] audio_path={audio_path}")
            transcriber.transcribe_streaming(audio_path, chunk_duration=30, callback=on_chunk)
            print(f"[run] 转写完成")

            text = _tasks[task_id]["transcript"]
            print(f"[run] 转写结果长度={len(text)}")
            if not text:
                _tasks[task_id]["status"] = "error"
                _tasks[task_id]["error"] = "转写结果为空"
                return

            # 润色
            _tasks[task_id]["status"] = "polishing"
            polisher = get_polisher()
            def on_polish_chunk(current_text):
                _tasks[task_id]["polished"] = current_text

            polished = polisher.polish(text, on_chunk=on_polish_chunk)
            _tasks[task_id]["polished"] = polished
            _tasks[task_id]["polish_progress"] = 100

            # 摘要
            _tasks[task_id]["status"] = "summarizing"
            def on_summary_chunk(current_text):
                _tasks[task_id]["summary"] = current_text

            summary = polisher.summarize(polished, on_chunk=on_summary_chunk)
            _tasks[task_id]["summary"] = summary
            _tasks[task_id]["summary_progress"] = 100
            _tasks[task_id]["metadata"] = polisher.generate_post_metadata(polished, summary)
            _tasks[task_id]["status"] = "done"

        except Exception as e:
            import traceback
            traceback.print_exc()
            _tasks[task_id]["status"] = "error"
            _tasks[task_id]["error"] = str(e)

    _executor.submit(run)
    return jsonify({"task_id": task_id})

@app.route('/api/stream/<task_id>')
def stream(task_id):
    def generate():
        if task_id not in _tasks:
            yield f"data: {json.dumps({'type': 'error', 'error': 'Task not found'})}\n\n"
            return

        last_status = ""
        last_transcript = ""
        last_polished = ""
        last_summary = ""
        last_poll = time.time()

        while True:
            task = _tasks.get(task_id)
            if not task:
                yield f"data: {json.dumps({'type': 'error', 'error': 'Task disappeared'})}\n\n"
                break

            status = task["status"]
            transcript = task.get("transcript", "")
            polished = task.get("polished", "")
            summary = task.get("summary", "")
            metadata = task.get("metadata", {})
            error = task.get("error")

            # ====== 状态变化检测 ======

            # transcribing → polishing 转换
            if last_status == "" and status == "transcribing":
                yield f"data: {json.dumps({'type': 'transcribe_start'})}\n\n"

            # transcript 更新：只发新增的字符（逐字流式）
            if transcript and transcript != last_transcript:
                # 发所有字符（前端负责逐字动画显示）
                yield f"data: {json.dumps({'type': 'chunk', 'text': transcript})}\n\n"
                last_transcript = transcript

            if last_status == "transcribing" and status in ("polishing", "summarizing", "done"):
                yield f"data: {json.dumps({'type': 'transcribe_done'})}\n\n"

            # 进入润色
            if last_status != "polishing" and status == "polishing":
                yield f"data: {json.dumps({'type': 'polish_start'})}\n\n"

            # 润色流式增量
            if polished and polished != last_polished:
                yield f"data: {json.dumps({'type': 'polish_char', 'text': polished})}\n\n"
                last_polished = polished

            # 润色完成
            if last_status in ("polishing", "transcribing") and status in ("summarizing", "done") and polished:
                yield f"data: {json.dumps({'type': 'polish_done', 'polished_text': polished})}\n\n"

            # 进入摘要
            if last_status != "summarizing" and status == "summarizing":
                yield f"data: {json.dumps({'type': 'summary_start'})}\n\n"

            # 摘要流式增量
            if summary and summary != last_summary:
                yield f"data: {json.dumps({'type': 'summary_char', 'text': summary})}\n\n"
                last_summary = summary

            # 摘要完成
            if last_status == "summarizing" and status == "done" and summary:
                yield f"data: {json.dumps({'type': 'summary_done', 'summary_text': summary})}\n\n"
                yield f"data: {json.dumps({'type': 'done', 'raw_text': transcript, 'polished_text': polished, 'summary_text': summary, 'char_count': len(polished), 'metadata': metadata, 'task_id': task_id})}\n\n"
                break

            # 错误
            if status == "error":
                yield f"data: {json.dumps({'type': 'error', 'error': error or 'Unknown error'})}\n\n"
                break

            # 超时保护（5分钟）
            if time.time() - last_poll > 300:
                yield f"data: {json.dumps({'type': 'error', 'error': '处理超时'})}\n\n"
                break

            last_status = status
            last_poll = time.time()
            time.sleep(0.3)

    response = Response(generate(), mimetype='text/event-stream', headers={
        'Cache-Control': 'no-cache',
        'X-Accel-Buffering': 'no',
    })
    return response

@app.route('/uploads/<path:filename>')
def uploaded_file(filename):
    return send_from_directory(UPLOAD_FOLDER, filename)

@app.route('/outputs/<path:filename>')
def output_file(filename):
    return send_from_directory(OUTPUT_FOLDER, filename)


@app.route('/api/export-markdown/<task_id>')
def export_markdown(task_id):
    task = _tasks.get(task_id)
    if not task:
        return jsonify({"error": "Task not found"}), 404

    if task.get("status") != "done":
        return jsonify({"error": "任务尚未完成，暂时不能导出 Markdown"}), 400

    markdown = build_markdown_document(task)
    metadata = task.get("metadata") or {}
    title = str(metadata.get("title") or task.get("file_name") or "untitled").strip()
    filename = build_export_filename(task, task_id)
    utf8_filename = quote(f"{title}.md")

    return Response(
        markdown,
        mimetype='text/markdown; charset=utf-8',
        headers={
            'Content-Disposition': f"attachment; filename=\"{filename}\"; filename*=UTF-8''{utf8_filename}",
        }
    )

if __name__ == '__main__':
    import socket
    # 检查端口 5000 是否有残留进程
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    result = sock.connect_ex(('127.0.0.1', 5000))
    if result == 0:
        print("[启动] 端口 5000 已被占用，尝试接管...")
        import subprocess
        try:
            result = subprocess.run(['netstat', '-ano'], capture_output=True, text=True)
            for line in result.stdout.split('\n'):
                if ':5000' in line and 'LISTENING' in line:
                    pid = int(line.split()[-1])
                    print(f"[启动] 杀掉残留进程 PID={pid}")
                    subprocess.run(['taskkill', '/F', '/PID', str(pid)], capture_output=True)
                    break
        except:
            pass
    sock.close()
    print("[启动] 启动 Flask on 0.0.0.0:5000")
    app.run(host='0.0.0.0', port=5000, debug=False, threaded=True, use_reloader=False)
