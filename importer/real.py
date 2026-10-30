"""Strict local real-source adapter: bounded COPY staging and explicit safe promotion.
Only verified declarative mappings are accepted. No source content is printed.
"""
from __future__ import annotations
import argparse
import csv
from datetime import date, datetime
import hashlib
import json
import os
from pathlib import Path
import re
import resource
import sys
import time
from collections import Counter

from importer import cli

VERSION = 'real-1.0.0'
BATCH_SIZE = 10000
BATCH_BYTES = 8 * 1024 * 1024
MAX_RECORD_CHARS = 2 * 1024 * 1024
LOCK = 87301826
KINDS = cli.KINDS | {'model_counts', 'recall_catalog'}
ALLOWED_FORMATS = {'iso_date', 'iso_datetime', 'iso_month', 'yyyymm', 'year'}


def mapping_file(path):
    config = json.loads(Path(path).read_text(encoding='utf-8'))
    if os.environ.get('DATA_MODE') != 'live':
        raise ValueError('Real source importer requires explicit DATA_MODE=live')
    if config.get('synthetic') is not False or config.get('verified') is not True:
        raise ValueError('Only verified non-synthetic mapping accepted')
    if config.get('kind') not in KINDS or not config.get('id') or not config.get('version'):
        raise ValueError('Unknown source mapping')
    if not config.get('official_url', '').startswith('https://') or not config.get('verification'):
        raise ValueError('Official documentation evidence is required')
    if config.get('encoding') not in ('utf-8', 'utf-8-sig', 'windows-1255', 'cp1255') or config.get('encoding_verified') is not True:
        raise ValueError('Explicit verified encoding required')
    if config.get('delimiter') not in (',', '|', '\t'):
        raise ValueError('Explicit supported delimiter required')
    if config.get('dialect', 'csv') not in ('csv', 'mot_envelope', 'mot_envelope_bytesbridge'):
        raise ValueError('Unknown source dialect')
    if config.get('dialect') in ('mot_envelope','mot_envelope_bytesbridge') and config.get('dialect_verified') is not True:
        raise ValueError('MOT envelope dialect requires per-source verification')
    if config.get('dialect') == 'mot_envelope_bytesbridge':
        policy=config.get('quarantine_policy', {})
        if not (policy.get('allowed_reasons') == ['decode_error'] and isinstance(policy.get('max_records'),int) and 0 < policy['max_records'] <= 3 and 0 < policy.get('max_fraction',0) <= 0.000001 and config.get('full_audit_report')):
            raise ValueError('Bytes bridge requires narrow explicit audited decode quarantine policy')
    elif config.get('quarantine_policy'):
        raise ValueError('Quarantine policy is only supported by audited bytes bridge')
    fields = config.get('fields')
    if not isinstance(fields, dict) or not fields:
        raise ValueError('Expected exact ordered source fields')
    targets = []
    for field in fields.values():
        if field.get('ignore'):
            if field.get('target'):
                raise ValueError('Ignored field cannot have a target')
            continue
        if not field.get('target') or field.get('type', 'text') not in ('text','integer','date'):
            raise ValueError('Unknown mapped field type')
        if field.get('normalize') not in (None, 'plate', 'strip'):
            raise ValueError('Unknown normalization rule')
        if field.get('type') == 'date' and (not field.get('formats') or not set(field['formats']) <= ALLOWED_FORMATS):
            raise ValueError('Date formats must be explicit')
        targets.append(field['target'])
    if len(set(targets)) != len(targets):
        raise ValueError('Target fields are ambiguous')
    for target, rule in config.get('derived_fields', {}).items():
        if config['kind'] != 'ownership' or rule.get('transform') != 'ownership_quarter' or rule.get('source') not in targets or target in targets or not rule.get('evidence_url','').startswith('https://www.gov.il/'):
            raise ValueError('Unknown or unverified derived ownership period')
    if config.get('key_mode', 'fields') not in ('row_number', 'fields'):
        raise ValueError('Unknown source record key mode')
    if config.get('key_mode', 'fields') == 'fields' and (not config.get('keys') or not set(config['keys']) <= set(targets)):
        raise ValueError('Explicit source record keys required')
    if config['kind'] not in ('specs','model_counts','recall_catalog') and 'plate' not in targets:
        raise ValueError('Vehicle-linked source requires verified plate mapping')
    if config['kind'] == 'specs' and (not config.get('verified_composite_key') or not config.get('composite_key_fields')):
        raise ValueError('Specs need a verified composite key')
    if config['kind'] == 'recalls' and config.get('verified_plate_link') is not True:
        raise ValueError('Recall plate semantics not verified')
    if config.get('plate_pattern', '[0-9]{7,8}') not in ('[0-9]{7,8}', '[0-9]{1,8}'):
        raise ValueError('Unsupported explicit plate pattern')
    if config.get('cross_source_overlap_policy', 'block') not in ('block', 'retain_ambiguous'):
        raise ValueError('Unsupported overlap policy')
    threshold = config.get('max_unmatched_rate', 0)
    if not isinstance(threshold, (int, float)) or not 0 <= threshold <= 1:
        raise ValueError('Invalid unmatched threshold')
    return config


