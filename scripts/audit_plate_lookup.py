#!/usr/bin/env python3
"""Aggregate-only lookup representation audit. Does not alter source or DB data."""
import json,os,time
from pathlib import Path
import psycopg
ROOT=Path(__file__).resolve().parents[1]
TABLES=('vehicles','statuses','recalls','mileage','ownership')

def main():
 started=time.monotonic()
 if not os.environ.get('DATABASE_URL'):raise SystemExit('DATABASE_URL required')
 official=json.loads((ROOT/'data/reports/official-metadata.json').read_text())['sources']
 numeric={x['resource_id']:any(f['id'].lower()=='mispar_rechev' and f['type']=='numeric' for f in x.get('fields',[])) for x in official}
 report={'status':'complete','scope':'Full active normalized PostgreSQL sources; only aggregate values emitted','lookup_rule':'For verified zero-padded-8 source, exactly7-digit input may also query one leading zero plus original input. No stored plate mutation. Exact lookup first.','sources':[],'user_case':{},'elapsed_seconds':None}
 with psycopg.connect(os.environ['DATABASE_URL']) as c:
  c.execute('SET TRANSACTION READ ONLY')
  for table in TABLES:
   rows=c.execute(f"""SELECT n.source_id,count(*),count(*) FILTER(WHERE n.plate IS NULL OR n.plate !~ '^[0-9]{{8}}$'),count(*) FILTER(WHERE n.plate LIKE '0%'),count(DISTINCT n.plate),count(DISTINCT CASE WHEN n.plate LIKE '0%' THEN substring(n.plate FROM 2) ELSE n.plate END) FROM live.{table} n JOIN live.sources s ON s.id=n.source_id AND s.active_run_id=n.run_id GROUP BY n.source_id""").fetchall()
   for source,total,bad,zero,distinct,aliases in rows:
    rid=source.removeprefix('mot-')
    report['sources'].append({'source_id':source,'table':table,'rows':total,'invalid_or_non_8_digit_rows':bad,'leading_zero_rows':zero,'distinct_original_plates':distinct,'distinct_lookup_aliases':aliases,'alias_collision_count':distinct-aliases,'official_plate_field_numeric':numeric.get(rid,False),'lookup_format_verified':bad==0 and distinct==aliases and numeric.get(rid,False)})
   counts=c.execute(f'SELECT count(*) FILTER(WHERE n.plate=%s),count(*) FILTER(WHERE n.plate=%s) FROM live.{table} n JOIN live.sources s ON s.id=n.source_id AND s.active_run_id=n.run_id WHERE n.plate=ANY(%s)',('5555555','05555555',['5555555','05555555'])).fetchone()
   report['user_case'][table]={'exact_7_matches':counts[0],'padded_8_matches':counts[1]}
  global_counts=c.execute("""SELECT count(DISTINCT n.plate),count(DISTINCT CASE WHEN n.plate LIKE '0%' THEN substring(n.plate FROM 2) ELSE n.plate END) FROM live.vehicles n JOIN live.sources s ON s.id=n.source_id AND s.active_run_id=n.run_id""").fetchone()
  report['active_vehicle_global']={'distinct_original_plates':global_counts[0],'distinct_aliases':global_counts[1],'alias_collision_count':global_counts[0]-global_counts[1]}
 report['elapsed_seconds']=round(time.monotonic()-started,3)
 target=ROOT/'data/reports/plate-lookup-audit.json';target.write_text(json.dumps(report,ensure_ascii=False,indent=2))
 print(json.dumps({'status':report['status'],'active_sources_checked':len(report['sources']),'verified':sum(x['lookup_format_verified'] for x in report['sources']),'alias_collisions':report['active_vehicle_global']['alias_collision_count'],'user_case':report['user_case'],'report':str(target)},ensure_ascii=False))
if __name__=='__main__':main()
