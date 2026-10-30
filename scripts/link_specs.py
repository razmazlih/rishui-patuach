"""Build only unique, run-bound numeric-code composite links. No row values printed.
This is a derived projection: plate, original source codes and payloads stay intact.
"""
import argparse,json,os,resource,sys,time
from pathlib import Path
import psycopg

ROOT=Path(__file__).resolve().parents[1]
METHOD='numeric_code_v1'
KEY_FIELDS=('sug_degem','tozeret_cd','degem_cd','shnat_yitzur')
VERIFIED_VEHICLE_RESOURCES={'053cea08-09bc-40ec-8f7a-156f0677aff3','f6efe89a-fb3d-43a4-bb61-9bf12a9b9099'}
SPEC_RESOURCE='142afde2-6228-49f9-8a29-9b6c3a0cbe40'
COUNT_RESOURCE='5e87a7a1-2f6f-41c1-8aec-7216d52a6cf6'


def evidence(path):
    records=json.loads(Path(path).read_text())['sources']
    approved={}
    for item in records:
        fields={f['id']:f['type'] for f in item.get('fields',[])}
        if all(k in fields for k in KEY_FIELDS) and fields['sug_degem']=='text' and all(fields[k]=='numeric' for k in KEY_FIELDS[1:]):
            approved['mot-'+item['resource_id']]=item['resource_id']
    required=VERIFIED_VEHICLE_RESOURCES|{SPEC_RESOURCE,COUNT_RESOURCE}
    if not all('mot-'+rid in approved for rid in required):
        raise ValueError('Official numeric composite field evidence absent')
    return approved


def build(database_url,mode='live',report_path=None,metadata=None):
    if mode not in ('live','demo'):raise ValueError('Invalid mode')
    started=time.monotonic()
    approved=evidence(metadata or ROOT/'data/reports/official-metadata.json') if mode=='live' else {}
    report={'status':'not_run','method':METHOD,'mode':mode,'source_rows_modified':0,'scope':'complete database scan of active runs; no source content printed','evidence':{'official_dictionary':'data/reports/official-metadata.json','source_codes_preserved':True,'normalization':'derived numeric-code identity only; model_type/year exact; no model name join'}}
    with psycopg.connect(database_url) as db:
        db.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
        db.execute(f'SET search_path TO {mode},public')
        if not db.execute('SELECT pg_try_advisory_xact_lock(87301826)').fetchone()[0]:raise RuntimeError('Another data operation is running')
        db.execute((ROOT/'db/003_spec_links.sql').read_text())
        db.execute("SET LOCAL work_mem='32MB'")
        # Whitelist identities verified against official numeric field definitions.
        vehicle_ids=['mot-'+v for v in sorted(VERIFIED_VEHICLE_RESOURCES)] if mode=='live' else None
        spec_ids=['mot-'+SPEC_RESOURCE] if mode=='live' else None
        count_ids=['mot-'+COUNT_RESOURCE] if mode=='live' else None
        def active(table,ids):
            clause=' AND n.source_id=ANY(%s)' if ids is not None else ''
            params=(ids,) if ids is not None else ()
            db.execute(f'CREATE TEMP TABLE active_{table} ON COMMIT DROP AS SELECT n.id,n.run_id,n.source_id,spec_join_key(n.payload) key FROM {table} n JOIN sources s ON s.id=n.source_id AND s.active_run_id=n.run_id WHERE true'+clause,params)
            db.execute(f'CREATE INDEX ON active_{table}(key)')
            db.execute(f'ANALYZE active_{table}')
        active('vehicles',vehicle_ids)
        vehicles=db.execute('SELECT count(*),count(key) FROM active_vehicles').fetchone()
        all_vehicles=db.execute('SELECT count(*) FROM vehicles v JOIN sources s ON s.id=v.source_id AND s.active_run_id=v.run_id').fetchone()[0]
        report['vehicles']={'active_total':all_vehicles,'eligible_verified_source_rows':vehicles[0],'valid_composite':vehicles[1],'missing_or_invalid_composite':vehicles[0]-vehicles[1],'outside_verified_key_sources':all_vehicles-vehicles[0]}
        report['active_run_ids']={r[0]:r[1] for r in db.execute('SELECT id,active_run_id FROM sources WHERE active_run_id IS NOT NULL')}
        for table,ids,link,entity,entity_run in [('specs',spec_ids,'spec_links','spec_id','spec_run_id'),('model_counts',count_ids,'model_count_links','model_count_id','model_count_run_id')]:
            active(table,ids)
            total,valid=db.execute(f'SELECT count(*),count(key) FROM active_{table}').fetchone()
            db.execute(f'CREATE TEMP TABLE groups_{table} ON COMMIT DROP AS SELECT key,count(*) n,min(id) id,min(run_id) run_id FROM active_{table} WHERE key IS NOT NULL GROUP BY key')
            db.execute(f'CREATE UNIQUE INDEX ON groups_{table}(key)')
            db.execute(f'ANALYZE groups_{table}')
            ambiguous_groups=db.execute(f'SELECT count(*) FROM groups_{table} WHERE n>1').fetchone()[0]
            matched,ambiguous,unmatched=db.execute(f'SELECT count(*) FILTER(WHERE g.n=1),count(*) FILTER(WHERE g.n>1),count(*) FILTER(WHERE g.key IS NULL) FROM active_vehicles v LEFT JOIN groups_{table} g ON g.key=v.key').fetchone()
            inserted=db.execute(f"INSERT INTO {link}(vehicle_id,vehicle_run_id,{entity},{entity_run},canonical_key,method) SELECT v.id,v.run_id,g.id,g.run_id,v.key,%s FROM active_vehicles v JOIN groups_{table} g ON g.key=v.key AND g.n=1 ON CONFLICT(vehicle_id,{entity_run}) DO NOTHING",(METHOD,)).rowcount
            report[table]={'active_rows':total,'valid_composite':valid,'missing_or_invalid_composite':total-valid,'canonical_ambiguous_groups':ambiguous_groups,'matched_vehicle_rows':matched,'ambiguous_vehicle_rows_withheld':ambiguous,'unmatched_vehicle_rows':unmatched,'match_rate':matched/vehicles[0] if vehicles[0] else None,'new_links':inserted}
            if matched+ambiguous+unmatched!=vehicles[0]:raise RuntimeError('Link accounting mismatch')
            db.execute(f'ANALYZE {link}')
        # API guards both active runs, so older links remain useful for rollback.
        report['status']='complete'
        report['elapsed_seconds']=round(time.monotonic()-started,3)
        report['peak_client_rss_bytes']=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*(1 if sys.platform=='darwin' else 1024)
        target=Path(report_path) if report_path else Path(os.environ.get('DATA_DIR',str(ROOT/'data')))/'reports'/f'spec-links-{time.time_ns()}.json'
        target.parent.mkdir(parents=True,exist_ok=True)
        with target.open('x',encoding='utf-8') as output:json.dump(report,output,ensure_ascii=False,indent=2)
        report['report_path']=str(target)
    return report


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--report');a=p.parse_args()
    if os.environ.get('DATA_MODE')!='live':raise SystemExit('DATA_MODE=live required')
    if not os.environ.get('DATABASE_URL'):raise SystemExit('DATABASE_URL required')
    try:
        result=build(os.environ['DATABASE_URL'],report_path=a.report)
        print(json.dumps(result,ensure_ascii=False))
    except Exception as exc:
        print(json.dumps({'status':'failed','error':type(exc).__name__+':'+str(exc)[:200]},ensure_ascii=False));raise SystemExit(1)
if __name__=='__main__':main()
