import os
import logging
import socket
import subprocess


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


def run_dev_server(app, host: str = '0.0.0.0', port: int = 5000) -> None:
    hot_reload = _env_flag('FLASK_HOT_RELOAD', True)
    debug = _env_flag('FLASK_DEBUG', False)

    # Werkzeug reloader 会启动一个子进程；端口接管只在父进程做一次。
    if os.environ.get('WERKZEUG_RUN_MAIN') != 'true':
        ensure_port_available(port)

    reload_label = 'on' if hot_reload else 'off'
    debug_label = 'on' if debug else 'off'
    logger.info('starting Flask host=%s port=%s hot_reload=%s debug=%s', host, port, reload_label, debug_label)
    app.run(host=host, port=port, debug=debug, threaded=True, use_reloader=hot_reload)
