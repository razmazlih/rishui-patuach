#!/usr/bin/env python3
"""Bounded strict-parser audit. Never prints data values or changes source files."""
import argparse,codecs,csv,hashlib,json,os,re,resource,sqlite3,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
csv.field_size_limit(1024*1024)
CP={'053cea08-09bc-40ec-8f7a-156f0677aff3','5e87a7a1-2f6f-41c1-8aec-7216d52a6cf6','bf9df4e2-d90d-4c0a-a400-19e15af8e95f','cd3acc5c-03c3-4c89-9c54-d40f93c0d790'}
def shape(v):
 for name,pattern in [('day_iso',r'\d{4}-\d{2}-\d{2}'),('month_iso',r'\d{4}-\d{2}'),('year',r'\d{4}'),('compact_day',r'\d{8}'),('compact_month',r'\d{6}'),('timestamp',r'\d{4}-\d{2}-\d{2}[T ].*')]:
  if re.fullmatch(pattern,v):return name
 if re.fullmatch(r'[0-9/\-:. T]+',v):
  return 'numeric_shape:'+re.sub(r'[0-9]+',lambda m:'D'+str(len(m.group())),v)
 return 'other_text'
def audit(path,report_dir,work,dialect='csv',byte_preserving=False):
 started=time.monotonic();before=path.stat();enc='cp1255' if path.stem in CP else 'utf-8-sig'
 source_encoding=enc
 if byte_preserving:enc='latin1'
 report={'byte_preserving_structural_only':byte_preserving,'intended_encoding':source_encoding,'name':path.name,'encoding':enc,'encoding_verification':'structural_only_pending_official_content_verification','delimiter':'|','dialect':dialect,'dialect_verification':'candidate_pending_official_verification' if dialect!='csv' else 'standard_csv','status':'not_run','scan_complete':False,'records_read':0,'structure_errors':0,'decode_errors':0,'headers':[],'missing':{},'date_shapes':{},'duplicates':{'status':'not_run'},'plate_keys':{'status':'not_run'},'size_bytes':before.st_size}
 h=hashlib.sha256();undefined_cp1255=0
 decoder=codecs.getincrementaldecoder(source_encoding)('strict');encoding_error=None
 invalid=set()
 if source_encoding=='cp1255':
  for value in range(256):
   try:bytes([value]).decode('cp1255')
   except UnicodeDecodeError:invalid.add(value)
 with path.open('rb') as f:
  for chunk in iter(lambda:f.read(1024*1024),b''):
   h.update(chunk)
   if encoding_error is None:
    try:decoder.decode(chunk,final=False)
    except UnicodeError as exc:encoding_error=str(exc)[:250]
   if invalid:undefined_cp1255+=sum(chunk.count(value) for value in invalid)
 if encoding_error is None:
  try:decoder.decode(b'',final=True)
  except UnicodeError as exc:encoding_error=str(exc)[:250]
 report['encoding_full_validation']={'status':'failed' if encoding_error else 'complete','error':encoding_error}
 report['parser_version']='mot-envelope-2' if dialect=='mot_envelope' else 'python-csv-strict'
 report['sha256']=h.hexdigest();report['undefined_cp1255_bytes']=undefined_cp1255
 dbpath=work/(path.stem+'.audit.sqlite')
 if dbpath.exists():raise FileExistsError('Audit work file already exists; choose a fresh work directory')
 db=sqlite3.connect(dbpath)
 db.execute('PRAGMA journal_mode=OFF');db.execute('PRAGMA synchronous=OFF');db.execute('PRAGMA temp_store=FILE');db.execute('PRAGMA cache_size=-8192')
 db.execute('CREATE TABLE rows(hash BLOB NOT NULL,plate TEXT)')
 batch=[]
 try:
  with path.open(encoding=enc,newline='') as f:
   
   if dialect=='mot_envelope':
    from importer.motpipe import rows as envelope_rows
    rows=envelope_rows(f)
   else: rows=csv.reader(f,delimiter='|',strict=True)
   headers=next(rows);report['headers']=headers;report['missing']={k:0 for k in headers}
   plateidx=next((i for i,k in enumerate(headers) if k.lower()=='mispar_rechev'),None)
   dateidx=[(i,k) for i,k in enumerate(headers) if any(q in k.lower() for q in ['_dt','date','taarich','begin','end','moed'])]
   report['date_shapes']={k:{} for _,k in dateidx}
   for row in rows:
    report['records_read']+=1
    if len(row)!=len(headers):report['structure_errors']+=1;continue
    for k,v in zip(headers,row):
     if v=='':report['missing'][k]+=1
    for i,k in dateidx:
     if row[i]:
      sk=shape(row[i]);report['date_shapes'][k][sk]=report['date_shapes'][k].get(sk,0)+1
    key=row[plateidx] if plateidx is not None else None
    batch.append((hashlib.sha256(json.dumps(row,ensure_ascii=False,separators=(',',':')).encode()).digest(),key))
    if len(batch)>=10000:
     db.executemany('INSERT INTO rows VALUES(?,?)',batch);db.commit();batch.clear()
   report['scan_complete']=True;report['status']='complete' if not report['structure_errors'] else 'failed'
 except (UnicodeError,csv.Error,StopIteration,ValueError) as e:
  report['status']='failed';report['parser_error']=str(e)[:250]
  if isinstance(e,UnicodeError):report['decode_errors']+=1
  else:report['structure_errors']+=1
 finally:
  if batch:db.executemany('INSERT INTO rows VALUES(?,?)',batch);db.commit()
 report['records_structurally_valid']=db.execute('SELECT count(*) FROM rows').fetchone()[0]
 db.execute('CREATE INDEX rowhash ON rows(hash)')
 duplicate_groups,duplicate_rows=db.execute('SELECT count(*),coalesce(sum(n-1),0) FROM (SELECT count(*) n FROM rows GROUP BY hash HAVING count(*)>1)').fetchone()
 report['duplicates']={'status':'complete' if report['scan_complete'] else 'partial','groups':duplicate_groups,'extra_rows':duplicate_rows,'definition':'SHA256 of parsed full record; includes every source column'}
 if any(k.lower()=='mispar_rechev' for k in report['headers']):
  db.execute('CREATE INDEX plate ON rows(plate)')
  distinct,repeated,extras=db.execute('SELECT count(*),coalesce(sum(case when n>1 then 1 else 0 end),0),coalesce(sum(n-1),0) FROM (SELECT count(*) n FROM rows WHERE plate IS NOT NULL GROUP BY plate)').fetchone()
  report['plate_keys']={'status':'complete' if report['scan_complete'] else 'partial','distinct':distinct,'repeated_keys':repeated,'extra_rows':extras,'length_distribution':dict(db.execute('SELECT length(plate),count(*) FROM rows GROUP BY length(plate)').fetchall()),'non_ascii_digit_records':db.execute("SELECT count(*) FROM rows WHERE plate GLOB '*[^0-9]*' OR plate=''").fetchone()[0],'interpretation':'Repeated plate is not automatically a conflict in history/event sources'}
 db.close();after=path.stat();report['source_unchanged']=(before.st_size,before.st_mtime_ns,before.st_ino)==(after.st_size,after.st_mtime_ns,after.st_ino)
 report['elapsed_seconds']=round(time.monotonic()-started,3);report['peak_rss_bytes']=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*(1 if sys.platform=='darwin' else 1024)
 report['work_index']=str(dbpath)
 target=report_dir/(path.stem+'.audit.json');target.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps({k:report[k] for k in ['name','status','scan_complete','records_read','structure_errors','duplicates','plate_keys','elapsed_seconds','peak_rss_bytes','source_unchanged']},ensure_ascii=False),flush=True)
 return report
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--file');p.add_argument('--byte-preserving',action='store_true');p.add_argument('--dialect',choices=['csv','mot_envelope'],default='csv');p.add_argument('--tag',default=str(time.time_ns()));a=p.parse_args()
 report_dir=ROOT/'data/reports'/('audit-'+a.tag);work=ROOT/'data/work'/('audit-'+a.tag);report_dir.mkdir(parents=True,exist_ok=True);work.mkdir(parents=True,exist_ok=True)
 results=[]
 for path in ([ROOT/'data/raw'/a.file] if a.file else sorted((ROOT/'data/raw').glob('*.csv'))):results.append(audit(path,report_dir,work,a.dialect,a.byte_preserving))
 (report_dir/'summary.json').write_text(json.dumps({'files':results},ensure_ascii=False,indent=2),encoding='utf-8')
