from backend.config.settings import (
    REFERENCE_FOLDER,
    REFERENCE_INDEX_FILE,
    MP4_REFERENCE_DATA_FOLDER,
    MP4_REFERENCE_TYPE_INDEX,
    STOCK_REFERENCE_INDEX_FILE,
    STOCK_REFERENCE_DATA_FOLDER,
    STOCK_REFERENCE_ANNOTATION_INDEX_FILE,
    STOCK_REFERENCE_WORKSPACE_INDEX_FILE,
)
from backend.utils.json_io import read_json_file, write_json_file


def ensure_reference_index_files():
    if not REFERENCE_INDEX_FILE.exists() or REFERENCE_INDEX_FILE.stat().st_size == 0:
        write_json_file(REFERENCE_INDEX_FILE, {
            'version': 1,
            'updated_at': None,
            'types': {
                'mp4_parse': {
                    'title': 'MP4 Parse History',
                    'index_file': str(MP4_REFERENCE_TYPE_INDEX.relative_to(REFERENCE_FOLDER)).replace('\\', '/'),
                    'data_dir': str(MP4_REFERENCE_DATA_FOLDER.relative_to(REFERENCE_FOLDER)).replace('\\', '/'),
                    'count': 0,
                },
                'stock_chart': {
                    'title': 'Stock Chart Workspace',
                    'index_file': str(STOCK_REFERENCE_INDEX_FILE.relative_to(REFERENCE_FOLDER)).replace('\\', '/'),
                    'data_dir': str(STOCK_REFERENCE_DATA_FOLDER.relative_to(REFERENCE_FOLDER)).replace('\\', '/'),
                    'count': 0,
                },
            },
        })

    if not MP4_REFERENCE_TYPE_INDEX.exists() or MP4_REFERENCE_TYPE_INDEX.stat().st_size == 0:
        write_json_file(MP4_REFERENCE_TYPE_INDEX, {
            'type': 'mp4_parse',
            'version': 1,
            'updated_at': None,
            'items': [],
        })

    if not STOCK_REFERENCE_INDEX_FILE.exists() or STOCK_REFERENCE_INDEX_FILE.stat().st_size == 0:
        write_json_file(STOCK_REFERENCE_INDEX_FILE, {
            'type': 'stock_chart',
            'version': 1,
            'updated_at': None,
            'items': [],
        })

    if not STOCK_REFERENCE_ANNOTATION_INDEX_FILE.exists() or STOCK_REFERENCE_ANNOTATION_INDEX_FILE.stat().st_size == 0:
        write_json_file(STOCK_REFERENCE_ANNOTATION_INDEX_FILE, {
            'type': 'stock_chart_annotations',
            'version': 1,
            'updated_at': None,
            'items': [],
        })

    if not STOCK_REFERENCE_WORKSPACE_INDEX_FILE.exists() or STOCK_REFERENCE_WORKSPACE_INDEX_FILE.stat().st_size == 0:
        write_json_file(STOCK_REFERENCE_WORKSPACE_INDEX_FILE, {
            'type': 'stock_chart_workspaces',
            'version': 1,
            'updated_at': None,
            'items': [],
        })
