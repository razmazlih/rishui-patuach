"""Production no-fallback checks. Explicit RUN_MODE_TESTS=1 and built .next required.
Uses local disposable demo/live PostgreSQL schemas; starts temporary local servers.
"""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import signal
import subprocess
import time
import unittest
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]


def request(url):
    try:
        with urlopen(url, timeout=8) as response:
            return response.status, response.read().decode('utf-8')
    except HTTPError as error:
        with error:
            return error.code, error.read().decode('utf-8')


@contextmanager
def server(port, mode, database_url):
    reports = Path(os.environ.get('DATA_DIR', str(ROOT / 'data'))) / 'reports'
    reports.mkdir(parents=True, exist_ok=True)
    with (reports / f'mode-server-{port}.log').open('w', encoding='utf-8') as log:
        process = subprocess.Popen(
            ['npm', 'run', 'start'],
            cwd=ROOT, env={**os.environ, 'DATA_MODE': mode, 'DATABASE_URL': database_url, 'PORT': str(port), 'HOSTNAME': '127.0.0.1'},
            stdout=log, stderr=subprocess.STDOUT, start_new_session=True,
        )
        try:
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    raise RuntimeError(f'Production server exited; see {reports / f"mode-server-{port}.log"}')
                try:
                    if request(f'http://127.0.0.1:{port}/')[0] == 200:
                        break
                except (URLError, OSError):
                    pass
                time.sleep(0.2)
            else:
                raise RuntimeError('Production server did not become ready in 30 seconds')
            yield f'http://127.0.0.1:{port}'
        finally:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=3)


@unittest.skipUnless(os.environ.get('RUN_MODE_TESTS') == '1', 'set RUN_MODE_TESTS=1 after npm run build')
class ProductionModes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not (ROOT / '.next' / 'BUILD_ID').is_file():
            raise RuntimeError('Run npm run build first')
        if not os.environ.get('DATABASE_URL'):
            raise RuntimeError('DATABASE_URL required: use the disposable local test database')

    def test_live_never_returns_imported_demo_vehicle(self):
        with server(3101, 'live', os.environ['DATABASE_URL']) as base:
            status, html = request(base + '/')
            self.assertEqual(status, 200)
            self.assertNotIn('מצב הדגמה — נתונים סינתטיים', html)
            status, body = request(base + '/api/vehicles/01234567')
            self.assertEqual(status, 200)
            report = json.loads(body)
            self.assertEqual(report['mode'], 'live')
            for group in report['groups'].values():
                self.assertEqual(group['rows'], [])
                self.assertEqual(group['state'], 'not_loaded')

    def test_database_failure_never_falls_back_to_demo(self):
        with server(3102, 'live', 'postgresql://invalid:invalid@127.0.0.1:1/unreachable') as base:
            status, body = request(base + '/api/vehicles/01234567')
            self.assertEqual(status, 503)
            report = json.loads(body)
            self.assertIn('error', report)
            self.assertNotIn('groups', report)
            self.assertNotIn('01234567', body)
            self.assertNotIn('synthetic', body)


if __name__ == '__main__':
    unittest.main()
