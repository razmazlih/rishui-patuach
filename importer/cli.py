"""Local-only, strict, bounded-memory CSV importer. Never modifies source files."""
import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import time
import resource

VERSION = '1.0.0'
ROOT = Path(__file__).resolve().parents[1]
csv.field_size_limit(1024 * 1024)
KINDS = {'vehicles', 'specs', 'ownership', 'mileage', 'statuses', 'recalls'}

def mode():
    value = os.environ.get('DATA_MODE', 'live')
    if value not in ('demo', 'live'):
        raise ValueError('DATA_MODE must be demo or live')
    return value

def connect():
    import psycopg
    conn = psycopg.connect(os.environ.get('DATABASE_URL', 'postgresql://vehicle:vehicle@localhost:5432/vehicle'))
    conn.execute(f'SET search_path TO {mode()}, public')
    return conn

def migrate():
    import psycopg
    with psycopg.connect(os.environ.get('DATABASE_URL', 'postgresql://vehicle:vehicle@localhost:5432/vehicle')) as conn:
        for schema in ('demo', 'live'):
            conn.execute(f'CREATE SCHEMA IF NOT EXISTS {schema}')
            conn.execute(f'SET search_path TO {schema}, public')
            for migration in sorted((ROOT / 'db').glob('[0-9]*.sql')):
                conn.execute(migration.read_text())

def digest(path):
    h = hashlib.sha256()
    with open(path, 'rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()

def reader(path, encoding, delimiter):
    return open(path, encoding=encoding, newline=''), delimiter

def inspect(path, encoding=None, delimiter=None):
    """Sampling only: encoding success is never treated as proof of correctness."""
    report = {'name': Path(path).name, 'size_bytes': Path(path).stat().st_size,
              'status': 'sampled', 'encoding': encoding, 'encoding_selection_explicit': encoding is not None, 'encoding_requires_verification': True, 'requires_content_verification': True,
              'delimiter': delimiter, 'headers': [], 'sample_records': 0}
    selected = encoding or 'utf-8-sig'
    try:
        with open(path, encoding=selected, newline='') as stream:
            sample = stream.read(65536)
            chosen = delimiter or csv.Sniffer().sniff(sample, delimiters=',|\t').delimiter
            stream.seek(0)
            rows = csv.reader(stream, delimiter=chosen, strict=True)
            report.update(encoding=selected, delimiter=chosen, headers=next(rows))
            widths = []
            for _, row in zip(range(3), rows):
                widths.append(len(row))
            report.update(sample_records=len(widths), sample_widths=widths)
    except (UnicodeError, csv.Error, StopIteration) as exc:
        report.update(status='failed', error=str(exc)[:250], encoding_requires_verification=True)
    return report

def load_mapping(path):
    config = json.loads(Path(path).read_text(encoding='utf-8'))
    if config.get('kind') not in KINDS or not config.get('verified') or not config.get('version'):
        raise ValueError('Unknown or unverified source mapping')
    if config.get('encoding') not in ('utf-8', 'utf-8-sig', 'windows-1255', 'cp1255'):
        raise ValueError('Explicit supported encoding required')
    if config.get('delimiter') not in (',', '|', '\t'):
        raise ValueError('Explicit delimiter required')
    if bool(config.get('synthetic')) != (mode() == 'demo'):
        raise ValueError('Synthetic/live separation violation')
    if not config.get('fields') or not config.get('keys'):
        raise ValueError('Explicit fields and keys required')
    for field in config['fields'].values():
        if field.get('type', 'text') not in ('text','integer','date','month') or field.get('normalize') not in (None,'plate'):
            raise ValueError('Unknown type or normalization')
    if not 0 <= config.get('max_unmatched_rate', 0) <= 1:
        raise ValueError('Invalid matching quality threshold')
    if not config.get('encoding_verified'):
        raise ValueError('Encoding must be explicitly verified in source mapping')
    if config['kind'] == 'specs' and config.get('composite_key_fields') != ['manufacturer_code','model_code','variant_code','year']:
        raise ValueError('Specs require verified composite fields')
    return config

def normalize(value, rule):
    if rule.get('normalize') == 'plate':
        return re.sub(r'[\s-]', '', value)
    return value

def convert(row, config):
    payload = {}
    missing = 0
    for source, rule in config['fields'].items():
        raw = row[source]
        value = normalize(raw, rule)
        target = rule['target']
        if value == '':
            missing += 1
            if rule.get('required'):
                raise ValueError(f'missing required {source}')
            payload[target] = None
            continue
        datatype = rule.get('type', 'text')
        if datatype == 'integer':
            value = int(value)
            if value < 0:
                raise ValueError(f'negative {source}')
        elif datatype == 'date':
            import datetime
            if not re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}',value):
                raise ValueError(f'invalid canonical date {source}')
            value=datetime.date.fromisoformat(value).isoformat()
        elif datatype == 'month':
            if not re.fullmatch(r'[0-9]{4}-(0[1-9]|1[0-2])', value):
                raise ValueError(f'invalid month {source}')
        payload[target] = value
        if rule.get('precision'):
            payload[target + '_precision'] = rule['precision']
        if target == 'plate':
            payload['plate_original'] = raw
            if not re.fullmatch(r'[0-9]{7,8}', value):
                raise ValueError('plate must contain 7–8 digits; leading zeroes are preserved')
    if config['kind'] == 'specs':
        components = [payload.get(k) for k in ('manufacturer_code','model_code','variant_code','year')]
        if any(v is None for v in components) or payload.get('spec_key') != json.dumps(components, ensure_ascii=False, separators=(',',':')):
            raise ValueError('spec_key must encode verified composite as compact JSON array')
    key = json.dumps([payload.get(k) for k in config['keys']],ensure_ascii=False,separators=(',',':'))
    if not key or any(payload.get(k) is None for k in config['keys']):
        raise ValueError('missing source key')
    return key, payload, missing