def date_value(value, formats):
    for kind in formats:
        if kind == 'iso_date' and re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}', value):
            return date.fromisoformat(value).isoformat(), 'day'
        if kind == 'iso_datetime' and re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}[ T][0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]+)?(?:Z|[+-][0-9]{2}:[0-9]{2})?', value):
            return datetime.fromisoformat(value.replace('Z', '+00:00')).date().isoformat(), 'day'
        if kind == 'iso_month' and re.fullmatch(r'[0-9]{4}-(0[1-9]|1[0-2])', value):
            return value, 'month'
        if kind == 'yyyymm' and re.fullmatch(r'[0-9]{4}(0[1-9]|1[0-2])', value):
            return value[:4] + '-' + value[4:], 'month'
        if kind == 'year' and re.fullmatch(r'[0-9]{4}', value):
            return value, 'year'
    raise ValueError('date_format_mismatch')


def transform(row, config, number):
    payload, missing = {}, Counter()
    for source, rule in config['fields'].items():
        if rule.get('ignore'):
            continue
        raw = row[source]
        value = raw.strip() if rule.get('normalize') == 'strip' or rule.get('strip') else raw
        target = rule['target']
        if rule.get('normalize') == 'plate':
            value = re.sub(r'[\s-]', '', value)
            payload['plate_original'] = raw
        if value == '' or value in rule.get('null_values', []):
            missing[target] += 1
            if rule.get('required'):
                raise ValueError('required:' + source)
            payload[target] = None
            continue
        datatype = rule.get('type', 'text')
        if datatype == 'integer':
            if not re.fullmatch(r'[0-9]+', value):
                raise ValueError('integer:' + source)
            value = int(value)
        elif datatype == 'date':
            try:
                value, precision = date_value(value, rule['formats'])
            except ValueError:
                raise ValueError('date:' + source) from None
            payload[target + '_precision'] = precision
            payload[target + '_original'] = raw
        if target == 'plate' and not re.fullmatch(config.get('plate_pattern', r'[0-9]{7,8}'), value):
            raise ValueError('plate_format:' + source)
        payload[target] = value
    if config.get('derived_fields'):
        from importer.ownership_period import derive_ownership
        derive_ownership(payload, config)
    composite = config.get('composite_key_fields')
    if composite:
        components = [payload.get(k) for k in composite]
        payload['spec_key'] = json.dumps(components,ensure_ascii=False,separators=(',',':')) if all(x is not None for x in components) else None
        if config['kind'] == 'specs' and payload['spec_key'] is None:
            raise ValueError('required:composite_key')
    if config.get('key_mode', 'fields') == 'row_number':
        key = str(number)
    else:
        components = [payload.get(k) for k in config['keys']]
        if any(v is None for v in components):
            raise ValueError('required:source_record_key')
        key = json.dumps(components,ensure_ascii=False,separators=(',',':'))
    return key, payload, missing


