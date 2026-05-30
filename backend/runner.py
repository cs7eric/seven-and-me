import socket
import subprocess


def ensure_port_available(port: int) -> None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    result = sock.connect_ex(('127.0.0.1', port))
    if result == 0:
        print(f'[启动] 端口 {port} 已被占用，尝试接管...')
        try:
            netstat_result = subprocess.run(['netstat', '-ano'], capture_output=True, text=True)
            for line in netstat_result.stdout.split('\n'):
                if f':{port}' in line and 'LISTENING' in line:
                    pid = int(line.split()[-1])
                    print(f'[启动] 杀掉残留进程 PID={pid}')
                    subprocess.run(['taskkill', '/F', '/PID', str(pid)], capture_output=True)
                    break
        except Exception:
            pass
    sock.close()


def run_dev_server(app, host: str = '0.0.0.0', port: int = 5000) -> None:
    ensure_port_available(port)
    print(f'[启动] 启动 Flask on {host}:{port}')
    app.run(host=host, port=port, debug=False, threaded=True, use_reloader=False)
