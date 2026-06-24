"""MP4 history reference service.

维护前请先看:
- `F:\\dev-repo\\mp4-to-word-new\\design\\backend\\mp4-history-reference-flow.md`

这里负责把 runtime task snapshot 导出到 reference 历史索引，并维护 Ask AI 附加记录。
"""
import time
from datetime import datetime

from backend.config.settings import REFERENCE_FOLDER
from backend.repositories.mp4_history_repo import (
    delete_mp4_history_record,
    list_mp4_history_items,
    load_mp4_history_record,
    mp4_history_file,
    reorder_mp4_history_index_items,
    save_mp4_history_record,
    upsert_mp4_history_item,
)


def build_task_snapshot(task_id: str, task: dict) -> dict:
    return {
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
        'qa_items': task.get('qa_items', []),
    }


def export_task_to_reference(task_id: str, task: dict) -> dict:
    if not task:
        raise ValueError('Task not found')
    if task.get('status') != 'done':
        raise ValueError('Task is not completed yet')

    snapshot = build_task_snapshot(task_id, task)
    metadata = snapshot.get('metadata') or {}
    title = str(metadata.get('title') or snapshot.get('file_name') or task_id).strip() or task_id
    created_at = datetime.now().isoformat()
    history_id = f'mp4-{task_id}'
    data_file = str(mp4_history_file(history_id).relative_to(REFERENCE_FOLDER)).replace('\\', '/')

    record_payload = {
        'id': history_id,
        'type': 'mp4_parse',
        'version': 1,
        'created_at': created_at,
        'updated_at': created_at,
        'title': title,
        'task': snapshot,
    }
    save_mp4_history_record(history_id, record_payload)

    upsert_mp4_history_item({
        'id': history_id,
        'title': title,
        'created_at': created_at,
        'updated_at': created_at,
        'task_id': task_id,
        'status': snapshot.get('status'),
        'file_name': snapshot.get('file_name'),
        'data_file': data_file,
    })

    return {
        'id': history_id,
        'title': title,
        'created_at': created_at,
        'data_file': data_file,
    }


def load_reference_history_list() -> list[dict]:
    return list_mp4_history_items()


def load_reference_history_detail(history_id: str) -> dict | None:
    return load_mp4_history_record(history_id)


def reorder_reference_history_items(ordered_ids: list[str]) -> list[dict]:
    return reorder_mp4_history_index_items(ordered_ids)


def delete_reference_history_item(history_id: str) -> dict:
    deleted = delete_mp4_history_record(history_id)
    if not deleted:
        raise ValueError('History record not found')
    return deleted


def add_mp4_history_qa(history_id: str, question: str, answer: str) -> dict:
    detail = load_mp4_history_record(history_id)
    if not detail:
        raise ValueError('History record not found')

    qa_item = {
        'id': f'qa-{int(time.time() * 1000)}',
        'question': question,
        'answer': answer,
        'created_at': datetime.now().isoformat(),
    }
    task = detail.get('task') or {}
    task.setdefault('qa_items', []).insert(0, qa_item)
    detail['task'] = task
    detail['updated_at'] = datetime.now().isoformat()
    save_mp4_history_record(history_id, detail)
    return qa_item
