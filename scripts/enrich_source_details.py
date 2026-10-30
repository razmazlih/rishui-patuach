"""Attach full verified model fields to original lineage. Never print row contents."""
import hashlib,json,os,sys,time
from pathlib import Path
from importer import cli,real
ROOT=Path(__file__).resolve().parents[1]
SOURCE='mot-142afde2-6228-49f9-8a29-9b6c3a0cbe40'
if os.environ.get('DATA_MODE')!='live':raise SystemExit('Explicit live mode required')
config=real.mapping_file(ROOT/'mappings/real/142afde2-6228-49f9-8a29-9b6c3a0cbe40.json')
path=Path(os.environ.get('DATA_DIR',str(ROOT/'data')))/'raw'/config['source_file']
started=time.monotonic();before=real.stat_identity(path);sha=cli.digest(path)
with cli.connect() as db:
 db.execute((ROOT/'db/006_record_details.sql').read_text())
 source=db.execute('SELECT s.active_run_id,f.sha256,r.report FROM sources s JOIN import_runs r ON r.id=s.active_run_id JOIN source_files f ON f.id=r.file_id WHERE s.id=%s',(SOURCE,)).fetchone()
 if not source or source[1]!=sha:raise RuntimeError('Verified active source SHA does not match local file')
 run=source[0];expected=source[2]['records_read']
 db.execute('CREATE TEMP TABLE detail_load(source_record_id text PRIMARY KEY,details jsonb NOT NULL) ON COMMIT DROP')
 count=0;batch=[]
 def flush():
  if batch:
   with db.cursor().copy('COPY detail_load(source_record_id,details) FROM STDIN') as cp:
    for item in batch:cp.write_row(item)
   batch.clear()
 with path.open(encoding=config['encoding'],newline='') as stream:
  for number,row in enumerate(real.records(stream,config),1):
   key,_,_=real.transform(row,config,number)
   batch.append((key,json.dumps(row,ensure_ascii=False)));count+=1
   if len(batch)>=1000:flush()
 flush()
 if count!=expected or before!=real.stat_identity(path):raise RuntimeError('Source count or immutable identity changed')
 unmatched=db.execute('SELECT count(*) FROM detail_load d WHERE NOT EXISTS(SELECT 1 FROM specs n WHERE n.source_id=%s AND n.run_id=%s AND n.source_record_id=d.source_record_id)',(SOURCE,run)).fetchone()[0]
 if unmatched:raise RuntimeError('Full technical details do not match original row identifiers')
 db.execute('INSERT INTO record_details(source_id,run_id,source_record_id,details,source_sha256) SELECT %s,%s,source_record_id,details,%s FROM detail_load ON CONFLICT(source_id,run_id,source_record_id) DO UPDATE SET details=EXCLUDED.details,source_sha256=EXCLUDED.source_sha256',(SOURCE,run,sha))
 if db.execute('SELECT active_run_id FROM sources WHERE id=%s',(SOURCE,)).fetchone()[0]!=run:raise RuntimeError('Active source changed while enriching')
report={'status':'complete','source_id':SOURCE,'run_id':run,'rows':count,'unmatched':unmatched,'source_unchanged':True,'source_sha256':sha,'elapsed_seconds':round(time.monotonic()-started,3)}
folder=Path(os.environ.get('DATA_DIR',str(ROOT/'data')))/'reports';folder.mkdir(parents=True,exist_ok=True)
(folder/'full-spec-details.json').write_text(json.dumps(report,ensure_ascii=False,indent=2));print(json.dumps(report))
