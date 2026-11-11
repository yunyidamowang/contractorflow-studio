// Execute the actual workflow script against explicit mocks. No GitHub/model calls.
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const {spawnSync} = require('node:child_process');
const assert = require('node:assert/strict');
const script = JSON.parse(fs.readFileSync('.github/workflows/codex-intake.yml', 'utf8'))
  .jobs.intake.steps[0].with.script;
const AsyncFunction = Object.getPrototypeOf(async function() {}).constructor;
async function run({actor='owner', body, labels=[{name:'codex-ready'}]}={}) {
  const comments=[];
  const issue={number:4,state:'open',user:{login:'owner'},labels,
    body:body ?? '## Goal\nSample\n## Acceptance\nSample\n## Allowed paths\n- docs/sample.md\n## References\nREADME.md'};
  const context={repo:{owner:'yunyidamowang',repo:'contractorflow-studio'},payload:{issue},actor,runId:42};
  const github={rest:{issues:{get:async()=>({data:issue}),createComment:async x=>comments.push(x)}}};
  const summary={addHeading(){return this},addRaw(){return this},async write(){}};
  await new AsyncFunction('github','context','core','process',script)(github,context,{summary},{env:{ALLOWED_ACTORS:'["owner"]'}});
  return comments;
}
(async()=>{
  const comments=await run();assert.equal(comments.length,1);
  assert.match(comments[0].body,/\nTask registered/);
  await assert.rejects(run({actor:'stranger'}),/not allowlisted/);
  await assert.rejects(run({body:'Missing required sections'}),/Missing structured section/);
  await assert.rejects(run({labels:[{name:'codex-ready'},{name:'codex-stop'}]}),/stopped/);
  await run({body:'## Goal\r\nSample\r\n## Acceptance\r\nSample\r\n## Allowed paths\r\n- docs/sample.md\r\n## References\r\nREADME.md'});
  const reportEnv = JSON.parse(fs.readFileSync('.github/workflows/codex-intake.yml', 'utf8')).jobs['gate-report'].steps[0].env;
  for (const [key, value] of Object.entries(reportEnv)) {
    assert.match(key, /^GATE_/);
    assert.match(value, /^\$\{\{\s*.+\s*\}\}$/);
    assert.equal(value.includes("vars.CF_ALLOWED_ACTORS }}"), false);
    assert.equal(value === '${{ github.actor }}' || value === '${{ github.event.issue.user.login }}', false);
    const body = value.replace(/^\$\{\{\s*/, '').replace(/\s*\}\}$/, '');
    assert.equal(body.includes('==') || body.includes('!=') || body.startsWith('contains(') || body.startsWith('!contains('), true);
  }
  const passed = {
    GATE_REPOSITORY:'true', GATE_INTAKE_ENABLED:'true', GATE_STOP_CLEAR:'true', GATE_LABEL:'true',
    GATE_ISSUE_OPEN:'true', GATE_NOT_PULL_REQUEST:'true', GATE_ALLOWLIST_CONFIGURED:'true',
    GATE_ACTOR_ALLOWLISTED:'true', GATE_AUTHOR_ALLOWLISTED:'true', GATE_STOP_LABEL_ABSENT:'true',
    GATE_READY_LABEL_PRESENT:'true'};
  const cases = [
    [{...passed, GATE_INTAKE_ENABLED:'false'}, 'intake_job: skipped', 'intake_blocked: intake_disabled'],
    [{...passed, GATE_LABEL:'false', GATE_READY_LABEL_PRESENT:'false', LEAKED:'ZZ-SENTINEL-LABEL'}, 'intake_blocked: wrong_label', 'registration_blocked: ready_label_missing'],
    [{...passed, GATE_ACTOR_ALLOWLISTED:'false', LEAKED:'ZZ-SENTINEL-ACTOR'}, 'intake_job: runs', 'registration_blocked: wrong_actor'],
    [{...passed, GATE_AUTHOR_ALLOWLISTED:'false', LEAKED:'ZZ-SENTINEL-AUTHOR'}, 'registration_blocked: wrong_author'],
    [{...passed, GATE_STOP_LABEL_ABSENT:'false'}, 'registration_blocked: stop_label_present'],
    [{...passed, GATE_STOP_CLEAR:'false'}, 'intake_blocked: automation_stop'],
    [{...passed, GATE_REPOSITORY:'false'}, 'intake_blocked: wrong_repository'],
    [{...passed, GATE_ALLOWLIST_CONFIGURED:'false', GATE_ACTOR_ALLOWLISTED:'false', GATE_AUTHOR_ALLOWLISTED:'false'}, 'registration_blocked: allowlist_missing,wrong_actor,wrong_author'],
    [passed, 'intake_job: runs', 'registration_precheck: clear'],
    [{}, 'intake_job: unknown', 'registration_precheck: unknown'],
  ];
  for (const [env, ...needles] of cases) {
    const result = runReport(env);
    for (const needle of needles) assert.match(result.summary, new RegExp(needle.replace(/[.]/g, '\\.')));
    assert.equal(result.summary.includes('ZZ-SENTINEL'), false);
    assert.equal(result.stdout.includes('ZZ-SENTINEL'), false);
  }
  console.log('PASS actual intake script: LF/CRLF task accepted; unauthorized, malformed and stopped tasks rejected; real newline feedback. Gate report names intake disabled, wrong label, wrong actor/author, stop label, stop variable, and unknown inputs without echoing raw values. SIMULATED GitHub only.');
})().catch(error=>{console.error(error);process.exitCode=1});

function reportScript() {
  const run = JSON.parse(fs.readFileSync('.github/workflows/codex-intake.yml', 'utf8')).jobs['gate-report'].steps[0].run;
  const marker = "<<'CF_GATE_REPORT'\n";
  return run.slice(run.indexOf(marker) + marker.length, run.lastIndexOf('\nCF_GATE_REPORT'));
}
function runReport(env) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'cf-gate-'));
  const scriptPath = path.join(dir, 'report.cjs');
  const summaryPath = path.join(dir, 'summary.md');
  fs.writeFileSync(scriptPath, reportScript());
  const result = spawnSync(process.execPath, [scriptPath], {
    env: {PATH: process.env.PATH || '', GITHUB_STEP_SUMMARY: summaryPath, ...env},
    encoding: 'utf8'});
  const summary = fs.readFileSync(summaryPath, 'utf8');
  fs.rmSync(dir, {recursive: true, force: true});
  if (result.status !== 0) throw new Error(result.stderr || 'gate report failed');
  return {stdout: result.stdout, summary};
}
