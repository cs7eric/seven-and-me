import os
import logging
import socket
import subprocess
import sys
from pathlib import Path


logger = logging.getLogger(__name__)


def ensure_port_available(port: int) -> None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    result = sock.connect_ex(('127.0.0.1', port))
    if result == 0:
        logger.info('port %s is busy, trying to take over stale process', port)
        try:
            netstat_result = subprocess.run(['netstat', '-ano'], capture_output=True, text=True)
            for line in netstat_result.stdout.split('\n'):
                if f':{port}' in line and 'LISTENING' in line:
                    pid = int(line.split()[-1])
                    logger.info('killing stale process pid=%s on port=%s', pid, port)
                    subprocess.run(['taskkill', '/F', '/PID', str(pid)], capture_output=True)
                    break
        except Exception:
            logger.exception('failed to inspect or free port %s', port)
    sock.close()


def _env_flag(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() not in {'0', 'false', 'no', 'off'}


def _backend_root() -> Path:
    return Path(__file__).resolve().parent


def _reloader_extra_files() -> list[str]:
    raw = os.getenv('FLASK_RELOADER_FILES')
    if raw:
        return [item.strip() for item in raw.split(';') if item.strip()]
    backend_root = _backend_root()
    excluded_parts = {'__pycache__', 'scripts', 'reference'}
    return [
        str(path)
        for path in backend_root.rglob('*.py')
        if not any(part in excluded_parts for part in path.relative_to(backend_root).parts)
    ]


def _reloader_exclude_patterns() -> list[str]:
    raw = os.getenv('FLASK_RELOADER_EXCLUDE')
    if raw:
        return [item.strip() for item in raw.split(';') if item.strip()]
    repo_root = _backend_root().parent
    backend_root = _backend_root()
    stdlib_dir = os.path.dirname(os.__file__)
    site_packages_dir = next(
        (p for p in sys.path if p.endswith(('site-packages', 'dist-packages'))),
        None,
    )
    patterns = [
        os.path.join(stdlib_dir, '*'),
        os.path.join(stdlib_dir, '**', '*'),
        str(repo_root / 'scripts' / '*'),
        str(repo_root / 'scripts' / '**' / '*'),
        str(repo_root / 'runtime' / '*'),
        str(repo_root / 'runtime' / '**' / '*'),
        str(repo_root / 'scheduler' / '*'),
        str(repo_root / 'scheduler' / '**' / '*'),
        str(repo_root / 'reference' / '*'),
        str(repo_root / 'reference' / '**' / '*'),
        str(repo_root / 'frontend' / '*'),
        str(repo_root / 'frontend' / '**' / '*'),
        str(backend_root / '__pycache__' / '*'),
        str(backend_root / '**' / '__pycache__' / '*'),
        str(backend_root / 'scripts' / '*'),
        str(backend_root / 'scripts' / '**' / '*'),
        str(backend_root / 'reference' / '*'),
        str(backend_root / 'reference' / '**' / '*'),
    ]
    if site_packages_dir:
        patterns.extend([
            os.path.join(site_packages_dir, '*'),
            os.path.join(site_packages_dir, '**', '*'),
        ])
    patterns.extend([
        'scripts/*',
        'runtime/*',
        'scheduler/*',
        'reference/*',
        '*.duckdb',
        '*.duckdb.wal',
        '*.log',
        '__pycache__/*',
    ])
    return patterns


def run_dev_server(app, host: str = '0.0.0.0', port: int = 5000) -> None:
    hot_reload = _env_flag('FLASK_HOT_RELOAD', True)
    debug = _env_flag('FLASK_DEBUG', False)

    # Werkzeug reloader 会启动一个子进程；端口接管只在父进程做一次。
    if os.environ.get('WERKZEUG_RUN_MAIN') != 'true':
        ensure_port_available(port)

    reload_label = 'on' if hot_reload else 'off'
    debug_label = 'on' if debug else 'off'
    logger.info('starting Flask host=%s port=%s hot_reload=%s debug=%s', host, port, reload_label, debug_label)
    app.run(
        host=host,
        port=port,
        debug=debug,
        threaded=True,
        use_reloader=hot_reload,
        extra_files=_reloader_extra_files(),
        exclude_patterns=_reloader_exclude_patterns(),
    )
