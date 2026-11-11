# Test report

## 2026-11-07 快照修复待审

只读GET最多3次、0.5/1秒退避、遵守任务截止时间；写请求不重试。加入脱敏错误分类、blob及完整Git树校验、相同SHA去重、完整下载后写入。38项测试通过；固定d158043快照66/66真实只读预检通过，独立Git校验一致，账本未变、模型未调用。enabled=false、canary=4；最后一次canary仍须合并修复并另获用户批准。详见handoff/outbox/CF-20261107-005.md。

日期：2026-11-06，macOS arm64 / Python 3.12 独立环境。

已执行 `.venv/bin/python -m unittest discover -s tests -v`，11 项集成测试全部通过（测试使用临时数据目录）：

1. 3 家客户、30 条咨询、10 条种子邮件存在。
2. 无密钥 401，恶意 Host 400，外源写入 403。
3. 确定性金额 155.00、审批前拦截、非法状态转换、跨客户访问和 PDF/CSV/摘要导出。
4. 相同幂等键同内容不重复，相同键不同内容 409。
5. 缺失字段不可批准，负数/NaN/无穷/超限价格与错误日期拒绝。
6. 20 个合成图片跨 3 客户，精确去重、伪格式和超大文件拒绝、跨客户归档拦截、ZIP 字节与原始文件一致。
7. 备份恢复后逐文件哈希一致，禁止覆盖恢复目录，篡改备份拒绝。
8. 0.005 → 0.01，CSV 公式注入前缀处理。
9. 邮件规则分类、未发送草稿、待办、日报、成功操作日志。
10. Demo 营收幂等提交、冲突和错误月份拒绝。
11. 本地网页及资源路由 200、未知客户 404。

已执行模拟交付脚本：artifacts/demo-delivery 包含 3 套演示。脚本中的批准是模拟操作，不是真实用户审签。
PDF 已用 pypdf 提取验证 155.00，并用 Poppler 渲染人工查看单页：标题、表格、金额、英文说明可读，无可见裁切。渲染器有 fontconfig 缓存警告，输出可用。

已执行 node --check 检查两份前端 JS。真实本机 HTTP 请求返回 200，Uvicorn 成功监听 127.0.0.1:8765。浏览器预览工具超时，桌面/移动端视觉及点击交互尚未验收，不将 API 测试当作浏览器测试。

未执行：真实邮箱/真实客户数据、生产多用户隔离、并发负载、持续运行、重启、崩溃一致性、扫描件 OCR、恶意文档沙箱、依赖漏洞扫描、跨时区提醒、官网名称商标冲突审查。

限制：Starlette 测试客户端对 httpx 有弃用警告，当前测试可执行；未来升级时评估迁移。API 返回处理耗时响应头，界面展示平均交付历时（不是人工活跃工作时间）。数据库日志非防篡改。

最终复核：模拟交付脚本连续重复运行两次成功；业务库保持 3 客户、20 文件、43 条记录、3 条 Completed、0 条营业额记录；SQLite integrity_check=ok。已对该实际 Demo 数据目录执行离线备份与新目录恢复。最终 PDF（含备注）再次渲染确认。启动脚本通过 zsh -n。

## 第二轮验收：2026-11-06

使用独立真实 Google Chrome 会话（agent-browser 驱动），未使用用户已登录浏览器。Playwright CLI 下载因网络超时失败，改用已有浏览器工具完成。证据位于 artifacts/browser-qa（不提交Git）。桌面与390×844手机视口，均使用虚构数据。不是实体手机或Safari测试。

验证后台解锁、客户选择、逐行报价提交、人工批准、CSV/PDF/摘要下载、邮件草稿批准下载、PNG上传、文件交付批准与ZIP下载、待办、日报、官网本地需求表单；手机宽度390时document.scrollWidth=390。实际浏览器下载的PDF和CSV提取到155.00，邮件有Not sent标记，ZIP含index.csv。前端未捕获页面异常。

修复：旧客户响应覆盖、上传过程中客户范围漂移、接口错误提示；无效时区可导致500；并发幂等写竞争；图片像素阈值未严格拒绝；源文件损坏时原归档流程未核验哈希。报价输入改为逐行表单，审核显示可读预览。

