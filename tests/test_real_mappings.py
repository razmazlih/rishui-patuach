"""Structural contract tests for tracked mappings. No raw datasets are read."""
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch
from importer.real import mapping_file

MAPPINGS=Path(__file__).resolve().parents[1]/'mappings/real'


class RealMappingContracts(unittest.TestCase):
    def test_all_sixteen_verified_structural_mappings_validate(self):
        paths=list(MAPPINGS.glob('*.json'))
        self.assertEqual(len(paths),16)
        with patch.dict(os.environ,{'DATA_MODE':'live'}):
            for path in paths:
                with self.subTest(source=path.name):
                    config=mapping_file(path)
                    self.assertTrue(config['verification']['full_validation_required'])
                    self.assertIsNone(config['coverage']['as_of'])

    def test_codes_are_text_and_spec_join_not_guessed(self):
        for path in MAPPINGS.glob('*.json'):
            c=json.loads(path.read_text())
            for rule in c['fields'].values():
                if rule.get('target','').endswith('_code') or rule.get('target') in ('year','model_type'):
                    self.assertEqual(rule['type'],'text')
            if c['kind']=='vehicles':
                self.assertNotIn('composite_key_fields',c)

    def test_ownership_date_is_raw_and_display_uses_verified_quarter(self):
        c=json.loads((MAPPINGS/'bb2355dc-9ec7-4f06-9c3f-3344672171da.json').read_text())
        self.assertEqual(c['fields']['baalut_dt']['target'],'ownership_date_raw')
        self.assertEqual(c['fields']['baalut_dt']['type'],'text')
        self.assertNotIn('baalut_dt_semantics_unverified',c['publication_hold'])
        self.assertEqual(c['derived_fields']['ownership_period']['source'],'ownership_date_raw')
        self.assertEqual(c['derived_fields']['ownership_period']['transform'],'ownership_quarter')
        self.assertTrue(c['derived_fields']['ownership_period']['evidence_url'].startswith('https://www.gov.il/'))
        self.assertEqual(c['verification']['ownership_period_evidence'],'docs/OWNERSHIP.md')
        self.assertEqual(c['coverage']['ownership_period_precision'],'quarter')
        self.assertTrue(c['preserve_exact_events'])
        self.assertEqual(c['key_mode'],'row_number')

    def test_undated_mileage_has_no_invented_measurement_date(self):
        c=json.loads((MAPPINGS/'56063a99-8a3e-4ff4-912e-5966c0279bad.json').read_text())
        targets={r.get('target') for r in c['fields'].values()}
        self.assertIn('kilometers',targets)
        self.assertNotIn('measured_at',targets)
        self.assertNotIn('measurement_date',targets)

    def test_catalog_not_misclassified_as_plate_recall(self):
        c=json.loads((MAPPINGS/'2c33523f-87aa-44ec-a736-edbb0a82975e.json').read_text())
        self.assertEqual(c['kind'],'recall_catalog')
        self.assertNotIn('plate',{r.get('target') for r in c['fields'].values()})


if __name__=='__main__':unittest.main()
