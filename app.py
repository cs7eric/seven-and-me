import os
import sys
import uuid
import subprocess
import imageio_ffmpeg
import json
from flask import Flask, render_template, request, jsonify, Response, send_from_directory
from werkzeug.utils import secure_filename
from pathlib import Path
from dotenv import load_dotenv
from concurrent.futures import ThreadPoolExecutor
import queue
import threading

load_dotenv()

app = Flask(__name__, static_folder='static')
app.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024 * 1024  # 10GB max
UPLOAD_FOLDER = Path(__file__).parent / 'uploads'
OUTPUT_FOLDER = Path(__file__).parent / 'outputs'
UPLOAD_FOLDER.mkdir(exist_ok=True)
OUTPUT_FOLDER.mkdir(exist_ok=True)

_executor = ThreadPoolExecutor(max_workers=2)

_tasks = {}

LOCAL_MODEL_PATH = os.getenv("WHISPER_MODEL_PATH", None)
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

    # 转换为 WAV (16kHz mono)
    try:
        ffmpeg_cmd = [
            imageio_ffmpeg.get_ffmpeg_exe(),
            "-y",
            "-i", str(file_path),
            "-ar", "16000",
            "-ac", "1",
            "-acodec", "pcm_s16le",
            str(wav_path)
        ]
        result = subprocess.run(ffmpeg_cmd, capture_output=True, timeout=300)
        if result.returncode != 0:
            return jsonify({"error": f"ffmpeg 转换失败: {result.stderr.decode('utf-8', errors='replace')}"}), 500
    except Exception as e:
        return jsonify({"error": f"转换音频失败: {e}"}), 500

    _tasks[task_id] = {"status": "processing", "result": None, "transcript": "", "polished": "", "summary": ""}

    def on_chunk(chunk_idx, text, is_final):
        _tasks[task_id]["transcript"] = text
        _tasks[task_id]["status"] = "done" if is_final else "processing"

    def run():
        try:
            transcriber = get_transcriber()
            audio_path = str(wav_path)
            transcriber.transcribe_streaming(audio_path, chunk_duration=1, callback=on_chunk)

            # 转写完成后自动润色和摘要
            text = _tasks[task_id]["transcript"]
            if text:
                polisher = get_polisher()
                result = polisher.polish_and_summarize(text)
                _tasks[task_id]["polished"] = result.get("polished", "")
                _tasks[task_id]["summary"] = result.get("summary", "")
                _tasks[task_id]["status"] = "done"
            else:
                _tasks[task_id]["status"] = "error"
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
            yield f"data: {json.dumps({'type': 'error', 'message': 'Task not found'})}\n\n"
            return

        last_status = ""
        while True:
            task = _tasks[task_id]
            status = task["status"]

            if status == "done" and last_status != "done":
                transcript = task.get("transcript", "")
                polished = task.get("polished", "")
                summary = task.get("summary", "")
                yield f"data: {json.dumps({'type': 'done', 'text': transcript, 'polished': polished, 'summary': summary})}\n\n"
                break

            elif status == "error":
                yield f"data: {json.dumps({'type': 'error', 'message': task.get('error', 'Unknown error')})}\n\n"
                break

            elif status != last_status and status == "processing":
                transcript = task.get("transcript", "")
                if transcript:
                    yield f"data: {json.dumps({'type': 'transcript', 'text': transcript})}\n\n"

            last_status = status

    response = Response(generate(), mimetype='text/event-stream', headers={
        'Cache-Control': 'no-cache',
        'X-Accel-Buffering': 'no',
        'Connection': 'keep-alive'
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