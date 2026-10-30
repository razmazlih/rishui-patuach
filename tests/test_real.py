"""Real adapter logic tested only against tiny synthetic, locally generated values."""
import csv
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from importer import real


def config():
    return {'id':'adapter-unit','kind':'vehicles','name':'synthetic isolated test','version':'1',
            'verified':True,'synthetic':False,'official_url':'https://example.gov.invalid/test',
            'verification':{'test_only':True},'encoding':'utf-8-sig','encoding_verified':True,'delimiter':'|',
            'fields':{'id':{'target':'record_id'},'plate':{'target':'plate','normalize':'plate','required':True},
                      'date':{'target':'test_date','type':'date','formats':['iso_date','iso_datetime','yyyymm']},
                      'raw':{'ignore':True}},
            'keys':['record_id'],'coverage':{'description':'isolated test only'},'key_mode':'fields'}


class RealAdapterUnit(unittest.TestCase):
    def test_explicit_verified_envelope_parser_preserves_literal_quotes(self):
        from io import StringIO
        c=config();c['dialect']='mot_envelope';c['dialect_verified']=True
        # Tiny synthetic record, including a literal unmatched quote inside a value.
        stream=StringIO('id|plate|date|raw\n"1"|"01234567"|"202606"|"text " literal"\n')
        row=next(real.records(stream,c))
        self.assertEqual(row['raw'],'text " literal')

    def test_catalog_requires_no_plate_and_stays_separate(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'map.json';c=config();c['kind']='recall_catalog'
            c['fields']={'recall':{'target':'recall_id'}};c['keys']=['recall_id']
            p.write_text(json.dumps(c))
            with patch.dict(os.environ,{'DATA_MODE':'live'}):self.assertEqual(real.mapping_file(p)['kind'],'recall_catalog')

    def test_quarantine_requires_audited_whole_record_and_tiny_fraction(self):
        c=config();c['quarantine_policy']={'max_records':3,'max_fraction':0.000001,'allowed_reasons':['decode_error']}
        r={'scan_complete':True,'sha256':'a'*64,'records_read':4197986,'records_rejected':3,'decode_error_records':3,'structure_errors':0,
           'rejection_reasons':{'decode_error:raw':3},'full_source_audit':{'status':'complete','sha256':'a'*64,'records_read':4197986}}
        self.assertTrue(real.quarantine_allowed(c,r))
        self.assertFalse(real.quarantine_allowed(c,{**r,'records_rejected':4,'decode_error_records':4}))
        self.assertFalse(real.quarantine_allowed(c,{**r,'scan_complete':False}))
        self.assertFalse(real.quarantine_allowed(c,{**r,'rejection_reasons':{'date:date':3}}))
        self.assertFalse(real.quarantine_allowed(c,{**r,'records_read':2}))

    def test_bytes_bridge_decodes_valid_cells_and_quarantines_undefined_byte(self):
        from io import StringIO
        c=config();c.update(dialect='mot_envelope_bytesbridge',encoding='windows-1255')
        source=b'id|plate|date|raw\n"1"|"01234567"|"202606"|"'+ 'שם'.encode('cp1255')+b'"\n"2"|"01234567"|"202606"|"\x9f"\n'
        rows=list(real.records(StringIO(source.decode('latin1')),c))
        self.assertEqual(rows[0]['raw'],'שם')
        self.assertIsInstance(rows[1],real.DecodeRejected)
        self.assertEqual(rows[1].fields,['raw'])

    def test_preserves_plate_original_zeros_and_ignored_fields(self):
        key,payload,missing=real.transform({'id':'1','plate':'01-234 567','date':'2026-06-01','raw':'ignore'},config(),1)
        self.assertEqual(payload['plate'],'01234567')
        self.assertEqual(payload['plate_original'],'01-234 567')
        self.assertEqual(payload['test_date_precision'],'day')
        self.assertNotIn('raw',payload)
        self.assertEqual(json.loads(key),['1'])

    def test_month_not_fabricated_as_day(self):
        _,p,_=real.transform({'id':'1','plate':'01234567','date':'202606','raw':''},config(),1)
        self.assertEqual(p['test_date'],'2026-06')
        self.assertEqual(p['test_date_precision'],'month')
        self.assertEqual(p['test_date_original'],'202606')

    def test_iso_datetime_explicitly_supported(self):
        self.assertEqual(real.date_value('2026-01-03T00:00:00',['iso_datetime']),('2026-01-03','day'))
        with self.assertRaises(ValueError):real.date_value('20260103',['iso_date'])
        with self.assertRaises(ValueError):real.date_value('202613',['yyyymm'])

    def test_missing_date_stays_missing(self):
        _,p,missing=real.transform({'id':'1','plate':'01234567','date':'','raw':''},config(),1)
        self.assertIsNone(p['test_date'])
        self.assertNotIn('test_date_precision',p)
        self.assertEqual(missing['test_date'],1)

    def test_history_rows_not_keyed_by_plate(self):
        c=config();c['key_mode']='row_number';c['kind']='ownership'
        row={'id':'a','plate':'01234567','date':'','raw':''}
        self.assertNotEqual(real.transform(row,c,1)[0],real.transform(row,c,2)[0])

    def test_ambiguous_mapping_or_mode_refused(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'map.json';c=config();p.write_text(json.dumps(c))
            with patch.dict(os.environ,{'DATA_MODE':'demo'}), self.assertRaises(ValueError):real.mapping_file(p)
            c['verified']=False;p.write_text(json.dumps(c))
            with patch.dict(os.environ,{'DATA_MODE':'live'}), self.assertRaises(ValueError):real.mapping_file(p)

    def test_explicit_short_plates_preserve_values(self):
        c=config();row={'id':'1','plate':'01234','date':'','raw':''}
        with self.assertRaises(ValueError):real.transform(row,c,1)
        c['plate_pattern']='[0-9]{1,8}'
        self.assertEqual(real.transform(row,c,1)[1]['plate'],'01234')

    def test_source_local_composite_not_shared_row_id(self):
        c=config();c['composite_key_fields']=['record_id','test_date'];c['kind']='specs'
        _,p,_=real.transform({'id':'001','plate':'01234567','date':'202606','raw':''},c,1)
        self.assertEqual(json.loads(p['spec_key']),['001','2026-06'])

@unittest.skipUnless(os.environ.get('TEST_REAL_DATABASE_URL'), 'explicit isolated TEST_REAL_DATABASE_URL required')
class RealAdapterDatabase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from importer import cli
        cls.env=patch.dict(os.environ,{'DATABASE_URL':os.environ['TEST_REAL_DATABASE_URL'],'DATA_MODE':'live'})
        cls.env.start()
        cls.addClassCleanup(cls.env.stop)
        cli.migrate()

    def setUp(self):
        import uuid
        self.plate='0' + str(int(uuid.uuid4().hex[:8],16) % 10000000).zfill(7)
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'source.csv';self.mapping=Path(self.temp.name)/'mapping.json'
        self.c=config();self.c['id']='adapter-'+uuid.uuid4().hex
        self.addCleanup(self.cleanup_source)
        self.write([['a',self.plate,'202606','ignored']])

    def cleanup_source(self):
        from importer import cli
        with cli.connect() as c:
            source=self.c['id']
            for kind in real.KINDS:
                c.execute(f'DELETE FROM {kind} WHERE source_id=%s',(source,))
            c.execute('DELETE FROM staging WHERE run_id IN (SELECT id FROM import_runs WHERE source_id=%s)',(source,))
            c.execute('DELETE FROM rejected_rows WHERE run_id IN (SELECT id FROM import_runs WHERE source_id=%s)',(source,))
            c.execute('UPDATE sources SET active_run_id=NULL WHERE id=%s',(source,))
            c.execute('DELETE FROM import_runs WHERE source_id=%s',(source,))
            c.execute('DELETE FROM source_files WHERE source_id=%s',(source,))
            c.execute('DELETE FROM sources WHERE id=%s',(source,))

    def write(self,rows):
        self.mapping.write_text(json.dumps(self.c))
        with self.path.open('w',encoding='utf-8-sig',newline='') as f:
            writer=csv.writer(f,delimiter='|');writer.writerow(self.c['fields']);writer.writerows(rows)

    def test_copy_stage_promote_repeat_and_failure_preserves_active(self):
        from importer import cli
        first=real.stage(self.path,self.mapping)
        self.assertEqual(first['status'],'staged')
        self.assertEqual(first['records_staged'],1)
        with cli.connect() as c:
            self.assertIsNone(c.execute('SELECT active_run_id FROM sources WHERE id=%s',(self.c['id'],)).fetchone()[0])
        promoted=real.promote(first['run_id'])
        self.assertEqual(promoted['status'],'complete')
        self.assertEqual(promoted['records_published'],1)
        self.assertEqual(real.stage(self.path,self.mapping)['status'],'unchanged')
        self.write([['a',self.plate,'202606','same'],['a',self.plate,'202606','same']])
        bad=real.stage(self.path,self.mapping)
        self.assertEqual(bad['full_duplicates'],1)
        self.assertEqual(real.promote(bad['run_id'])['status'],'blocked')
        with cli.connect() as c:
            self.assertEqual(c.execute('SELECT active_run_id FROM sources WHERE id=%s',(self.c['id'],)).fetchone()[0],first['run_id'])

    def test_duplicate_history_is_preserved_with_row_lineage(self):
        self.c.update(kind='ownership',key_mode='row_number',preserve_exact_events=True,max_unmatched_rate=1)
        row=['a',self.plate,'202606','same']
        self.write([row,row])
        staged=real.stage(self.path,self.mapping)
        self.assertEqual(staged['full_duplicates'],1)
        promoted=real.promote(staged['run_id'])
        self.assertEqual(promoted['status'],'complete')
        self.assertEqual(promoted['records_published'],2)

    @unittest.skipUnless(os.environ.get('RUN_QUARANTINE_VOLUME_TESTS')=='1','explicit optional 3-million-row quarantine boundary test')
    def test_audited_quarantine_within_budget_publishes(self):
        from importer import cli
        from importer.motpipe import rows as envelope_rows
        total=3000000
        self.c.update(kind='statuses',key_mode='row_number',max_unmatched_rate=1,dialect='mot_envelope_bytesbridge',dialect_verified=True,encoding='windows-1255',quarantine_policy={'max_records':3,'max_fraction':0.000001,'allowed_reasons':['decode_error']})
        with self.path.open('wb') as stream:
            stream.write(b'id|plate|date|raw\n')
            for index in range(total):
                value=b'\x9f' if index in (100,1000000,2999999) else 'שם'.encode('cp1255') if index==0 else b'v'
                stream.write(b'"'+str(index).encode()+b'"|"'+self.plate.encode()+b'"||"'+value+b'"\n')
        before=cli.digest(self.path)
        # Independent full structural audit: a unique explicit increasing source
        # ID in every full parsed record proves that no full rows are duplicates.
        count=0
        with self.path.open(encoding='latin1',newline='') as stream:
            reader=envelope_rows(stream);headers=next(reader)
            for index,values in enumerate(reader):
                self.assertEqual(values[0],str(index))
                count+=1
        self.assertEqual(count,total)
        audit={'status':'complete','scan_complete':True,'source_unchanged':True,'sha256':before,'records_read':count,'headers':headers,'duplicates':{'status':'complete','extra_rows':0}}
        audit_path=Path(self.temp.name)/'audit.json';audit_path.write_text(json.dumps(audit))
        self.c['full_audit_report']=str(audit_path)
        self.mapping.write_text(json.dumps(self.c))
        staged=real.stage(self.path,self.mapping)
        self.assertEqual(staged['status'],'staged')
        self.assertEqual(staged['records_read'],total)
        self.assertEqual(staged['records_rejected'],3)
        self.assertEqual(staged['records_staged'],total-3)
        self.assertTrue(staged['scan_complete'])
        self.assertTrue(staged['record_count_reliable'])
        self.assertTrue(staged['quarantine_policy_passed'])
        promoted=real.promote(staged['run_id'])
        self.assertEqual(promoted['status'],'complete')
        self.assertEqual(promoted['records_published'],total-3)
        self.assertEqual(promoted['published_coverage']['quarantined_records'],3)
        self.assertTrue(promoted['published_coverage']['partial'])
        self.assertEqual(cli.digest(self.path),before)
        with cli.connect() as c:
            self.assertEqual(c.execute('SELECT count(*) FROM rejected_rows WHERE run_id=%s',(staged['run_id'],)).fetchone()[0],3)
            self.assertEqual(c.execute('SELECT count(*) FROM statuses WHERE run_id=%s',(staged['run_id'],)).fetchone()[0],total-3)

    def test_undefined_bytes_above_policy_fail_without_source_mutation(self):
        from importer import cli
        self.c.update(dialect='mot_envelope_bytesbridge',dialect_verified=True,encoding='windows-1255',quarantine_policy={'max_records':3,'max_fraction':0.000001,'allowed_reasons':['decode_error']})
        self.path.write_bytes(b'id|plate|date|raw\n"1"|"'+self.plate.encode()+b'"|"202606"|"valid"\n"2"|"'+self.plate.encode()+b'"|"202606"|"\x9f"\n')
        before=cli.digest(self.path)
        audit={'status':'complete','scan_complete':True,'source_unchanged':True,'sha256':before,'records_read':2,'headers':list(self.c['fields']),'duplicates':{'status':'complete','extra_rows':0}}
        audit_path=Path(self.temp.name)/'audit.json';audit_path.write_text(json.dumps(audit))
        self.c['full_audit_report']=str(audit_path)
        self.mapping.write_text(json.dumps(self.c))
        failed=real.stage(self.path,self.mapping)
        self.assertEqual(failed['status'],'failed')
        self.assertEqual(failed['records_read'],2)
        self.assertEqual(failed['records_rejected'],1)
        self.assertTrue(failed['scan_complete'])
        self.assertFalse(failed['quarantine_policy_passed'])
        self.assertEqual(cli.digest(self.path),before)
        with self.assertRaises(ValueError):real.promote(failed['run_id'])

    def test_malformed_csv_never_publishes(self):
        with self.path.open('a',encoding='utf-8') as f:f.write('"unterminated')
        failed=real.stage(self.path,self.mapping)
        self.assertEqual(failed['status'],'failed')
        self.assertFalse(failed['scan_complete'])
        with self.assertRaises(ValueError):real.promote(failed['run_id'])


if __name__=='__main__':unittest.main()
