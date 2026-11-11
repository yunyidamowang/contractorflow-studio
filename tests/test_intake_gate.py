"""Static and simulated checks for the intake gate report. No GitHub or model calls."""
import hashlib
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / '.github/workflows/codex-intake.yml'
CI_WORKFLOW = ROOT / '.github/workflows/ci.yml'
INTAKE_IF = (
    "github.repository == 'yunyidamowang/contractorflow-studio' && "
    "vars.CF_INTAKE_ENABLED == 'true' && vars.CF_AUTOMATION_STOP != 'true' && "
    "github.event.label.name == 'codex-ready'"
)
INTAKE_JOB_SHA256 = 'f172cef8bb535760fe77d1c8d2c9afade205fe357e0e17b18de6db8d2c695aaa'
CI_SHA256 = '4576223a294403ed8e15536941da5d73110c9f157bbf1bc3a008872dce62260d'
WRITE_API = (
    'createComment', 'github.rest', 'octokit', 'pull_request_target', 'curl', 'wget',
    'api.github.com', 'addLabels', 'removeLabel', 'setLabels', 'GITHUB_TOKEN',
    'issues.create', 'issues.update', 'issues.delete', 'writeFileSync',
)


def workflow():
    return json.loads(WORKFLOW.read_text())


def report_script(data=None):
    run = (data or workflow())['jobs']['gate-report']['steps'][0]['run']
    marker = "<<'CF_GATE_REPORT'\n"
    start = run.index(marker) + len(marker)
    return run[start:run.rindex('\nCF_GATE_REPORT')]


def passing_env(**overrides):
    env = {
        'GATE_REPOSITORY': 'true',
        'GATE_INTAKE_ENABLED': 'true',
        'GATE_STOP_CLEAR': 'true',
        'GATE_LABEL': 'true',
        'GATE_ISSUE_OPEN': 'true',
        'GATE_NOT_PULL_REQUEST': 'true',
        'ACTOR': 'owner',
        'AUTHOR': 'owner',
        'ALLOWED_ACTORS': '["owner"]',
        'LABEL_NAMES': '["codex-ready"]',
    }
    env.update(overrides)
    return env


def execute(env):
    with tempfile.TemporaryDirectory() as temp:
        directory = Path(temp)
        script_path = directory / 'report.cjs'
        summary_path = directory / 'summary.md'
        script_path.write_text(report_script())
        proc = subprocess.run(
            ['node', str(script_path)],
            capture_output=True,
            text=True,
            env={'PATH': os.environ['PATH'], 'GITHUB_STEP_SUMMARY': str(summary_path), **env},
            check=False,
        )
        summary = summary_path.read_text() if summary_path.exists() else ''
        return proc.returncode, proc.stdout, proc.stderr, summary


