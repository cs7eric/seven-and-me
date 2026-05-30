from concurrent.futures import ThreadPoolExecutor
import time


class TaskRuntimeStore:
    def __init__(self, max_workers: int = 2):
        self.executor = ThreadPoolExecutor(max_workers=max_workers)
        self.tasks: dict[str, dict] = {}

    def get_task(self, task_id: str) -> dict | None:
        return self.tasks.get(task_id)

    def set_task(self, task_id: str, task: dict) -> dict:
        self.tasks[task_id] = task
        return task

    def update_task(self, task_id: str, **fields) -> dict | None:
        task = self.tasks.get(task_id)
        if not task:
            return None
        task.update(fields)
        return task

    def create_task_record(self, task_id: str, file_name: str, source_url: str | None = None) -> dict:
        now = time.time()
        task = {
            'status': 'transcribing',
            'transcript': '',
            'polished': '',
            'summary': '',
            'metadata': {},
            'file_name': file_name,
            'polish_progress': 0,
            'summary_progress': 0,
            'error': None,
            'created_at': now,
            'download_progress': {
                'phase': 'pending',
                'progress': 0,
                'downloaded_bytes': 0,
                'total_bytes': 0,
                'eta_seconds': None,
                'speed_bytes_per_sec': 0,
            },
            'intake_progress': {
                'phase': 'pending',
                'progress': 0,
                'processed_bytes': 0,
                'total_bytes': 0,
                'eta_seconds': None,
            },
        }
        if source_url:
            task['source_url'] = source_url
        self.tasks[task_id] = task
        return task


runtime_store = TaskRuntimeStore()
