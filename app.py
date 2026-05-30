import os
import sys
import uuid
import subprocess
import imageio_ffmpeg
import json
import time
import mimetypes
import requests
from datetime import datetime
from urllib.parse import quote, urlparse
from flask import Flask, render_template, request, jsonify, Response, send_from_directory
from flask_cors import CORS
from werkzeug.utils import secure_filename
from pathlib import Path
from dotenv import load_dotenv
from concurrent.futures import ThreadPoolExecutor

load_dotenv()

app = Flask(__name__, static_folder='static')
CORS(app)
app.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024 * 1024
UPLOAD_FOLDER = Path(__file__).parent / 'uploads'
OUTPUT_FOLDER = Path(__file__).parent / 'outputs'
UPLOAD_FOLDER.mkdir(exist_ok=True)
OUTPUT_FOLDER.mkdir(exist_ok=True)

_executor = ThreadPoolExecutor(max_workers=2)

DOWNLOAD_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36",
    "Accept": "*/*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Connection": "keep-alive",
    "Referer": "https://www.bilibili.com/",
}
_tasks = {}

REFERENCE_FOLDER = Path(__file__).parent / 'reference'
REFERENCE_INDEX_FILE = REFERENCE_FOLDER / 'index.json'
MP4_REFERENCE_FOLDER = REFERENCE_FOLDER / 'parse'
MP4_REFERENCE_DATA_FOLDER = MP4_REFERENCE_FOLDER / 'data'
MP4_REFERENCE_INDEX_FOLDER = MP4_REFERENCE_FOLDER / 'index'
MP4_REFERENCE_TYPE_INDEX = MP4_REFERENCE_INDEX_FOLDER / 'index.json'

REFERENCE_FOLDER.mkdir(exist_ok=True)
MP4_REFERENCE_DATA_FOLDER.mkdir(parents=True, exist_ok=True)
MP4_REFERENCE_INDEX_FOLDER.mkdir(parents=True, exist_ok=True)

API_KEY = os.getenv("MINIMAX_API_KEY")
GROUP_ID = os.getenv("MINIMAX_GROUP_ID")

from transcribe import Transcriber
from polisher import TextPolisher

_transcriber = None
_polisher = None


def read_json_file(path: Path, default):
    if not path.exists() or path.stat().st_size == 0:
        return default
    try:
        with path.open('r', encoding='utf-8') as file:
            return json.load(file)
    except Exception:
        return default


