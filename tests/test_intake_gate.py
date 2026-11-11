"""Static and simulated checks for the intake gate report. No GitHub or model calls."""
import hashlib
import json
import os
import re
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
INTAKE_JOB_SHA256 = '22316e67291e6ba0a6f9c59424acf6e4e2bf78b00b7758b3df4b007f48a7afc6'
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


EXPRESSION = re.compile(r'^\$\{\{\s*(?P<body>.+?)\s*\}\}$')
RAW_ENV = (
    '${{ vars.CF_ALLOWED_ACTORS }}',
    '${{ vars.CF_INTAKE_ENABLED }}',
    '${{ vars.CF_AUTOMATION_STOP }}',
    '${{ github.actor }}',
    '${{ github.event.issue.user.login }}',
    '${{ toJSON(github.event.issue.labels.*.name) }}',
)


def expression_body(value):
    match = EXPRESSION.fullmatch(value)
    if match is None or not match.group('body'):
        raise AssertionError('not a delimited expression: ' + value)
    return match.group('body')


def assert_boolean_expression(testcase, body):
    array_guard = "startsWith(toJSON(fromJSON(vars.CF_ALLOWED_ACTORS || '[]')), '[')"
    compared = (
        body.startswith('contains(') or body.startswith('!contains(')
        or ' == ' in body or ' != ' in body
        or (body.startswith('startsWith(toJSON(fromJSON(') and '&&' in body))
    testcase.assertTrue(compared, body)
    testcase.assertNotIn('toJSON(github', body)
    if 'toJSON' in body:
        testcase.assertIn(array_guard, body)
        testcase.assertFalse(body.startswith('toJSON('))
    for found in re.finditer(r'vars\.[A-Za-z0-9_]+', body):
        after = body[found.end():]
        testcase.assertTrue(
            after.startswith(' == ') or after.startswith(' != ') or after.startswith(" || '[]'"),
            body)


