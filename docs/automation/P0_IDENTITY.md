# P0-D identity migration

Task CF-20261112-027. Base main `b454016ee9a3a595f06ab1146b122eec09f6c447` (PR #15 merged). This file is documentation for the repository owner. It does not create a GitHub App, a token, an account, or a permission change.

**Dual identity is not solved. The pilot stays disabled until it is.**

`automation/settings.example.json` on this commit has `enabled` false and `canary_issue` 4. The dispatcher still authenticates with one bearer token and still allowlists login strings. Nothing in this change separates the planning identity from the owner.

## What this task read

- `automation/settings.example.json`: `enabled` is false, `canary_issue` is 4, `allowed_actors` is the single login `yunyidamowang`.
- `automation/dispatcher.py`: the supervisor reads `.automation/github.token`, rejects a file whose mode is not 0600, and allows only the routes in the matrix below. There is no GitHub App JWT and no installation-token exchange.
- `.github/workflows/ci.yml`: token permission `contents: read`, checkout `persist-credentials: false`, no secrets. The check name to require later is `cf-ci-gate`. This task did not change that file. SHA256 remains `4576223a294403ed8e15536941da5d73110c9f157bbf1bc3a008872dce62260d`.
- `.github/workflows/codex-intake.yml`: unchanged. Intake diagnosis is already delivered by P0-C (PR #13, merge `78d09b9a77c501e79cb2871821b2a1ef436ffd22`, handoff `handoff/outbox/CF-20261111-022.md`). This document only points at that result.

The live `.automation/settings.json` and `.automation/github.token` on the owner's Mac were not read. They are gitignored. Their current contents are UNVERIFIED.

Earlier handoffs record a single-repository fine-grained personal access token, later given Workflows read and write, with an expiry written as 2026-11-14. This task did not open the token list and does not confirm that token still exists.

## Roles

| Role | Who it is | What it may hold |
|---|---|---|
| Planner | A future planning identity for Grok, acting as its own GitHub App. | No private key in this repository. It must not be the owner's login with a different display name. |
| Publisher | The local supervisor on the controlled machine, acting as a second GitHub App. | One app private key, held by the owner on that machine. The model process does not receive it. |
| CI | GitHub-hosted Actions for this repository. | The workflow `GITHUB_TOKEN` only, as already declared in `ci.yml`. No owner secret. |
| User | The human repository owner. | App registration, installation, private keys, branch rules, alert settings, and the merge button. |

The intake workflow is not a fifth role and not an authorization root. Its default permission is `issues: read`. The intake job still has `issues: write` and still runs only when its existing `if` passes. `gate-report` has `permissions: {}` and only writes an Actions summary. P0-C explains the skipped runs. This task does not turn intake on.

Changing a display name does not change a numeric user id, an App id, or an installation id. The current allowlist compares the login string on the `codex-ready` event. A shared owner login cannot tell the owner from Grok. That is why `canary_issue` stays 4 and `enabled` stays false.

## Endpoint to permission matrix

Permissions below are what the owner selects when registering each GitHub App. They are the GitHub App repository permissions for the routes the current broker and CI actually use. This task did not install an app or call these routes with an app token.

Metadata is Read-only on every GitHub App and is not repeated on each row. Administration, Workflows, Actions, Secrets, and organization permissions are No access for both apps. Neither app requests a user access token. "Request user authorization (OAuth) during installation" stays off, so the app does not act as the owner.

CI is not an app permission. The CI column is the `GITHUB_TOKEN` already set in `.github/workflows/ci.yml`, or "none" when that workflow does not call the route.

| Action | Planner app | Publisher app | CI token | User |
|---|---|---|---|---|
| `GET /repos/yunyidamowang/contractorflow-studio` | Metadata: Read-only | Metadata: Read-only | `contents: read` via checkout | Owner session |
| `GET /issues`, `GET /issues/{n}`, comments, events | Issues: Read-only | Issues: Read and write | none | Owner session |
| `GET /labels/codex-stop` | Issues: Read-only | Issues: Read and write | none | Owner session |
| `POST /issues/{n}/comments` | Issues: Read and write | Issues: Read and write | none in `ci.yml`. The separate intake job can comment; it is not CI and not the planner | Owner session |
| `GET /git/ref/heads/main`, `GET /git/commits/{sha}`, `GET /git/trees/{sha}`, `GET /git/blobs/{sha}` | Contents: Read-only | Contents: Read and write | `contents: read` | Owner session |
| `POST /git/blobs`, `POST /git/trees`, `POST /git/commits` | No access | Contents: Read and write | none | Not delegated |
| `POST /git/refs` for a new `refs/heads/codex/issue-{n}-attempt-{1 or 2}-{time}` branch only | No access | Contents: Read and write | none | Not delegated |
| `GET /pulls` | Pull requests: Read-only | Pull requests: Read and write | none | Owner session |
| `POST /pulls` with base `main` and `draft: true` only | No access | Pull requests: Read and write | none | Not delegated |
| Merge a pull request | No access | No separate permission exists. Pull requests: Read and write can call the merge API when branch rules allow it. The broker has no merge route | none | Owner, in the web UI, after review |
| Update or delete `refs/heads/main`, force-push, delete the branch | No access | Not a broker route. Contents: Read and write is still broad on the platform. Branch rules have to refuse it | none | Owner configures the rules. See `docs/automation/P0_SECURITY_SETTINGS.md` |
| Branch protection, rulesets, required checks | Administration: No access | Administration: No access | none | Owner |
| Secret scanning, push protection, Dependabot settings | No access | No access | none | Owner |
| Read the `cf-ci-gate` result | Checks: Read-only | Checks: No access | The workflow produces the check. It cannot require it | Owner, when deciding to merge |
| Repository variables, secrets, and labels as an API | No access | No access. Issues: Read and write can also edit labels on the platform. The broker's only issue write is a comment | `ci.yml` declares no secrets. `gate-report` computes booleans from variables and does not print them | Owner. This task does not ask to set any |
| Push a change under `.github/workflows/` | Workflows: No access | Workflows: No access | none | Owner, by a reviewed pull request |

The broker, not GitHub, enforces the narrow route list. A stolen publisher token can do more than the broker will ask: push other branches, open a non-draft pull request, edit labels, or call merge if the branch rules allow it. Those platform gaps are why the publisher key stays off the model, why main needs the rules in the security checklist, and why Pull requests: Read and write is not a platform ban on merge.

GitHub treats a required check in state `success`, `skipped`, or `neutral` as satisfied. `cf-ci-gate` exists so a skipped test job is not acceptance. The owner still does not treat a skipped `cf-tests` run as a pass. Requiring the check is a user step and is not done by this change. Whether it is required today is UNVERIFIED; the protection API returned HTTP 403 to this task.

## Preferred route: two GitHub Apps

Use two apps owned by the repository owner's personal account. One app for the planner, one for the publisher. Each acts as itself through an installation token. Do not use one app for both roles. Do not authorize either app to act as the user.

The owner does all of the following. This task did none of it.

1. USER step. Sign in as the repository owner. Open Settings, then Developer settings, then GitHub Apps, then New GitHub App. Register the planner app. Choose a name that is unique on GitHub and does not contain a secret. Homepage URL may be this repository's public URL. Leave callback URL empty. Leave "Request user authorization (OAuth) during installation" off. Leave Device Flow off. Deselect Active under webhooks so no webhook secret is created. Set "Where can this GitHub App be installed?" to Only on this account.
2. USER step. On that app, set only the planner column above. Every other repository permission stays No access.
3. USER step. Repeat the registration for the publisher app, with only the publisher column. Do not give it Workflows, Administration, Actions, or Secrets.
4. USER step. Install each app on this account, and only on `yunyidamowang/contractorflow-studio`. If the installer offers all repositories, switch it to the single selected repository.
5. USER step. Generate the publisher private key from the app settings page. GitHub shows the PEM once. Store it as described under credential hygiene below. Do not download it into the repository, an Issue, a pull request, or a chat. The planner app does not need a private key until a connector can actually use an app identity. If a planner key is generated during a rehearsal, delete it before leaving the page unless a reviewed design is ready to hold it.
6. USER step. Write down, on the controlled machine only, the App id, the installation id, and the bot account's numeric user id for each app. Those identifiers are not secrets, and they still do not belong in this public repository until a later reviewed change teaches the allowlist to require them. Do not write down the PEM, a client secret, or an installation token.
7. USER step. Compare the three numeric user ids: owner, planner bot, publisher bot. Dual identity is solved only when all three differ, the dispatcher requires those ids, and a migration test shows the planner cannot publish and the publisher's actor is not the owner. That code does not exist. Until the comparison is true, do not set `enabled` to true, do not clear `canary_issue`, and do not add `codex-ready`.

Official registration steps, read 2026-11-12: [Registering a GitHub App](https://docs.github.com/en/apps/creating-github-apps/registering-a-github-app/registering-a-github-app). If GitHub renames a control, follow the label on the page and record that label. Do not invent a permission to make the page match this table.

## Optional machine account, and no classic PAT

The App route is the one to use. A machine account is optional and only for a client that cannot authenticate as a GitHub App at all.

GitHub's Terms of Service, read 2026-11-12 at <https://docs.github.com/en/site-policy/github-terms/github-terms-of-service>, say a human must create an account, accounts registered by bots are not permitted, and a machine account is allowed only under these conditions: one human accepts the terms for it, supplies a valid email address, and is responsible for it; it is used exclusively to run a machine; and "You may maintain no more than one free machine account in addition to your free Personal Account." The same section says one person or legal entity may maintain no more than one free account, and that an extra machine account "can only be used for running a machine."

USER step, and only if the App route cannot serve the connector:

- The owner personally registers at most one free machine account, accepts the current terms, and keeps it for automation only.
- Do not register a second free personal account for ordinary use.
- Do not transfer this repository to the machine account.
- Do not create a classic personal access token for the owner, the machine account, or anyone else. Classic personal access tokens are not a fallback when a fine-grained token or an app is awkward.

Fine-grained personal access tokens, from [Managing your personal access tokens](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens) read 2026-11-12, are limited to resources owned by one user or organization. GitHub documents that they cannot be used to contribute to a public repository where the user is not a member, and cannot be used where the user is an outside or repository collaborator. A machine user added as a collaborator on this personal repository can therefore be unable to push with a fine-grained token. The documented alternative for that gap is a classic personal access token. This project does not take that alternative. Stop and report the gap. The owner installs the publisher app instead.

A fine-grained token is also still the identity of the user who created it. It does not create a second actor. The existing single-repository token, whatever its current state, is not dual identity.

## Grok connector

UNVERIFIED. `HANDOFF.md` already says the connector's OAuth, tool list, and revocation were not measured on the user's account. This task did not call a connector and did not create an app. A product page that mentions GitHub is not evidence that this account can attach a GitHub App.

USER step, later, not as part of applying this document: in the connector's own settings, see whether it can use a GitHub App installation rather than the owner's user session. If it can, one read-only action should show a planner actor id different from the owner. Record the ids, not the token. If it cannot, stop. Do not point the connector at the owner's account and rename the display. The machine-account route above is a separate decision and still forbids a classic personal access token.

## Rotation drill

Not performed. Do not run this drill until there is a key to rotate. If a rehearsal key is created before the supervisor can use a PEM, delete that key before leaving the page.

1. USER step. On the publisher app's settings, generate a second private key. Leave the current key in place.
2. USER step. Store the new PEM with the credential rules below. Do not print it, commit it, or paste it.
3. USER step. After a later reviewed code change can read that key, point only the supervisor at it. Confirm one read-only `GET` of this repository as the installation. Record the HTTP status, the installation id, and the bot user id. Do not record the token or the response headers.
4. USER step. Delete the old private key in the app settings. Repeat the same read-only `GET` with the old key and record only that it fails, including the HTTP status. Confirm `enabled` is still false and `canary_issue` is still 4.
5. USER step. Confirm no new branch, pull request, label, or comment appeared during the drill.

There is no PEM reader in `automation/dispatcher.py` today. Generating a key does not by itself cut the supervisor over.

## Revocation drill

Not performed.

1. USER step. Delete every private key on the app.
2. USER step. Uninstall the app from this repository.
3. USER step. Confirm a token that was issued before the uninstall now fails. Record only the HTTP status.
4. USER step. Confirm the repository gained no commit, label, or pull request from the drill.
5. USER step. On the controlled machine, confirm the live `enabled` value is false and `canary_issue` is 4. Record only those two values.
6. USER step. Leave the historical fine-grained token where it is until a separate approved cutover. Do not replace it with a classic personal access token. This document does not revoke it, because the running supervisor still expects a bearer token file and cannot yet use an app key.

## Commit metadata and credential hygiene

Future commits that land in this public repository use a GitHub noreply address. The owner turns on "Keep my email addresses private" and "Block command line pushes that expose my email" under Settings, then Emails. For an account created after 18 July 2017, GitHub's noreply form is `ID+LOGIN@users.noreply.github.com`, as documented in [Email addresses reference](https://docs.github.com/en/account-and-profile/reference/email-addresses-reference), read 2026-11-12. The owner copies the address GitHub displays into the repository-local `user.email` on every machine that commits here. Do not put a personal mailbox in that setting.

No history rewrite. Do not amend commits that are already on main, do not run a history-filter tool, and do not force-push. Decision D021 records that historical personal addresses were left in place when the repository was made public. This task does not quote those addresses and does not remove them. A count of existing main commits whose address is not a `users.noreply.github.com` address is in the handoff; the addresses are not.

The isolated sample commit inside the dispatcher already uses `codex-worker@users.noreply.github.com`. That is a noreply address, it is already in the source, and this task does not change `automation/dispatcher.py`. It is not a personal mailbox and it is not the owner's noreply address.

Raw logs stay on the controlled local machine. `.automation/` is gitignored. It holds `audit.jsonl`, `state.db`, run directories, and model output. Those files are not uploaded. Before an Issue, pull request, or handoff, redact tokens, `Authorization` headers, private keys, personal email addresses, and customer data. Publish HTTP status codes, booleans, check names, and hashes.

Credential files are mode 0600 and credential directories are mode 0700. The dispatcher already creates `.automation` at 0700, sets the project Codex config file to 0600, and refuses a `github.token` whose mode is not 0600. Prefer the operating-system keychain or other system credential store when a later reviewed change can read it. This task ran on a cloud VM, not the owner's Mac, and did not test Keychain. That compatibility is UNVERIFIED. Until a keychain reader exists, the 0600 file inside the 0700 directory is the required fallback. Do not store the publisher key in the repository, in an Actions secret the model can read, or in a chat.

USER step. On each machine that commits to this repository, set the noreply address and the two email-privacy controls above. Do not rewrite old commits.

USER step. On the controlled machine, confirm credential files are 0600 and their directory is 0700, or that the only copy is in the system credential store. Record modes, not contents.

## What remains disabled

Until the three numeric ids differ and the dispatcher enforces them:

- `enabled` stays false.
- `canary_issue` stays 4.
- Do not run `automation.dispatcher once` or a watch loop.
- Do not add `codex-ready` or any other execution label.
- Do not treat this document, a display-name change, or the existing fine-grained token as the migration.
