"""Run local verified sources through staging; never promotes or logs source values."""
import argparse,json,os,subprocess,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser();p.add_argument('--skip-main',action='store_true');p.add_argument('--only-main',action='store_true');args=p.parse_args()
if os.environ.get('DATA_MODE')!='live':raise SystemExit('Explicit DATA_MODE=live required')
DATA=Path(os.environ.get('DATA_DIR',str(ROOT/'data')))
folder=DATA/'reports'/('real-load-'+str(time.time_ns()));folder.mkdir()
configs=[]
for file in (ROOT/'mappings/real').glob('*.json'):
 c=json.loads(file.read_text());main=c['source_file'].startswith('053cea08')
 if args.skip_main and main or args.only_main and not main:continue
 configs.append((file,c))
priority={'specs':0,'recall_catalog':1,'model_counts':2,'vehicles':3,'statuses':4,'recalls':5,'mileage':6,'ownership':7}
configs.sort(key=lambda x:(priority[x[1]['kind']],x[1]['source_file']))
results=[]
for file,c in configs:
 log=folder/(file.stem+'.log')
 with log.open('w') as output:
  process=subprocess.run([sys.executable,'-m','importer.real','stage',str(DATA/'raw'/c['source_file']),'--mapping',str(file)],cwd=ROOT,stdout=output,stderr=subprocess.STDOUT)
 try:r=json.loads(log.read_text())
 except (ValueError,OSError):r={'status':'failed','details_path':str(log)}
 results.append({'source_file':c['source_file'],'kind':c['kind'],**r})
 (folder/'summary.json').write_text(json.dumps(results,ensure_ascii=False,indent=2))
 print(json.dumps({k:results[-1].get(k) for k in ['source_file','status','run_id','records_read','records_staged','records_rejected','quality_passed','publication_blockers']},ensure_ascii=False),flush=True)
print(json.dumps({'report':str(folder/'summary.json'),'sources':len(results),'staged':sum(r.get('status') in ('staged','unchanged') for r in results)},ensure_ascii=False))
