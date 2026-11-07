"""Policy rejection regressions; synthetic suites/worker only, no model or real ledger."""
import contextlib
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from automation.trusted_tests import validate, main


class PolicyNegativeTests(unittest.TestCase):
    def check_names(self, actual, expected):
        class Named(unittest.TestCase):
            def __init__(self, name):super().__init__();self.name=name
            def id(self):return self.name
        suite=unittest.TestSuite([Named(name) for name in actual])
        with patch('automation.trusted_tests.unittest.defaultTestLoader.discover', return_value=suite):
            with self.assertRaises(ValueError):
                validate(Path('.'), {'baseline_files':{},'tests':expected})

    def test_missing_name(self):self.check_names(['a'], ['a','b'])
    def test_extra_name(self):self.check_names(['a','b'], ['a'])
    def test_renamed_same_count(self):self.check_names(['a','renamed'], ['a','b'])
    def test_duplicate_discovered(self):self.check_names(['a','a'], ['a'])
    def test_duplicate_manifest(self):self.check_names(['a'], ['a','a'])

    def test_removed_original_baseline(self):
        with self.assertRaises(ValueError):
            validate(Path('.'), {'baseline_tests':['original'],'baseline_files':{},'tests':['replacement']})

    def test_run_count_mismatch(self):
        self.check_runner(unittest.TestSuite(), ['missing'])

    def check_runner(self, suite, names):
        with patch('sys.argv',['runner',str(Path.cwd()),'{}']), patch('automation.trusted_tests.validate',return_value=(suite,names)), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main(),1)

    def test_expected_failure(self):
        class Expected(unittest.TestCase):
            @unittest.expectedFailure
            def runTest(self):self.fail('synthetic')
        self.check_runner(unittest.TestSuite([Expected()]), ['expected'])

    def test_skipped(self):
        class Skipped(unittest.TestCase):
            def runTest(self):self.skipTest('synthetic')
        self.check_runner(unittest.TestSuite([Skipped()]), ['skipped'])

    def pipeline(self, log=None, exit_failure=False):
        from test_automation import AutomationTest
        AutomationTest('test_simulated_issue_model_tests_pr_feedback').pipeline(test_log=log,test_exit=exit_failure)

    def record(self, **changes):
        policy=json.loads(Path('automation/test_manifest.json').read_text())
        r={'success':True,'count':len(policy['tests']),'tests':sorted(policy['tests'])};r.update(changes)
        return 'CF_TEST_RESULT '+json.dumps(r)+'\n'

    def test_parent_process_failure_never_publishes(self):self.pipeline(exit_failure=True)
    def test_multiple_results_never_publish(self):self.pipeline(self.record()*2)
    def test_no_result_never_publishes(self):self.pipeline('Ran 999 tests\nOK\n')
    def test_wrong_count_never_publishes(self):self.pipeline(self.record(count=1))
    def test_same_count_wrong_names_never_publish(self):
        policy=json.loads(Path('automation/test_manifest.json').read_text());names=sorted(policy['tests']);names[0]='renamed'
        self.pipeline(self.record(tests=names))
    def test_failed_result_never_publishes(self):self.pipeline(self.record(success=False))
    def test_malformed_result_never_publishes(self):self.pipeline('CF_TEST_RESULT {invalid}\n')
