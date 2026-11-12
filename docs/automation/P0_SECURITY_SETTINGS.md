# P0-D owner security settings

Task CF-20261112-027. Base main `b454016ee9a3a595f06ab1146b122eec09f6c447`. This is a checklist for the repository owner. Nothing here was applied to repository settings, branch protection, secrets, variables, or labels.

Every item below is a USER step. A step is done only after the owner performs it and records redacted evidence. This task's own reads are listed separately. They do not complete a USER step. Where this task could not read a control, the result is UNVERIFIED.

Identity, the App route, noreply commits, and credential file modes are in `docs/automation/P0_IDENTITY.md`. Intake diagnosis is P0-C (PR #13). It is not repeated here.

## How to record redacted evidence

Write one block per control, on the controlled machine or in a private note. Do not put it in an Issue if it contains a secret, a personal email address, or a raw API body.

```text
item:
read_at: YYYY-MM-DDTHH:MM:SS+08:00
surface: UI label, or METHOD /repos/yunyidamowang/contractorflow-studio/...
http_status:
observed: booleans, counts, and setting names only
raw_values_included: no
```

Omit arrays of users, tokens, email addresses, and alert bodies. A secret-scanning or Dependabot alert body can contain credential material. Record the alert count and the state name, not the matched text.

## Reads this task actually performed

Time of the HTTP date header: 2026-11-12T09:24:15+08:00. Caller: this task's GitHub integration, not the owner's admin session.

| Read | Result |
|---|---|
| `GET /repos/yunyidamowang/contractorflow-studio` | Success. `visibility` public, `private` false, `default_branch` main, `allow_auto_merge` false, `delete_branch_on_merge` false, `security_and_analysis` null. Null is not evidence that secret scanning or Dependabot is off. GitHub omits that object from callers who lack administration. |
| `GET /repos/yunyidamowang/contractorflow-studio/branches/main/protection` | HTTP 403, `Resource not accessible by integration`. Branch protection is UNVERIFIED. |
| `GET /repos/yunyidamowang/contractorflow-studio/rulesets` | HTTP 200, body `[]`. No repository ruleset was visible to this caller. That does not prove a classic branch protection rule is absent. Classic protection is the other resource, and it returned 403. |
| `GET /repos/yunyidamowang/contractorflow-studio/vulnerability-alerts` | HTTP 403. Response header `X-Accepted-Github-Permissions: administration=read`. Whether Dependabot alerts are enabled is UNVERIFIED. |
| `GET /repos/yunyidamowang/contractorflow-studio/automated-security-fixes` | HTTP 403, same accepted permission. Whether Dependabot security updates are enabled is UNVERIFIED. |

`allow_auto_merge: false` is a verified field on the public repository payload. It is not a substitute for the owner looking at the setting.

Earlier prose in `AUTOMATION.md` says that on 2026-11-07 main required a pull request, had zero required approvals, blocked administrator bypass, and blocked force-push and deletion. That is a historical report. This task did not repeat those checks.

## S1. Secret scanning alerts

USER step. UNVERIFIED.

Open the repository, then Settings. In the Security and quality section of the sidebar, open Advanced Security. Read the secret scanning alerts control.

Two official pages, both read 2026-11-12, do not use the same words. [About secret scanning](https://docs.github.com/en/code-security/secret-scanning/introduction/about-secret-scanning) says secret scanning runs automatically for free on public repositories. [Managing security and analysis settings](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/enabling-features-for-your-repository/managing-security-and-analysis-settings-for-your-repository) says secret scanning is not enabled by default and is toggled on that Advanced Security page. The page the owner sees wins.

- If the control is already on and does not mention a purchase, leave it on and record the label.
- If the control says Enable and does not ask for GitHub Secret Protection, Code Security, or any other paid license, turn on alerts only.
- If the control requires a paid license, stop. Do not buy it. Record the label and leave the control unchanged.

Do not enable generic patterns, custom patterns, validity checks, or AI-detected secrets unless the same page shows they are free. The secret-scanning documentation describes those as extra features, and AI detection is documented as billed. They are out of scope.

Do not paste a real secret into an Issue or a commit to test the scanner.

## S2. Push protection

USER step. UNVERIFIED.

There are two different controls.

User push protection is the free control. [Managing push protection for users](https://docs.github.com/en/code-security/how-tos/secure-your-secrets/prevent-future-leaks/manage-user-push-protection), read 2026-11-12, says: profile picture, Settings, Code security, then "Push protection for yourself". The concept page says this control is on by default, applies to the signed-in user, and blocks that user from pushing supported secrets to public repositories. It does not by itself create a repository alert. Confirm it is on for the owner account. Record on or off. Do not turn it off.

Repository push protection is a different control on the same Advanced Security page as S1. [About push protection](https://docs.github.com/en/code-security/secret-scanning/introduction/about-push-protection) says repository push protection requires GitHub Secret Protection and is off by default. The public-repository settings page lists push protection as a toggle and says it is not on by default. Those pages disagree.

- Enable the repository control only when the button does not require a paid product.
- If it requires GitHub Secret Protection or any purchase, do not enable it and do not buy the product. Record the label.
- Do not enable push protection for AI-detected secrets. The documentation says that feature is billed.

## S3. Dependabot alerts

USER step. UNVERIFIED.

On the same Advanced Security page, enable Dependabot alerts if the control does not require a purchase. [Configuring Dependabot alerts](https://docs.github.com/en/code-security/how-tos/secure-your-supply-chain/secure-your-dependencies/configure-dependabot-alerts), read 2026-11-12, places it at Settings, Security and quality, Advanced Security, then Enable next to Dependabot alerts. Alerts need the dependency graph. If the page says the graph must be on first, enable the graph, then the alerts.

Record whether the control was already on, turned on, or blocked by a purchase prompt. Do not open or copy alert bodies into git. A count and the enabled/disabled state are enough.

This is alerts only. It does not approve a dependency upgrade.

## S4. Paid and automatic changes

USER step. UNVERIFIED, except the single `allow_auto_merge` field recorded above.

On the same Advanced Security page, leave these off:

- Dependabot security updates. They open pull requests.
- Dependabot version updates. Do not add a Dependabot version-updates configuration.
- Auto-triage rules that open pull requests.
- Assignment of alerts to Copilot or any other agent. The alerts documentation says an assigned agent opens a draft pull request, and assignment can require a paid license.
- Code scanning, if the control requires GitHub Code Security or another paid license.
- Secret Protection and Code Security license toggles.

Do not enable auto-merge. A version-update pull request, if one is ever proposed, is a separate review. This checklist does not open one.

## S5. Required status check on main

USER step. UNVERIFIED. The protection read was HTTP 403 and the ruleset list was empty. Neither result authorizes this task to create a rule.

The owner edits the existing classic protection rule for `main`, or creates one if the Branches page shows none. Do not add a second ruleset on top of a classic rule in order to "make sure". One mechanism is enough. If a ruleset is used instead, it has to produce the same outcome. This task found no ruleset and could not see the classic rule.

Navigation from [Managing a branch protection rule](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/managing-a-branch-protection-rule), read 2026-11-12: repository Settings, the Branches protection page, then the rule whose pattern is `main`. If the sidebar says Rules rather than Branches, record the label that is actually there and edit the `main` rule in that UI.

Set or confirm all of the following:

- Require status checks to pass before merging: on.
- Require branches to be up to date before merging: on. This is the strict setting. The loose setting is the same checkbox left off, and it is not acceptable here.
- In the status-check search, select the check whose name is exactly `cf-ci-gate`. Do not select a similarly named job. Do not require `cf-tests (head)` or `cf-tests (merge)` in place of the gate. The gate is the stable name. It runs with `if: always()` and passes only when the test jobs' result is `success`.
- If the page offers a source for that check, choose GitHub Actions. Do not choose Any source when Actions is listed. Any source lets any writer post a check with the same name.
- Do not allow bypassing the above settings: on. This applies the rule to administrators.
- Allow force pushes: off.
- Allow deletions: off.
- Do not add the publisher app, the planner app, or the owner to a bypass list.
- Leave "Require a pull request before merging" on if it is already on. This task could not read the current review count and does not change it.
- Save.

GitHub's own protection documentation says a required check in `success`, `skipped`, or `neutral` meets the rule. That is why the gate job has to be the required check, and why a skipped Actions run is still not business acceptance.

After saving, an admin read of the protection resource may record only these fields: HTTP status, `required_status_checks.strict`, the required check name `cf-ci-gate`, the check source if shown, `enforce_admins`, `allow_force_pushes`, and `allow_deletions`. Do not paste the rest of the payload. User lists and URLs stay out of the note.

## S6. Auto-merge

USER step. The API field is verified false. The settings page was not opened, so the UI confirmation is UNVERIFIED.

Confirm the repository setting "Allow auto-merge" is off. The public payload field `allow_auto_merge` was false at the read above. Leave it false. Do not turn on a merge queue as part of this checklist.

## S7. Repository variables and secrets

USER step. Do not perform a change. UNVERIFIED for the current variable values. P0-C recorded `GET /repos/yunyidamowang/contractorflow-studio/actions/variables` as HTTP 403 and did not read the values. This task did not call that route again and did not set `CF_INTAKE_ENABLED`, `CF_AUTOMATION_STOP`, `CF_ALLOWED_ACTORS`, or any secret.

Leave those variables unset or unchanged. Do not add `codex-ready`. Do not run the dispatcher.

## Owner evidence still missing

The owner still has to record, in the redacted form above:

- Secret scanning alerts: on, off, or purchase-blocked.
- User push protection: on or off.
- Repository push protection: on, off, or purchase-blocked.
- Dependabot alerts: on, off, or purchase-blocked.
- Dependabot security updates: off.
- Auto-merge: off, confirmed on the settings page.
- `cf-ci-gate` required on `main`, strict up to date, no admin bypass, force-push off, deletion off, and the check source if the page shows one.

Until those notes exist, this checklist is not done.
