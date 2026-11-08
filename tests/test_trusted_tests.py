import json
from pathlib import Path
import tempfile
import unittest
from automation.trusted_tests import validate

class TrustedTests(unittest.TestCase):
    def test_empty_collection_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'tests').mkdir();(root/'tests/__init__.py').touch()
            with self.assertRaises(ValueError):validate(root,{'baseline_files':{},'tests':[]})

    def test_baseline_tamper_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'test.py').write_text('changed')
            with self.assertRaises(ValueError):validate(root,{'baseline_files':{'test.py':'wrong'},'tests':[]})

    def test_names_and_failure_result(self):
        import contextlib
        import io
        from unittest.mock import patch
        from automation.trusted_tests import main
        for outcome, expected in [('failure', 1), ('skip', 1), ('success', 0)]:
            class Synthetic(unittest.TestCase):
                def runTest(self):
                    if outcome == 'failure':self.fail('synthetic failure')
                    if outcome == 'skip':self.skipTest('synthetic skip')
            suite=unittest.TestSuite([Synthetic()])
            output=io.StringIO()
            with patch('sys.argv', ['runner', str(Path.cwd()), '{}']), patch('automation.trusted_tests.validate', return_value=(suite, ['synthetic'])), contextlib.redirect_stdout(output), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(main(), expected)
            record=json.loads(output.getvalue().split('CF_TEST_RESULT ')[1])
            self.assertEqual(record['success'], expected == 0)
            self.assertEqual(record['count'], 1)
