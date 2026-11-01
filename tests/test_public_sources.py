import unittest
from scripts.reconcile_public import conflict_fields

class PublicSourceRules(unittest.TestCase):
    def test_complementary_fields_are_not_conflicts(self):
        self.assertEqual(conflict_fields({'plate':'01234567','year':'2020','color':None},{'plate':'01234567','year':'2020','color':'blue','model':'test'}),[])
    def test_actual_disagreement_retains_both_field_values(self):
        left={'plate':'01234567','model':'source model A','year':'2020'}
        right={'plate':'01234567','model':'source model B','year':'2020'}
        self.assertEqual(conflict_fields(left,right),['model'])
        self.assertEqual(left['model'],'source model A')
        self.assertEqual(right['model'],'source model B')
    def test_original_plate_metadata_is_not_a_vehicle_fact_conflict(self):
        self.assertEqual(conflict_fields({'plate_original':'01-234567','year':'2020'},{'plate_original':'01234567','year':'2020'}),[])


# Read-only live checks are opt-in and never expose registration values.
import json
import os
from pathlib import Path

@unittest.skipUnless(os.environ.get('RUN_PUBLIC_SOURCE_TESTS')=='1','explicit live data check required')
class PublicSourceDatabase(unittest.TestCase):
    def test_published_profile_snapshot_preserves_original_staging(self):
        import psycopg
        root=Path(__file__).resolve().parents[1]
        evidence=json.loads((root/'data/reports/public-registry-activation.json').read_text())
        audit=json.loads((root/'data/reports/public-registry-reconciliation.json').read_text())
        with psycopg.connect(os.environ['DATABASE_URL']) as db:
            active=db.execute("SELECT active_run_id,availability,coverage->>'plate_lookup_run_id' FROM live.sources WHERE id=%s",(evidence['source'],)).fetchone()
            self.assertEqual(active[0],evidence['run_id'])
            self.assertEqual(active[1],'available')
            self.assertEqual(active[2],str(evidence['run_id']))
            matched=db.execute('SELECT count(*) FROM live.vehicles v JOIN live.staging s ON s.source_record_id=v.source_record_id AND s.run_id=%s WHERE v.run_id=%s AND v.source_id=%s AND v.payload=s.payload AND v.plate=s.plate',(audit['run_id'],evidence['run_id'],evidence['source'])).fetchone()[0]
            self.assertEqual(matched,evidence['records_published'])
    def test_archive_lookup_configuration_is_bound_to_audited_runs(self):
        import psycopg
        root=Path(__file__).resolve().parents[1]
        audit=json.loads((root/'data/reports/archive-lookup-audit.json').read_text())
        with psycopg.connect(os.environ['DATABASE_URL']) as db:
            for source in audit['sources']:
                result=db.execute("SELECT active_run_id,coverage->>'plate_lookup_run_id',coverage->>'plate_lookup_format' FROM live.sources WHERE id=%s",(source['source_id'],)).fetchone()
                self.assertEqual(result,(source['active_run_id'],str(source['active_run_id']),'zero_padded_8'))

if __name__=='__main__':unittest.main()
