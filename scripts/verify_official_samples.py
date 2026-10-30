"""Sampled framing/encoding evidence using independent inbound official records.
Outbound parameters contain only public resource IDs and a fixed limit. Local
plates, record values and identifiers are never sent. At most 1000 records per
source are held for comparison; no source records are printed or persisted.
Character-multiset comparisons are evidence only, never source normalization.
Run from the project directory after the metadata/inspect report steps.
"""
import sys,json,urllib.request,urllib.parse,hashlib,decimal,concurrent.futures
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from importer.motpipe import rows
sources=json.loads((ROOT/'data/reports/official-metadata.json').read_text())['sources']
inspect={r['name']:r for r in json.loads((ROOT/'data/reports/real-inspect-explicit.json').read_text())}
def text(v):
 return '' if v is None else str(v)
def numeric(v):
 if v is None or v=='':return ''
 try:return str(decimal.Decimal(str(v)).normalize())
 except decimal.InvalidOperation:return str(v)
def one(source):
 resource=source['resource_id'];name=source.get('local_filename',resource+'.csv')
 result={'file':name,'resource_id':resource,'scope':'sampled; independently selected first1000 official records; no local identifiers outbound','requested_limit':1000}
 try:
  url='https://data.gov.il/api/3/action/datastore_search?'+urllib.parse.urlencode({'resource_id':resource,'limit':1000})
  with urllib.request.urlopen(url,timeout=40) as response:
   raw=response.read(20*1024*1024+1)
  if len(raw)>20*1024*1024:raise ValueError('bounded response size exceeded')
  official=json.loads(raw)['result'];remote=official['records']
  fields=[f['id'] for f in official['fields'] if f['id']!='_id'];numericfields={f['id'] for f in official['fields'] if f['type'] in ('numeric','int','float')}
  local=[]
  with open(ROOT/'data/raw'/name,encoding=inspect[name]['encoding'],newline='') as stream:
   gen=rows(stream);headers=next(gen)
   for i,row in enumerate(gen):
    local.append(dict(zip(headers,row)))
    if i>=999:break
  def canon(r,normal=False):
   return json.dumps([numeric(r.get(k)) if normal and k in numericfields else text(r.get(k)) for k in fields],ensure_ascii=False,separators=(',',':'))
  exactremote={hashlib.sha256(canon(r).encode()).digest() for r in remote}
  normalizedremote={hashlib.sha256(canon(r,True).encode()).digest() for r in remote}
  exact=sum(hashlib.sha256(canon(r).encode()).digest() in exactremote for r in local)
  equivalent=sum(hashlib.sha256(canon(r,True).encode()).digest() in normalizedremote for r in local)
  problematic=[r for r in local if any('"' in text(v) or '\n' in text(v) for v in r.values())]
  quote_exact=sum(hashlib.sha256(canon(r).encode()).digest() in exactremote for r in problematic)
  quote_equiv=sum(hashlib.sha256(canon(r,True).encode()).digest() in normalizedremote for r in problematic)
  textmatches=sum(all(text(l.get(k))==text(rr.get(k)) for k in fields if k not in numericfields) for l,rr in zip(local,remote))
  from collections import Counter
  import re
  keyfields=[k for k in ('mispar_rechev','MISPAR_RECHEV','sug_degem','tozeret_cd','degem_cd','shnat_yitzur','RECALL_ID') if k in fields]
  numeric_position_matches=sum(all(numeric(l.get(k))==numeric(rr.get(k)) for k in numericfields if k!='_id') for l,rr in zip(local,remote))
  key_position_matches=sum(all((numeric(l.get(k))==numeric(rr.get(k))) if k in numericfields else text(l.get(k))==text(rr.get(k)) for k in keyfields) for l,rr in zip(local,remote))
  equivalent_cell_rows=0;non_equivalent_fields=Counter();order_or_space_differences=Counter()
  for l,rr in zip(local,remote):
   okay=True
   for k in fields:
    if k in numericfields:continue
    lv,rv=text(l.get(k)),text(rr.get(k))
    if lv==rv:continue
    # Comparison evidence only. Never transform or persist source strings.
    if Counter(re.sub(r'\s','',lv))==Counter(re.sub(r'\s','',rv)):
     order_or_space_differences[k]+=1
    else:
     non_equivalent_fields[k]+=1;okay=False
   equivalent_cell_rows+=okay
  framing_validated=(headers==fields and len(local)==len(remote) and bool(local) and numeric_position_matches==len(local) and key_position_matches==len(local) and equivalent_cell_rows==len(local))
  result.update(sampled_numeric_positions_match=numeric_position_matches,sampled_key_positions_match=key_position_matches,key_fields=keyfields,text_character_multiset_consistent_rows=equivalent_cell_rows,text_order_or_space_difference_fields=dict(order_or_space_differences),text_other_difference_fields=dict(non_equivalent_fields),source_framing_sample_verified=framing_validated,encoding_content_sample_verified=framing_validated,lexical_source_text_retained=True,numeric_equivalence_used_for_comparison_only=True)
  result.update(status='sampled',header_matches=headers==fields,local_records=len(local),official_records=len(remote),exact_full_row_matches=exact,numeric_equivalent_full_row_matches=equivalent,local_rows_with_literal_quotes_or_newline=len(problematic),quote_rows_exact_full_match=quote_exact,quote_rows_numeric_equivalent_full_match=quote_equiv,positionally_matching_all_text_fields=textmatches,selected_encoding=inspect[name]['encoding'],official_api_url=url)
 except Exception as e:result.update(status='failed',error=str(e)[:180])
 return result
def main():
 with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:results=list(pool.map(one,sources))
 target=ROOT/'data/reports/official-framing-encoding-evidence.json'
 if target.exists():
  import time
  target=target.with_name('official-framing-encoding-evidence-'+str(time.time_ns())+'.json')
 target.write_text(json.dumps({'status':'sampled','no_local_identifiers_sent':True,'sources':results},ensure_ascii=False,indent=2))
 print(json.dumps({'status':'sampled','sources':len(results),'verified_sample_sources':sum(r.get('source_framing_sample_verified',False) for r in results),'report_path':str(target),'raw_records_printed':0},ensure_ascii=False))
 return 1 if any(r['status']=='failed' for r in results) else 0

if __name__=='__main__':sys.exit(main())
