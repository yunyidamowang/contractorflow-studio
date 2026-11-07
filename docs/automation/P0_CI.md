# P0-A independent CI (under review)

The reviewed main 2392dbcc81260ebd44b421fbc76d8c11c22c71d4 supplies the original 38 named tests and source hashes in automation/test_manifest.json. The original names remain mandatory; three new validator tests are registered explicitly (41 total). test_automation.py only adapts the synthetic successful-worker log fixture to the structured result; existing assertions are retained. Original and updated source hashes are both retained for review.

The trusted supervisor supplies runner code and policy from its own checkout after model execution, via argv, not from the model workspace. Tests and the manifest are unavailable for ordinary worker modification. The result must include the exact names/count, successful exit, no skips/expected failures, and matching baseline source hashes. This is a single-process test runner, not protection against arbitrary malicious Python in the application altering interpreter internals.

CI tests both PR head and merge revision, with read-only contents, no secrets, ephemeral Ubuntu, no persisted checkout credential, fixed action SHAs and a stable always-running cf-ci-gate. No path filters or continue-on-error. Draft PR events included. The initial CI workflow and manifest are a bootstrap trust decision requiring independent review; GitHub executes PR workflow code, so a PR author can also propose changing that workflow. A successful self-modified workflow alone cannot prove a trusted source. Required-check/source binding must be configured separately by an authorized maintainer after real checks exist; this PR does not change branch protection. Fork first-run approval must not be bypassed. Dependency installation contacts PyPI; pinned versions are retained, no new dependencies added.

Ubuntu results do not verify macOS sandbox semantics. Mac native isolation must be reported separately. No dispatcher once/watch, no new canary, no ledger migration or edits. enabled=false/canary=4 remain unchanged. P0-B/C/D follow only after this stage has actual CI evidence or the blocking condition is reported to #10.

## Executed evidence and blocker (2026-11-07)

Local exact-manifest runner: 41 tests passed in 1.457s. Native macOS isolation probe passed (outside/auth-root read denied, git protected, network denied); the archived source checkout then passed 41 tests in 25.384s. Ledger SHA256 remained b31ac93a3d6850f6053ed16b913970f1f424981a9a4e52d9c0d2c1df2066d3ca. enabled=false, canary_issue=4. No worker/model invocation.

GitHub rejected uploading .github/workflows/ci.yml because the existing PAT has no workflow permission. No permission expansion was attempted. The review PR therefore contains the test-policy portion only. CI configuration remains local and is not active on GitHub. Independent CI and A acceptance are NOT complete; B/C/D are paused per the handoff. An authorized maintainer must install/review the proposed workflow using existing authorized workflow access, then obtain actual head and merge CI results before configuring required checks or proceeding.

The exact inactive workflow proposal is supplied in docs/automation/proposed-ci.json for remote review. An authorized maintainer can install its reviewed contents as .github/workflows/ci.yml. This document file does not activate Actions or bypass workflow permission.
