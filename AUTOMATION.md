# Grok → Codex 自动开发：首轮受控配置

## 2026-11-07 快照修复待审

只读GET最多3次、0.5/1秒退避、遵守任务截止时间；写请求不重试。加入脱敏错误分类、blob及完整Git树校验、相同SHA去重、完整下载后写入。38项测试通过；固定d158043快照66/66真实只读预检通过，独立Git校验一致，账本未变、模型未调用。enabled=false、canary=4；最后一次canary仍须合并修复并另获用户批准。详见handoff/outbox/CF-20261107-005.md。

## 2026-11-07 公开仓库适配（已公开，真实 canary 等待加标）

最新实查：仓库 Public；main 要求 PR、审批人数0、管理员不得绕过、禁止强推与删除，自动合并关闭。所有者网页直接提交被拒绝；项目 PAT 对 main 同 SHA 的无变更更新返回 HTTP 422 `Changes must be made through a pull request.`，main 未变。专用 ChatGPT 登录成功，7天单仓库 PAT 已验证、0600保存，旧暴露 Token 已从列表移除。原生隔离探针及33项固定测试通过。已在 Issue #4 回复 `canary ready`，仅临时 enabled=true，保持 canary=4 和原限额；未启动长期轮询。真实模型/自动草稿PR/worker结果尚待一次执行验证。公开适配在 PR #6，本机从该分支运行；PR #6 不是 canary 产物。

用户已明确接受审查报告列出的历史个人邮箱、身份与商业资料随原仓库公开；GitHub最终公开确认由用户亲自完成。代码仅接受精确的 `yunyidamowang/contractorflow-studio` **公开**仓库，拒绝其他仓库、仍为私有或无法核实可见性的响应；旧版仅接受私有仓库的检查已相应调整。以下私有仓库背景作为历史记录保留，不表示已完成迁移。

公开会增加不可信Issue/评论，作者和最后加标人白名单、canary_issue=4、路径限制及原限额不变。公开源码不等于上线网站或接入真实客户。真实canary未通过前不能开放其他任务；本次单次执行结束后恢复enabled=false。

当前：**默认关闭，尚未授权 Grok 无人值守执行**。配置在开发分支/草稿PR审核，不能把模拟当作真实账号端到端通过。无生产部署、无API购买、无常驻服务安装，也未复制现有Codex凭据。

## 方案决定与官方依据

1. 首选Mac本机独立Codex CLI + ChatGPT登录 + Python标准库轮询。复用已有CLI 0.144.6，无gh/Docker/模型安装。每120秒检查一个指定私有仓库，开机、联网且终端运行时接单，休眠/关机不能执行；唤醒后继续扫描持久队列。
2. `.github/workflows/codex-intake.yml` 是Issue labeled登记器，不checkout代码、不调用模型，仅校验并回写接收信息。本地轮询独立重新核验；Actions不可用时仍能通过GitHub标签轮询，不需要用户转发聊天。
3. 已研究官方 `openai/codex-action`，源码固定为 `13e9c17417b29e9a276f73ec6ed7fb574137d3c3`。`automation/codex-cloud.yml.example` 提供关闭的只读手动探针，**不是已开通的自动开发后端**。未放进workflows目录，不设置API密钥。未来若选择API付费，须单独批准并配置预算/权限，再扩展隔离生成补丁、独立测试和PR发布的多作业方案。