def write_json_file(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8') as file:
        json.dump(data, file, ensure_ascii=False, indent=2)


def ensure_reference_index_files():
    if not REFERENCE_INDEX_FILE.exists() or REFERENCE_INDEX_FILE.stat().st_size == 0:
        write_json_file(REFERENCE_INDEX_FILE, {
            "version": 1,
            "updated_at": None,
            "types": {
                "mp4_parse": {
                    "title": "MP4 Parse History",
                    "index_file": str(MP4_REFERENCE_TYPE_INDEX.relative_to(REFERENCE_FOLDER)).replace('\\', '/'),
                    "data_dir": str(MP4_REFERENCE_DATA_FOLDER.relative_to(REFERENCE_FOLDER)).replace('\\', '/'),
                    "count": 0,
                }
            }
        })

    if not MP4_REFERENCE_TYPE_INDEX.exists() or MP4_REFERENCE_TYPE_INDEX.stat().st_size == 0:
        write_json_file(MP4_REFERENCE_TYPE_INDEX, {
            "type": "mp4_parse",
            "version": 1,
            "updated_at": None,
            "items": []
        })


def build_task_snapshot(task_id: str, task: dict) -> dict:
    return {
        "task_id": task_id,
        "status": task.get("status"),
        "transcript": task.get("transcript", ""),
        "polished": task.get("polished", ""),
        "summary": task.get("summary", ""),
        "metadata": task.get("metadata", {}),
        "file_name": task.get("file_name", ""),
        "error": task.get("error"),
        "download_progress": task.get("download_progress", {}),
        "intake_progress": task.get("intake_progress", {}),
        "qa_items": task.get("qa_items", []),
    }


def export_task_to_reference(task_id: str) -> dict:
    task = _tasks.get(task_id)
    if not task:
        raise ValueError("Task not found")
    if task.get("status") != "done":
        raise ValueError("Task is not completed yet")

    ensure_reference_index_files()

    snapshot = build_task_snapshot(task_id, task)
    metadata = snapshot.get("metadata") or {}
    title = str(metadata.get("title") or snapshot.get("file_name") or task_id).strip() or task_id
    created_at = datetime.now().isoformat()
    history_id = f"mp4-{task_id}"
    record_file = MP4_REFERENCE_DATA_FOLDER / f"{history_id}.json"

    record_payload = {
        "id": history_id,
        "type": "mp4_parse",
        "version": 1,
        "created_at": created_at,
        "updated_at": created_at,
        "title": title,
        "task": snapshot,
    }
    write_json_file(record_file, record_payload)

    type_index = read_json_file(MP4_REFERENCE_TYPE_INDEX, {
        "type": "mp4_parse",
        "version": 1,
        "updated_at": None,
        "items": []
    })
    items = [item for item in type_index.get("items", []) if item.get("id") != history_id]
    items.insert(0, {
        "id": history_id,
        "title": title,
        "created_at": created_at,
        "task_id": task_id,
        "status": snapshot.get("status"),
        "file_name": snapshot.get("file_name"),
        "data_file": str(record_file.relative_to(REFERENCE_FOLDER)).replace('\\', '/'),
    })
    type_index["items"] = items
    type_index["updated_at"] = created_at
    write_json_file(MP4_REFERENCE_TYPE_INDEX, type_index)

    root_index = read_json_file(REFERENCE_INDEX_FILE, {
        "version": 1,
        "updated_at": None,
        "types": {}
    })
    root_index.setdefault("types", {})["mp4_parse"] = {
        "title": "MP4 Parse History",
        "index_file": str(MP4_REFERENCE_TYPE_INDEX.relative_to(REFERENCE_FOLDER)).replace('\\', '/'),
        "data_dir": str(MP4_REFERENCE_DATA_FOLDER.relative_to(REFERENCE_FOLDER)).replace('\\', '/'),
        "count": len(items),
    }
    root_index["updated_at"] = created_at
    write_json_file(REFERENCE_INDEX_FILE, root_index)

    return {
        "id": history_id,
        "title": title,
        "created_at": created_at,
        "data_file": str(record_file.relative_to(REFERENCE_FOLDER)).replace('\\', '/'),
    }


def load_reference_history_list() -> list[dict]:
    ensure_reference_index_files()
    type_index = read_json_file(MP4_REFERENCE_TYPE_INDEX, {
        "type": "mp4_parse",
        "version": 1,
        "updated_at": None,
        "items": []
    })
    return type_index.get("items", [])


def load_reference_history_detail(history_id: str) -> dict | None:
    items = load_reference_history_list()
    item = next((entry for entry in items if entry.get("id") == history_id), None)
    if not item:
        return None
    data_file = item.get("data_file")
    if not data_file:
        return None
    record_file = REFERENCE_FOLDER / data_file
    return read_json_file(record_file, None)


def reorder_reference_history_items(ordered_ids: list[str]) -> list[dict]:
    ensure_reference_index_files()
    type_index = read_json_file(MP4_REFERENCE_TYPE_INDEX, {
        "type": "mp4_parse",
        "version": 1,
        "updated_at": None,
        "items": []
    })
    items = type_index.get("items", [])
    item_map = {item.get("id"): item for item in items}
    reordered = [item_map[item_id] for item_id in ordered_ids if item_id in item_map]
    remaining = [item for item in items if item.get("id") not in ordered_ids]
    final_items = reordered + remaining
    type_index["items"] = final_items
    type_index["updated_at"] = datetime.now().isoformat()
    write_json_file(MP4_REFERENCE_TYPE_INDEX, type_index)
    return final_items


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


def guess_extension_from_url(url: str) -> str:
    path = urlparse(url).path
    suffix = Path(path).suffix.lower()
    if suffix in {'.mp4', '.mov', '.mkv', '.webm', '.avi', '.mp3', '.wav', '.m4a', '.aac', '.ogg', '.flac', '.aiff'}:
        return suffix
    return '.mp4'


def build_download_filename(source_url: str, title: str | None, content_type: str | None) -> str:
    ext = guess_extension_from_url(source_url)
    guessed_ext = mimetypes.guess_extension((content_type or '').split(';')[0].strip()) if content_type else None
    if guessed_ext in {'.mp4', '.mov', '.mkv', '.webm', '.avi', '.mp3', '.wav', '.m4a', '.aac', '.ogg', '.flac', '.aiff'}:
        ext = guessed_ext

    base = sanitize_filename(title or Path(urlparse(source_url).path).stem or 'downloaded-video')
    return f"{base}{ext}"


def create_task_record(task_id: str, file_name: str, source_url: str | None = None) -> dict:
    now = time.time()
    task = {
        "status": "transcribing",
        "transcript": "",
        "polished": "",
        "summary": "",
        "metadata": {},
        "file_name": file_name,
        "polish_progress": 0,
        "summary_progress": 0,
        "error": None,
        "created_at": now,
        "download_progress": {
            "phase": "pending",
            "progress": 0,
            "downloaded_bytes": 0,
            "total_bytes": 0,
            "eta_seconds": None,
            "speed_bytes_per_sec": 0,
        },
        "intake_progress": {
            "phase": "pending",
            "progress": 0,
            "processed_bytes": 0,
            "total_bytes": 0,
            "eta_seconds": None,
        },
    }
    if source_url:
        task["source_url"] = source_url
    _tasks[task_id] = task
    return task


def start_transcription_task(task_id: str, file_path: Path, display_name: str):
    wav_path = UPLOAD_FOLDER / f"{task_id}_audio.wav"
    filename_lower = display_name.lower()
    is_audio = any(filename_lower.endswith(ext) for ext in ('.mp3', '.wav', '.m4a', '.aac', '.ogg', '.flac', '.aiff'))

    try:
        source_size = file_path.stat().st_size
    except OSError:
        source_size = 0

    task = _tasks.get(task_id)
    if task:
        task["intake_progress"] = {
            "phase": "preparing",
            "progress": 8,
            "processed_bytes": 0,
            "total_bytes": source_size,
            "eta_seconds": None,
        }

    if is_audio:
        audio_path = str(file_path)
        if task:
            task["intake_progress"] = {
                "phase": "ready",
                "progress": 100,
                "processed_bytes": source_size,
                "total_bytes": source_size,
                "eta_seconds": 0,
            }
    else:
        audio_path = str(wav_path)
        if task:
            task["intake_progress"] = {
                "phase": "preparing",
                "progress": 22,
                "processed_bytes": 0,
                "total_bytes": source_size,
                "eta_seconds": None,
            }
        ffmpeg_cmd = [
            imageio_ffmpeg.get_ffmpeg_exe(),
            "-y", "-i", str(file_path),
            "-ar", "16000", "-ac", "1", "-acodec", "pcm_s16le",
            str(wav_path)
        ]
        result = subprocess.run(ffmpeg_cmd, capture_output=True, timeout=300)
        if result.returncode != 0:
            raise RuntimeError("ffmpeg 转换失败")
        if task:
            try:
                prepared_size = wav_path.stat().st_size
            except OSError:
                prepared_size = source_size
            task["intake_progress"] = {
                "phase": "ready",
                "progress": 100,
                "processed_bytes": prepared_size,
                "total_bytes": prepared_size,
                "eta_seconds": 0,
            }

    def on_chunk(chunk_idx, text, is_final):
        _tasks[task_id]["transcript"] = text

    def run():
        try:
            print(f"[run] 开始转写 task_id={task_id}, audio={audio_path}")
            transcriber = get_transcriber()
            transcriber.transcribe_streaming(audio_path, chunk_duration=30, callback=on_chunk)
            print(f"[run] 转写完成")

            text = _tasks[task_id]["transcript"]
            print(f"[run] 转写结果长度={len(text)}")
            if not text:
                _tasks[task_id]["status"] = "error"
                _tasks[task_id]["error"] = "转写结果为空"
                return

            _tasks[task_id]["status"] = "polishing"
            polisher = get_polisher()

            def on_polish_chunk(current_text):
                _tasks[task_id]["polished"] = current_text

            polished = polisher.polish(text, on_chunk=on_polish_chunk)
            _tasks[task_id]["polished"] = polished
            _tasks[task_id]["polish_progress"] = 100

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

    try:
        file.save(str(file_path))
    except Exception as e:
        return jsonify({"error": f"文件保存失败: {e}"}), 500

    create_task_record(task_id, file.filename)

    try:
        start_transcription_task(task_id, file_path, file.filename)
    except Exception as e:
        _tasks[task_id]["status"] = "error"
        _tasks[task_id]["error"] = str(e)
        return jsonify({"error": f"转换音频失败: {e}"}), 500

    return jsonify({"task_id": task_id})

@app.route('/api/parse-video', methods=['POST'])
def parse_video_from_downloader():
    data = request.get_json()
    if not data:
        return jsonify({"error": "Invalid request"}), 400

    source_url = str(data.get('download_url') or '').strip()
    title = str(data.get('title') or '').strip()
    source_page_url = str(data.get('source_url') or '').strip()
    metadata = data.get('metadata') if isinstance(data.get('metadata'), dict) else {}

    if not source_url:
        return jsonify({"error": "download_url is required"}), 400

    task_id = str(uuid.uuid4())

    try:
        session = requests.Session()
        head_response = session.head(source_url, allow_redirects=True, timeout=(5, 15), headers=DOWNLOAD_HEADERS)
        file_name = build_download_filename(
            source_url,
            title,
            head_response.headers.get('Content-Type') if head_response.ok else None,
        )
        create_task_record(task_id, file_name, source_page_url or source_url)
        _tasks[task_id]["metadata"] = {
            **metadata,
            "title": title or metadata.get("title") or Path(file_name).stem,
            "source_url": source_page_url or source_url,
            "download_url": source_url,
        }
        _tasks[task_id]["status"] = "downloading"
        _tasks[task_id]["download_progress"] = {
            "phase": "queued",
            "progress": 0,
            "downloaded_bytes": 0,
            "total_bytes": int(head_response.headers.get('Content-Length') or 0),
            "eta_seconds": None,
            "speed_bytes_per_sec": 0,
        }
        _tasks[task_id]["intake_progress"] = {
            "phase": "pending",
            "progress": 0,
            "processed_bytes": 0,
            "total_bytes": 0,
            "eta_seconds": None,
        }

        def run_download_and_parse():
            try:
                request_headers = {
                    **DOWNLOAD_HEADERS,
                    "Referer": source_page_url or DOWNLOAD_HEADERS["Referer"],
                }
                with session.get(source_url, stream=True, timeout=(10, 300), headers=request_headers) as response:
                    response.raise_for_status()
                    resolved_file_name = build_download_filename(source_url, title, response.headers.get('Content-Type'))
                    file_path = UPLOAD_FOLDER / f"{task_id}_{secure_filename(resolved_file_name)}"
                    _tasks[task_id]["file_name"] = resolved_file_name
                    _tasks[task_id]["metadata"]["title"] = title or metadata.get("title") or Path(resolved_file_name).stem

                    total_size = int(response.headers.get('Content-Length') or 0)
                    downloaded = 0
                    started_at = time.time()
                    _tasks[task_id]["download_progress"] = {
                        "phase": "running",
                        "progress": 1,
                        "downloaded_bytes": 0,
                        "total_bytes": total_size,
                        "eta_seconds": None,
                        "speed_bytes_per_sec": 0,
                    }
                    with open(file_path, 'wb', buffering=8 * 1024 * 1024) as target:
                        for chunk in response.iter_content(chunk_size=4 * 1024 * 1024):
                            if not chunk:
                                continue
                            target.write(chunk)
                            downloaded += len(chunk)
                            elapsed = max(time.time() - started_at, 0.001)
                            speed = downloaded / elapsed
                            eta_seconds = int((total_size - downloaded) / speed) if total_size and speed > 0 else None
                            progress = int(downloaded * 100 / total_size) if total_size else min(95, max(5, downloaded // (4 * 1024 * 1024)))
                            _tasks[task_id]["download_progress"] = {
                                "phase": "running",
                                "progress": min(progress, 99 if total_size else progress),
                                "downloaded_bytes": downloaded,
                                "total_bytes": total_size,
                                "eta_seconds": eta_seconds,
                                "speed_bytes_per_sec": int(speed),
                            }

                    if total_size and downloaded != total_size:
                        raise RuntimeError("下载文件不完整")

                _tasks[task_id]["download_progress"] = {
                    "phase": "done",
                    "progress": 100,
                    "downloaded_bytes": downloaded,
                    "total_bytes": total_size,
                    "eta_seconds": 0,
                    "speed_bytes_per_sec": _tasks[task_id]["download_progress"].get("speed_bytes_per_sec", 0),
                }
                _tasks[task_id]["status"] = "transcribing"
                start_transcription_task(task_id, file_path, resolved_file_name)
            except requests.exceptions.RequestException as e:
                _tasks[task_id]["status"] = "error"
                _tasks[task_id]["error"] = f"下载失败: {e}"
            except Exception as e:
                _tasks[task_id]["status"] = "error"
                _tasks[task_id]["error"] = f"工作流启动失败: {e}"
            finally:
                session.close()

        _executor.submit(run_download_and_parse)
        return jsonify({"task_id": task_id, "file_name": file_name})
    except requests.exceptions.RequestException as e:
        return jsonify({"error": f"预检失败: {e}"}), 502
    except Exception as e:
        task = _tasks.get(task_id)
        if task:
            task["status"] = "error"
            task["error"] = f"工作流启动失败: {e}"
        return jsonify({"error": f"工作流启动失败: {e}"}), 500

@app.route('/api/task/<task_id>')
def task_detail(task_id):
    task = _tasks.get(task_id)
    if not task:
        return jsonify({"error": "Task not found"}), 404

    return jsonify({
        "task_id": task_id,
        "status": task.get("status"),
        "transcript": task.get("transcript", ""),
        "polished": task.get("polished", ""),
        "summary": task.get("summary", ""),
        "metadata": task.get("metadata", {}),
        "file_name": task.get("file_name", ""),
        "error": task.get("error"),
        "download_progress": task.get("download_progress", {}),
        "intake_progress": task.get("intake_progress", {}),
    })

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
            download_progress = task.get("download_progress") or {}
            intake_progress = task.get("intake_progress") or {}

            if last_status == "" and status == "downloading":
                yield f"data: {json.dumps({'type': 'download_start', 'task_id': task_id, 'metadata': metadata, 'file_name': task.get('file_name'), 'progress': download_progress.get('progress', 0), 'downloaded_bytes': download_progress.get('downloaded_bytes', 0), 'total_bytes': download_progress.get('total_bytes', 0), 'eta_seconds': download_progress.get('eta_seconds'), 'speed_bytes_per_sec': download_progress.get('speed_bytes_per_sec', 0)})}\n\n"

            if status == "downloading":
                yield f"data: {json.dumps({'type': 'download_progress', 'task_id': task_id, 'progress': download_progress.get('progress', 0), 'downloaded_bytes': download_progress.get('downloaded_bytes', 0), 'total_bytes': download_progress.get('total_bytes', 0), 'eta_seconds': download_progress.get('eta_seconds'), 'speed_bytes_per_sec': download_progress.get('speed_bytes_per_sec', 0), 'phase': download_progress.get('phase', 'running')})}\n\n"

            if intake_progress and intake_progress.get('progress', 0) > 0:
                yield f"data: {json.dumps({'type': 'ingest_progress', 'task_id': task_id, 'progress': intake_progress.get('progress', 0), 'processed_bytes': intake_progress.get('processed_bytes', 0), 'total_bytes': intake_progress.get('total_bytes', 0), 'eta_seconds': intake_progress.get('eta_seconds'), 'phase': intake_progress.get('phase', 'preparing')})}\n\n"

            if last_status == "downloading" and status == "transcribing":
                yield f"data: {json.dumps({'type': 'download_done', 'task_id': task_id, 'progress': 100, 'downloaded_bytes': download_progress.get('downloaded_bytes', 0), 'total_bytes': download_progress.get('total_bytes', 0), 'metadata': metadata})}\n\n"
                yield f"data: {json.dumps({'type': 'ingest_done', 'task_id': task_id, 'progress': intake_progress.get('progress', 100), 'processed_bytes': intake_progress.get('processed_bytes', 0), 'total_bytes': intake_progress.get('total_bytes', 0)})}\n\n"
                yield f"data: {json.dumps({'type': 'transcribe_start'})}\n\n"

            if last_status == "" and status == "transcribing":
                if intake_progress:
                    yield f"data: {json.dumps({'type': 'ingest_done', 'task_id': task_id, 'progress': intake_progress.get('progress', 100), 'processed_bytes': intake_progress.get('processed_bytes', 0), 'total_bytes': intake_progress.get('total_bytes', 0)})}\n\n"
                yield f"data: {json.dumps({'type': 'transcribe_start'})}\n\n"

            if transcript and transcript != last_transcript:
                yield f"data: {json.dumps({'type': 'chunk', 'text': transcript})}\n\n"
                last_transcript = transcript

            if last_status == "transcribing" and status in ("polishing", "summarizing", "done"):
                yield f"data: {json.dumps({'type': 'transcribe_done'})}\n\n"

            if last_status != "polishing" and status == "polishing":
                yield f"data: {json.dumps({'type': 'polish_start'})}\n\n"

            if polished and polished != last_polished:
                yield f"data: {json.dumps({'type': 'polish_char', 'text': polished})}\n\n"
                last_polished = polished

            if last_status in ("polishing", "transcribing") and status in ("summarizing", "done") and polished:
                yield f"data: {json.dumps({'type': 'polish_done', 'polished_text': polished})}\n\n"

            if last_status != "summarizing" and status == "summarizing":
                yield f"data: {json.dumps({'type': 'summary_start'})}\n\n"

            if summary and summary != last_summary:
                yield f"data: {json.dumps({'type': 'summary_char', 'text': summary})}\n\n"
                last_summary = summary

            if status == "done":
                if summary:
                    yield f"data: {json.dumps({'type': 'summary_done', 'summary_text': summary})}\n\n"
                yield f"data: {json.dumps({'type': 'done', 'raw_text': transcript, 'polished_text': polished, 'summary_text': summary, 'char_count': len(polished), 'metadata': metadata, 'task_id': task_id})}\n\n"
                break

            if status == "error":
                yield f"data: {json.dumps({'type': 'error', 'error': error or 'Unknown error'})}\n\n"
                break

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


@app.route('/api/reference/mp4-history', methods=['POST'])
def save_mp4_history():
    data = request.get_json() or {}
    task_id = data.get("task_id")
    if not task_id:
        return jsonify({"error": "Task ID is required"}), 400

    try:
        result = export_task_to_reference(task_id)
        return jsonify(result)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": f"保存历史记录失败: {e}"}), 500


@app.route('/api/reference/mp4-history')
def list_mp4_history():
    return jsonify({"items": load_reference_history_list()})


@app.route('/api/reference/mp4-history/reorder', methods=['POST'])
def reorder_mp4_history():
    data = request.get_json() or {}
    ordered_ids = data.get("ordered_ids") or []
    if not isinstance(ordered_ids, list):
        return jsonify({"error": "ordered_ids must be a list"}), 400
    items = reorder_reference_history_items([str(item_id) for item_id in ordered_ids])
    return jsonify({"items": items})


@app.route('/api/reference/mp4-history/<history_id>')
def get_mp4_history(history_id):
    detail = load_reference_history_detail(history_id)
    if not detail:
        return jsonify({"error": "History record not found"}), 404
    return jsonify(detail)


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
    ascii_filename = filename.encode('ascii', 'replace').decode('ascii')
    utf8_filename = quote(filename)

    return Response(
        markdown,
        mimetype='text/markdown; charset=utf-8',
        headers={
            'Content-Disposition': f"attachment; filename=\"{ascii_filename}\"; filename*=UTF-8''{utf8_filename}",
        }
    )


@app.route('/api/ask', methods=['POST'])
def ask_about_content():
    data = request.get_json()
    if not data:
        return jsonify({"error": "Invalid request"}), 400

    task_id = data.get("task_id")
    question = data.get("question", "").strip()

    if not task_id:
        return jsonify({"error": "Task ID is required"}), 400
    if not question:
        return jsonify({"error": "Question cannot be empty"}), 400

    task = _tasks.get(task_id)
    if not task:
        return jsonify({"error": "Task not found"}), 404
    if task.get("status") != "done":
        return jsonify({"error": "Task is not completed yet"}), 400

    polished = (task.get("polished") or "").strip()
    summary = (task.get("summary") or "").strip()

    if not polished and not summary:
        return jsonify({"error": "No content available for Q&A"}), 400

    polisher = get_polisher()
    answer = polisher.ask_about_content(question, polished, summary)
    task.setdefault("qa_items", []).insert(0, {
        "id": f"qa-{int(time.time() * 1000)}",
        "question": question,
        "answer": answer,
        "created_at": datetime.now().isoformat(),
    })
    return jsonify({"answer": answer})

if __name__ == '__main__':
    import socket
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
