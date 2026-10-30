"""Additional import safety tests against explicit isolated TEST_DATABASE_URL."""
import csv
import json
import os
from pathlib import Path
import tempfile
import unittest
import uuid
from unittest.mock import patch
from importer import cli

@unittest.skipUnless(os.environ.get('TEST_DATABASE_URL'), 'requires isolated TEST_DATABASE_URL')
class PublicationSafety(unittest.TestCase):
    def setUp(self):
        self.env=patch.dict(os.environ,{'DATABASE_URL':os.environ['TEST_DATABASE_URL'],'DATA_MODE':'demo'})
        self.env.start();self.addCleanup(self.env.stop)
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.folder=Path(self.temp.name)
        self.config=json.loads((cli.ROOT/'mappings/synthetic-statuses.json').read_text())
        self.config['id']='audit-'+uuid.uuid4().hex
        self.addCleanup(self.cleanup_source)
        self.config['required_sources']=[]
        self.config['max_unmatched_rate']=1
        self.mapping=self.folder/'mapping.json';self.file=self.folder/'data.csv'
        self.write([['a','09999999','מצב סינתטי','2025-01']])

    def cleanup_source(self):
        with cli.connect() as conn:
            source = self.config['id']
            conn.execute('DELETE FROM statuses WHERE source_id=%s', (source,))
            conn.execute('DELETE FROM staging WHERE run_id IN (SELECT id FROM import_runs WHERE source_id=%s)', (source,))
            conn.execute('DELETE FROM rejected_rows WHERE run_id IN (SELECT id FROM import_runs WHERE source_id=%s)', (source,))
            conn.execute('UPDATE sources SET active_run_id=NULL WHERE id=%s', (source,))
            conn.execute('DELETE FROM import_runs WHERE source_id=%s', (source,))
            conn.execute('DELETE FROM source_files WHERE source_id=%s', (source,))
            conn.execute('DELETE FROM sources WHERE id=%s', (source,))

    def write(self,rows):
        self.mapping.write_text(json.dumps(self.config),encoding='utf-8')
        with self.file.open('w',encoding='utf-8-sig',newline='') as f:
            writer=csv.writer(f,delimiter='|');writer.writerow(self.config['fields']);writer.writerows(rows)

    def active(self):
        with cli.connect() as conn:return conn.execute('SELECT active_run_id FROM sources WHERE id=%s',(self.config['id'],)).fetchone()[0]

    def test_required_source_missing_preserves_active(self):
        first=cli.import_file(self.file,self.mapping)
        self.config['required_sources']=['unloaded-'+uuid.uuid4().hex]
        self.write([['b','09999999','עדכון סינתטי','2025-02']])
        failed=cli.import_file(self.file,self.mapping)
        self.assertEqual(failed['status'],'failed')
        self.assertTrue(failed['scan_complete'])
        self.assertEqual(failed['records_published'],0)
        self.assertEqual(self.active(),first['run_id'])

    def test_advisory_lock_blocks_competitor_preserves_active(self):
        first=cli.import_file(self.file,self.mapping)
        self.write([['b','09999999','עדכון סינתטי','2025-02']])
        with cli.connect() as other:
            other.execute('SELECT pg_advisory_lock(87301826)')
            try:
                with self.assertRaisesRegex(ValueError,'Another import'):
                    cli.import_file(self.file,self.mapping)
            finally:other.execute('SELECT pg_advisory_unlock(87301826)')
        self.assertEqual(self.active(),first['run_id'])

    def test_structural_error_has_partial_counts_and_no_publication(self):
        with self.file.open('a',encoding='utf-8') as f:f.write('"unterminated\n')
        failed=cli.import_file(self.file,self.mapping)
        self.assertEqual(failed['status'],'failed')
        self.assertFalse(failed['scan_complete'])
        self.assertFalse(failed['record_count_reliable'])
        self.assertEqual(failed['records_parsed_valid'],1)
        self.assertEqual(failed['records_staged'],0)
        self.assertEqual(failed['records_accepted'],0)
        self.assertEqual(failed['records_published'],0)
        self.assertIsNone(self.active())

if __name__=='__main__':unittest.main()