class DecodeRejected:
    def __init__(self, fields):
        self.fields=fields


def records(stream, config):
    if config.get('dialect', 'csv') in ('mot_envelope','mot_envelope_bytesbridge'):
        from importer.motpipe import rows as envelope_rows
        reader = envelope_rows(stream)
        if next(reader) != list(config['fields']):
            raise ValueError('Headers differ from verified mapping')
        for values in reader:
            if config.get('dialect') == 'mot_envelope_bytesbridge':
                decoded=[];bad=[]
                for field,value in zip(config['fields'],values):
                    try:decoded.append(value.encode('latin1').decode(config['encoding'],errors='strict'))
                    except UnicodeDecodeError:
                        decoded.append(None);bad.append(field)
                if bad:
                    yield DecodeRejected(bad)
                    continue
                values=decoded
            yield dict(zip(config['fields'],values))
    else:
        reader = csv.DictReader(stream,delimiter=config['delimiter'],strict=True)
        if reader.fieldnames != list(config['fields']):
            raise ValueError('Headers differ from verified mapping')
        yield from reader


def structural_audit(config, sha):
    if config.get('dialect') != 'mot_envelope_bytesbridge':
        return None
    audit_path=Path(config['full_audit_report'])
    if not audit_path.is_absolute():
        if audit_path.parts and audit_path.parts[0]=='data':
            audit_path=Path(os.environ.get('DATA_DIR',str(cli.ROOT/'data'))).joinpath(*audit_path.parts[1:])
        else:
            audit_path=cli.ROOT/audit_path
    audit=json.loads(audit_path.read_text(encoding='utf-8'))
    if not (audit.get('status')=='complete' and audit.get('scan_complete') is True and audit.get('source_unchanged') is True and audit.get('sha256')==sha and audit.get('duplicates',{}).get('status')=='complete' and audit['duplicates'].get('extra_rows')==0 and audit.get('records_read',0)>0 and audit.get('headers')==list(config['fields'])):
        raise ValueError('Complete unchanged matching-SHA structural audit with zero full-source duplicates required')
    return {'status':'complete','sha256':sha,'records_read':audit['records_read'],'duplicates':audit['duplicates'],'scope':'byte-preserving structure and duplicates; not semantic decoding','report_path':str(audit_path)}


def quarantine_allowed(config, report):
    policy=config.get('quarantine_policy')
    if not policy:return False
    audit=report.get('full_source_audit') or {}
    rejected=report.get('records_rejected',0)
    return (report.get('scan_complete') is True and audit.get('status')=='complete'
            and audit.get('sha256')==report.get('sha256')
            and audit.get('records_read')==report.get('records_read')
            and rejected==report.get('decode_error_records',0)
            and rejected<=policy['max_records']
            and rejected/max(1,report['records_read'])<=policy['max_fraction']
            and not report.get('structure_errors')
            and all(reason.startswith('decode_error:') for reason in report.get('rejection_reasons',{})))


def stat_identity(path):
    s = path.stat()
    return {'size_bytes':s.st_size,'mtime_ns':s.st_mtime_ns,'inode':s.st_ino}


def _copy_batch(conn, batch):
    if not batch:
        return
    with conn.cursor().copy('COPY staging(run_id,row_number,source_record_id,plate,payload,row_hash) FROM STDIN') as copy:
        for row in batch:
            copy.write_row(row)
    conn.commit()
    batch.clear()


