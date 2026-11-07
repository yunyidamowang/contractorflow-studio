// Execute the actual workflow script against explicit mocks. No GitHub/model calls.
const fs = require('node:fs');
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
  console.log('PASS actual intake script: LF/CRLF task accepted; unauthorized, malformed and stopped tasks rejected; real newline feedback. SIMULATED GitHub only.');
})().catch(error=>{console.error(error);process.exitCode=1});
