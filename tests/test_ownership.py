import unittest
from importer.ownership_period import ownership_quarter,derive_ownership
from importer.real import transform

class OwnershipPeriod(unittest.TestCase):
    def test_all_months_map_to_quarters(self):
        for month in range(1,13):
            self.assertEqual(ownership_quarter(f'2024{month:02d}'),f'2024-Q{(month-1)//3+1}')
    def test_no_invented_day_or_end(self):
        original={'ownership_date_raw':'202402','ownership_type':'סינתטי'}
        config={'kind':'ownership','derived_fields':{'ownership_period':{'source':'ownership_date_raw','transform':'ownership_quarter'}}}
        result=derive_ownership(dict(original),config)
        self.assertEqual(result['ownership_date_raw'],'202402')
        self.assertEqual(result['ownership_period'],'2024-Q1')
        self.assertEqual(result['ownership_period_precision'],'quarter')
        self.assertNotIn('start_date',result);self.assertNotIn('end_date',result)
    def test_invalid_never_guessed(self):
        for value in ('000001','202400','202413','2024-02','20240201','garbage'):
            with self.assertRaises(ValueError):ownership_quarter(value)
    def test_missing_stays_unknown(self):
        self.assertIsNone(ownership_quarter(None));self.assertIsNone(ownership_quarter(''))
    def test_record_identity_and_plate_preserved(self):
        c={'kind':'ownership','key_mode':'row_number','fields':{'p':{'target':'plate','normalize':'plate'},'d':{'target':'ownership_date_raw'},'t':{'target':'ownership_type'}},'derived_fields':{'ownership_period':{'source':'ownership_date_raw','transform':'ownership_quarter'}}}
        key,payload,_=transform({'p':'01234567','d':'202402','t':'סינתטי'},c,18)
        self.assertEqual(key,'18');self.assertEqual(payload['plate'],'01234567');self.assertEqual(payload['plate_original'],'01234567')
        self.assertEqual(payload['ownership_period'],'2024-Q1')

if __name__=='__main__':unittest.main()
