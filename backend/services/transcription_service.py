import subprocess
import time
from pathlib import Path

import imageio_ffmpeg
import requests

from backend.config.settings import DOWNLOAD_HEADERS, UPLOAD_FOLDER
from backend.services.export_service import build_download_filename


def start_transcription_task(runtime_store, get_transcriber, get_polisher, task_id: str, file_path: Path, display_name: str):
    wav_path = UPLOAD_FOLDER / f'{task_id}_audio.wav'
    filename_lower = display_name.lower()
    is_audio = any(filename_lower.endswith(ext) for ext in ('.mp3', '.wav', '.m4a', '.aac', '.ogg', '.flac', '.aiff'))

    try:
        source_size = file_path.stat().st_size
    except OSError:
        source_size = 0

    task = runtime_store.get_task(task_id)
    if task:
        task['intake_progress'] = {
            'phase': 'preparing',
            'progress': 8,
            'processed_bytes': 0,
            'total_bytes': source_size,
            'eta_seconds': None,
        }

    if is_audio:
        audio_path = str(file_path)
        if task:
            task['intake_progress'] = {
                'phase': 'ready',
                'progress': 100,
                'processed_bytes': source_size,
                'total_bytes': source_size,
                'eta_seconds': 0,
            }
    else:
        audio_path = str(wav_path)
        if task:
            task['intake_progress'] = {
                'phase': 'preparing',
                'progress': 22,
                'processed_bytes': 0,
                'total_bytes': source_size,
                'eta_seconds': None,
            }
        ffmpeg_cmd = [
            imageio_ffmpeg.get_ffmpeg_exe(),
            '-y', '-i', str(file_path),
            '-ar', '16000', '-ac', '1', '-acodec', 'pcm_s16le',
            str(wav_path),
        ]
        result = subprocess.run(ffmpeg_cmd, capture_output=True, timeout=300)
        if result.returncode != 0:
            raise RuntimeError('ffmpeg 转换失败')
        if task:
            try:
                prepared_size = wav_path.stat().st_size
            except OSError:
                prepared_size = source_size
            task['intake_progress'] = {
                'phase': 'ready',
                'progress': 100,
                'processed_bytes': prepared_size,
                'total_bytes': prepared_size,
                'eta_seconds': 0,
            }

    def on_chunk(chunk_idx, text, is_final):
        current = runtime_store.get_task(task_id)
        if current is not None:
            current['transcript'] = text

    def run():
        try:
            transcriber = get_transcriber()
            transcriber.transcribe_streaming(audio_path, chunk_duration=30, callback=on_chunk)

            task = runtime_store.get_task(task_id)
            if not task:
                return
            text = task.get('transcript', '')
            if not text:
                task['status'] = 'error'
                task['error'] = '转写结果为空'
                return

            task['status'] = 'polishing'
            polisher = get_polisher()

            def on_polish_chunk(current_text):
                current = runtime_store.get_task(task_id)
                if current is not None:
                    current['polished'] = current_text

            polished = polisher.polish(text, on_chunk=on_polish_chunk)
            task['polished'] = polished
            task['polish_progress'] = 100
            task['status'] = 'summarizing'

            def on_summary_chunk(current_text):
                current = runtime_store.get_task(task_id)
                if current is not None:
                    current['summary'] = current_text

            summary = polisher.summarize(polished, on_chunk=on_summary_chunk)
            task['summary'] = summary
            task['summary_progress'] = 100
            task['metadata'] = polisher.generate_post_metadata(polished, summary)
            task['status'] = 'done'
        except Exception as exc:
            task = runtime_store.get_task(task_id)
            if task is not None:
                task['status'] = 'error'
                task['error'] = str(exc)

    runtime_store.executor.submit(run)


def queue_remote_parse(runtime_store, get_transcriber, get_polisher, task_id: str, source_url: str, title: str, source_page_url: str, metadata: dict):
    session = requests.Session()
    head_response = session.head(source_url, allow_redirects=True, timeout=(5, 15), headers=DOWNLOAD_HEADERS)
    file_name = build_download_filename(
        source_url,
        title,
        head_response.headers.get('Content-Type') if head_response.ok else None,
    )
    runtime_store.create_task_record(task_id, file_name, source_page_url or source_url)
    task = runtime_store.get_task(task_id)
    task['metadata'] = {
        **metadata,
        'title': title or metadata.get('title') or Path(file_name).stem,
        'source_url': source_page_url or source_url,
        'download_url': source_url,
    }
    task['status'] = 'downloading'
    task['download_progress'] = {
        'phase': 'queued',
        'progress': 0,
        'downloaded_bytes': 0,
        'total_bytes': int(head_response.headers.get('Content-Length') or 0),
        'eta_seconds': None,
        'speed_bytes_per_sec': 0,
    }
    task['intake_progress'] = {
        'phase': 'pending',
        'progress': 0,
        'processed_bytes': 0,
        'total_bytes': 0,
        'eta_seconds': None,
    }

    def run_download_and_parse():
        try:
            request_headers = {
                **DOWNLOAD_HEADERS,
                'Referer': source_page_url or DOWNLOAD_HEADERS['Referer'],
            }
            with session.get(source_url, stream=True, timeout=(10, 300), headers=request_headers) as response:
                response.raise_for_status()
                resolved_file_name = build_download_filename(source_url, title, response.headers.get('Content-Type'))
                file_path = UPLOAD_FOLDER / f'{task_id}_{resolved_file_name}'.replace(' ', '_')
                task = runtime_store.get_task(task_id)
                if not task:
                    return
                task['file_name'] = resolved_file_name
                task['metadata']['title'] = title or metadata.get('title') or Path(resolved_file_name).stem

                total_size = int(response.headers.get('Content-Length') or 0)
                downloaded = 0
                started_at = time.time()
                task['download_progress'] = {
                    'phase': 'running',
                    'progress': 1,
                    'downloaded_bytes': 0,
                    'total_bytes': total_size,
                    'eta_seconds': None,
                    'speed_bytes_per_sec': 0,
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
                        task['download_progress'] = {
                            'phase': 'running',
                            'progress': min(progress, 99 if total_size else progress),
                            'downloaded_bytes': downloaded,
                            'total_bytes': total_size,
                            'eta_seconds': eta_seconds,
                            'speed_bytes_per_sec': int(speed),
                        }

                if total_size and downloaded != total_size:
                    raise RuntimeError('下载文件不完整')

            task['download_progress'] = {
                'phase': 'done',
                'progress': 100,
                'downloaded_bytes': downloaded,
                'total_bytes': total_size,
                'eta_seconds': 0,
                'speed_bytes_per_sec': task['download_progress'].get('speed_bytes_per_sec', 0),
            }
            task['status'] = 'transcribing'
            start_transcription_task(runtime_store, get_transcriber, get_polisher, task_id, file_path, resolved_file_name)
        except requests.exceptions.RequestException as exc:
            task = runtime_store.get_task(task_id)
            if task is not None:
                task['status'] = 'error'
                task['error'] = f'下载失败: {exc}'
        except Exception as exc:
            task = runtime_store.get_task(task_id)
            if task is not None:
                task['status'] = 'error'
                task['error'] = f'工作流启动失败: {exc}'
        finally:
            session.close()

    runtime_store.executor.submit(run_download_and_parse)
    return file_name