官方说明：[Codex Action](https://learn.chatgpt.com/docs/github-action)、[非交互与ChatGPT账号认证](https://learn.chatgpt.com/docs/non-interactive-mode)、[登录凭据](https://learn.chatgpt.com/docs/auth)、[受限文件权限](https://learn.chatgpt.com/docs/permissions)。官方支持高级ChatGPT账号自动化认证；它不表示GitHub托管Action自动继承本机会员。账号配额/可用模型和实际计费未从本账户验证。

GitHub权限依据：[GITHUB_TOKEN](https://docs.github.com/en/actions/concepts/security/github_token)、[Actions设置](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/enabling-features-for-your-repository/managing-github-actions-settings-for-a-repository)。不使用pull_request_target，不将Mac注册成通用self-hosted runner。所有第三方Actions固定完整SHA。

## 一次性、必须由用户完成的授权

- 先审核并手动合并本配置PR（程序没有merge接口）；目前自动化代码只在开发分支，main不自动更新。
- 双击 `Automation Login.command`，在官方页面使用现有ChatGPT账号登录**项目独立**CODEX_HOME。该目录强制ChatGPT认证；不读取/复制全局auth.json。现有全局CLI模型配置报错，独立配置已绕开且未修改原设置。新登录未完成前，不能确认会员剩余额度或真实模型调用成功。
- GitHub网页创建fine-grained PAT，仅选 `contractorflow-studio`：Contents、Issues、Pull requests读写及自动Metadata读取；不给管理、删除、Actions/Workflows权限。设置短有效期。双击 `Automation GitHub Token.command` 隐藏输入，仅本机0600保存。不要贴到聊天或Issue。此PAT有Contents权限，GitHub层面仍需分支规则保护main；调度器自身只提供新codex分支创建，无main写入/合并能力。
- 创建 `codex-ready`、`codex-stop` 标签。获取Grok实际GitHub身份，与用户身份一并列入 `.automation/settings.json` 的allowed_actors；不能根据Bot名称猜测身份。第一轮仅allowlist仓库所有者。
- 在GitHub设置保护main：PR人工审核、禁止直接推送/force push、禁自动合并。检查账号Actions预算并设置停止超额支出；不新增付费额度。首选本机模式无API密钥，不会自动切换API，但账号自身额外积分/自动充值仍须用户检查。
- 可选启用登记器：仓库变量 `CF_INTAKE_ENABLED=true`、`CF_ALLOWED_ACTORS=["实际账号"]`；`CF_AUTOMATION_STOP=true`停止登记。登记器仅提示，本机关闭时不会开发。未启用不影响本机标签轮询。未把 `CF_INTAKE_ENABLED` 设为字符串 `true` 时，intake 作业保持 skipped。每次 labeled 运行另有 `gate-report` 作业，只在 Actions 摘要写出哪一条门控未通过或未知。该作业的环境变量只有布尔表达式结果，不放入 `CF_ALLOWED_ACTORS` 原值、actor、author 或标签列表。allowlist 不是合法 JSON 时，`fromJSON` 在写摘要之前让作业失败，这是关闭失败。不写 Issue。

不要求用户逐任务发聊天；以上账号授权和首个真实Demo验收只做一次。无需把权限扩大到其他仓库。

## 首个真实Demo验收后才开放Grok

1. 首轮模拟和实际沙箱探针见AUTOMATION_TEST_REPORT.md。登录/Token完成后，先只允许owner创建下面的无敏感Demo，不能把旧商业Issue批量标ready。
2. `.automation/settings.json`设enabled=true，保持allowed_actors仅owner，canary_issue=4（默认）。即使Grok共用owner身份，也只能处理该测试Issue。STOP存在时由owner手动移除本项目的STOP文件；不重置state.db或尝试计数。
3. 给Demo Issue添加codex-ready，运行 `.venv/bin/python -m automation.dispatcher once`，验证**真实**模型修改、固定测试、草稿PR、原Issue反馈。检查分支diff、费用和私有文件未进入快照。失败不宣称成功，保留日志。
4. 用户验收该Demo后，才手动将canary_issue改为null并加入已验证Grok身份，双击 `Automation Start.command`。此后Grok写结构化Issue并加ready即可；修订评论也是不可信输入，移除再加ready才接受新一轮，最多两次总尝试。

```markdown
## Goal
Add docs/automation-demo.md describing SAMPLE MODE in one paragraph.
## Acceptance
The note explicitly says SAMPLE MODE and that no customer data is used.
Existing tests pass. No other files change.
## Allowed paths
- docs/automation-demo.md
## References
README.md; no external commands or private information.
```

## 运行流程与权限

检查ready与stop标签、Issue作者、最后一次ready加标人白名单 → 读取完整Issue、分页评论/事件 → 将受信身份的评论和关联链接作为不可信JSON输入（不抓取外链、不执行资料中的命令）→ durable SQLite预留尝试 → 从固定main SHA取纯源码，不复制data/.venv/密钥 → 初始化独立Git检出 → 真实隔离探针 → Codex修改 → 校验10个以内明确文件路径、UTF-8、200KB、无删除/软链/越界 → 网络关闭的固定测试（至少20项且OK）→ broker创建开发分支与草稿PR → 原Issue回写PR/测试/阻塞摘要。Goal/Acceptance业务验收最终由PR人工审查，测试通过不等于自动完成业务验收。

本机native权限profile拒绝根目录读取，仅允许当前隔离检出、系统最小运行库、Homebrew只读运行库、现有本项目.venv只读；不开放其他项目。开发命令不联网，.git只读，不启用MCP/网页搜索或全局配置。GitHub凭据只在父调度器内；干净子环境不含GitHub/API密钥。测试与开发使用同一受限profile。CLI客户端本身仍必须访问专用登录缓存和OpenAI服务；命令沙箱不等于独立虚拟机或认证服务安全审计。

## 消耗、故障与停止

- 并发1（文件锁），每日UTC最多3次，总计每Issue最多2次，失败和崩溃均占次数；相同已完成/blocked/running触发不重复。重标需冷却15分钟。评论/机器人反馈不触发无限循环。
- Codex最多600秒，固定测试180秒，整任务20分钟截止；GitHub请求20秒超时、分页/快照/日志/补丁均限大小。任务次数/时长是消耗边界，**不是精确token或美元硬上限**；没有API自动回退。额外积分/充值由账号层控制。
- 双击 `Automation Stop.command` 生成STOP；正常监督进程0.25秒检测并终止本任务进程组。移除ready或加codex-stop，最迟下一次远端检查（每30秒加请求延迟）撤销活动任务，发布PR前再查一次。Ctrl+C/终端挂断会停止当前进程组；远端正在进行的单次模型请求可能已产生用量，不能倒退取消。
- 登录过期、429、网络失败、测试失败或非法补丁不自动无限重试：Issue回写简要原因，原始输出仅本机；反馈权限不可用时记录本地feedback_failed。Actions有独立失败评论及运行日志；在GitHub启用失败通知。未实现独立邮件/短信告警。
- `.automation/audit.jsonl`元数据日志；state.db留尝试/PR状态；runs下留隔离源码、任务快照与测试/model日志。目录0700、Git忽略，无自动清理原件。日志不防篡改，原始模型输出可能含内容，不上传GitHub。
- 强制杀进程/断电不是本轮稳定性验收。持久running记录阻止同触发自动重跑，先人工检查孤儿进程/已创建PR；不删除账本绕过限额。休眠、重新登录、长期运行、真实模型及GitHub账号权限都仍待真实Demo验收。首轮不安装launchd，也不更改Mac休眠设置。

恢复：修复问题→检查是否已有PR→重新授权加标；最多剩余一次。紧急撤权同时STOP、撤销项目PAT、退出项目专用Codex登录。只给GrokIssues权限，不授予它本机命令入口。

## P0-B / CF-20261108-018 (2026-11-11)

Added task-wide POSIX ITIMER_REAL/SIGALRM watchdog, default total_timeout_seconds=1200 (30..1200 allowed), starting at durable attempt reservation. Checks every 100ms and interrupts blocking supervisor I/O across snapshot, preparation, model, tests and publication. Per-phase limits remain. Child/git process groups receive TERM then KILL after at most 3s even if the leader exited; timer delivery is deferred during bounded group cleanup. Kernel uninterruptible operations, interpreter-native code that never handles signals, and descendants deliberately escaping the process group are not claimed as VM-level isolation.

STOP lstat failures stop safely. Any open repository Issue labeled codex-stop is a global stop; current task authorization is also checked. Remote monitoring polls every 2s, errors stop, and stale results >25s stop even if network stalls; each POST performs a fresh remote check. No new permissions or dependencies. Failure notification is best-effort after stopping, with no task publication retry. Existing attempt quota is retained. Task stop reasons are sanitized audit events.

Archived draft note, not a current result and not an open CI task: before the final P0-B head, one local run was recorded as 67/67 with 10 new guard tests, and CI had not run yet when that draft sentence was written. That count was superseded before merge. The merged result is 68/68. Review head 970a772fa59061bb51c5984f5f1a67590ef2636e passed cf-tests (head), cf-tests (merge), and cf-ci-gate on runs 43034624833 and 43035695029. Squash-merged as 0c4fe5c4797e442c4ab61fca1e250a0a22109cbd; main push run 43035715958 succeeded.

## P0-C intake gate report (2026-11-11)

The intake job still registers a task only when the repository is `yunyidamowang/contractorflow-studio`, `CF_INTAKE_ENABLED` is the string `true`, `CF_AUTOMATION_STOP` is not the string `true`, and the event label is `codex-ready`. Those four clauses and the job's `issues: write` permission are unchanged. `gate-report` has no `if`, `permissions: {}`, and no checkout. It writes the Actions step summary from booleans computed in the workflow expressions and does not comment, label, or edit the repository. The step environment does not contain `CF_ALLOWED_ACTORS`, the actor, the author, or the label list. An unset allowlist is treated as an empty JSON array, so membership is false and the configured flag is false. A non-empty value that is not valid JSON makes `fromJSON` fail the job before the summary is written; that is fail-closed, and the Actions error is the reason. The summary itself prints only passed, blocked, or unknown. The intake job is unchanged, including its existing environment variable, and still runs only when its own `if` passes. This change does not set repository variables and does not change `enabled=false` or `canary_issue=4`.

Two completed intake runs on issue #4 are skipped with no steps: https://github.com/yunyidamowang/contractorflow-studio/actions/runs/42333078469 and https://github.com/yunyidamowang/contractorflow-studio/actions/runs/42366943272. Both followed a `codex-ready` label by yunyidamowang within two seconds, so the label and repository clauses matched. Actions variables were not readable (HTTP 403), so which of the enabled or stop variables failed is unknown. An unset enabled variable would fail its clause; an unset stop variable would not.

## P0-B2 follow-ups (2026-11-11)

SIGALRM is blocked before a session is spawned and stays blocked until the cleanup frame holds the pid. The child is given the mask from before that block, via `posix_spawn` `setsigmask`, so a descendant is not left unable to receive SIGALRM. Cleanup is still TERM, then KILL after at most 3 seconds, including when the leader has already exited.

`GET /labels/codex-stop` must return a label named `codex-stop`. A missing label, a lookup error, or any open issue carrying the label is a global stop. `once()` audits that locally and does not post a GitHub comment. A running task's best-effort failure comment is unchanged.

The draft-PR request and the status/audit record that follows it run with SIGALRM blocked. The audit line is one complete append. A published attempt stays `pr`, so the same trigger is not published again.

`CF_ALLOWED_ACTORS` must be a JSON array before `contains` or `includes` can match. A string, object, number, boolean, or null allowlists nobody. Invalid JSON still fails `fromJSON` before the gate summary is written. The intake job `if` string and `issues: write` permission are unchanged. Workflow permissions are unchanged. `pull_request_target` is not used. `.github/workflows/ci.yml` is unchanged. `enabled` remains false and `canary_issue` remains 4.

## P0-D identity and security documentation (2026-11-12)

Dual identity is not solved. The pilot stays disabled. The owner checklist and the target App permissions are `docs/automation/P0_IDENTITY.md` and `docs/automation/P0_SECURITY_SETTINGS.md`. The fine-grained token steps earlier in this file describe the current disabled supervisor, which still reads one bearer token. They are not the target identity, and they are not permission to create a classic personal access token. Future commits in this public repository use a GitHub noreply address. History is not rewritten. Credential files stay mode 0600 and their directory mode 0700, with the OS credential store preferred once a reviewed reader exists. No app, token, account, label, variable, secret, or branch rule was changed. `enabled` remains false and `canary_issue` remains 4.

## P1a queue, claim, lease, and fencing (2026-11-12)

This slice is single-machine only. A local `flock` plus `BEGIN IMMEDIATE` stops two processes on one machine from both claiming the same key. It does not provide multi-machine distributed mutual exclusion. A copied database, a second host, or a clock that moves backwards fails closed.

The queue is off unless settings contain `task_queue.enabled` set exactly to true and a database path that is not named `state.db`. `automation/settings.example.json` does not contain that key. With the feature unconfigured, `run_issue` still uses the existing `runs` reservation and does not import the queue. `enabled` remains false and `canary_issue` remains 4. The dispatcher does not migrate a database. `migrate_up` and `migrate_down` are explicit, create or drop only the new v1 tables, and are tested on fixture databases. They refuse a file named `state.db`. Existing `runs` and `notices` rows are not modified, deleted, or renumbered.

The unique key is `(repo, issue, authorization version, trigger)`. The default authorization version is the existing ready-label event id. `activate` inserts the attempt as `claimed` and commits it before it returns. A later call does not adopt that row, so a restart does not continue it and does not start the model again. Reserved rows are not deleted or refunded. Lease default is 120 seconds. Heartbeat default is 30 seconds and does not change the fencing token. The token increases when a claim is granted and when the row becomes `blocked`, `stopped`, or `interrupted`. A publish callback runs only while the token, owner, and `publishing` state still match. An expired lease moves `queued`, `claimed`, `snapshot`, `model`, `testing`, `publishing`, and `feedback_pending` to `interrupted`. `review`, `blocked`, `stopped`, and `interrupted` stay as they are. An unknown state is treated as `blocked` and, on reconcile, is stored as `blocked`. Reconcile never claims a row and never starts a model.

States: `queued`, `claimed`, `snapshot`, `model`, `testing`, `publishing`, `feedback_pending`, `review`, `blocked`, `stopped`, `interrupted`.

Not in this slice: POST reconciliation after a publish whose result is unknown, a launchd sample, and an audit export or hash-chain anchor. Those remain follow-ups. No once, watch, model call, ledger migration, label, variable, secret, or branch-rule change was run.

## P1b publish uncertainty, feedback repost, and circuit breaker (2026-11-12)

This slice stays off unless settings contain `publish_reconcile.enabled` set exactly to true and `task_queue.enabled` set exactly to true. `automation/settings.example.json` contains neither key. `enabled` remains false and `canary_issue` remains 4. The dispatcher does not migrate a database and still refuses a file named `state.db`.

A create POST is one attempt. `GitHub.api` still retries a read-only GET at most three times. That retry loop is not used to repeat a branch create, a pull create, or a comment create. If a publish write times out, or the process cannot tell whether it landed, the attempt becomes `publish_unknown` and further creates for that task stop. Reconciliation then uses read-only GETs of the recorded branch name, commit, linked draft PR, and the feedback marker `<!-- cf-codex-feedback -->`. A proved match is stored and the attempt moves to `feedback_pending`. A proved absence, or a branch with no matching draft PR, stays blocked for a person. An undecided read stays blocked. None of those outcomes sends the create again, and none starts the model again.

If the draft PR is already recorded and the redacted feedback comment failed, the only automatic write is that same redacted comment. It is sent only when a read shows the feedback marker is absent. The queue counts each send before the POST, allows at most two, and also refuses a send more than 24 hours after the first. The count is not reset. The acceptance comment uses the older worker marker and does not count as this feedback.

The circuit breaker is a mode-0600 file beside the queue database, or the path in `publish_reconcile.breaker`. It is not `state.db`. These events latch it: auth failure (HTTP 401 or 403), `main` no longer protected, repository policy drift (`full_name`, visibility, or `allow_auto_merge`), ledger corruption or a schema the process will not alter, a duplicate claim while the breaker is attached, a write that cannot be reconciled, or a failed trusted-test result. The first reason is kept. No function in this repository deletes or rewrites that file. Clearing it is a manual owner step: stop the worker, set `enabled` false, read the one-line reason, review the queue row, and delete only that breaker file. Deleting the queue database is not the clear procedure. A later process still sees the latch.

`publish_unknown` is not turned into `interrupted` when its lease expires, and an expired `publishing` row that already recorded a branch becomes `publish_unknown` instead of losing that name. Reserved attempts are not deleted or refunded. `once()` calls the read-only recovery only when this feature is exactly enabled and the global stop is not active. This change did not run `once` or `watch`.

A queue file created by the P1a migration does not gain the new columns automatically. Opening that file fails closed. There is no automatic `ALTER`. Launchd and the audit hash chain remain later work.

## P1c audit chain, ledger proof, and launchd sample (2026-11-12)

This slice stays off unless settings contain `audit_chain.enabled` set exactly to true, and the queue or publish path that should record into the chain is itself exactly enabled. `automation/settings.example.json` contains none of `audit_chain`, `task_queue`, or `publish_reconcile`. `enabled` remains false and `canary_issue` remains 4. The dispatcher does not call `once` or `watch` from this change, and it still does not migrate a database.

When `audit_chain.enabled` is exactly true, queue transitions append one versioned record in the same transaction: claim, lease renew, lease expiry, fencing reject, each run state, `publish_unknown`, reconcile result, feedback retry, and breaker latch. Each record stores the hash of the previous record. `verify_export` is read-only. It reports the first tamper, deletion, reorder, or truncation and does not repair the file. A chain that fails that check cannot be opened for work. Records are limited to short allowlisted labels. They do not store tokens, email addresses, or secret values. With the key omitted, the chain table exists after an explicit `migrate_up` but stays at its genesis tip, and queue behavior matches the previous slice.

`automation/ledger_proof.py` is not called by the dispatcher. It takes a read-only backup of a legacy database, writes an export of the `runs` and `notices` rows, and runs `migrate_up` / `migrate_down` only on a copy. The proof is that those row values and the attempt count are unchanged, and that the migration on the copy can be reversed. It does not claim the original file's whole-file hash stays the same. A file named `state.db` is refused unless the caller passes `fixture=True`. A path inside `.automation` is always refused.

`docs/automation/com.contractorflow.studio.sample.plist` is an example user LaunchAgent. It is not installed. Nothing in this repository loads it. `KeepAlive` is false. Start and throttle intervals are 120 seconds. The sample program exits when a breaker file is present and does not start the dispatcher. It does not run `caffeinate` or change sleep settings. The plist has no `NetworkState` key; that kind of hint would not prove GitHub is reachable. Installation remains a separate future owner decision, described in `docs/automation/P1_LAUNCHD.md`.

The acceptance tests use temporary databases, `SIGKILL` after a committed stage, and an in-memory HTTP stand-in. They are not a Mac power-loss test and not a live GitHub test.