自动化测试14项通过，新增异常时区、4路并发相同幂等键只生成一条记录、源文件篡改交付409。JS语法检查通过。测试工具曾误点新增行按钮，已修正为明确提交ID并断言生成报价；不把该工具失败算作产品通过。

仍未验收：多用户授权、实体移动设备、Safari、长期运行、断电恢复、真实客户数据安全和依赖漏洞扫描。此前第一轮浏览器未验收记录作为历史保留，以本节复核为准。

## Grok交接后的第二轮开发验收（2026-11-06，最新）

已按Issue #1/#2/#3正文及当时全部评论核验，来源可用性和未核验项见REQUIREMENTS_REVIEW.md。本节取代上文旧版本的功能/测试数量快照；保留历史记录。

- `.venv/bin/python -m unittest discover -s tests -v`：20项全部通过。新增覆盖SAMPLE配置与页面、报价附件跨客户404、六状态看板与无下一步筛选、三语气互异、编辑邮件后撤回审批并禁止导出、照片缺completion时invoice_ready=false、报价包审批门槛和CSV小计。既有金额舍入、幂等、越权、异常输入、备份恢复、篡改归档拦截继续通过。
- 最新版本再次运行 `scripts/browser_qa.py`：实际上传PNG、客户切换、审批/CSV/PDF/TXT/文件ZIP完整交付、待办/日报及官网需求表单通过；下载内容另行核对样本标签、155.00和ZIP索引。390px视口无页面溢出。
- `scripts/browser_round2.py`：真实Google Chrome，1440×900桌面和390×900手机视口，均通过看板筛选/状态保存/CSV下载、三种邮件语气生成→编辑→重新批准→实际TXT下载、PM声称完成但缺照片→审查→批准→实际PDF下载；检查导出SAMPLE文字、编辑内容保留和页面无横向溢出。浏览器未捕获页面异常。
- `scripts/browser_packet.py`：真实Chrome生成报价→人工按钮批准→下载ZIP；核验PDF/CSV的样本标识、155.00小计、源笔记和同客户附件存在。发现报价包CSV缺少小计行，已修复并新增断言、复跑通过。
- 照片PDF已改为六槽位表格，Poppler渲染后人工查看可读；pypdf核验样本页脚和completion缺项。字体缓存报错通过项目内临时字体配置解决，配置不进入业务依赖。
- 隔离临时数据目录以自定义CF_BRAND启动TestClient，验证替换生效及HTML转义。`node --check`两份后台JS、`zsh -n Start.command`、`git diff --check`通过。模拟交付脚本重复运行成功。

证据：artifacts/round2/results.txt、studio-1440.png、studio-390.png、quote-packet.zip、三语气TXT、照片PDF及预览；仅保留本机，虚构数据和密钥均不提交Git。部分浏览器工具点击/下载选择器最初命中错误元素，已改为稳定元素并断言下载内容；这些工具失败不计作产品通过。

未验收：实体手机/Safari、生产客户认证/分权、实际邮件发送、恶意文档防护、漏洞审计、长期负载/断电恢复、真实客户私人资料、品牌商标清权。系统无真实数据开关；SAMPLE标识不能自动检测私人内容。生产条件单列PRODUCTION_BACKLOG.md，Issue保持开放待用户与商业验收。

## 自动开发配置验收（2026-11-07）

独立结果见AUTOMATION_TEST_REPORT.md，区分普通测试、实际CLI权限探针、受限环境测试、显式模拟和仍未运行的真实账号E2E。未使用API、未购买额度、未允许Grok自动执行。

## 首次 canary 前置复核（2026-11-07）

本轮普通完整测试33项OK（2.518秒），登记器JS模拟通过；原生CLI隔离探针再次PASS。doctor仍无项目专用登录或Token。真实GitHub浏览器显示私有仓库保护规则不会生效，故未启动真实模型或once、未创建PR。Actions预算$0且Usage blocked。主分支源码树与当前本地一致，Git远端历史同步因无本机凭据未完成。详见handoff/outbox/CF-20261107-001.md；不将本轮检查视为真实自动开发闭环通过。

## 公开仓库适配验证（2026-11-07）

