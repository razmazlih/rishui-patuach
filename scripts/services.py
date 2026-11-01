"""Local stack lifecycle. Tracks only the web process started by this project.
No raw source files are read or changed; stopping never removes database storage.
"""
from __future__ import annotations
import argparse
import fcntl
import json
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.parse import urlparse
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
DATA = Path(os.environ.get('DATA_DIR') or str(ROOT / 'data')).resolve()
WORK = DATA / 'work' / 'services'
STATE = WORK / 'web.json'
LOG = WORK / 'web.log'
PORT = int(os.environ.get('PORT', '3000'))
URL = f'http://127.0.0.1:{PORT}'
DB_URL = os.environ.get('DATABASE_URL') or 'postgresql://vehicle:vehicle_local@127.0.0.1:55432/vehicles'


def run(args, **kwargs):
    return subprocess.run(args, cwd=ROOT, check=True, **kwargs)


def docker_available():
    if not shutil.which('docker'):
        return False
    try:
        return subprocess.run(['docker', 'info'], stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL, timeout=8).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def native_status():
    if not (DATA / 'work' / 'postgres' / 'PG_VERSION').is_file():
        return False
    return subprocess.run(['sh', 'scripts/local-postgres.sh', 'status'], cwd=ROOT,
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0


def managed_database():
    parsed = urlparse(DB_URL)
    return parsed.hostname in ('localhost', '127.0.0.1') and parsed.port == 55432 and parsed.path == '/vehicles'


def database_ready():
    import psycopg
    try:
        with psycopg.connect(DB_URL, connect_timeout=2) as conn:
            conn.execute('SELECT 1')
        return True
    except psycopg.Error:
        return False


def process_identity(pid):
    """Include process creation time to prevent signaling a recycled PID."""
    if not isinstance(pid, int) or pid <= 1:
        return None
    # Next.js changes its process title after boot; creation time stays stable.
    result = subprocess.run(['ps', '-p', str(pid), '-o', 'lstart='],
                            capture_output=True, text=True)
    return result.stdout.strip() if result.returncode == 0 else None


def state():
    try:
        return json.loads(STATE.read_text())
    except (OSError, ValueError):
        return {}


def web_running(saved):
    return bool(saved.get('identity') and saved['identity'] == process_identity(saved.get('pid')))


def http_ready(url):
    try:
        with urlopen(url, timeout=2) as response:
            return response.status == 200
    except (OSError, URLError):
        return False


def port_busy():
    with socket.socket() as sock:
        return sock.connect_ex(('127.0.0.1', PORT)) == 0


def start_database():
    if not managed_database():
        if not database_ready():
            raise RuntimeError('Configured external PostgreSQL is not reachable; it is not managed by this project.')
        return 'external'
    # Reuse the existing native data directory instead of creating a separate empty Docker database.
    if (DATA / 'work' / 'postgres' / 'PG_VERSION').is_file():
        backend = 'native'
    elif docker_available():
        backend = 'docker'
    else:
        backend = 'native'
    if backend == 'native':
        run(['sh', 'scripts/local-postgres.sh', 'start'])
    else:
        run(['docker', 'compose', 'up', '-d', '--wait', 'db'])
    for _ in range(30):
        if database_ready():
            return backend
        time.sleep(.5)
    raise RuntimeError('PostgreSQL did not become ready.')


def stop_web():
    saved = state()
    if web_running(saved):
        pid = saved['pid']
        # Each managed server has its own session, never the caller's process group.
        if os.getpgid(pid) != pid:
            raise RuntimeError('Managed web process group changed; refusing to signal another group.')
        os.killpg(pid, signal.SIGTERM)
        deadline = time.monotonic() + 12
        while time.monotonic() < deadline and web_running(saved):
            time.sleep(.1)
        if web_running(saved):
            os.killpg(pid, signal.SIGKILL)
        print('Web stopped.')
    else:
        print('Managed web is already stopped.')
    STATE.unlink(missing_ok=True)


def down():
    stop_web()
    # Stop both project backends, including an earlier explicit make up/db-native.
    if native_status():
        run(['sh', 'scripts/local-postgres.sh', 'stop'])
    if docker_available():
        run(['docker', 'compose', 'down'])
    print('Project services stopped. Database files and Docker volumes are preserved.')


def start():
    saved = state()
    if web_running(saved):
        if database_ready() and http_ready(saved['url']):
            print(f"All services are already ready: {saved['url']}")
            return
        raise RuntimeError('A managed server is running but unhealthy. Run make restart; see ' + str(LOG))
    if port_busy():
        raise RuntimeError(f'Port {PORT} is in use by an unmanaged process. Stop that server first; no unrelated process was stopped.')
    if not (ROOT / 'node_modules' / 'next').is_dir():
        raise RuntimeError('Install dependencies first: make setup')
    backend = start_database()
    run([sys.executable, '-m', 'importer.cli', 'migrate'])
    # Always build on a fresh start: the launched server must match current source.
    run(['npm', 'run', 'build'])
    env = {**os.environ, 'DATABASE_URL': DB_URL, 'DATA_MODE': os.environ.get('DATA_MODE') or 'live',
           'HOSTNAME': '127.0.0.1', 'PORT': str(PORT)}
    with LOG.open('ab') as output:
        process = subprocess.Popen(['node', str(ROOT / '.next' / 'standalone' / 'server.js')],
                                   cwd=ROOT, env=env, stdout=output, stderr=subprocess.STDOUT,
                                   start_new_session=True, stdin=subprocess.DEVNULL)
    try:
        identity = process_identity(process.pid)
        if not identity:
            raise RuntimeError('Web process exited before initialization.')
        STATE.write_text(json.dumps({'pid': process.pid, 'identity': identity, 'url': URL, 'backend': backend}))
        deadline = time.monotonic() + 40
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError('Web process exited during startup.')
            if http_ready(URL):
                print(f'All services ready: {URL}\nWeb runs in the background. Log: {LOG}\nStop: make down · Restart: make restart')
                return
            time.sleep(.25)
        raise RuntimeError('Web readiness timed out.')
    except BaseException:
        stop_web()
        raise


def status():
    saved = state()
    running = web_running(saved)
    print('Web: ' + ('ready at ' + saved['url'] if running and http_ready(saved['url']) else 'running but not ready' if running else 'stopped'))
    print('PostgreSQL: ' + ('ready' if database_ready() else 'stopped or unavailable'))
    print(f'Web log: {LOG}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['start', 'down', 'restart', 'status'])
    args = parser.parse_args()
    os.environ.update(DATABASE_URL=DB_URL, DATA_DIR=str(DATA),
                      DATA_MODE=os.environ.get('DATA_MODE') or 'live')
    WORK.mkdir(parents=True, exist_ok=True)
    with (WORK / 'controller.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('Another service command is running; wait for it to finish.') from None
        if args.action == 'restart':
            down()
            start()
        else:
            {'start': start, 'down': down, 'status': status}[args.action]()


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, subprocess.CalledProcessError, OSError) as error:
        print(f'Service command failed: {error}', file=sys.stderr)
        print(f'Web log (if created): {LOG}', file=sys.stderr)
        sys.exit(1)
