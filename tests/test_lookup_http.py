"""Live lookup regression: numbers remain private; output only test counts.
Requires RUN_LIVE_LOOKUP_TESTS=1, DATABASE_URL and a running live server.
"""
import json
import os
import unittest
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import urlopen

BASE = os.environ.get('E2E_BASE_URL', 'http://127.0.0.1:3000')


@unittest.skipUnless(os.environ.get('RUN_LIVE_LOOKUP_TESTS') == '1', 'requires explicit live lookup tests')
class LiveLookup(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import psycopg
        if not os.environ.get('DATABASE_URL'):
            raise RuntimeError('DATABASE_URL required')
        with psycopg.connect(os.environ['DATABASE_URL']) as conn:
            row = conn.execute("SELECT v.plate FROM live.vehicles v JOIN live.sources s ON s.id=v.source_id AND s.active_run_id=v.run_id WHERE s.id='mot-053cea08-09bc-40ec-8f7a-156f0677aff3' AND v.plate LIKE '0_______' AND substring(v.plate,2,1)<>'0' LIMIT 1").fetchone()
            if not row:
                raise RuntimeError('No existing padded registration available for lookup regression')
            cls.eight = row[0]
            cls.seven = cls.eight[1:]
            cls.missing = None
            for number in range(100):
                candidate = f'{number:08d}'
                queries = [f'SELECT 1 FROM live.{table} v JOIN live.sources s ON s.id=v.source_id AND s.active_run_id=v.run_id WHERE v.plate=%s' for table in ('vehicles','ownership','mileage','statuses','recalls')]
                exists = conn.execute('SELECT EXISTS(' + ' UNION ALL '.join(queries) + ')', (candidate,) * len(queries)).fetchone()[0]
                if not exists:
                    cls.missing = candidate
                    break
            if cls.missing is None:
                raise RuntimeError('No absent test key available')

    def get(self, plate):
        try:
            with urlopen(BASE + '/api/vehicles/' + quote(plate, safe=''), timeout=12) as response:
                return response.status, json.load(response)
        except HTTPError as error:
            with error:
                return error.code, json.load(error)

    @staticmethod
    def ids(body):
        return sorted((r['source_id'], r['run_id'], r['source_record_id']) for r in body['groups']['vehicles']['rows'])

    def test_eight_digit_exact_lookup(self):
        status, body = self.get(self.eight)
        self.assertEqual(status, 200)
        self.assertEqual(body['mode'], 'live')
        self.assertEqual(body['lookup']['kind'], 'exact')
        self.assertTrue(bool(self.ids(body)), 'Existing stored registration must be found')
        self.assertTrue(body['plate'] == self.eight, 'Requested registration must remain unchanged')

    def test_seven_digit_equivalence_preserves_source_identifiers(self):
        _, exact = self.get(self.eight)
        status, short = self.get(self.seven)
        self.assertEqual(status, 200)
        self.assertEqual(short['lookup']['kind'], 'zero_padded_8')
        self.assertTrue(short['lookup']['matched_plate'] == self.eight)
        self.assertTrue(short['plate'] == self.seven)
        self.assertTrue(self.ids(exact) == self.ids(short), 'Exact and verified alias must select the same source records')
        self.assertTrue(all(r['payload']['plate'] == self.eight for r in short['groups']['vehicles']['rows']), 'Stored plate text must not be rewritten')

    def test_formatted_seven_digit_input(self):
        formatted = self.seven[:2] + '-' + self.seven[2:5] + ' ' + self.seven[5:]
        status, body = self.get(formatted)
        self.assertEqual(status, 200)
        self.assertEqual(body['lookup']['kind'], 'zero_padded_8')
        self.assertTrue(bool(self.ids(body)))

    def test_absence_is_not_reported_as_global_quality_failure(self):
        status, body = self.get(self.missing)
        self.assertEqual(status, 200)
        self.assertEqual(body['groups']['vehicles']['state'], 'not_found')
        self.assertFalse(body['groups']['vehicles']['rows'])
        self.assertEqual(body['lookup']['kind'], 'not_found')
        self.assertTrue(any(s['state'] == 'quality_failed' for s in body['groups']['vehicles']['sources']), 'Per-source hold must remain visible independently of lookup absence')

    def test_invalid_does_not_trigger_alias_search(self):
        for value in ('123', '123456789', 'abcdefg'):
            status, _ = self.get(value)
            self.assertEqual(status, 400)


if __name__ == '__main__':
    unittest.main()
