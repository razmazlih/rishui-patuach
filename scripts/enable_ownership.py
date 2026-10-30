"""Create an audited ownership-quarter version from validated staging, then activate.
Preserves all raw records, duplicate events, source keys, original dates and row hashes.
"""
import json,os,sys,time,hashlib
from pathlib import Path
from importer import cli,real
ROOT=Path(__file__).resolve().parents[1]
SOURCE='mot-bb2355dc-9ec7-4f06-9c3f-3344672171da'
LOCK=87301826


def acquire(conn,wait=900):
    end=time.monotonic()+wait
    while not conn.execute('SELECT pg_try_advisory_lock(%s)',(LOCK,)).fetchone()[0]:
        conn.commit()
        if time.monotonic()>end:raise RuntimeError('Import lock remained busy; no ownership activation performed')
        time.sleep(3)


def main():
    if os.environ.get('DATA_MODE')!='live':raise ValueError('Explicit DATA_MODE=live required')
    config=real.mapping_file(ROOT/'mappings/real/bb2355dc-9ec7-4f06-9c3f-3344672171da.json')
    raw=Path(os.environ.get('DATA_DIR',str(ROOT/'data')))/'raw'/config['source_file']
    before=real.stat_identity(raw);sha=cli.digest(raw)
    fingerprint=hashlib.sha256((sha+json.dumps(config,sort_keys=True)+real.VERSION).encode()).hexdigest()
    started=time.monotonic();report=None
    with cli.connect() as conn:
        acquire(conn)
        try:
            existing=conn.execute("SELECT id,state,report FROM import_runs WHERE source_id=%s AND fingerprint=%s AND state IN ('staged','published') ORDER BY id DESC LIMIT 1",(SOURCE,fingerprint)).fetchone()
            if existing:
                run_id,state,report=existing
            else:
                original=conn.execute("SELECT r.id,r.file_id,r.report,f.sha256 FROM import_runs r JOIN source_files f ON f.id=r.file_id WHERE r.source_id=%s AND r.state IN ('staged','published') AND r.report->>'sha256'=%s ORDER BY r.id LIMIT 1",(SOURCE,sha)).fetchone()
                if not original:raise ValueError('No same-SHA fully staged ownership source found')
                old_run,file_id,old_report,file_sha=original
                if not (old_report.get('scan_complete') and old_report.get('record_count_reliable') and old_report.get('records_rejected',0)==0 and old_report.get('decode_errors',0)==0 and old_report.get('structure_errors',0)==0):raise ValueError('Original ownership scan was not complete and valid')
                counts=conn.execute("SELECT count(*),count(*) FILTER (WHERE coalesce(payload->>'ownership_date_raw','') !~ '^[0-9]{4}(0[1-9]|1[0-2])$'),count(*) FILTER (WHERE plate !~ '^[0-9]{8}$') FROM staging WHERE run_id=%s",(old_run,)).fetchone()
                count,bad_dates,bad_plates=counts
                if count!=old_report['records_read'] or bad_dates or bad_plates:raise ValueError('Full ownership record/date/plate validation failed')
                run_id=conn.execute("INSERT INTO import_runs(source_id,file_id,state,fingerprint,mapping_version,importer_version) VALUES(%s,%s,'loading',%s,%s,%s) RETURNING id",(SOURCE,file_id,fingerprint,config['version'],real.VERSION)).fetchone()[0]
                report={**old_report,'status':'loading','run_id':run_id,'mapping_snapshot':config,'derived_from_run_id':old_run,'records_published':0,'source_identity_before':before,'ownership_date_evidence':{'url':'https://www.gov.il/he/Departments/DynamicCollectors/private_vehicle_history_2?skip=0','precision':'quarter','scope':'Reported ownership quarter; no exact transition day/end inferred'},'ownership_full_date_validation':{'status':'complete','records':count,'invalid_yyyymm':bad_dates},'ownership_record_preservation':'Every original source key, row number, raw payload field and full-source row hash preserved; no duplicate removal'}
                conn.execute("""INSERT INTO staging(run_id,row_number,source_record_id,plate,payload,row_hash)
                    SELECT %s,row_number,source_record_id,plate,
                    payload || jsonb_build_object('ownership_period',substring(payload->>'ownership_date_raw',1,4)||'-Q'||(((substring(payload->>'ownership_date_raw',5,2))::int-1)/3+1)::text,'ownership_period_precision','quarter'),row_hash
                    FROM staging WHERE run_id=%s""",(run_id,old_run))
                after=real.stat_identity(raw)
                if before!=after:raise ValueError('Source changed during ownership projection')
                report['source_identity_after']=after
                report['scan_complete']=report['record_count_reliable']=True
                report['records_parsed_valid']=count
                okay=real._metrics(conn,run_id,config,report,check_relations=False)
                if not okay:raise ValueError('Ownership quality gate failed')
                report.update(status='staged',quality_passed=True,elapsed_seconds=round(time.monotonic()-started,3))
                report['report_path']=str(cli.write_report(report))
                conn.execute("UPDATE import_runs SET state='staged',report=%s::jsonb WHERE id=%s",(json.dumps(report),run_id));conn.commit()
        finally:
            conn.execute('SELECT pg_advisory_unlock(%s)',(LOCK,));conn.commit()
    deadline=time.monotonic()+900
    while True:
        try:result=real.promote(run_id);break
        except ValueError as exc:
            if 'Another import' not in str(exc) or time.monotonic()>deadline:raise
            time.sleep(3)
    if result['status'] not in ('complete','unchanged'):raise ValueError('Ownership promotion blocked; active version retained')
    with cli.connect() as conn:
        # The projection copied every source plate unchanged; original full audit verified numeric eight-digit keys.
        row=conn.execute('SELECT active_run_id FROM sources WHERE id=%s FOR UPDATE',(SOURCE,)).fetchone()
        if not row or row[0]!=run_id:raise ValueError('Ownership active run changed before lookup metadata binding')
        lookup={'plate_lookup_format':'zero_padded_8','plate_lookup_run_id':str(run_id),'plate_lookup_evidence':'data/reports/ownership-enable-summary.json'}
        conn.execute('UPDATE sources SET coverage=coverage||%s::jsonb WHERE id=%s',(json.dumps(lookup),SOURCE))
        stored=conn.execute('SELECT report FROM import_runs WHERE id=%s',(run_id,)).fetchone()[0]
    summary={'status':'complete','source':SOURCE,'run_id':run_id,'derived_from_run_id':stored.get('derived_from_run_id'),'records_read':stored['records_read'],'records_published':stored['records_published'],'full_duplicates_preserved':stored['full_duplicates'],'quarter_precision':True,'exact_start_end_inferred':False,'matching':stored.get('matching'),'source_sha256_unchanged':sha==cli.digest(raw),'source_files_modified':False,'elapsed_seconds':round(time.monotonic()-started,3),'evidence_url':'https://www.gov.il/he/Departments/DynamicCollectors/private_vehicle_history_2?skip=0'}
    path=Path(os.environ.get('DATA_DIR',str(ROOT/'data')))/'reports'/'ownership-enable-summary.json';path.write_text(json.dumps(summary,ensure_ascii=False,indent=2))
    print(json.dumps(summary,ensure_ascii=False))

if __name__=='__main__':
    try:main()
    except Exception as exc:
        print(json.dumps({'status':'failed','error_type':type(exc).__name__,'reason':str(exc)[:200]},ensure_ascii=False),file=sys.stderr);sys.exit(1)
