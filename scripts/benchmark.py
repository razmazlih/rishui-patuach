#!/usr/bin/env python3
"""Generate a configurable synthetic CSV in DATA_DIR/work, then import normally.
Uses bounded memory. Never reads or modifies real source files. Importing this
benchmark changes a dedicated demo source; use a disposable test database.
"""
import argparse
import csv
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--rows', type=int, default=10000)
    args = parser.parse_args()
    if not 1 <= args.rows <= 90_000_000:
        parser.error('--rows must be between 1 and 90000000')
    if os.environ.get('DATA_MODE', 'demo') != 'demo':
        parser.error('benchmark is synthetic and requires DATA_MODE=demo')
    if not os.environ.get('DATABASE_URL'):
        parser.error('set DATABASE_URL to a disposable local PostgreSQL database')
    data = Path(os.environ.get('DATA_DIR', str(ROOT / 'data')))
    work, reports = data / 'work', data / 'reports'
    work.mkdir(parents=True, exist_ok=True)
    reports.mkdir(parents=True, exist_ok=True)
    tag = time.time_ns()
    csv_path = work / f'benchmark-{tag}.csv'
    mapping_path = work / f'benchmark-{tag}.mapping.json'
    report_path = reports / f'benchmark-{tag}.json'
    log_path = reports / f'benchmark-{tag}.log'
    mapping = {
        'id': 'synthetic-benchmark', 'kind': 'vehicles', 'name': 'מבחן נפח סינתטי',
        'version': f'benchmark-{tag}', 'verified': True, 'synthetic': True,
        'encoding': 'utf-8-sig', 'encoding_verified': True, 'delimiter': '|',
        'coverage': {'description': 'Synthetic benchmark only'}, 'keys': ['record_id'],
        'fields': {
            'id': {'target': 'record_id', 'required': True},
            'plate': {'target': 'plate', 'normalize': 'plate', 'required': True},
            'manufacturer': {'target': 'manufacturer'},
            'model': {'target': 'model'},
        },
    }
    mapping_path.write_text(json.dumps(mapping, ensure_ascii=False), encoding='utf-8')
    start = time.monotonic()
    with csv_path.open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.writer(stream, delimiter='|')
        writer.writerow(mapping['fields'])
        for index in range(args.rows):
            writer.writerow([str(index), str(10000000 + index), 'יצרן סינתטי', 'דגם נפח'])
    generated_seconds = time.monotonic() - start
    start = time.monotonic()
    with log_path.open('w', encoding='utf-8') as log:
        result = subprocess.run([sys.executable, '-m', 'importer.cli', 'import', str(csv_path), '--mapping', str(mapping_path)], cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, env={**os.environ, 'DATA_MODE': 'demo'})
    elapsed = time.monotonic() - start
    # CLI stdout is a compact JSON report, not dataset content.
    raw = log_path.read_text(encoding='utf-8')
    try:
        imported = json.loads(raw)
    except json.JSONDecodeError:
        imported = {'status': 'failed', 'details': str(log_path)}
    summary = {
        'status': 'complete' if result.returncode == 0 and imported.get('status') == 'complete' and imported.get('records_read') == args.rows else 'failed',
        'synthetic': True, 'requested_rows': args.rows,
        'generated_seconds': round(generated_seconds, 3),
        'import_wall_seconds': round(elapsed, 3),
        'peak_importer_rss_bytes': imported.get('max_rss_bytes'),
        'records_read': imported.get('records_read'),
        'records_accepted': imported.get('records_accepted'),
        'run_id': imported.get('run_id'), 'source_bytes': csv_path.stat().st_size,
        'report_path': str(report_path), 'log_path': str(log_path),
        'measurement_scope': 'Importer process peak RSS; excludes PostgreSQL server memory',
    }
    report_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False))
    return 0 if summary['status'] == 'complete' else 1


if __name__ == '__main__':
    sys.exit(main())
