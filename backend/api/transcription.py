import json
import time
import uuid
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from flask import Blueprint, Response, jsonify, request
from werkzeug.utils import secure_filename

from backend.config.settings import DOWNLOAD_HEADERS, UPLOAD_FOLDER
from backend.services.export_service import build_download_filename, build_export_filename, build_markdown_document
from backend.services.transcription_service import queue_remote_parse, start_transcription_task


def create_transcription_bp(runtime_store, get_transcriber, get_polisher):
    transcription_bp = Blueprint('transcription', __name__)

    @transcription_bp.route('/api/transcribe', methods=['POST'])
    def transcribe():
        if 'file' not in request.files:
            return jsonify({'error': '没有文件'}), 400

        file = request.files['file']
        if file.filename == '':
            return jsonify({'error': '文件名为空'}), 400

        task_id = str(uuid.uuid4())
        file_path = UPLOAD_FOLDER / f'{task_id}_{secure_filename(file.filename)}'

        try:
            file.save(str(file_path))
        except Exception as exc:
            return jsonify({'error': f'文件保存失败: {exc}'}), 500

        runtime_store.create_task_record(task_id, file.filename)

        try:
            start_transcription_task(runtime_store, get_transcriber, get_polisher, task_id, file_path, file.filename)
        except Exception as exc:
            task = runtime_store.get_task(task_id)
            if task is not None:
                task['status'] = 'error'
                task['error'] = str(exc)
            return jsonify({'error': f'转换音频失败: {exc}'}), 500

        return jsonify({'task_id': task_id})

    @transcription_bp.route('/api/parse-video', methods=['POST'])
    def parse_video_from_downloader():
        data = request.get_json()
        if not data:
            return jsonify({'error': 'Invalid request'}), 400

        source_url = str(data.get('download_url') or '').strip()
        title = str(data.get('title') or '').strip()
        source_page_url = str(data.get('source_url') or '').strip()
        metadata = data.get('metadata') if isinstance(data.get('metadata'), dict) else {}

        if not source_url:
            return jsonify({'error': 'download_url is required'}), 400

        task_id = str(uuid.uuid4())

        try:
            file_name = queue_remote_parse(runtime_store, get_transcriber, get_polisher, task_id, source_url, title, source_page_url, metadata)
            return jsonify({'task_id': task_id, 'file_name': file_name})
        except Exception as exc:
            task = runtime_store.get_task(task_id)
            if task:
                task['status'] = 'error'
                task['error'] = f'工作流启动失败: {exc}'
            return jsonify({'error': f'工作流启动失败: {exc}'}), 500

    @transcription_bp.route('/api/task/<task_id>')
    def task_detail(task_id):
        task = runtime_store.get_task(task_id)
        if not task:
            return jsonify({'error': 'Task not found'}), 404

        return jsonify({
            'task_id': task_id,
            'status': task.get('status'),
            'transcript': task.get('transcript', ''),
            'polished': task.get('polished', ''),
            'summary': task.get('summary', ''),
            'metadata': task.get('metadata', {}),
            'file_name': task.get('file_name', ''),
            'error': task.get('error'),
            'download_progress': task.get('download_progress', {}),
            'intake_progress': task.get('intake_progress', {}),
        })

    @transcription_bp.route('/api/stream/<task_id>')
    def stream(task_id):
        def generate():
            if runtime_store.get_task(task_id) is None:
                yield f"data: {json.dumps({'type': 'error', 'error': 'Task not found'})}\n\n"
                return

            last_status = ''
            last_transcript = ''
            last_polished = ''
            last_summary = ''
            last_poll = time.time()

            while True:
                task = runtime_store.get_task(task_id)
                if not task:
                    yield f"data: {json.dumps({'type': 'error', 'error': 'Task disappeared'})}\n\n"
                    break

                status = task['status']
                transcript = task.get('transcript', '')
                polished = task.get('polished', '')
                summary = task.get('summary', '')
                metadata = task.get('metadata', {})
                error = task.get('error')
                download_progress = task.get('download_progress') or {}
                intake_progress = task.get('intake_progress') or {}

                if last_status == '' and status == 'downloading':
                    yield f"data: {json.dumps({'type': 'download_start', 'task_id': task_id, 'metadata': metadata, 'file_name': task.get('file_name'), 'progress': download_progress.get('progress', 0), 'downloaded_bytes': download_progress.get('downloaded_bytes', 0), 'total_bytes': download_progress.get('total_bytes', 0), 'eta_seconds': download_progress.get('eta_seconds'), 'speed_bytes_per_sec': download_progress.get('speed_bytes_per_sec', 0)})}\n\n"

                if status == 'downloading':
                    yield f"data: {json.dumps({'type': 'download_progress', 'task_id': task_id, 'progress': download_progress.get('progress', 0), 'downloaded_bytes': download_progress.get('downloaded_bytes', 0), 'total_bytes': download_progress.get('total_bytes', 0), 'eta_seconds': download_progress.get('eta_seconds'), 'speed_bytes_per_sec': download_progress.get('speed_bytes_per_sec', 0), 'phase': download_progress.get('phase', 'running')})}\n\n"

                if intake_progress and intake_progress.get('progress', 0) > 0:
                    yield f"data: {json.dumps({'type': 'ingest_progress', 'task_id': task_id, 'progress': intake_progress.get('progress', 0), 'processed_bytes': intake_progress.get('processed_bytes', 0), 'total_bytes': intake_progress.get('total_bytes', 0), 'eta_seconds': intake_progress.get('eta_seconds'), 'phase': intake_progress.get('phase', 'preparing')})}\n\n"

                if last_status == 'downloading' and status == 'transcribing':
                    yield f"data: {json.dumps({'type': 'download_done', 'task_id': task_id, 'progress': 100, 'downloaded_bytes': download_progress.get('downloaded_bytes', 0), 'total_bytes': download_progress.get('total_bytes', 0), 'metadata': metadata})}\n\n"
                    yield f"data: {json.dumps({'type': 'ingest_done', 'task_id': task_id, 'progress': intake_progress.get('progress', 100), 'processed_bytes': intake_progress.get('processed_bytes', 0), 'total_bytes': intake_progress.get('total_bytes', 0)})}\n\n"
                    yield f"data: {json.dumps({'type': 'transcribe_start'})}\n\n"

                if last_status == '' and status == 'transcribing':
                    if intake_progress:
                        yield f"data: {json.dumps({'type': 'ingest_done', 'task_id': task_id, 'progress': intake_progress.get('progress', 100), 'processed_bytes': intake_progress.get('processed_bytes', 0), 'total_bytes': intake_progress.get('total_bytes', 0)})}\n\n"
                    yield f"data: {json.dumps({'type': 'transcribe_start'})}\n\n"

                if transcript and transcript != last_transcript:
                    yield f"data: {json.dumps({'type': 'chunk', 'text': transcript})}\n\n"
                    last_transcript = transcript

                if last_status == 'transcribing' and status in ('polishing', 'summarizing', 'done'):
                    yield f"data: {json.dumps({'type': 'transcribe_done'})}\n\n"

                if last_status != 'polishing' and status == 'polishing':
                    yield f"data: {json.dumps({'type': 'polish_start'})}\n\n"

                if polished and polished != last_polished:
                    yield f"data: {json.dumps({'type': 'polish_char', 'text': polished})}\n\n"
                    last_polished = polished

                if last_status in ('polishing', 'transcribing') and status in ('summarizing', 'done') and polished:
                    yield f"data: {json.dumps({'type': 'polish_done', 'polished_text': polished})}\n\n"

                if last_status != 'summarizing' and status == 'summarizing':
                    yield f"data: {json.dumps({'type': 'summary_start'})}\n\n"

                if summary and summary != last_summary:
                    yield f"data: {json.dumps({'type': 'summary_char', 'text': summary})}\n\n"
                    last_summary = summary

                if status == 'done':
                    if summary:
                        yield f"data: {json.dumps({'type': 'summary_done', 'summary_text': summary})}\n\n"
                    yield f"data: {json.dumps({'type': 'done', 'raw_text': transcript, 'polished_text': polished, 'summary_text': summary, 'char_count': len(polished), 'metadata': metadata, 'task_id': task_id})}\n\n"
                    break

                if status == 'error':
                    yield f"data: {json.dumps({'type': 'error', 'error': error or 'Unknown error'})}\n\n"
                    break

                if time.time() - last_poll > 300:
                    yield f"data: {json.dumps({'type': 'error', 'error': '处理超时'})}\n\n"
                    break

                last_status = status
                last_poll = time.time()
                time.sleep(0.3)

        return Response(generate(), mimetype='text/event-stream', headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no',
        })

    @transcription_bp.route('/api/export-markdown/<task_id>')
    def export_markdown(task_id):
        task = runtime_store.get_task(task_id)
        if not task:
            return jsonify({'error': 'Task not found'}), 404

        if task.get('status') != 'done':
            return jsonify({'error': '任务尚未完成，暂时不能导出 Markdown'}), 400

        markdown = build_markdown_document(task, datetime.now().strftime('%Y/%m/%d %H:%M:%S'))
        filename = build_export_filename(task, task_id)
        ascii_filename = filename.encode('ascii', 'replace').decode('ascii')
        utf8_filename = quote(filename)

        return Response(
            markdown,
            mimetype='text/markdown; charset=utf-8',
            headers={
                'Content-Disposition': f"attachment; filename=\"{ascii_filename}\"; filename*=UTF-8''{utf8_filename}",
            },
        )

    @transcription_bp.route('/api/ask', methods=['POST'])
    def ask_about_content():
        data = request.get_json()
        if not data:
            return jsonify({'error': 'Invalid request'}), 400

        task_id = data.get('task_id')
        question = str(data.get('question', '')).strip()

        if not task_id:
            return jsonify({'error': 'Task ID is required'}), 400
        if not question:
            return jsonify({'error': 'Question cannot be empty'}), 400

        task = runtime_store.get_task(task_id)
        if not task:
            return jsonify({'error': 'Task not found'}), 404
        if task.get('status') != 'done':
            return jsonify({'error': 'Task is not completed yet'}), 400

        polished = str(task.get('polished') or '').strip()
        summary = str(task.get('summary') or '').strip()
        if not polished and not summary:
            return jsonify({'error': 'No content available for Q&A'}), 400

        polisher = get_polisher()
        answer = polisher.ask_about_content(question, polished, summary)
        task.setdefault('qa_items', []).insert(0, {
            'id': f'qa-{int(time.time() * 1000)}',
            'question': question,
            'answer': answer,
            'created_at': datetime.now().isoformat(),
        })
        return jsonify({'answer': answer})

    return transcription_bp
