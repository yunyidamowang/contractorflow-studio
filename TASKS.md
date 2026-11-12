# Tasks

P0-A (#10 / CF-20261107-011) in development: exact trusted test manifest, structured results and independent head/merge CI. 38 original names retained, 3 new validator tests registered. CI runtime evidence pending; no P0 completion claim. enabled=false/canary=4; historical canary records untouched. See docs/automation/P0_CI.md.

## 2026-11-07 快照修复待审

只读GET最多3次、0.5/1秒退避、遵守任务截止时间；写请求不重试。加入脱敏错误分类、blob及完整Git树校验、相同SHA去重、完整下载后写入。38项测试通过；固定d158043快照66/66真实只读预检通过，独立Git校验一致，账本未变、模型未调用。enabled=false、canary=4；最后一次canary仍须合并修复并另获用户批准。详见handoff/outbox/CF-20261107-005.md。

最新自动化状态（2026-11-07）：公开和main保护真实验证通过；项目ChatGPT认证、新单仓库PAT验证通过，旧暴露凭据已移除。33项测试OK（0.909秒）、原生隔离探针PASS。Issue #4 已回写canary ready，等待Grok加标；仅canary=4临时启用，无watch。尚未执行真实模型和自动PR；以下旧阶段记录保留作历史。

更新：2026-11-06（Asia/Shanghai）

| 编号 | 类型 | 内容 | 负责人 | 状态/验证 |
|---|---|---|---|---|
| CF-001 | DEV | 环境检查、独立 Git 和虚拟环境 | Codex | 完成；arm64/macOS 27.0.1，Python 3.12；约 48 GiB 可用 |
| CF-002 | DEV | 协作格式、Issue 模板、文件入口 | Codex | 完成；HANDOFF 和 handoff/ |
| CF-003 | REVIEW | 11 项开源组件评估 | Codex | 官方Atom已直接核实11项维护时间，见maintenance_snapshot.json |
| CF-004 | DEV | 内部后台与三套 Demo | Codex | 完成 API 实现与模拟交付 |
| CF-005 | TEST | 隔离、金额、审批、恢复测试 | Codex | 20 项集成测试通过（含第二轮新增审批/隔离/报价包/缺项） |
| CF-006 | TEST | 浏览器桌面/移动端点击与视觉验收 | Codex | 真实Chrome桌面及390px手机视口验收，见TEST_REPORT |
| CF-007 | APPROVAL | 创建并推送私有 GitHub 仓库 | 用户/Codex | 已授权，私有仓库已建立；源码、测试、协作文档同步至 main |
| CF-008 | MARKET | 首个细分客户需求与套餐边界 | Grok | 已收到Issue #1/#3；关键工作流核验见REQUIREMENTS_REVIEW，不重复市场研究 |
| CF-009 | BRAND | 品牌、英文文案、美国/澳洲名称冲突证据 | Grok | 已收到Issue #2；用户确认仅候选名，不对外发布 |
| CF-010 | REVIEW | 对真实数据使用做安全复核 | Codex/用户 | 未开始；须在任何真实数据接入前 |
| CF-011 | DEV | 按首个需求补强文件信息提取、业务耗时展示 | Codex | 待需求验证；当前邮件模板分类和日期清单能力有限 |
| CF-012 | TEST | 并发、持续运行、断电恢复、依赖漏洞检查 | Codex | 未运行；真实运营前必做 |

本地演示完成不代表商业验证、商标确认或生产上线。GitHub URL 只能在真实创建并回读后记录。

## 第二轮开发验收

| ID | 工作 | 责任人 | 状态 |
|---|---|---|---|
| CF-R2-P0 | SAMPLE MODE、导出样本标识、审批、隐私说明 | Codex | 已实现；测试见TEST_REPORT |
| CF-R2-A | 报价包/附件/假设排除/缺项/ZIP | Codex | 已实现；仅确定性给定数据 |
| CF-R2-B | 六状态看板、日期/账龄/无下一步筛选、三语气编辑重审 | Codex | 已实现；不发送 |
| CF-R2-C | 照片人工槽位、缺项/例外、命名前后对照 | Codex | 已实现；不推断工程或批准开票 |
| CF-R2-DEMO | 3分40秒脚本与候选品牌配置 | Codex | DEMO_WALKTHROUGH/CF_BRAND |
| CF-R2-REVIEW | Grok遗漏、冲突与来源核验 | Codex | REQUIREMENTS_REVIEW；Allstate及全部12条未全部独立复核 |

生产安全未完成工作独立维护于PRODUCTION_BACKLOG.md；不会关闭尚未完成验收的Issue。

## 自动开发首轮（2026-11-07）

| ID | 内容 | 状态 |
|---|---|---|
| CF-AUTO-CONFIG | 标签登记、白名单、本地受限CLI、预算/锁/停止、草稿PR及反馈 | 实现，默认关闭；待配置PR审核 |
| CF-AUTO-TEST | 普通/真实受限环境测试、登记脚本和非敏感模拟 | 见AUTOMATION_TEST_REPORT；不冒充真实模型E2E |
| CF-AUTO-AUTH | 专用ChatGPT登录、单仓库PAT、Grok真实身份、main保护 | 待用户一次性授权/核实 |
| CF-AUTO-DEMO | Issue #4真实模型→测试→PR→Issue反馈 | 待授权；未加codex-ready |
| CF-AUTO-OPS | 长期运行、休眠/重启、凭据过期及断电恢复 | 未验收；首轮不安装后台服务 |

## CF-20261107-001 实查更新

PR #5 已合并，main 与本地源码树相同，Git历史同步尚缺本机凭据。真实浏览器确认当前私有仓库分支保护不生效；Actions预算为$0且Usage blocked。依用户要求不扩大自动化权限，保留enabled=false、canary_issue=4、owner白名单及限额。33项测试、登记器模拟、原生CLI隔离探针通过；真实模型/草稿PR/worker反馈未运行。详见handoff/outbox/CF-20261107-001.md；Issue #4 已回写阻断，不加执行标签。

## 公开仓库恢复准备

用户已明确接受公开前审查发现的历史邮箱、身份说明和商业资料，选择公开原仓库。公开前检查覆盖远程全部可枚举引用、7提交、113历史文件版本及全部Issue/PR讨论；未发现实际凭据。已补强.gitignore并适配调度器只接受原指定公开仓库，拒绝其他仓库或未确认可见性；33项测试通过（1.445秒）。GitHub最终确认交用户亲自操作；main保护、专用认证和真实canary待后续，不启动长期轮询。

P0-A blocked: local + Mac isolated 41/41 pass, but GitHub rejected workflow upload with existing PAT. Review PR contains policy only; CI pending authorized workflow installation. B/C/D paused; no permission expansion.

## CF-20261107-012 review revision

User authorized and confirmed adding Workflows read/write to the existing single-repository Token; GitHub displayed “Your personal access token has been updated”. Repository selection and 2026-11-14 expiry unchanged. The previous missing-permission blocker is superseded, but no workflow is installed until Grok reviews this revised candidate.

Candidate now adds push to main and per-PR/ref concurrency with cancel-in-progress. Push jobs both use the actual push SHA; PR jobs use head and merge revisions. Added 16 negative tests: missing/extra/renamed/duplicate names, duplicate manifest, removed baseline, same-count wrong names, run-count mismatch, skips/expected failures, failed parent process, missing/multiple/malformed/failed result. Pipeline negatives assert zero publication using only synthetic APIs and in-memory ledgers. Baseline test fixture accepts negative inputs without removing original assertions. Manifest now registers 57 tests including all original 38; original source hashes remain recorded. Local exact-manifest run: 57/57 in 1.763s. Actual CI remains NOT RUN pending candidate review and installation.

## P0-B / CF-20261108-018 (2026-11-11)

Added task-wide POSIX ITIMER_REAL/SIGALRM watchdog, default total_timeout_seconds=1200 (30..1200 allowed), starting at durable attempt reservation. Checks every 100ms and interrupts blocking supervisor I/O across snapshot, preparation, model, tests and publication. Per-phase limits remain. Child/git process groups receive TERM then KILL after at most 3s even if the leader exited; timer delivery is deferred during bounded group cleanup. Kernel uninterruptible operations, interpreter-native code that never handles signals, and descendants deliberately escaping the process group are not claimed as VM-level isolation.

STOP lstat failures stop safely. Any open repository Issue labeled codex-stop is a global stop; current task authorization is also checked. Remote monitoring polls every 2s, errors stop, and stale results >25s stop even if network stalls; each POST performs a fresh remote check. No new permissions or dependencies. Failure notification is best-effort after stopping, with no task publication retry. Existing attempt quota is retained. Task stop reasons are sanitized audit events.

Archived draft note, not a current result and not an open CI task: before the final P0-B head, one local run was recorded as 67/67 with 10 new guard tests, and CI had not run yet when that draft sentence was written. That count was superseded before merge. Local enabled=false/canary_issue=4/settings and the attempt ledger were unchanged. No once/watch/model/real-data/deployment/merge.

P0-B final local evidence: 68/68 tests (1.786s); native Mac isolation probe PASS and exact-manifest 68/68 (25.425s), code ab34825. Initial native run exposed denied killpg(...,0) probe; fixed by conservative bounded escalation without changing sandbox policy, with a new regression. Original 57 tests unchanged. Ledger hash unchanged; enabled=false/canary=4. Final-head CI later passed: review head 970a772fa59061bb51c5984f5f1a67590ef2636e, runs 43034624833 and 43035695029 (cf-tests head, cf-tests merge, cf-ci-gate). Squash-merged as 0c4fe5c4797e442c4ab61fca1e250a0a22109cbd; main push run 43035715958 succeeded. The archived draft note above is the only place that count appears.

## P0-C / CF-20261111-021 (2026-11-11)

Intake runs 42333078469 (2026-11-07T03:14:30Z, d158043) and 42366943272 (2026-11-07T11:09:00Z, 2392dbc) completed skipped. The intake job had no steps. Issue #4 was labeled `codex-ready` by yunyidamowang at 03:14:28Z and 11:08:58Z. The repository was yunyidamowang/contractorflow-studio. The job `if` at both SHAs is unchanged, so those skips are `CF_INTAKE_ENABLED` not equal to the string true, `CF_AUTOMATION_STOP` equal to the string true, or both. GET /repos/.../actions/variables returned HTTP 403. The variable values were not read and are not recorded.

Inference, not a fact: an unset enabled variable fails the enabled clause, and an unset stop variable does not fail the stop clause. No record in this repository shows either variable being set.

`gate-report` always runs with `permissions: {}`, writes only the Actions step summary and a notice or warning of reason codes, and does not call the GitHub API. The intake job `if` and `issues: write` permission are unchanged. No repository variable, secret, label, dispatcher setting, or attempt ledger was modified. enabled=false and canary_issue=4 remain. No once, watch, or codex-ready label.

Review CF-20261111-023 required the gate-report environment to carry booleans only. `CF_ALLOWED_ACTORS`, actor, author, and label names are not step environment values. An allowlist that is not valid JSON fails `fromJSON` before the summary is written. Exact manifest 80/80 (1.429s) and unittest discover 80/80 (1.450s) on Python 3.12.16. Twelve intake-gate tests are registered; none of the previous names were removed or renamed. The `tests/test_intake_gate.py` baseline hash was updated to the revised file. ci.yml SHA256 remains 4576223a294403ed8e15536941da5d73110c9f157bbf1bc3a008872dce62260d. Draft PR: https://github.com/yunyidamowang/contractorflow-studio/pull/13 . Annotations on run 43038325637 are the runner notice that ubuntu-latest moves to Ubuntu 26, and a Node.js 20 deprecation warning for the checkout and setup-python actions pinned in the unchanged ci.yml. They are not produced by gate-report. A live gate-report summary is not observable until this workflow file is on main. That live run was not attempted.

## CF-20261106-007 sample marketplace assets (2026-11-11)

Fictional SAMPLE gallery for the $49 one-off trial. Three 1280×769 covers, four 1000×750 catalog images, and two 3-page PDFs under `assets/samples/`. Regenerated by `tools/samples/generate_samples.py` with vendored Liberation fonts (SIL OFL). The pictures use North Pine Demo Builders and job NP-1042. They do not show a studio brand, a contact method, a rating, or a third-party mark. Not published. Draft PR only. The generator is outside the trusted test manifest. Details: `handoff/outbox/CF-20261106-007.md` and `TEST_REPORT.md`.

## P0-B2 / CF-20261111-025 (2026-11-11)

Follow-ups from PR #12 review CF-20261111-020 (N1–N6) and the non-array allowlist note in PR #13 review CF-20261111-023. Spawn holds SIGALRM until the process-group cleanup frame exists, and the child mask is the pre-block mask. A real grandchild that ignores TERM is killed after the leader exits. A missing `codex-stop` label or a lookup error is STOP. `once()` does not comment while that stop is active. The PR status and audit line are written before a pending timer is delivered, and the attempt is not published twice. A JSON allowlist that is not an array allowlists nobody in the intake script and in gate-report. The intake `if` string was not loosened. ci.yml is byte-identical. enabled=false and canary_issue=4 are unchanged. No once, watch, model call, ledger edit, or codex-ready label.

Python 3.12.3: unittest discover 91/91 in 1.992s. Exact manifest runner 91/91 in 1.968s, `CF_TEST_RESULT` success true, count 91. `node scripts/test_intake.cjs` passed. Manifest 80 to 91, eleven new names, none removed or renamed. Baseline hashes updated for the four test files this change edited. macOS was not run. Dispatcher once/watch was not run.

## P0-D / CF-20261112-027 (2026-11-12)

Documentation for the repository owner. Dual identity is not solved. The pilot stays disabled: `automation/settings.example.json` remains `enabled` false and `canary_issue` 4. No app, token, account, repository variable, secret, label, or branch rule was created or changed. Intake diagnosis stays the P0-C result (PR #13); it was not redone.

`docs/automation/P0_IDENTITY.md` is the endpoint-to-permission matrix for planner, publisher, CI, and user, the two-app route, the single optional machine account, rotation and revocation drills, noreply commits, and 0600/0700 credential storage. `docs/automation/P0_SECURITY_SETTINGS.md` is the owner checklist for secret-scanning alerts, push protection, Dependabot alerts, and `cf-ci-gate` as a required check. Each of those is a USER step. Reads that returned HTTP 403, or `security_and_analysis: null`, are marked UNVERIFIED. The public repository payload did show `allow_auto_merge` false; the settings page was not opened.

Python 3.12.3: unittest discover 93/93 in 1.861s. Exact manifest runner 93/93 in 1.934s, `CF_TEST_RESULT` success true, count 93. Two new test names, none removed or renamed. `ci.yml` SHA256 remains `4576223a294403ed8e15536941da5d73110c9f157bbf1bc3a008872dce62260d`. macOS, Keychain, dispatcher once/watch, and the live `.automation` directory were not run or read. PR #7 was read only and was not closed, merged, or updated.

## P1a / CF-20261112-029 (2026-11-12)

Single-machine queue, atomic claim, lease, and fencing. New versioned tables only; the dispatcher does not migrate, and a database named `state.db` is refused. The feature stays off unless `task_queue.enabled` is exactly true. Example settings omit that key. `enabled` remains false and `canary_issue` remains 4. An expired lease becomes `interrupted` and is not a second model run. Reserved attempts are not refunded. Unknown state is `blocked`.

Python 3.12.3: unittest discover 109/109 in 2.236s. Exact manifest runner 109/109 in 2.162s, `CF_TEST_RESULT` success true, count 109. Sixteen new names, none removed or renamed. The new file's baseline hash was added. Other baseline hashes, `original_baseline_files`, and `baseline_tests` are unchanged. `ci.yml` SHA256 remains `4576223a294403ed8e15536941da5d73110c9f157bbf1bc3a008872dce62260d`.

Not in this slice: POST reconciliation, a launchd sample, and audit export. Not run: macOS, dispatcher once/watch, a live model, a migration against a real ledger, and any write of repository variables, secrets, labels, or branch protection. PR #7 was not updated.

Head `983a0d63be29eb2ea00c5c263d8807e30420f47f`: Actions run https://github.com/yunyidamowang/contractorflow-studio/actions/runs/43163109679 completed at 2026-11-12T13:41:59+08:00. cf-tests (head), cf-tests (merge), and cf-ci-gate all succeeded.

## P1b / CF-20261112-032 (2026-11-12)

Unknown GitHub writes do not start a second model run and do not repeat a create. The attempt becomes `publish_unknown` and is reconciled with read-only GETs. A proved object is recorded and moves to `feedback_pending`. A proved absence or a branch without a matching draft PR stays blocked, with no automatic resend. An undecided read stays blocked. The redacted feedback comment can be posted again only when its marker is absent, at most twice, and never by restarting the model. Auth, protection, or policy drift, ledger corruption, a duplicate claim, an unreconcilable write, and a failed safety test latch a breaker file. No code path clears that file.

The path stays off unless `publish_reconcile.enabled` and `task_queue.enabled` are both exactly true. Example settings omit both keys. `enabled` remains false and `canary_issue` remains 4.

Python 3.12.3: unittest discover 128/128 in 2.748s. Exact manifest runner 128/128 in 2.663s, `CF_TEST_RESULT` success true, count 128. Nineteen new names, none removed or renamed. The new file's baseline hash was added. Other baseline hashes, `original_baseline_files`, and `baseline_tests` are unchanged. `ci.yml` SHA256 remains `4576223a294403ed8e15536941da5d73110c9f157bbf1bc3a008872dce62260d`.

Not in this slice: a launchd sample and an audit hash chain. Not run: macOS, dispatcher once/watch, a live model, a migration against a real ledger, and any write of repository variables, secrets, labels, or branch protection. PR #7 was not updated. Issue #10 was not closed.

Implementation head `c025fbda7444df54b09d75bd80b2e0ac2f10a317`: Actions run https://github.com/yunyidamowang/contractorflow-studio/actions/runs/43194516350 completed at 2026-11-12T17:47:26+08:00. cf-tests (head), cf-tests (merge), and cf-ci-gate all succeeded. The commit that records this sentence is a later head. Its own Actions result is not claimed until that run finishes.