后续前置验收：仓库Public、有效main保护、项目ChatGPT认证及新PAT均真实验证；PAT无变更直接更新main返回422要求PR，main未变。原生隔离探针PASS，33项OK（0.909秒）。旧暴露Token已移除。已发送canary ready；真实模型及自动开发PR尚待Grok加标后的单次执行。

用户明确接受审查发现的信息后要求公开原仓库。调度器仅接受指定公开仓库，新增错误仓库、私有响应及缺失可见性字段的拒绝断言，保留Issue #4锁定检查。完整unittest仍33项OK（1.445秒）；git check-ignore验证认证、日志、数据库及新增.env变体/密钥忽略规则，git diff --check通过。仓库可见性、main保护和真实canary尚未因此验证通过。

## P0-A / Issue #10

41 local tests pass (38 retained baseline + 3 policy tests); exact manifest runner also exercised. New CI head/merge workflow pending actual GitHub execution. No automatic task/model run, no ledger changes. Native Mac validation recorded separately in P0_CI.md.

Native macOS archived-source isolation check passed; exact-manifest suite passed 41/41 in 25.384s. Ledger hash unchanged. GitHub PAT rejected workflow upload (missing workflow permission); CI not executed. P0-A partial implementation only; B/C/D paused.

## CF-20261107-012 review revision

User authorized and confirmed adding Workflows read/write to the existing single-repository Token; GitHub displayed “Your personal access token has been updated”. Repository selection and 2026-11-14 expiry unchanged. The previous missing-permission blocker is superseded, but no workflow is installed until Grok reviews this revised candidate.

Candidate now adds push to main and per-PR/ref concurrency with cancel-in-progress. Push jobs both use the actual push SHA; PR jobs use head and merge revisions. Added 16 negative tests: missing/extra/renamed/duplicate names, duplicate manifest, removed baseline, same-count wrong names, run-count mismatch, skips/expected failures, failed parent process, missing/multiple/malformed/failed result. Pipeline negatives assert zero publication using only synthetic APIs and in-memory ledgers. Baseline test fixture accepts negative inputs without removing original assertions. Manifest now registers 57 tests including all original 38; original source hashes remain recorded. Local exact-manifest run: 57/57 in 1.763s. Actual CI remains NOT RUN pending candidate review and installation.

Follow-up executed evidence: native Mac isolation probe PASS; archived code 99cee00 exact runner 57/57 in 27.115s. Full unittest discovery 57/57 in 1.425s. Ledger hash unchanged (b31ac93a3d6850f6053ed16b913970f1f424981a9a4e52d9c0d2c1df2066d3ca). CI still not installed pending Grok candidate review.

## P0-B / CF-20261108-018 (2026-11-11)

Added task-wide POSIX ITIMER_REAL/SIGALRM watchdog, default total_timeout_seconds=1200 (30..1200 allowed), starting at durable attempt reservation. Checks every 100ms and interrupts blocking supervisor I/O across snapshot, preparation, model, tests and publication. Per-phase limits remain. Child/git process groups receive TERM then KILL after at most 3s even if the leader exited; timer delivery is deferred during bounded group cleanup. Kernel uninterruptible operations, interpreter-native code that never handles signals, and descendants deliberately escaping the process group are not claimed as VM-level isolation.

STOP lstat failures stop safely. Any open repository Issue labeled codex-stop is a global stop; current task authorization is also checked. Remote monitoring polls every 2s, errors stop, and stale results >25s stop even if network stalls; each POST performs a fresh remote check. No new permissions or dependencies. Failure notification is best-effort after stopping, with no task publication retry. Existing attempt quota is retained. Task stop reasons are sanitized audit events.

Historical, superseded before merge: exact manifest 67/67 passed locally (1.992s), 10 new guard tests; original tests/hashes preserved. CI had not run when this sentence was written. Local enabled=false/canary_issue=4/settings and attempt ledger unchanged. No once/watch/model/real-data/deployment/merge.

