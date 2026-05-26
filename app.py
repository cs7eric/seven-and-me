import os
import sys
import uuid
import subprocess
import imageio_ffmpeg
import json
import time
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
        "polish_progress": 0,
        "summary_progress": 0,
        "error": None,
    }

    def on_chunk(chunk_idx, text, is_final):
        _tasks[task_id]["transcript"] = text

    def run():
        try:
            transcriber = get_transcriber()
            audio_path = str(wav_path)
            transcriber.transcribe_streaming(audio_path, chunk_duration=30, callback=on_chunk)

            text = _tasks[task_id]["transcript"]
            if not text:
                _tasks[task_id]["status"] = "error"
                _tasks[task_id]["error"] = "转写结果为空"
                return

            # 润色
            _tasks[task_id]["status"] = "polishing"
            polisher = get_polisher()
            polished = polisher.polish(text)
            _tasks[task_id]["polished"] = polished
            _tasks[task_id]["polish_progress"] = 100

            # 摘要
            _tasks[task_id]["status"] = "summarizing"
            summary = polisher.summarize(polished)
            _tasks[task_id]["summary"] = summary
            _tasks[task_id]["summary_progress"] = 100
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
        last_summary_str = ""
        last_poll = time.time()

        while True:
            task = _tasks.get(task_id)
            if not task:
                yield f"data: {json.dumps({'type': 'error', 'error': 'Task disappeared'})}\n\n"
                break

            status = task["status"]
            transcript = task.get("transcript", "")
            polished = task.get("polished", "")
            summary = task.get("summary", {})
            error = task.get("error")

            # ====== 状态变化检测 ======

            # transcribing → polishing 转换
            if last_status == "" and status == "transcribing":
                yield f"data: {json.dumps({'type': 'transcribe_start'})}\n\n"

            # transcript 更新
            if transcript and transcript != last_transcript:
                yield f"data: {json.dumps({'type': 'chunk', 'text': transcript})}\n\n"
                last_transcript = transcript

            # 转写完成
            if last_status != "polishing" and status == "polishing" and last_status != "transcribing":
                # 第一次进入 polishing
                pass

            if last_status == "transcribing" and status in ("polishing", "summarizing", "done"):
                yield f"data: {json.dumps({'type': 'transcribe_done'})}\n\n"

            # 进入润色
            if last_status != "polishing" and status == "polishing":
                yield f"data: {json.dumps({'type': 'polish_start'})}\n\n"

            # 润色完成
            if last_status in ("polishing", "transcribing") and status in ("summarizing", "done") and polished:
                yield f"data: {json.dumps({'type': 'polish_done', 'polished_text': polished})}\n\n"

            # 进入摘要
            if last_status != "summarizing" and status == "summarizing":
                yield f"data: {json.dumps({'type': 'summary_start'})}\n\n"

            # 摘要完成
            if last_status == "summarizing" and status == "done" and summary:
                summary_str = json.dumps(summary, ensure_ascii=False)
                yield f"data: {json.dumps({'type': 'summary_done', 'summary_text': summary})}\n\n"
                yield f"data: {json.dumps({'type': 'done', 'raw_text': transcript, 'polished_text': polished, 'summary_text': summary, 'char_count': len(polished)})}\n\n"
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

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False, threaded=True, use_reloader=False)
