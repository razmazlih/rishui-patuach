#!/usr/bin/env python3
"""Disk-index full lexical relationships. Never emits source rows or values."""
import argparse,csv,hashlib,json,sqlite3,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from importer.motpipe import rows

def spec_keys(work):
    path=ROOT/'data/raw/142afde2-6228-49f9-8a29-9b6c3a0cbe40.csv'
    target=work/'spec-composite.sqlite'
    db=sqlite3.connect(target);db.execute('CREATE TABLE IF NOT EXISTS spec_keys(key text,hash blob)');db.execute('DELETE FROM spec_keys')
    fields=['sug_degem','tozeret_cd','degem_cd','shnat_yitzur'];batch=[];missing=0
    with path.open(encoding='utf-8-sig',newline='') as f:
        parsed=rows(f);header=next(parsed);indices=[header.index(k) for k in fields]
        for record in parsed:
            values=[record[i] for i in indices]
            if any(v=='' for v in values):missing+=1
            batch.append((json.dumps(values,separators=(',',':')),hashlib.sha256(json.dumps(record,ensure_ascii=False).encode()).digest()))
            if len(batch)>=10000:db.executemany('INSERT INTO spec_keys VALUES(?,?)',batch);batch.clear()
    if batch:db.executemany('INSERT INTO spec_keys VALUES(?,?)',batch)
    db.execute('CREATE INDEX IF NOT EXISTS spec_key ON spec_keys(key)')
    total=db.execute('SELECT count(*) FROM spec_keys').fetchone()[0]
    duplicate_groups,extras,conflicts=db.execute('SELECT count(*),coalesce(sum(n-1),0),coalesce(sum(case when variants>1 then 1 else 0 end),0) FROM (SELECT count(*) n,count(distinct hash) variants FROM spec_keys GROUP BY key HAVING count(*)>1)').fetchone()
    db.commit();db.close()
    return {'status':'complete','source':path.name,'candidate_key_fields':fields,'rows':total,'missing_key_rows':missing,'duplicate_key_groups':duplicate_groups,'duplicate_key_extra_rows':extras,'conflicting_key_groups':conflicts,'semantics_verified':False}

def vehicle_specs(work):
    db=sqlite3.connect(work/'spec-composite.sqlite');db.execute('PRAGMA cache_size=-8192');db.execute('CREATE TABLE IF NOT EXISTS vehicle_spec_keys(source text,key text)');db.execute('DELETE FROM vehicle_spec_keys')
    fields=['sug_degem','tozeret_cd','degem_cd','shnat_yitzur'];result=[]
    for name in ['053cea08-09bc-40ec-8f7a-156f0677aff3','f6efe89a-fb3d-43a4-bb61-9bf12a9b9099']:
        path=ROOT/'data/raw'/(name+'.csv');batch=[];missing=0
        # Structural/key audit only. Latin1 is a bijection for source bytes, not a semantic codec fallback.
        with path.open(encoding='latin1',newline='') as f:
            parsed=rows(f);header=next(parsed);indices=[header.index(k) for k in fields]
            for record in parsed:
                values=[record[i] for i in indices]
                if any(v=='' for v in values):missing+=1
                batch.append((name,json.dumps(values,separators=(',',':'))))
                if len(batch)>=10000:db.executemany('INSERT INTO vehicle_spec_keys VALUES(?,?)',batch);batch.clear()
        if batch:db.executemany('INSERT INTO vehicle_spec_keys VALUES(?,?)',batch)
        db.commit()
        total,matched=db.execute('SELECT count(*),coalesce(sum(EXISTS(SELECT 1 FROM spec_keys p WHERE p.key=v.key)),0) FROM vehicle_spec_keys v WHERE source=?',(name,)).fetchone()
        result.append({'source':path.name,'status':'complete','records':total,'missing_key_rows':missing,'matched_records':matched,'unmatched_records':total-matched,'relationship':'exact lexical composite only; semantic mapping requires source verification'})
    db.close();return result

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--audit-dir',required=True);a=ap.parse_args()
    folder=Path(a.audit_dir);reports=[json.loads(p.read_text()) for p in sorted(folder.glob('*.audit.json'))]
    indexes={r['name']:{'index':r['work_index'],'complete':r['scan_complete'],'has_plates':r['plate_keys']['status']!='not_run'} for r in reports}
    report={'status':'complete','relationship_semantics':'exact lexical identifiers only; requires independently verified source meaning before publication','links':[]}
    for name,source in indexes.items():
        if not source['complete'] or not source['has_plates']:continue
        db=sqlite3.connect(':memory:');db.execute('PRAGMA temp_store=FILE');db.execute('PRAGMA cache_size=-4096')
        db.execute('ATTACH DATABASE ? AS source',(source['index'],))
        for refname in ['053cea08-09bc-40ec-8f7a-156f0677aff3.csv','f6efe89a-fb3d-43a4-bb61-9bf12a9b9099.csv']:
            ref=indexes.get(refname)
            if not ref or not ref['complete']:continue
            db.execute('ATTACH DATABASE ? AS reference',(ref['index'],))
            count,matched=db.execute('SELECT count(*),coalesce(sum(EXISTS(SELECT 1 FROM reference.rows r WHERE r.plate=s.plate)),0) FROM source.rows s').fetchone()
            distinct,distinct_matched=db.execute('SELECT count(*),coalesce(sum(EXISTS(SELECT 1 FROM reference.rows r WHERE r.plate=s.plate)),0) FROM (SELECT DISTINCT plate FROM source.rows) s').fetchone()
            report['links'].append({'source':name,'reference':refname,'records':count,'matched_records':matched,'unmatched_records':count-matched,'distinct_plates':distinct,'matched_distinct_plates':distinct_matched,'unmatched_distinct_plates':distinct-distinct_matched})
            db.execute('DETACH DATABASE reference')
        db.close()
    work=ROOT/'data/work/audit-mot-v2-bytes-20261030';work.mkdir(exist_ok=True)
    report['spec_composite']=spec_keys(work)
    report['vehicle_to_spec_composite']=vehicle_specs(work)
    path=folder/'relationships.json';path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'status':report['status'],'relationship_pairs':len(report['links']),'spec_composite':report['spec_composite'],'report_path':str(path)},ensure_ascii=False))
if __name__=='__main__':main()