P0-B final local evidence: 68/68 tests (1.786s); native Mac isolation probe PASS and exact-manifest 68/68 (25.425s), code ab34825. Initial native run exposed denied killpg(...,0) probe; fixed by conservative bounded escalation without changing sandbox policy, with a new regression. Original 57 tests unchanged. Ledger hash unchanged; enabled=false/canary=4. Final-head CI later passed: review head 970a772fa59061bb51c5984f5f1a67590ef2636e, runs 43034624833 and 43035695029 (cf-tests head, cf-tests merge, cf-ci-gate). Squash-merged as 0c4fe5c4797e442c4ab61fca1e250a0a22109cbd; main push run 43035715958 succeeded. The earlier "CI pending" wording is historical.

## P0-C / CF-20261111-021 (2026-11-11)

Python 3.12.16 after the CF-20261111-023 env fix: `.venv/bin/python -m unittest discover -s tests -v` 80/80 in 1.450s. Exact manifest runner 80/80 in 1.429s, `CF_TEST_RESULT` success true, count 80. `node scripts/test_intake.cjs` passed. `tests/test_intake_gate.py` has 12 methods. `test_gate_report_env_values_are_boolean_expressions` requires every gate-report environment value to be a `${{ ... }}` boolean expression (`==`, `!=`, `contains`, or `!contains`) and rejects an uncompared `vars.CF_ALLOWED_ACTORS`, `github.actor`, author login, or `toJSON` label dump. The report script no longer parses allowlist or label JSON. Other cases still cover intake disabled, wrong label, wrong actor and author, stop label, stop variable, wrong repository, closed issue, pull request, combined blockers, clear gates, unknown inputs, and an empty membership result. Sentinels placed beside the booleans are absent from the summary. Manifest grew 68 to 79 and then to 80. No test name was removed or renamed. The baseline hash for `tests/test_intake_gate.py` was replaced with the revised file hash. Other baseline hashes are unchanged. ci.yml bytes are unchanged (SHA256 4576223a294403ed8e15536941da5d73110c9f157bbf1bc3a008872dce62260d).

Run 43038325637 annotations, read from the check-run API: cf-ci-gate has the ubuntu-latest to Ubuntu 26 notice. Each cf-tests job has that notice plus a warning that `actions/checkout` and `actions/setup-python` in ci.yml target Node.js 20. Those actions are pinned in the file this change must not edit, so the annotations were not changed.

Not run: a live Actions execution of `gate-report` (the issues workflow on main does not yet contain it), macOS isolation, dispatcher once/watch, and any read of the repository variable values (HTTP 403). Ubuntu 3.12.3's unittest loader does not restore the discovery top directory, so the pre-existing `test_empty_collection_rejected` fails there; Python 3.12.12+ used by setup-python restores it, and 3.12.16 passed.

## CF-20261106-007 sample marketplace assets (2026-11-11)

`.venv/bin/python tools/samples/generate_samples.py` on Python 3.12.3. The script writes the nine `assets/samples/` files and checks them in the same run. Check passed: PNG sizes 1280×769 (three covers) and 1000×750 (four catalog images), PNG mode RGB, DPI 72, each PNG under 10 MB; both PDFs are 3 pages. Quote-packet amounts found in the extracted text are only 4,800.00, 640.00, and 5,440.00. The photo report has no money amount. Extracted PDF text includes SAMPLE, Fictional data, and “not a real client”. A second run produced byte-identical PDFs (`invariant=1`). Poppler `pdftoppm` renders of all six pages were read for clipping, column alignment, and the missing-file labels. Cover PNGs were also read at full composition and at a 360 px thumbnail width. Headlines remain short. No studio brand, contact string, rating, or third-party mark is drawn.

The generator is not registered in `automation/test_manifest.json` and is not collected by `unittest discover -s tests`. Product tests were not given new cases. `automation/`, `.github/`, and dispatcher settings were not edited.

`.venv/bin/python -m unittest discover -s tests -v` on this machine's Python 3.12.3: 80 tests, 79 passed, 1 failed in 1.460s. The failure is the pre-existing `test_empty_collection_rejected` (`Path must be within the project` while discovering `tests/`). TEST_REPORT already records that Ubuntu 3.12.3's loader leaves the discovery top directory changed, and that Python 3.12.12+ used by CI passes the same test. This change adds no test and does not edit the manifest. No marketplace upload was done. macOS was not run.