def _metrics(conn, run_id, config, report, check_relations=True):
    report['records_staged'] = conn.execute('SELECT count(*) FROM staging WHERE run_id=%s',(run_id,)).fetchone()[0]
    report['records_accepted'] = report['records_staged']
    report['full_duplicates'] = conn.execute('SELECT coalesce(sum(n-1),0)::bigint FROM (SELECT count(*) n FROM staging WHERE run_id=%s GROUP BY row_hash HAVING count(*)>1) x',(run_id,)).fetchone()[0]
    report['key_conflicts'] = conn.execute('SELECT count(*) FROM (SELECT source_record_id FROM staging WHERE run_id=%s GROUP BY source_record_id HAVING count(*)>1) x',(run_id,)).fetchone()[0]
    kind = config['kind']
    if kind in ('vehicles','specs'):
        key = 'plate' if kind == 'vehicles' else "payload->>'spec_key'"
        report['entity_key_conflicts'] = conn.execute(f'SELECT count(*) FROM (SELECT {key} FROM staging WHERE run_id=%s GROUP BY {key} HAVING count(*)>1) x',(run_id,)).fetchone()[0]
    else:
        report['entity_key_conflicts'] = 0
    report['matching'] = {'status':'not_run'}
    if check_relations and kind in ('ownership','mileage','statuses','recalls'):
        unmatched = conn.execute('SELECT count(*) FROM staging n WHERE n.run_id=%s AND NOT EXISTS(SELECT 1 FROM vehicles v JOIN sources s ON s.id=v.source_id AND s.active_run_id=v.run_id WHERE v.plate=n.plate)',(run_id,)).fetchone()[0]
        total = report['records_staged']
        report['matching'] = {'status':'complete','eligible':total,'unmatched':unmatched,'matched':total-unmatched,'rate':(total-unmatched)/total if total else None}
    if check_relations and kind == 'vehicles' and config.get('composite_key_fields'):
        eligible, unmatched = conn.execute("SELECT count(*),count(*) FILTER (WHERE NOT EXISTS(SELECT 1 FROM specs v JOIN sources s ON s.id=v.source_id AND s.active_run_id=v.run_id WHERE v.payload->>'spec_key'=n.payload->>'spec_key')) FROM staging n WHERE n.run_id=%s AND n.payload->>'spec_key' IS NOT NULL",(run_id,)).fetchone()
        report['matching'] = {'status':'complete','eligible':eligible,'unmatched':unmatched,'matched':eligible-unmatched,'rate':(eligible-unmatched)/eligible if eligible else None}
    allowed_quarantine=quarantine_allowed(config,report)
    report['quarantine_policy_passed']=allowed_quarantine if config.get('quarantine_policy') else None
    blockers = list(config.get('publication_hold', []))
    encoding_complete=report.get('encoding_full_validation')=='complete' or (allowed_quarantine and report.get('encoding_full_validation')=='complete_with_quarantine')
    if config.get('verification',{}).get('full_validation_required') and (not encoding_complete or report.get('framing_full_validation') != 'complete'):
        blockers.append('full_encoding_or_framing_validation_incomplete')
    if not report.get('scan_complete') or not report.get('record_count_reliable'):
        blockers.append('incomplete_scan')
    if not report['records_staged'] or ((report.get('records_rejected') or report.get('decode_errors')) and not allowed_quarantine) or report.get('structure_errors'):
        blockers.append('empty_or_invalid_records')
    if report['key_conflicts'] or report['entity_key_conflicts']:
        blockers.append('ambiguous_keys')
    if report['full_duplicates'] and not (kind == 'ownership' and config.get('preserve_exact_events') is True):
        blockers.append('full_duplicates')
    matching = report['matching']
    if matching['status'] == 'complete' and matching['unmatched'] / max(1,matching['eligible']) > config.get('max_unmatched_rate', 0):
        blockers.append('unmatched_threshold')
    for source in config.get('required_sources', []):
        row = conn.execute('SELECT active_run_id FROM sources WHERE id=%s',(source,)).fetchone()
        if not row or not row[0]:
            blockers.append('required_source_not_loaded:' + source)
    report['publication_blockers'] = blockers
    return not blockers


def _summary(report):
    hidden = {'mapping_snapshot','missing_by_field','rejection_reasons'}
    return {k:v for k,v in report.items() if k not in hidden}


