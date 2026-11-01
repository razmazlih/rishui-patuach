"""Derived spec keys and unique/run-bound linking, without source mutations."""
import json,os,tempfile,unittest,uuid
from pathlib import Path
import psycopg
from scripts.link_specs import build
ROOT=Path(__file__).resolve().parents[1]

@unittest.skipUnless(os.environ.get('TEST_SPEC_DATABASE_URL'),'explicit isolated spec test database required')
class SpecLinks(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.url=os.environ['TEST_SPEC_DATABASE_URL']
  with psycopg.connect(cls.url) as db:
   db.execute('CREATE SCHEMA IF NOT EXISTS demo');db.execute('SET search_path TO demo,public')
   for file in sorted((ROOT/'db').glob('[0-9]*.sql')):db.execute(file.read_text())

 def setUp(self):
  self.sources=[];self.runs=[];self.ids=[]
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
  self.addCleanup(self.cleanup)

 def connect(self):
  db=psycopg.connect(self.url);db.execute('SET search_path TO demo,public');return db

 def add(self,kind,payload,plate=None):
  source='spec-test-'+uuid.uuid4().hex;self.sources.append(source)
  with self.connect() as db:
   db.execute("INSERT INTO sources(id,kind,name,coverage,synthetic) VALUES(%s,%s,'test','{}',true)",(source,kind))
   run=db.execute("INSERT INTO import_runs(source_id,state,fingerprint,mapping_version,importer_version) VALUES(%s,'published',%s,'test','test') RETURNING id",(source,uuid.uuid4().hex)).fetchone()[0];self.runs.append(run)
   db.execute("UPDATE sources SET active_run_id=%s,availability='available' WHERE id=%s",(run,source))
   identifier=db.execute(f'INSERT INTO {kind}(plate,source_id,run_id,source_record_id,payload) VALUES(%s,%s,%s,%s,%s::jsonb) RETURNING id',(plate,source,run,'row',json.dumps(payload))).fetchone()[0]
   return identifier,run,source

 def cleanup(self):
  with self.connect() as db:
   db.execute('DELETE FROM spec_links WHERE vehicle_run_id=ANY(%s) OR spec_run_id=ANY(%s)',(self.runs,self.runs))
   db.execute('DELETE FROM model_count_links WHERE vehicle_run_id=ANY(%s) OR model_count_run_id=ANY(%s)',(self.runs,self.runs))
   for table in ('vehicles','specs','model_counts'):db.execute(f'DELETE FROM {table} WHERE source_id=ANY(%s)',(self.sources,))
   db.execute('UPDATE sources SET active_run_id=NULL WHERE id=ANY(%s)',(self.sources,))
   db.execute('DELETE FROM import_runs WHERE source_id=ANY(%s)',(self.sources,))
   db.execute('DELETE FROM sources WHERE id=ANY(%s)',(self.sources,))

 def test_key_preserves_originals_and_does_not_guess_text_or_variant(self):
  payload={'model_type':'P','manufacturer_code':'00001','model_code':'00042','year':'2022'}
  with self.connect() as db:
   key=db.execute('SELECT spec_join_key(%s::jsonb)',(json.dumps(payload),)).fetchone()[0]
   self.assertEqual(json.loads(key),['P','1','42','2022'])
   for target,value in [('model_code','43'),('model_type','M'),('year','2023')]:
    other={**payload,target:value,'model':'same name'}
    self.assertNotEqual(db.execute('SELECT spec_join_key(%s::jsonb)',(json.dumps(other),)).fetchone()[0],key)
   for target,value in [('model_code','42x'),('model_type',''),('year','2022-01')]:
    bad={**payload,target:value}
    self.assertIsNone(db.execute('SELECT spec_join_key(%s::jsonb)',(json.dumps(bad),)).fetchone()[0])
  self.assertEqual(payload['manufacturer_code'],'00001')

 def test_unique_join_idempotence_and_run_guard(self):
  vehicle={'model_type':'P','manufacturer_code':'1','model_code':'42','year':'2022','plate':'01234567'}
  spec={**vehicle,'manufacturer_code':'00001','model_code':'00042','engine_volume_raw':'1600'}
  v,vr,vs=self.add('vehicles',vehicle,'01234567');s,sr,ss=self.add('specs',spec)
  c,cr,cs=self.add('model_counts',{**spec,'active_vehicle_count':123})
  first=build(self.url,'demo',Path(self.temp.name)/'first.json')
  second=build(self.url,'demo',Path(self.temp.name)/'second.json')
  self.assertEqual(first['specs']['matched_vehicle_rows'],1)
  self.assertEqual(first['model_counts']['matched_vehicle_rows'],1)
  self.assertEqual(second['specs']['new_links'],0)
  with self.connect() as db:
   self.assertEqual(db.execute('SELECT payload FROM vehicles WHERE id=%s',(v,)).fetchone()[0],vehicle)
   self.assertEqual(db.execute('SELECT payload FROM specs WHERE id=%s',(s,)).fetchone()[0],spec)
   db.execute('UPDATE sources SET active_run_id=NULL WHERE id=%s',(ss,))
   n=db.execute('SELECT count(*) FROM spec_links l JOIN vehicles v ON v.id=l.vehicle_id AND v.run_id=l.vehicle_run_id JOIN sources vs ON vs.id=v.source_id AND vs.active_run_id=v.run_id JOIN specs s ON s.id=l.spec_id AND s.run_id=l.spec_run_id JOIN sources ss ON ss.id=s.source_id AND ss.active_run_id=s.run_id WHERE v.id=%s',(v,)).fetchone()[0]
   self.assertEqual(n,0)

 def test_ambiguous_canonical_key_is_never_picked(self):
  base={'model_type':'P','manufacturer_code':'1','model_code':'42','year':'2022'}
  self.add('vehicles',base,'01234567');self.add('specs',base);self.add('specs',{**base,'manufacturer_code':'00001','model_code':'00042','trim':'other'})
  report=build(self.url,'demo',Path(self.temp.name)/'report.json')
  self.assertEqual(report['specs']['canonical_ambiguous_groups'],1)
  self.assertEqual(report['specs']['ambiguous_vehicle_rows_withheld'],1)
  self.assertEqual(report['specs']['matched_vehicle_rows'],0)

if __name__=='__main__':unittest.main()
