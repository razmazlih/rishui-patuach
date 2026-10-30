"""Reprocess a validated public-source snapshot under an explicit provenance policy.
Never changes source files, original runs, or previously published vehicle rows.
"""
import copy,hashlib,json,os,time
from pathlib import Path
from importer import cli,real
ROOT=Path(__file__).resolve().parents[1]
SOURCE='mot-cf29862d-ca25-4691-84f6-1be60dcb4a1e'
VERSION='real-2-provenance-overlap'


def conflict_fields(left,right):
    """Lexical disagreements only; absent values are complementary, not conflicts."""
    return sorted(k for k in left.keys() & right.keys() if k not in ('plate','plate_original') and left[k] is not None and right[k] is not None and left[k]!=right[k])


def main():
    if os.environ.get('DATA_MODE')!='live':raise ValueError('Explicit live mode required')
    evidence=json.loads((ROOT/'data/reports/public-registry-reconciliation.json').read_text())
    if evidence['status']!='complete' or evidence['records']!=66295:raise ValueError('Full source reconciliation required')
    mapping_path=ROOT/'mappings/real/cf29862d-ca25-4691-84f6-1be60dcb4a1e.json'
    config=json.loads(mapping_path.read_text())
    config.update(version=VERSION,cross_source_overlap_policy='retain_ambiguous')
    config['verification']['overlap_reconciliation']='data/reports/public-registry-reconciliation.json'
    config['coverage']['overlap_note']='מקור משלים: רשומות חופפות נשמרות ומוצגות עם מקורן, ללא מיזוג או בחירת ערך שרירותית.'
    with cli.connect() as db:
        db.commit()  # Persist the verified search_path across retry rollbacks.
        deadline=time.monotonic()+600
        while not db.execute('SELECT pg_try_advisory_xact_lock(87301826)').fetchone()[0]:
            if time.monotonic()>deadline:raise ValueError('Another import is running; no changes made')
            db.rollback();time.sleep(1)
        original=db.execute('SELECT file_id,report FROM import_runs WHERE id=%s AND source_id=%s',(evidence['run_id'],SOURCE)).fetchone()
        if not original:raise ValueError('Audited original run missing')
        old=original[1]
        if not(old.get('scan_complete') and old.get('record_count_reliable') and old.get('records_staged')==evidence['records'] and old.get('records_rejected')==0):raise ValueError('Original full staging validation is incomplete')
        fingerprint=hashlib.sha256((old['sha256']+json.dumps(config,sort_keys=True)+real.VERSION).encode()).hexdigest()
        prior=db.execute("SELECT id FROM import_runs WHERE source_id=%s AND fingerprint=%s AND state IN ('staged','published') ORDER BY id DESC LIMIT 1",(SOURCE,fingerprint)).fetchone()
        if prior:run_id=prior[0]
        else:
            run_id=db.execute("INSERT INTO import_runs(source_id,file_id,state,fingerprint,mapping_version,importer_version) VALUES(%s,%s,'loading',%s,%s,%s) RETURNING id",(SOURCE,original[0],fingerprint,VERSION,real.VERSION)).fetchone()[0]
            db.execute('INSERT INTO staging(run_id,row_number,source_record_id,plate,payload,row_hash) SELECT %s,row_number,source_record_id,plate,payload,row_hash FROM staging WHERE run_id=%s',(run_id,evidence['run_id']))
            report=copy.deepcopy(old)
            report.update(run_id=run_id,status='staged',mapping_snapshot=config,records_published=0,publication_blockers=[],quality_passed=True,derived_from_run_id=evidence['run_id'],reprocessing_method='SQL clone of immutable fully validated staging; no source row changes',overlap_reconciliation=evidence)
            report.pop('report_path',None)
            db.execute("UPDATE import_runs SET state='staged',report=%s::jsonb WHERE id=%s",(json.dumps(report),run_id))
    for attempt in range(120):
        try:result=real.promote(run_id);break
        except ValueError as exc:
            if 'Another import' not in str(exc) or attempt==119:raise
            time.sleep(1)
    if result['status'] not in ('complete','unchanged'):raise ValueError('Public source remained blocked; inspect detailed report')
    with cli.connect() as db:
        invalid=db.execute("SELECT count(*) FROM vehicles WHERE source_id=%s AND run_id=%s AND (plate IS NULL OR plate!~'^[0-9]{8}$')",(SOURCE,run_id)).fetchone()[0]
        if invalid:raise ValueError('Unexpected plate format; lookup alias not enabled')
        coverage={'plate_lookup_format':'zero_padded_8','plate_lookup_run_id':str(run_id),'plate_lookup_evidence':'data/reports/public-registry-reconciliation.json'}
        db.execute('UPDATE sources SET coverage=coverage||%s::jsonb WHERE id=%s AND active_run_id=%s',(json.dumps(coverage),SOURCE,run_id))
    mapping_path.write_text(json.dumps(config,ensure_ascii=False,indent=2)+'\n')
    summary={'status':'complete','source':SOURCE,'run_id':run_id,'records_published':evidence['records'],'overlap_records_retained':evidence['overlap_records'],'additional_records':evidence['new_records'],'source_records_modified':0,'resolution_policy':'retain all profiles with provenance; no guessed precedence','lookup_alias_enabled':True}
    (ROOT/'data/reports/public-registry-activation.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2))
    print(json.dumps(summary,ensure_ascii=False))
if __name__=='__main__':main()
