import csv
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from importer.cli import convert, inspect, load_mapping, write_report

ROOT = Path(__file__).resolve().parents[1]

class ParserTests(unittest.TestCase):
    def test_pipe_bom_multiline(self):
        result=inspect(ROOT/'tests/fixtures/vehicles.csv','utf-8-sig','|')
        self.assertEqual(result['sample_records'],2)
        self.assertEqual(result['status'],'sampled')
        self.assertEqual(result['headers'][0],'record_id')

    def test_cp1255_comma(self):
        result=inspect(ROOT/'tests/fixtures/ownership.csv','windows-1255',',')
        self.assertEqual(result['status'],'sampled')
        with open(ROOT/'tests/fixtures/ownership.csv',encoding='windows-1255',newline='') as f:
            self.assertEqual(next(csv.DictReader(f))['ownership_type'],'השכרה')

    def test_tab_quoted_multiline(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'tab.csv';p.write_text('id\tvalue\n1\t"hello\nworld"\n',encoding='utf-8')
            self.assertEqual(inspect(p,'utf-8','\t')['sample_records'],1)

    def test_implicit_encoding_requires_verification(self):
        self.assertTrue(inspect(ROOT/'tests/fixtures/vehicles.csv')['encoding_requires_verification'])

    def test_explicit_encoding_still_requires_content_verification(self):
        result=inspect(ROOT/'tests/fixtures/ownership.csv','windows-1255',',')
        self.assertTrue(result['encoding_selection_explicit'])
        self.assertTrue(result['requires_content_verification'])
        self.assertTrue(result['encoding_requires_verification'])

    def test_unicode_digits_and_noncanonical_dates_refused(self):
        with patch.dict(os.environ,{'DATA_MODE':'demo'}):
            c=load_mapping(ROOT/'mappings/synthetic-vehicles.json')
        with open(ROOT/'tests/fixtures/vehicles.csv',encoding='utf-8-sig',newline='') as f:
            row=next(csv.DictReader(f,delimiter='|'))
        row['plate']='٠١٢٣٤٥٦٧'
        with self.assertRaises(ValueError):convert(row,c)
        row['plate']='01234567';row['license_valid_until']='20270601'
        with self.assertRaises(ValueError):convert(row,c)

    def test_decoding_error_not_ignored(self):
        self.assertEqual(inspect(ROOT/'tests/fixtures/ownership.csv','utf-8',',')['status'],'failed')

    def test_leading_zero_month_and_missing(self):
        with patch.dict(os.environ,{'DATA_MODE':'demo'}):
            c=load_mapping(ROOT/'mappings/synthetic-vehicles.json')
        with open(ROOT/'tests/fixtures/vehicles.csv',encoding='utf-8-sig',newline='') as f:
            row=next(csv.DictReader(f,delimiter='|'))
        row['plate']='0 123-4567';row['color']=''
        _,payload,missing=convert(row,c)
        self.assertEqual(payload['plate'],'01234567')
        self.assertEqual(payload['plate_original'],'0 123-4567')
        self.assertEqual(payload['last_test'],'2026-06')
        self.assertEqual(payload['last_test_precision'],'month')
        self.assertIsNone(payload['color'])
        self.assertEqual(missing,1)

    def test_synthetic_live_refused(self):
        with patch.dict(os.environ,{'DATA_MODE':'live'}), self.assertRaises(ValueError):
            load_mapping(ROOT/'mappings/synthetic-vehicles.json')

    def test_report_cannot_overwrite_source(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / 'source.csv'
            source.write_text('original', encoding='utf-8')
            with self.assertRaises(FileExistsError):
                write_report({'status': 'sampled'}, source)
            self.assertEqual(source.read_text(), 'original')

    def test_composite_not_guessed(self):
        with patch.dict(os.environ,{'DATA_MODE':'demo'}):
            c=load_mapping(ROOT/'mappings/synthetic-specs.json')
        with open(ROOT/'tests/fixtures/specs.csv',encoding='utf-8-sig',newline='') as f:
            row=next(csv.DictReader(f,delimiter='|'))
        self.assertIsNotNone(convert(row,c))
        row['spec_key']='model-name'
        with self.assertRaises(ValueError):convert(row,c)

if __name__=='__main__':unittest.main()