def write_report(report, path=None):
    folder = Path(os.environ.get('DATA_DIR', str(ROOT / 'data'))) / 'reports'
    folder.mkdir(parents=True, exist_ok=True)
    target = Path(path) if path else folder / f"run-{report.get('run_id', 'inspect')}-{time.time_ns()}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation prevents an accidental --report path from overwriting a source.
    with target.open('x', encoding='utf-8') as stream:
        stream.write(json.dumps(report, ensure_ascii=False, indent=2))
    return target

def import_file(path, mapping_path):
    config = load_mapping(mapping_path)
    sha = digest(path)
    fingerprint = hashlib.sha256((sha + json.dumps(config, sort_keys=True) + VERSION).encode()).hexdigest()
    started = time.monotonic()
    report = {'status': 'not_run', 'records_read': 0, 'scan_complete': False, 'record_count_reliable': False, 'records_parsed_valid': 0, 'records_staged': 0, 'records_published': 0, 'records_accepted': 0, 'records_rejected': 0,
              'missing_values': 0, 'decode_errors': 0, 'structure_errors': 0,
              'full_duplicates': 0, 'key_conflicts': 0, 'matching': {'status': 'not_run'}, 'sha256': sha, 'mapping_snapshot': config, 'source_date': config['coverage'].get('as_of'), 'source_date_precision':config['coverage'].get('date_precision')}
    with connect() as conn:
        locked = conn.execute('SELECT pg_try_advisory_lock(87301826)').fetchone()[0]
        if not locked:
            raise ValueError('Another import is running')
        try:
            prior = conn.execute("SELECT id FROM import_runs WHERE fingerprint=%s AND source_id=%s AND state='published'", (fingerprint,config['id'])).fetchone()
            if prior:
                active = conn.execute('SELECT active_run_id FROM sources WHERE id=%s',(config['id'],)).fetchone()
                return {'status': 'unchanged', 'run_id': prior[0], 'active_run_id':active[0] if active else None}
            conn.execute('INSERT INTO sources(id,kind,name,coverage,synthetic,official_url) VALUES(%s,%s,%s,%s::jsonb,%s,%s) ON CONFLICT(id) DO NOTHING',
                         (config['id'], config['kind'], config['name'], json.dumps(config['coverage']), config['synthetic'], config.get('official_url')))
            source = conn.execute('SELECT kind,synthetic FROM sources WHERE id=%s',(config['id'],)).fetchone()
            if source != (config['kind'],config['synthetic']):
                raise ValueError('Source identity cannot change kind or synthetic mode')
            file_id = conn.execute('INSERT INTO source_files(source_id,name,sha256,size_bytes) VALUES(%s,%s,%s,%s) RETURNING id', (config['id'],Path(path).name,sha,Path(path).stat().st_size)).fetchone()[0]
            run_id = conn.execute("INSERT INTO import_runs(source_id,file_id,state,fingerprint,mapping_version,importer_version) VALUES(%s,%s,'loading',%s,%s,%s) RETURNING id", (config['id'],file_id,fingerprint,config['version'],VERSION)).fetchone()[0]
            report['run_id'] = run_id
            conn.commit()
            try:
                with open(path, encoding=config['encoding'], newline='') as stream:
                    rows = csv.DictReader(stream, delimiter=config['delimiter'], strict=True)
                    if rows.fieldnames != list(config['fields']):
                        raise ValueError('Headers differ from verified mapping; source not published')
                    batch = []
                    for number, row in enumerate(rows, 1):
                        report['records_read'] += 1
                        try:
                            if None in row or None in row.values():
                                report['structure_errors'] += 1
                                raise ValueError('wrong column count')
                            key, payload, missing = convert(row, config)
                            report['missing_values'] += missing
                            encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True)
                            batch.append((run_id,number,key,payload.get('plate'),encoded,hashlib.sha256(encoded.encode()).hexdigest()))
                            report['records_parsed_valid'] += 1
                            if len(batch) >= 1000:
                                with conn.cursor() as cur:
                                    cur.executemany('INSERT INTO staging VALUES(%s,%s,%s,%s,%s::jsonb,%s)',batch)
                                conn.commit()
                                batch.clear()
                        except (ValueError, TypeError) as exc:
                            report['records_rejected'] += 1
                            conn.execute('INSERT INTO rejected_rows VALUES(%s,%s,%s)',(run_id,number,str(exc)[:400]))
                    if batch:
                        with conn.cursor() as cur:
                            cur.executemany('INSERT INTO staging VALUES(%s,%s,%s,%s,%s::jsonb,%s)',batch)
                    report['status'] = 'complete'
                    report['scan_complete'] = True
                    report['record_count_reliable'] = True
            except (UnicodeError,csv.Error,ValueError) as exc:
                report['status'] = 'failed'
                report['error'] = str(exc)[:400]
                if isinstance(exc,UnicodeError): report['decode_errors'] += 1
                if isinstance(exc,csv.Error): report['structure_errors'] += 1
            conn.commit()
            report['records_staged'] = conn.execute('SELECT count(*) FROM staging WHERE run_id=%s',(run_id,)).fetchone()[0]
            report['records_accepted'] = report['records_staged']
            report['full_duplicates'] = conn.execute('SELECT coalesce(sum(n-1),0)::bigint FROM (SELECT count(*) n FROM staging WHERE run_id=%s GROUP BY row_hash HAVING count(*)>1) x',(run_id,)).fetchone()[0]
            report['key_conflicts'] = conn.execute('SELECT count(*) FROM (SELECT source_record_id FROM staging WHERE run_id=%s GROUP BY source_record_id HAVING count(*)>1) x',(run_id,)).fetchone()[0]
            if config['kind'] in ('vehicles','specs'):
                kind=config['kind']
                condition = "v.plate=s.plate" if kind=='vehicles' else "v.payload->>'spec_key'=s.payload->>'spec_key'"
                report['key_conflicts'] += conn.execute(f'SELECT count(*) FROM staging s WHERE s.run_id=%s AND EXISTS(SELECT 1 FROM {kind} v JOIN sources src ON src.id=v.source_id AND src.active_run_id=v.run_id WHERE v.source_id<>%s AND {condition})',(run_id,config['id'])).fetchone()[0]
            if config['kind'] == 'vehicles':
                report['key_conflicts'] += conn.execute('SELECT count(*) FROM (SELECT plate FROM staging WHERE run_id=%s GROUP BY plate HAVING count(*)>1) x',(run_id,)).fetchone()[0]
                unmatched = conn.execute("SELECT count(*) FROM staging s WHERE s.run_id=%s AND s.payload->>'spec_key' IS NOT NULL AND NOT EXISTS(SELECT 1 FROM specs v JOIN sources src ON src.id=v.source_id AND src.active_run_id=v.run_id WHERE v.payload->>'spec_key'=s.payload->>'spec_key')",(run_id,)).fetchone()[0]
                eligible = conn.execute("SELECT count(*) FROM staging WHERE run_id=%s AND payload->>'spec_key' IS NOT NULL",(run_id,)).fetchone()[0]
                report['matching'] = {'status':'complete','unmatched':unmatched,'matched':eligible-unmatched,'eligible':eligible,'rate':(eligible-unmatched)/eligible if eligible else 0}
            if config['kind'] == 'specs':
                report['key_conflicts'] += conn.execute("SELECT count(*) FROM (SELECT payload->>'spec_key' FROM staging WHERE run_id=%s GROUP BY payload->>'spec_key' HAVING count(*)>1) x",(run_id,)).fetchone()[0]
            if config['kind'] not in ('vehicles','specs'):
                unmatched = conn.execute('SELECT count(*) FROM staging s WHERE s.run_id=%s AND NOT EXISTS(SELECT 1 FROM vehicles v JOIN sources src ON src.id=v.source_id AND src.active_run_id=v.run_id WHERE v.plate=s.plate)',(run_id,)).fetchone()[0]
                report['matching'] = {'status':'complete','unmatched':unmatched,'matched':report['records_accepted']-unmatched,'rate': (report['records_accepted']-unmatched)/report['records_accepted'] if report['records_accepted'] else 0}
            matching=report['matching']
            if matching['status']=='complete' and matching['unmatched'] / max(1, matching.get('eligible',report['records_accepted'])) > config.get('max_unmatched_rate',0):
                report.update(status='failed',error='Unmatched rate exceeds configured quality threshold')
            if config['kind'] == 'recalls' and not config.get('verified_plate_link'):
                report.update(status='failed', error='Recall plate identifier semantics not verified')
            if not report['records_accepted'] or report['records_rejected'] or report['key_conflicts'] or report['full_duplicates']:
                report['status'] = 'failed'
            for required in config.get('required_sources', []):
                active = conn.execute('SELECT active_run_id FROM sources WHERE id=%s',(required,)).fetchone()
                if not active or not active[0]:
                    report.update(status='failed',error=f'Required source not loaded: {required}')
            if report['status'] == 'complete':
                kind = config['kind'] # closed enum, never untrusted SQL identifier
                conn.execute(f'INSERT INTO {kind}(plate,source_id,run_id,source_record_id,payload) SELECT plate,%s,run_id,source_record_id,payload FROM staging WHERE run_id=%s',(config['id'],run_id))
                conn.execute("UPDATE sources SET active_run_id=%s,availability='available',updated_at=now(),coverage=%s::jsonb,name=%s,official_url=%s WHERE id=%s",(run_id,json.dumps(config['coverage']),config['name'],config.get('official_url'),config['id']))
                report['records_published'] = report['records_staged']
                state = 'published'
            else:
                state = 'failed'
            report['elapsed_seconds'] = round(time.monotonic()-started,3)
            # macOS ru_maxrss is bytes; Linux is KiB
            report['max_rss_bytes'] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * (1 if sys.platform == 'darwin' else 1024)
            conn.execute('UPDATE import_runs SET state=%s,published_at=CASE WHEN %s=\'published\' THEN now() ELSE NULL END,report=%s::jsonb WHERE id=%s',(state,state,json.dumps(report),run_id))
            # Ensure report storage works before committing the new active snapshot.
            report['report_path'] = str(write_report(report))
            conn.commit()
            return report
        except Exception as exc:
            conn.rollback()
            if 'run_id' in locals():
                report.update(status='failed',records_published=0,error=str(exc)[:400])
                conn.execute("UPDATE import_runs SET state='failed',report=%s::jsonb WHERE id=%s",(json.dumps(report),run_id))
                conn.commit()
                write_report(report)
            raise
        finally:
            conn.execute('SELECT pg_advisory_unlock(87301826)')

