from pathlib import Path
from urllib.parse import urlparse
import mimetypes


def sanitize_filename(name: str) -> str:
    safe = ''.join(ch for ch in name if ch.isprintable() and ch not in ('<', '>', ':', '"', '/', '\\', '|', '?', '*')).strip()
    safe = safe.replace(' ', '-')
    return safe[:80] or 'untitled'


def build_export_filename(task: dict, task_id: str) -> str:
    metadata = task.get('metadata') or {}
    title = str(metadata.get('title') or '').strip()
    original_name = Path(str(task.get('file_name') or '')).stem

    base_name = sanitize_filename(title)
    if not base_name or base_name == 'untitled':
        base_name = sanitize_filename(original_name)

    if not base_name or base_name == 'untitled':
        base_name = 'untitled'

    return f'{base_name}.md'


def build_markdown_document(task: dict, now_text: str) -> str:
    metadata = task.get('metadata') or {}
    title = str(metadata.get('title') or 'Untitled Note').strip()
    categories = metadata.get('categories') or ['Uncategorized']
    tags = metadata.get('tags') or ['待整理']
    polished = str(task.get('polished') or '').strip()
    summary = str(task.get('summary') or '').strip()

    frontmatter = '\n'.join([
        '---',
        f'title: {title}',
        '',
        f'categories: {",".join(categories)}',
        '',
        f'tags: {",".join(tags)}',
        '',
        f'date: {now_text}',
        '---',
    ])

    sections = [frontmatter, polished, summary]
    return '\n\n'.join(section for section in sections if section)


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
    return f'{base}{ext}'
