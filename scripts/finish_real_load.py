"""Finish the current local audited load; do not print any source record content."""
import json,os,time
from pathlib import Path
from importer import cli,real
ROOT=Path(__file__).resolve().parents[1]
if os.environ.get('DATA_MODE')!='live':raise SystemExit('DATA_MODE=live required')
log=ROOT/'data/reports/real-stage-batch.log'
deadline=time.monotonic()+1800
while time.monotonic()<deadline:
 lines=log.read_text().splitlines() if log.exists() else []
 try:last=json.loads(lines[-1]) if lines else {}
 except ValueError:last={}
 if last.get('sources')==15:break
 time.sleep(3)
else:raise SystemExit('Batch not complete; no activation attempted')
main=ROOT/'mappings/real/053cea08-09bc-40ec-8f7a-156f0677aff3.json'
config=real.mapping_file(main)
r=real.stage(ROOT/'data/raw'/config['source_file'],main)
print(json.dumps({'phase':'primary_stage','status':r['status'],'run_id':r.get('run_id'),'read':r.get('records_read'),'staged':r.get('records_staged'),'rejected':r.get('records_rejected'),'quality':r.get('quality_passed')},ensure_ascii=False),flush=True)
audits={p.stem.replace('.audit',''):json.loads(p.read_text()) for p in (ROOT/'data/reports/audit-mot-v2-bytes-20261030').glob('*.audit.json')}
with cli.connect() as db:
 runs=db.execute("SELECT DISTINCT ON (r.source_id) r.id,r.source_id,r.state,r.report,s.kind FROM import_runs r JOIN sources s ON s.id=r.source_id ORDER BY r.source_id,r.id DESC").fetchall()
priority={'vehicles':0,'specs':1,'recall_catalog':2,'model_counts':3,'statuses':4,'recalls':5,'mileage':6,'ownership':7}
runs.sort(key=lambda v:(priority[v[4]],0 if v[1]==config['id'] else 1,v[1]))
results=[]
for run,source,state,report,kind in runs:
 mapping=report.get('mapping_snapshot',{})
 name=mapping.get('source_file','');audit=audits.get(Path(name).stem)
 okay=(audit and audit.get('scan_complete') and report.get('scan_complete') and audit['sha256']==report.get('sha256') and audit['records_read']==report.get('records_read') and report.get('source_identity_before')==report.get('source_identity_after'))
 if state=='published':result={'status':'unchanged','run_id':run}
 elif not okay:result={'status':'blocked','run_id':run,'reason':'full_audit_mismatch_or_incomplete'}
 elif mapping.get('publication_hold'):result={'status':'blocked','run_id':run,'reason':mapping['publication_hold']}
 else:result=real.promote(run)
 result={'source':source,'kind':kind,**{k:result.get(k) for k in ('status','run_id','records_published','records_rejected','publication_blockers','reason','cross_source_key_conflicts','quarantine_policy_passed')}}
 results.append(result);print(json.dumps(result,ensure_ascii=False),flush=True)
 if result['status']=='blocked':
  with cli.connect() as db:
   db.execute("UPDATE sources SET availability='blocked',coverage=coverage||%s::jsonb WHERE id=%s AND active_run_id IS NULL",(json.dumps({'import_note':'המקור נטען לבדיקות אך נחסם לפרסום; ראו דוח איכות.'}),source))
 target=ROOT/'data/reports/real-publication-summary.json'
 target.write_text(json.dumps(results,ensure_ascii=False,indent=2))
print(json.dumps({'phase':'complete','active':sum(r['status'] in ('complete','unchanged') for r in results),'held':sum(r['status']=='blocked' for r in results),'report':str(target)},ensure_ascii=False),flush=True)