def passing_env(**overrides):
    env = {
        'GATE_REPOSITORY': 'true',
        'GATE_INTAKE_ENABLED': 'true',
        'GATE_STOP_CLEAR': 'true',
        'GATE_LABEL': 'true',
        'GATE_ISSUE_OPEN': 'true',
        'GATE_NOT_PULL_REQUEST': 'true',
        'GATE_ALLOWLIST_CONFIGURED': 'true',
        'GATE_ACTOR_ALLOWLISTED': 'true',
        'GATE_AUTHOR_ALLOWLISTED': 'true',
        'GATE_STOP_LABEL_ABSENT': 'true',
        'GATE_READY_LABEL_PRESENT': 'true',
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
        clauses = [expression_body(env[name]) for name in (
            'GATE_REPOSITORY', 'GATE_INTAKE_ENABLED', 'GATE_STOP_CLEAR', 'GATE_LABEL')]
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

    def test_gate_report_env_values_are_boolean_expressions(self):
        env = workflow()['jobs']['gate-report']['steps'][0]['env']
        self.assertEqual(set(env), {
            'GATE_REPOSITORY', 'GATE_INTAKE_ENABLED', 'GATE_STOP_CLEAR', 'GATE_LABEL',
            'GATE_ISSUE_OPEN', 'GATE_NOT_PULL_REQUEST', 'GATE_ALLOWLIST_CONFIGURED',
            'GATE_ACTOR_ALLOWLISTED', 'GATE_AUTHOR_ALLOWLISTED', 'GATE_STOP_LABEL_ABSENT',
            'GATE_READY_LABEL_PRESENT'})
        for key, value in env.items():
            self.assertTrue(key.startswith('GATE_'), key)
            assert_boolean_expression(self, expression_body(value))
        array_guard = "startsWith(toJSON(fromJSON(vars.CF_ALLOWED_ACTORS || '[]')), '[')"
        self.assertEqual(
            env['GATE_ALLOWLIST_CONFIGURED'],
            "${{ " + array_guard + " && vars.CF_ALLOWED_ACTORS != '' }}")
        self.assertEqual(
            env['GATE_ACTOR_ALLOWLISTED'],
            "${{ " + array_guard + " && contains(fromJSON(vars.CF_ALLOWED_ACTORS || '[]'), github.actor) }}")
        self.assertEqual(
            env['GATE_AUTHOR_ALLOWLISTED'],
            "${{ " + array_guard + " && contains(fromJSON(vars.CF_ALLOWED_ACTORS || '[]'), github.event.issue.user.login) }}")
        self.assertEqual(
            env['GATE_STOP_LABEL_ABSENT'],
            "${{ !contains(github.event.issue.labels.*.name, 'codex-stop') }}")
        self.assertEqual(
            env['GATE_READY_LABEL_PRESENT'],
            "${{ contains(github.event.issue.labels.*.name, 'codex-ready') }}")
        blob = json.dumps(workflow()['jobs']['gate-report'])
        for raw in RAW_ENV:
            self.assertNotIn(raw, blob)
        script = report_script()
        for leaked in ('ALLOWED_ACTORS', 'LABEL_NAMES', 'JSON.parse', 'toJSON', 'github.actor'):
            self.assertNotIn(leaked, script)

    def test_wrong_label_is_named_without_echoing_it(self):
        summary = self.assert_report(
            passing_env(GATE_LABEL='false', GATE_READY_LABEL_PRESENT='false', LEAKED_LABEL='ZZ-SENTINEL-LABEL'),
            'skipped', ['wrong_label'], 'blocked', ['ready_label_missing'], [],
            absent=('ZZ-SENTINEL-LABEL',))
        self.assertIn('- event_label_is_codex_ready: blocked', summary)
        self.assertIn('- ready_label_present: blocked', summary)
        self.assertIn('- stop_label_absent: passed', summary)

    def test_wrong_actor_and_author_are_named(self):
        summary = self.assert_report(
            passing_env(
                GATE_ACTOR_ALLOWLISTED='false', GATE_AUTHOR_ALLOWLISTED='false',
                LEAKED_ACTOR='ZZ-SENTINEL-ACTOR', LEAKED_AUTHOR='ZZ-SENTINEL-AUTHOR'),
            'runs', [], 'blocked', ['wrong_actor', 'wrong_author'], [],
            absent=('ZZ-SENTINEL-ACTOR', 'ZZ-SENTINEL-AUTHOR'))
        self.assertIn('- actor_allowlisted: blocked', summary)
        self.assertIn('- author_allowlisted: blocked', summary)
        self.assertIn('- allowlist_configured: passed', summary)

    def test_stop_label_is_named(self):
        summary = self.assert_report(
            passing_env(GATE_STOP_LABEL_ABSENT='false'),
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
                GATE_ALLOWLIST_CONFIGURED='true',
                GATE_ACTOR_ALLOWLISTED='false',
                GATE_AUTHOR_ALLOWLISTED='true',
                GATE_STOP_LABEL_ABSENT='false',
                GATE_READY_LABEL_PRESENT='false',
                LEAKED_ACTOR='ZZ-SENTINEL-ACTOR',
                LEAKED_LABEL='ZZ-SENTINEL-LABEL',
                LEAKED_ALLOWLIST='ZZ-SECRET-ALLOW',
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
            {'GATE_INTAKE_ENABLED': 'TRUE', 'LEAKED_ALLOWLIST': 'ZZ-SECRET-ALLOW', 'LEAKED_LABEL': 'ZZ-SENTINEL-LABEL'},
            'unknown', [], 'unknown', [],
            [
                'repository_matches', 'intake_enabled', 'automation_stop_clear', 'event_label_is_codex_ready',
                'allowlist_configured', 'actor_allowlisted', 'author_allowlisted',
                'stop_label_absent', 'ready_label_present', 'issue_open', 'not_pull_request',
            ],
            absent=('ZZ-SECRET-ALLOW', 'ZZ-SENTINEL-LABEL', 'TRUE'))
        for code in ('wrong_actor', 'wrong_author', 'intake_disabled', 'stop_label_present', 'wrong_label'):
            self.assertNotIn(code, summary)

    def test_non_array_allowlist_allowlists_nobody(self):
        data = workflow()
        env = data['jobs']['gate-report']['steps'][0]['env']
        guard = "startsWith(toJSON(fromJSON(vars.CF_ALLOWED_ACTORS || '[]')), '[')"
        for key in ('GATE_ALLOWLIST_CONFIGURED', 'GATE_ACTOR_ALLOWLISTED', 'GATE_AUTHOR_ALLOWLISTED'):
            body = expression_body(env[key])
            self.assertIn(guard, body)
            self.assertIn('&&', body)
            self.assertFalse(body.startswith('toJSON('))
            self.assertNotIn('${{ vars.CF_ALLOWED_ACTORS }}', env[key])
        self.assertIn('contains(fromJSON(vars.CF_ALLOWED_ACTORS || \'[]\'), github.actor)', expression_body(env['GATE_ACTOR_ALLOWLISTED']))
        self.assertIn('github.event.issue.user.login', expression_body(env['GATE_AUTHOR_ALLOWLISTED']))
        script = data['jobs']['intake']['steps'][0]['with']['script']
        self.assertLess(script.index('!Array.isArray(actors)'), script.index('actors.includes(context.actor)'))
        self.assertEqual(data['jobs']['intake']['if'], INTAKE_IF)
        self.assertEqual(data['permissions'], {'issues': 'read'})
        self.assertEqual(data['jobs']['intake']['permissions'], {'issues': 'write'})
        self.assertEqual(data['jobs']['gate-report']['permissions'], {})
        self.assertNotIn('pull_request_target', json.dumps(data))
        probe = r"""
const fs = require('node:fs');
const script = JSON.parse(fs.readFileSync(process.argv[1], 'utf8')).jobs.intake.steps[0].with.script;
const AsyncFunction = Object.getPrototypeOf(async function(){}).constructor;
async function once(actors, actor) {
  const comments = [];
  const issue = {number:4, state:'open', user:{login:actor}, labels:[{name:'codex-ready'}],
    body:'## Goal\nSample\n## Acceptance\nSample\n## Allowed paths\n- docs/sample.md\n## References\nREADME.md'};
  const context = {repo:{owner:'yunyidamowang', repo:'contractorflow-studio'}, payload:{issue}, actor, runId:7};
  const github = {rest:{issues:{get:async()=>({data:issue}), createComment:async item => comments.push(item)}}};
  const summary = {addHeading(){return this}, addRaw(){return this}, async write(){}};
  await new AsyncFunction('github','context','core','process', script)(github, context, {summary}, {env:{ALLOWED_ACTORS:actors}});
  return comments.length;
}
(async () => {
  const cases = [
    ['["owner"]', 'owner', true],
    ['"owner"', 'owner', false],
    ['"owner-extra"', 'owner', false],
    ['{"owner":true}', 'owner', false],
    ['true', 'owner', false],
    ['null', 'owner', false],
    ['12', 'owner', false],
    ['[]', 'owner', false],
    ['["guest"]', 'owner', false],
  ];
  for (const [actors, actor, ok] of cases) {
    let registered = false;
    let error = '';
    try { registered = (await once(actors, actor)) === 1; }
    catch (err) { error = String(err); }
    if (ok && !registered) throw new Error('expected allow ' + actors);
    if (!ok && (registered || !/not allowlisted/.test(error))) throw new Error('expected nobody for ' + actors + ' got ' + error);
  }
})().catch(err => { console.error(err); process.exit(1); });
"""
        proc = subprocess.run(['node', '-e', probe, str(WORKFLOW)], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr or proc.stdout)

    def test_empty_allowlist_blocks_actor_and_author(self):
        summary = self.assert_report(
            passing_env(GATE_ACTOR_ALLOWLISTED='false', GATE_AUTHOR_ALLOWLISTED='false'),
            'runs', [], 'blocked', ['wrong_actor', 'wrong_author'], [])
        self.assertIn('- allowlist_configured: passed', summary)


if __name__ == '__main__':
    unittest.main()