def rollback(source, run_id):
    with connect() as conn:
        if not conn.execute('SELECT pg_try_advisory_xact_lock(87301826)').fetchone()[0]:
            raise ValueError('Another import is running')
        row = conn.execute("SELECT id,report FROM import_runs WHERE id=%s AND source_id=%s AND state='published'",(run_id,source)).fetchone()
        if not row: raise ValueError('Only successfully published run can be restored')
        snapshot=row[1]['mapping_snapshot']
        conn.execute("UPDATE sources SET active_run_id=%s,updated_at=now(),coverage=%s::jsonb,name=%s,official_url=%s WHERE id=%s",(run_id,json.dumps(row[1].get('published_coverage',snapshot['coverage'])),snapshot['name'],snapshot.get('official_url'),source))
    return {'status':'rolled_back','run_id':run_id}

def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest='command',required=True)
    sub.add_parser('migrate')
    ins = sub.add_parser('inspect'); ins.add_argument('path'); ins.add_argument('--encoding'); ins.add_argument('--delimiter',choices=[',','|','\t']); ins.add_argument('--report')
    imp = sub.add_parser('import'); imp.add_argument('path'); imp.add_argument('--mapping',required=True)
    sub.add_parser('demo')
    rb = sub.add_parser('rollback'); rb.add_argument('source'); rb.add_argument('run_id',type=int)
    args = parser.parse_args()
    try:
        if args.command == 'migrate': migrate(); result={'status':'migrated'}
        elif args.command == 'inspect':
            report=inspect(args.path,args.encoding,args.delimiter); result={**report,'report_path':str(write_report(report,args.report))}
        elif args.command == 'import': result=import_file(args.path,args.mapping)
        elif args.command == 'rollback': result=rollback(args.source,args.run_id)
        else:
            if mode() != 'demo': raise ValueError('demo requires DATA_MODE=demo')
            result=[]
            for kind in ['specs','vehicles','ownership','mileage','statuses','recalls']:
                item=import_file(ROOT / f'tests/fixtures/{kind}.csv',ROOT / f'mappings/synthetic-{kind}.json'); result.append(item)
                if item['status']=='failed': break
        def compact(item):
            return {k:v for k,v in item.items() if k not in ('mapping_snapshot',)}
        output = [compact(x) for x in result] if isinstance(result,list) else compact(result)
        print(json.dumps(output,ensure_ascii=False,default=int))
        if isinstance(result,dict) and result.get('status')=='failed' or isinstance(result,list) and any(x['status']=='failed' for x in result): return 1
    except Exception as exc:
        print(json.dumps({'status':'failed','error':str(exc)[:400]},ensure_ascii=False),file=sys.stderr)
        return 1
    return 0

if __name__ == '__main__': sys.exit(main())
