# P1 launchd sample (not installed)

`docs/automation/com.contractorflow.studio.sample.plist` is an example of a user-level LaunchAgent. It is not installed. This repository does not copy it into `~/Library/LaunchAgents` or `/Library/LaunchDaemons`, and it does not contain an install script.

Installing or loading that example is a separate future decision for the repository owner. This document is not that approval. The dispatcher stays off: `automation/settings.example.json` has `enabled` false and `canary_issue` 4, and it omits `task_queue`, `publish_reconcile`, and `audit_chain`.

The sample is for the logged-in user, not the superuser. Do not put it in a system daemon directory.

`KeepAlive` is false. The example uses `StartInterval` and `ThrottleInterval` of 120 seconds so a later start is throttled. It must not be changed to `KeepAlive` true. `automation/launchd_sample.py` exits as soon as it sees a breaker file, and it does not start `once` or `watch`. A latched breaker stays latched; nothing in this sample deletes that file.

The sample does not run `caffeinate` and does not change the machine sleep policy. The plist has no `NetworkState` key. A launchd network hint would not prove that GitHub can be reached.

`WorkingDirectory` in the example is a placeholder path. Replace it only as part of the separate approval, on the machine where the agent would run.
