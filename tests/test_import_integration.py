"""Real PostgreSQL import checks; runs only when TEST_DATABASE_URL is explicit."""
import csv
import json
import os
from pathlib import Path
import tempfile
import unittest
import uuid

from importer import cli


@unittest.skipUnless(os.environ.get('TEST_DATABASE_URL'), 'set TEST_DATABASE_URL to an isolated local PostgreSQL database')
class ImportIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ['DATABASE_URL'] = os.environ['TEST_DATABASE_URL']
        os.environ['DATA_MODE'] = 'demo'
        cli.migrate()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.source = 'test-' + uuid.uuid4().hex
        self.plate = str(20000000 + uuid.uuid4().int % 69000000)
        self.raw_plate = self.plate[:2] + '-' + self.plate[2:5] + ' ' + self.plate[5:]
        self.mapping = {
            'id': self.source, 'kind': 'vehicles', 'name': 'בדיקה סינתטית',
            'version': '1', 'verified': True, 'synthetic': True,
            'encoding': 'utf-8-sig', 'encoding_verified': True, 'delimiter': '|',
            'coverage': {'description': 'בדיקה סינתטית בלבד'},
            'keys': ['record_id'],
            'fields': {
                'id': {'target': 'record_id', 'required': True},
                'plate': {'target': 'plate', 'normalize': 'plate', 'required': True},
                'name': {'target': 'manufacturer'},
                'date': {'target': 'measured_at', 'type': 'month', 'precision': 'month'},
            },
        }
        self.mapping_path = self.folder / 'mapping.json'
        self.file = self.folder / 'source.csv'

    def tearDown(self):
        # Remove only this test's explicitly named synthetic source artifacts.
        os.environ['DATA_MODE'] = 'demo'
        with cli.connect() as conn:
            for table in ('vehicles', 'specs', 'ownership', 'mileage', 'statuses', 'recalls'):
                conn.execute(f'DELETE FROM {table} WHERE source_id=%s', (self.source,))
            for table in ('rejected_rows', 'staging'):
                conn.execute(f'DELETE FROM {table} WHERE run_id IN (SELECT id FROM import_runs WHERE source_id=%s)', (self.source,))
            conn.execute('DELETE FROM import_runs WHERE source_id=%s', (self.source,))
            conn.execute('DELETE FROM source_files WHERE source_id=%s', (self.source,))
            conn.execute('DELETE FROM sources WHERE id=%s AND synthetic=true', (self.source,))

    def write(self, rows, **changes):
        self.mapping.update(changes)
        self.mapping_path.write_text(json.dumps(self.mapping), encoding='utf-8')
        with self.file.open('w', encoding=self.mapping['encoding'], newline='') as stream:
            writer = csv.writer(stream, delimiter=self.mapping['delimiter'])
            writer.writerow(self.mapping['fields'])
            writer.writerows([[self.raw_plate if x == '08-888 888' else self.plate if x == '08888888' else str(int(self.plate)+1) if x == '08888889' else x for x in row] for row in rows])

    def run_import(self):
        return cli.import_file(self.file, self.mapping_path)

    def active(self):
        with cli.connect() as conn:
            return conn.execute('SELECT active_run_id FROM sources WHERE id=%s', (self.source,)).fetchone()[0]

    def test_multiline_bom_hebrew_missing_month_and_leading_zero(self):
        self.write([['a', '08-888 888', 'יצרן\nסינתטי', '2025-02'], ['b', '08888889', '', '']])
        result = self.run_import()
        self.assertEqual(result['status'], 'complete')
        self.assertEqual(result['records_read'], 2)
        self.assertEqual(result['missing_values'], 2)
        with cli.connect() as conn:
            payload = conn.execute("SELECT payload FROM vehicles WHERE run_id=%s AND payload->>'record_id'=%s", (result['run_id'], 'a')).fetchone()[0]
        self.assertEqual(payload['plate'], self.plate)
        self.assertEqual(payload['plate_original'], self.raw_plate)
        self.assertEqual(payload['measured_at'], '2025-02')
        self.assertEqual(payload['measured_at_precision'], 'month')
        self.assertEqual(payload['manufacturer'], 'יצרן\nסינתטי')

    def test_cp1255_comma_quotes(self):
        self.write([['a', '08888888', 'יצרן, סינתטי', '2025-03']], encoding='cp1255', delimiter=',')
        result = self.run_import()
        self.assertEqual(result['status'], 'complete')
        self.assertEqual(result['records_read'], 1)

    def test_idempotent_failed_quality_preserves_active_and_rollback(self):
        self.write([['a', '08888888', 'סינתטי', '2025-03']])
        first = self.run_import()
        repeated = self.run_import()
        self.assertEqual(repeated['status'], 'unchanged')
        self.assertEqual(first['run_id'], repeated['run_id'])
        self.write([['a', '08888888', 'א', '2025-03'], ['a', '08888888', 'ב', '2025-03']])
        failed = self.run_import()
        self.assertEqual(failed['status'], 'failed')
        self.assertGreaterEqual(failed['key_conflicts'], 1)
        self.assertEqual(self.active(), first['run_id'])
        self.write([['b', '08888888', 'עדכון', '2025-04']])
        second = self.run_import()
        self.assertEqual(second['status'], 'complete')
        self.assertEqual(self.active(), second['run_id'])
        cli.rollback(self.source, first['run_id'])
        self.assertEqual(self.active(), first['run_id'])

    def test_bad_encoding_is_incomplete_and_preserves_active(self):
        self.write([['a', '08888888', 'סינתטי', '2025-03']])
        first = self.run_import()
        with self.file.open('ab') as stream:
            stream.write(b'\xff\n')
        failed = self.run_import()
        self.assertEqual(failed['status'], 'failed')
        self.assertGreater(failed['decode_errors'], 0)
        self.assertEqual(self.active(), first['run_id'])

    def test_unknown_and_ambiguous_source_never_publishes(self):
        self.write([['a', '08888888', '', '']], kind='unknown')
        with self.assertRaises(ValueError):
            self.run_import()
        self.write([['a', '08888888', '', '']], kind='vehicles', verified=False)
        with self.assertRaises(ValueError):
            self.run_import()

    def test_synthetic_source_refused_in_live(self):
        self.write([['a', '08888888', '', '']])
        os.environ['DATA_MODE'] = 'live'
        try:
            with self.assertRaises(ValueError):
                self.run_import()
            with cli.connect() as conn:
                self.assertEqual(conn.execute('SELECT count(*) FROM sources WHERE id=%s', (self.source,)).fetchone()[0], 0)
        finally:
            os.environ['DATA_MODE'] = 'demo'

    def test_full_duplicates_counted_by_parser(self):
        row = ['a', '08888888', 'סינתטי\nדגם', '2025-03']
        self.write([row, row])
        result = self.run_import()
        self.assertEqual(result['records_read'], 2)
        self.assertEqual(result['full_duplicates'], 1)
        self.assertEqual(result['status'], 'failed')


if __name__ == '__main__':
    unittest.main()
