"""HTTP integration checks; requires a running app with the synthetic demo loaded."""
import json
import os
import unittest
from urllib.error import HTTPError
from urllib.request import urlopen

BASE = os.environ.get('E2E_BASE_URL', 'http://127.0.0.1:3000')
PLATE = os.environ.get('E2E_PLATE', '01234567')


class APIIntegration(unittest.TestCase):
    def get(self, plate):
        try:
            with urlopen(f'{BASE}/api/vehicles/{plate}', timeout=10) as response:
                return response.status, json.load(response)
        except HTTPError as error:
            with error:
                return error.code, json.load(error)

    def test_full_report_and_separate_collections(self):
        status, report = self.get(PLATE)
        self.assertEqual(status, 200)
        self.assertEqual(report['plate'], PLATE)
        self.assertEqual(report['mode'], 'demo')
        for group in ('vehicles', 'specs', 'ownership', 'mileage', 'statuses', 'recalls'):
            self.assertIn(group, report['groups'])
            self.assertIsInstance(report['groups'][group]['rows'], list)
            self.assertIsInstance(report['groups'][group]['sources'], list)
        self.assertGreaterEqual(len(report['groups']['ownership']['rows']), 2)
        self.assertGreaterEqual(len(report['groups']['recalls']['rows']), 2)
        self.assertEqual(len(report['groups']['vehicles']['rows']), 1)

    def test_normalization_and_leading_zero(self):
        status, report = self.get(f'{PLATE[:2]}-{PLATE[2:]}')
        self.assertEqual(status, 200)
        self.assertEqual(report['plate'], PLATE)

    def test_invalid_input(self):
        for plate in ('123', '123456789', 'abcdefg', '1234567%27'):
            with self.subTest(plate=plate):
                self.assertEqual(self.get(plate)[0], 400)

    def test_absence_is_not_a_clean_bill_of_health(self):
        status, report = self.get('99999999')
        self.assertIn(status, (200, 404))
        serialized = json.dumps(report, ensure_ascii=False)
        for unsupported_claim in ('אין תאונות', 'אין שעבודים', 'הרכב תקין'):
            self.assertNotIn(unsupported_claim, serialized)
        if status == 200:
            self.assertEqual(report['groups']['vehicles']['rows'], [])


if __name__ == '__main__':
    unittest.main()