def stage(path, mapping_path):
    path = Path(path)
    config = mapping_file(mapping_path)
    before = stat_identity(path)
    sha = cli.digest(path)
    full_audit = structural_audit(config,sha)
    fingerprint = hashlib.sha256((sha + json.dumps(config,sort_keys=True) + VERSION).encode()).hexdigest()
    started = time.monotonic()
    report = {'status':'not_run','records_read':0,'records_parsed_valid':0,'records_staged':0,'records_accepted':0,'records_rejected':0,'records_published':0,'scan_complete':False,'record_count_reliable':False,'encoding_full_validation':'not_run','framing_full_validation':'not_run','decode_errors':0,'structure_errors':0,'sha256':sha,'mapping_snapshot':config,'source_identity_before':before,'missing_by_field':{},'rejection_reasons':{},'decode_error_records':0,'full_source_audit':full_audit,'source_date':config['coverage'].get('as_of'),'source_date_precision':config['coverage'].get('date_precision')}
    with cli.connect() as conn:
        if not conn.execute('SELECT pg_try_advisory_lock(%s)',(LOCK,)).fetchone()[0]:
            raise ValueError('Another import is running')
        run_id = None
        try:
            prior = conn.execute("SELECT id,state,report FROM import_runs WHERE source_id=%s AND fingerprint=%s AND state IN ('staged','published') ORDER BY id DESC LIMIT 1",(config['id'],fingerprint)).fetchone()
            if prior:
                return {'status':'unchanged','run_id':prior[0],'run_state':prior[1],'records_staged':prior[2].get('records_staged')}
            conn.execute('INSERT INTO sources(id,kind,name,coverage,synthetic,official_url) VALUES(%s,%s,%s,%s::jsonb,false,%s) ON CONFLICT(id) DO NOTHING',(config['id'],config['kind'],config['name'],json.dumps(config['coverage']),config['official_url']))
            identity = conn.execute('SELECT kind,synthetic FROM sources WHERE id=%s',(config['id'],)).fetchone()
            if identity != (config['kind'],False):
                raise ValueError('Existing source identity differs')
            file_id = conn.execute('INSERT INTO source_files(source_id,name,sha256,size_bytes) VALUES(%s,%s,%s,%s) RETURNING id',(config['id'],path.name,sha,before['size_bytes'])).fetchone()[0]
            run_id = conn.execute("INSERT INTO import_runs(source_id,file_id,state,fingerprint,mapping_version,importer_version) VALUES(%s,%s,'loading',%s,%s,%s) RETURNING id",(config['id'],file_id,fingerprint,config['version'],VERSION)).fetchone()[0]
            report['run_id'] = run_id
            conn.commit()
            missing, reasons = Counter(), Counter()
            batch = []
            batch_bytes = 0
            rejected = []
            try:
                source_encoding='latin1' if config.get('dialect')=='mot_envelope_bytesbridge' else config['encoding']
                with path.open(encoding=source_encoding,newline='') as stream:
                    rows = records(stream,config)
                    for number,row in enumerate(rows,1):
                        report['records_read'] += 1
                        if isinstance(row,DecodeRejected):
                            reason='decode_error:'+','.join(row.fields)
                            reasons[reason]+=1
                            report['decode_error_records']+=1
                            report['decode_errors']+=len(row.fields)
                            report['records_rejected']+=1
                            rejected.append((run_id,number,reason))
                            if len(rejected)>=BATCH_SIZE:
                                with conn.cursor().copy('COPY rejected_rows(run_id,row_number,reason) FROM STDIN') as copy:
                                    for item in rejected:copy.write_row(item)
                                conn.commit();rejected.clear()
                            continue
                        try:
                            if None in row or None in row.values():
                                report['structure_errors'] += 1
                                raise ValueError('wrong_column_count')
                            if sum(len(value) for value in row.values()) > MAX_RECORD_CHARS:
                                raise ValueError('record_size_limit')
                            key,payload,empty = transform(row,config,number)
                            missing.update(empty)
                            row_hash = hashlib.sha256(json.dumps(list(row.values()),ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
                            encoded = json.dumps(payload,ensure_ascii=False,separators=(',',':'))
                            batch.append((run_id,number,key,payload.get('plate'),encoded,row_hash))
                            batch_bytes += len(encoded.encode()) + len(key.encode()) + 128
                            report['records_parsed_valid'] += 1
                            if len(batch) >= BATCH_SIZE or batch_bytes >= BATCH_BYTES:
                                _copy_batch(conn,batch)
                                batch_bytes = 0
                        except ValueError as exc:
                            reason = str(exc)[:160]
                            reasons[reason] += 1
                            report['records_rejected'] += 1
                            rejected.append((run_id,number,reason))
                            if len(rejected) >= BATCH_SIZE:
                                with conn.cursor().copy('COPY rejected_rows(run_id,row_number,reason) FROM STDIN') as copy:
                                    for item in rejected: copy.write_row(item)
                                conn.commit();rejected.clear()
                    _copy_batch(conn,batch)
                    report['scan_complete'] = report['record_count_reliable'] = True
                    report['encoding_full_validation'] = 'complete_with_quarantine' if report['decode_error_records'] else 'complete'
                    report['framing_full_validation'] = 'complete'
            except (UnicodeError,csv.Error,ValueError) as exc:
                report['error'] = type(exc).__name__ + ':' + str(exc)[:180]
                if isinstance(exc,UnicodeError):
                    report['decode_errors'] += 1
                    report['encoding_full_validation'] = 'failed'
                    report['framing_full_validation'] = 'partial'
                else:
                    report['structure_errors'] += 1
                    report['encoding_full_validation'] = 'partial'
                    report['framing_full_validation'] = 'failed'
            if rejected:
                with conn.cursor().copy('COPY rejected_rows(run_id,row_number,reason) FROM STDIN') as copy:
                    for item in rejected:copy.write_row(item)
            conn.commit()
            report['missing_by_field'] = dict(missing)
            report['missing_values'] = sum(missing.values())
            report['rejection_reasons'] = dict(reasons)
            report['source_identity_after'] = stat_identity(path)
            if before != report['source_identity_after']:
                report['scan_complete'] = report['record_count_reliable'] = False
                report['error'] = 'Source changed during import'
            good = _metrics(conn,run_id,config,report,check_relations=False)
            # Missing dependencies do not invalidate staging; they are checked again on promote.
            permitted_quarantine=quarantine_allowed(config,report)
            report['status'] = 'staged' if report['scan_complete'] and (permitted_quarantine or not report['records_rejected'] and not report['decode_errors']) and not report['structure_errors'] else 'failed'
            report['quality_passed'] = good
            report['elapsed_seconds'] = round(time.monotonic()-started,3)
            report['max_rss_bytes'] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * (1 if sys.platform=='darwin' else 1024)
            report['report_path'] = str(cli.write_report(report))
            conn.execute('UPDATE import_runs SET state=%s,report=%s::jsonb WHERE id=%s',(report['status'],json.dumps(report),run_id))
            conn.commit()
            return _summary(report)
        except Exception as exc:
            conn.rollback()
            if run_id:
                report.update(status='failed',error=type(exc).__name__ + ':' + str(exc)[:180],records_published=0)
                conn.execute("UPDATE import_runs SET state='failed',report=%s::jsonb WHERE id=%s",(json.dumps(report),run_id));conn.commit()
                cli.write_report(report)
            raise
        finally:
            conn.execute('SELECT pg_advisory_unlock(%s)',(LOCK,))


def promote(run_id):
    if os.environ.get('DATA_MODE') != 'live':
        raise ValueError('Promotion requires DATA_MODE=live')
    with cli.connect() as conn:
        if not conn.execute('SELECT pg_try_advisory_xact_lock(%s)',(LOCK,)).fetchone()[0]:
            raise ValueError('Another import is running')
        found = conn.execute('SELECT source_id,state,report FROM import_runs WHERE id=%s FOR UPDATE',(run_id,)).fetchone()
        if not found or found[1] not in ('staged','published'):
            raise ValueError('Only completed staged or already published run accepted')
        source_id,state,report = found
        if state == 'published':
            return {'status':'unchanged','run_id':run_id}
        config = report['mapping_snapshot']
        if not _metrics(conn,run_id,config,report):
            report['status']='blocked'
            conn.execute('UPDATE import_runs SET report=%s::jsonb WHERE id=%s',(json.dumps(report),run_id))
            report['report_path']=str(cli.write_report(report));conn.commit()
            return _summary(report)
        if config['kind'] in ('vehicles','specs'):
            kind=config['kind']
            predicate = "v.plate=n.plate" if kind=='vehicles' else "v.payload->>'spec_key'=n.payload->>'spec_key'"
            overlaps=conn.execute(f'SELECT count(*) FROM staging n WHERE n.run_id=%s AND EXISTS(SELECT 1 FROM {kind} v JOIN sources s ON s.id=v.source_id AND s.active_run_id=v.run_id WHERE v.source_id<>%s AND {predicate})',(run_id,source_id)).fetchone()[0]
            report['cross_source_key_conflicts'] = overlaps
            if overlaps and not (kind == 'vehicles' and config.get('cross_source_overlap_policy') == 'retain_ambiguous'):
                report.update(status='blocked',cross_source_key_conflicts=overlaps)
                report['publication_blockers'].append('cross_source_key_conflicts')
                report['report_path']=str(cli.write_report(report));conn.execute('UPDATE import_runs SET report=%s::jsonb WHERE id=%s',(json.dumps(report),run_id));conn.commit()
                return _summary(report)
        kind=config['kind']
        conn.execute(f'INSERT INTO {kind}(plate,source_id,run_id,source_record_id,payload) SELECT plate,%s,run_id,source_record_id,payload FROM staging WHERE run_id=%s',(source_id,run_id))
        report.update(status='complete',records_published=report['records_staged'],quality_passed=True)
        coverage=dict(config['coverage'])
        if config.get('quarantine_policy'):
            coverage.update(quarantined_records=report['records_rejected'],source_records_total=report['records_read'],published_records=report['records_staged'],partial=bool(report['records_rejected']))
            if report['records_rejected']:
                coverage['quarantine_note']=f"מקור חלקי: {report['records_rejected']} רשומות בודדו בשל שגיאת פענוח. לא בוצע תיקון או ניחוש תווים."
                report['warnings']=['whole_record_decode_quarantine']
            else:
                coverage.pop('quarantine_note',None)
        report['published_coverage']=coverage
        report['report_path']=str(cli.write_report(report))
        conn.execute("UPDATE import_runs SET state='published',published_at=now(),report=%s::jsonb WHERE id=%s",(json.dumps(report),run_id))
        conn.execute("UPDATE sources SET active_run_id=%s,availability='available',updated_at=now(),coverage=%s::jsonb,name=%s,official_url=%s WHERE id=%s",(run_id,json.dumps(coverage),config['name'],config['official_url'],source_id))
        return _summary(report)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    sub=p.add_subparsers(dest='command',required=True)
    s=sub.add_parser('stage');s.add_argument('path');s.add_argument('--mapping',required=True)
    v=sub.add_parser('promote');v.add_argument('run_id',type=int)
    args=p.parse_args()
    try:
        result=stage(args.path,args.mapping) if args.command=='stage' else promote(args.run_id)
        print(json.dumps(result,ensure_ascii=False))
        return 1 if result['status'] in ('failed','blocked') else 0
    except Exception as exc:
        print(json.dumps({'status':'failed','error':type(exc).__name__ + ':' + str(exc)[:200]},ensure_ascii=False),file=sys.stderr)
        return 1

if __name__=='__main__':sys.exit(main())
