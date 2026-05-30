from datetime import datetime
from pathlib import Path

from backend.config.settings import (
    MP4_REFERENCE_DATA_FOLDER,
    MP4_REFERENCE_TYPE_INDEX,
    REFERENCE_FOLDER,
    REFERENCE_INDEX_FILE,
)
from backend.repositories.reference_index import ensure_reference_index_files
from backend.utils.json_io import read_json_file, write_json_file


def mp4_history_file(history_id: str) -> Path:
    return MP4_REFERENCE_DATA_FOLDER / f'{history_id}.json'


def load_mp4_history_index() -> dict:
    ensure_reference_index_files()
    return read_json_file(MP4_REFERENCE_TYPE_INDEX, {
        'type': 'mp4_parse',
        'version': 1,
        'updated_at': None,
        'items': [],
    })


def save_mp4_history_index(index_payload: dict) -> dict:
    write_json_file(MP4_REFERENCE_TYPE_INDEX, index_payload)
    return index_payload


def update_mp4_root_index(count: int, updated_at: str) -> None:
    root_index = read_json_file(REFERENCE_INDEX_FILE, {
        'version': 1,
        'updated_at': None,
        'types': {},
    })
    root_index.setdefault('types', {})['mp4_parse'] = {
        'title': 'MP4 Parse History',
        'index_file': str(MP4_REFERENCE_TYPE_INDEX.relative_to(REFERENCE_FOLDER)).replace('\\', '/'),
        'data_dir': str(MP4_REFERENCE_DATA_FOLDER.relative_to(REFERENCE_FOLDER)).replace('\\', '/'),
        'count': count,
    }
    root_index['updated_at'] = updated_at
    write_json_file(REFERENCE_INDEX_FILE, root_index)


def save_mp4_history_record(history_id: str, payload: dict) -> dict:
    write_json_file(mp4_history_file(history_id), payload)
    return payload


def load_mp4_history_record(history_id: str) -> dict | None:
    return read_json_file(mp4_history_file(history_id), None)


def list_mp4_history_items() -> list[dict]:
    index_payload = load_mp4_history_index()
    return index_payload.get('items', [])


def upsert_mp4_history_item(item: dict) -> list[dict]:
    index_payload = load_mp4_history_index()
    items = [existing for existing in index_payload.get('items', []) if existing.get('id') != item.get('id')]
    items.insert(0, item)
    index_payload['items'] = items
    index_payload['updated_at'] = item.get('updated_at') or datetime.now().isoformat()
    save_mp4_history_index(index_payload)
    update_mp4_root_index(len(items), index_payload['updated_at'])
    return items


def reorder_mp4_history_index_items(ordered_ids: list[str]) -> list[dict]:
    index_payload = load_mp4_history_index()
    items = index_payload.get('items', [])
    item_map = {item.get('id'): item for item in items}
    reordered = [item_map[item_id] for item_id in ordered_ids if item_id in item_map]
    remaining = [item for item in items if item.get('id') not in ordered_ids]
    final_items = reordered + remaining
    updated_at = datetime.now().isoformat()
    index_payload['items'] = final_items
    index_payload['updated_at'] = updated_at
    save_mp4_history_index(index_payload)
    update_mp4_root_index(len(final_items), updated_at)
    return final_items


def delete_mp4_history_record(history_id: str) -> dict | None:
    index_payload = load_mp4_history_index()
    items = index_payload.get('items', [])
    target = next((item for item in items if item.get('id') == history_id), None)
    if not target:
        return None

    record_file = mp4_history_file(history_id)
    if record_file.exists():
        record_file.unlink()

    final_items = [item for item in items if item.get('id') != history_id]
    updated_at = datetime.now().isoformat()
    index_payload['items'] = final_items
    index_payload['updated_at'] = updated_at
    save_mp4_history_index(index_payload)
    update_mp4_root_index(len(final_items), updated_at)
    return target
