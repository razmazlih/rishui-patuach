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

if __name__=='__main__':unittest.main()
