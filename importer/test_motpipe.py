import io
import unittest
from importer.motpipe import rows

class MOTEnvelopeTests(unittest.TestCase):
    def parse(self,text):return list(rows(io.StringIO(text)))
    def test_literal_internal_quote_and_bare_empty(self):
        self.assertEqual(self.parse('id|label|blank\n"001"|"עברית ל"ס"|\n'),[['id','label','blank'],['001','עברית ל"ס','']])
    def test_embedded_pipe_preserved(self):
        self.assertEqual(self.parse('id|label\n"001"|"a|b"\n')[1],['001','a|b'])
    def test_embedded_newline_inside_envelope(self):
        self.assertEqual(self.parse('id|label\n"001"|"שורה\nנוספת"\n')[1],['001','שורה\nנוספת'])
    def test_reject_width_and_unquoted_cells(self):
        for text in ['id|label\n"1"|"x"|"extra"\n','id|label\n"1"|bare\n','id|label\n"1"\n']:
            with self.subTest(text=text),self.assertRaises(ValueError):self.parse(text)
    def test_reject_unterminated_or_unbounded(self):
        with self.assertRaises(ValueError):self.parse('id|label\n"1"|"open\n')
        with self.assertRaises(ValueError):list(rows(io.StringIO('id\n"123456"\n'),max_record_chars=4))

if __name__=='__main__':unittest.main()