class IntakeGateTests(unittest.TestCase):
    def assert_report(self, env, intake_job, intake_blocked, registration, registration_blocked, unknown, absent=()):
        code, stdout, stderr, summary = execute(env)
        self.assertEqual(code, 0, stderr)
        self.assertEqual(stderr, '')
        self.assertTrue(stdout.startswith(summary), stdout)
        self.assertNotIn('::', summary)
        self.assertIn('intake_job: ' + intake_job, summary)
        self.assertIn('intake_blocked: ' + (','.join(intake_blocked) or 'none'), summary)
        self.assertIn('registration_precheck: ' + registration, summary)
        self.assertIn('registration_blocked: ' + (','.join(registration_blocked) or 'none'), summary)
        self.assertIn('unknown: ' + (','.join(unknown) or 'none'), summary)
        for secret in absent:
            self.assertNotIn(secret, stdout)
            self.assertNotIn(secret, summary)
        codes = intake_blocked + registration_blocked
        if intake_blocked:
            self.assertIn('::warning title=Intake job skipped::' + ','.join(codes) + '\n', stdout)
        elif registration_blocked:
            self.assertIn('::warning title=Intake registration blocked::' + ','.join(codes) + '\n', stdout)
        elif unknown:
            self.assertIn('::warning title=Intake gate unknown::' + ','.join(unknown) + '\n', stdout)
        else:
            self.assertIn('::notice title=Intake gates clear::no blocking intake condition\n', stdout)
            self.assertNotIn('::warning', stdout)
        return summary

    def test_workflow_gates_permissions_and_ci_bytes(self):
        data = workflow()
        self.assertEqual(data['on'], {'issues': {'types': ['labeled']}})
        self.assertNotIn('pull_request_target', json.dumps(data))
        self.assertEqual(data['permissions'], {'issues': 'read'})
        self.assertEqual(data['jobs']['intake']['if'], INTAKE_IF)
        self.assertEqual(data['jobs']['intake']['permissions'], {'issues': 'write'})
        self.assertEqual(hashlib.sha256(json.dumps(data['jobs']['intake'], sort_keys=True).encode()).hexdigest(), INTAKE_JOB_SHA256)
        intake_script = data['jobs']['intake']['steps'][0]['with']['script']
        self.assertIn("!actors.includes(context.actor)", intake_script)
        self.assertIn("!actors.includes(issue.user.login)", intake_script)
        self.assertIn("x.name === 'codex-stop'", intake_script)
        self.assertIn("x.name === 'codex-ready'", intake_script)
        report = data['jobs']['gate-report']
        self.assertNotIn('if', report)
        self.assertEqual(report['permissions'], {})
        self.assertEqual(report['runs-on'], 'ubuntu-latest')
        self.assertLessEqual(report['timeout-minutes'], 2)
        self.assertEqual(len(report['steps']), 1)
        self.assertNotIn('uses', report['steps'][0])
        env = report['steps'][0]['env']
        clauses = [
            env['GATE_REPOSITORY'][4:-3],
            env['GATE_INTAKE_ENABLED'][4:-3],
            env['GATE_STOP_CLEAR'][4:-3],
            env['GATE_LABEL'][4:-3],
        ]
        self.assertEqual(' && '.join(clauses), INTAKE_IF)
        blob = json.dumps(report)
        for banned in WRITE_API:
            self.assertNotIn(banned, blob)
        self.assertNotIn('actions/checkout', blob)
        for uses in (data['jobs']['intake']['steps'][0]['uses'], data['jobs']['intake']['steps'][1]['uses']):
            self.assertRegex(uses, r'^actions/github-script@[0-9a-f]{40}$')
        self.assertEqual(hashlib.sha256(CI_WORKFLOW.read_bytes()).hexdigest(), CI_SHA256)

    def test_disabled_intake_is_named(self):
        summary = self.assert_report(
            passing_env(GATE_INTAKE_ENABLED='false'),
            'skipped', ['intake_disabled'], 'clear', [], [])
        self.assertIn('- intake_enabled: blocked', summary)
        self.assertIn('- automation_stop_clear: passed', summary)
        self.assertIn('- event_label_is_codex_ready: passed', summary)

    def test_wrong_label_is_named_without_echoing_it(self):
        summary = self.assert_report(
            passing_env(GATE_LABEL='false', LABEL_NAMES='["ZZ-SENTINEL-LABEL"]'),
            'skipped', ['wrong_label'], 'blocked', ['ready_label_missing'], [],
            absent=('ZZ-SENTINEL-LABEL',))
        self.assertIn('- event_label_is_codex_ready: blocked', summary)
        self.assertIn('- ready_label_present: blocked', summary)
        self.assertIn('- stop_label_absent: passed', summary)

    def test_wrong_actor_and_author_are_named(self):
        summary = self.assert_report(
            passing_env(ACTOR='ZZ-SENTINEL-ACTOR', AUTHOR='ZZ-SENTINEL-AUTHOR', ALLOWED_ACTORS='["owner"]'),
            'runs', [], 'blocked', ['wrong_actor', 'wrong_author'], [],
            absent=('ZZ-SENTINEL-ACTOR', 'ZZ-SENTINEL-AUTHOR', '["owner"]'))
        self.assertIn('- actor_allowlisted: blocked', summary)
        self.assertIn('- author_allowlisted: blocked', summary)
        self.assertIn('- allowlist_configured: passed', summary)

    def test_stop_label_is_named(self):
        summary = self.assert_report(
            passing_env(LABEL_NAMES='["codex-ready","codex-stop"]'),
            'runs', [], 'blocked', ['stop_label_present'], [])
        self.assertIn('- stop_label_absent: blocked', summary)
        self.assertIn('- event_label_is_codex_ready: passed', summary)

    def test_stop_variable_and_wrong_repository_are_named(self):
        summary = self.assert_report(
            passing_env(GATE_REPOSITORY='false', GATE_STOP_CLEAR='false'),
            'skipped', ['wrong_repository', 'automation_stop'], 'clear', [], [])
        self.assertIn('- repository_matches: blocked', summary)
        self.assertIn('- automation_stop_clear: blocked', summary)
        self.assertNotIn('ZZ-SECRET-STOP', summary)

    def test_closed_issue_and_pull_request_are_named(self):
        self.assert_report(
            passing_env(GATE_ISSUE_OPEN='false', GATE_NOT_PULL_REQUEST='false'),
            'runs', [], 'blocked', ['issue_not_open', 'pull_request'], [])

    def test_multiple_blockers_omit_raw_values(self):
        summary = self.assert_report(
            passing_env(
                GATE_REPOSITORY='false',
                GATE_INTAKE_ENABLED='false',
                GATE_STOP_CLEAR='false',
                GATE_LABEL='false',
                GATE_ISSUE_OPEN='false',
                GATE_NOT_PULL_REQUEST='false',
                ACTOR='ZZ-SENTINEL-ACTOR',
                AUTHOR='owner',
                ALLOWED_ACTORS='["owner","ZZ-SECRET-ALLOW"]',
                LABEL_NAMES='["ZZ-SENTINEL-LABEL","codex-stop"]',
                CF_INTAKE_ENABLED='ZZ-SECRET-ENABLED',
                CF_AUTOMATION_STOP='ZZ-SECRET-STOP',
            ),
            'skipped',
            ['wrong_repository', 'intake_disabled', 'automation_stop', 'wrong_label'],
            'blocked',
            ['wrong_actor', 'stop_label_present', 'ready_label_missing', 'issue_not_open', 'pull_request'],
            [],
            absent=('ZZ-SENTINEL-ACTOR', 'ZZ-SENTINEL-LABEL', 'ZZ-SECRET-ALLOW', 'ZZ-SECRET-ENABLED', 'ZZ-SECRET-STOP', '["owner","ZZ-SECRET-ALLOW"]'),
        )
        self.assertIn('- author_allowlisted: passed', summary)

    def test_clear_gates_have_no_warning(self):
        summary = self.assert_report(passing_env(), 'runs', [], 'clear', [], [], absent=('owner',))
        conditions = [line for line in summary.split('## Conditions\n', 1)[1].splitlines() if line]
        self.assertTrue(conditions)
        self.assertTrue(all(line.endswith(': passed') for line in conditions))

    def test_unreadable_inputs_stay_unknown(self):
        summary = self.assert_report(
            {'ALLOWED_ACTORS': '{"not":"a list"}', 'LABEL_NAMES': 'codex-stop', 'GATE_INTAKE_ENABLED': 'TRUE'},
            'unknown', [], 'unknown', [],
            [
                'repository_matches', 'intake_enabled', 'automation_stop_clear', 'event_label_is_codex_ready',
                'allowlist_configured', 'actor_allowlisted', 'author_allowlisted',
                'stop_label_absent', 'ready_label_present', 'issue_open', 'not_pull_request',
            ],
            absent=('codex-stop', '{"not":"a list"}', 'TRUE'))
        for code in ('wrong_actor', 'wrong_author', 'intake_disabled', 'stop_label_present', 'wrong_label'):
            self.assertNotIn(code, summary)

    def test_empty_allowlist_blocks_actor_and_author(self):
        summary = self.assert_report(
            passing_env(ALLOWED_ACTORS='[]', ACTOR='', AUTHOR=''),
            'runs', [], 'blocked', ['wrong_actor', 'wrong_author'], [])
        self.assertIn('- allowlist_configured: passed', summary)


if __name__ == '__main__':
    unittest.main()
