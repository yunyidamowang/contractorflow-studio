# 自动开发配置首轮验收

P0-A (#10 / CF-20261107-011) in development: exact trusted test manifest, structured results and independent head/merge CI. 38 original names retained, 3 new validator tests registered. CI runtime evidence pending; no P0 completion claim. enabled=false/canary=4; historical canary records untouched. See docs/automation/P0_CI.md.

## 2026-11-07 快照修复待审

只读GET最多3次、0.5/1秒退避、遵守任务截止时间；写请求不重试。加入脱敏错误分类、blob及完整Git树校验、相同SHA去重、完整下载后写入。38项测试通过；固定d158043快照66/66真实只读预检通过，独立Git校验一致，账本未变、模型未调用。enabled=false、canary=4；最后一次canary仍须合并修复并另获用户批准。详见handoff/outbox/CF-20261107-005.md。

## 最新真实前置验证（2026-11-07）

仓库Public；main保护已实际拦截owner网页直接提交和项目PAT的同SHA无变更更新（HTTP422，要求PR），main SHA未变。新PAT已认证访问指定仓库，GitHub权限页确认仅本仓库metadata读及code/issues/pull requests读写，无用户权限；文件0600。项目独立CLI实际login status确认ChatGPT。旧暴露Token已从列表移除。真实原生隔离探针再次PASS，固定33项测试OK（0.909秒）。doctor在单次准备阶段enabled=true、stop=false、canary=4、登录及Token存在；真正认证和隔离由前述独立检查证明。已发canary ready，等待Grok标签。未执行真实once/模型/自动PR；下文历史结果不覆盖此状态。

日期：2026-11-07（Asia/Shanghai）。仅虚构数据；默认enabled=false。以下结果不等于真实Codex账号→GitHub PR端到端验收。

| 检查 | 已执行结果 |
|---|---|
| 普通完整测试 | `.venv/bin/python -m unittest discover -s tests -v`，33项全部通过 |
| 实际CLI隔离环境完整测试 | `codex sandbox -P contractorflow`，最终33项通过，最终日志见本机tests-final.log；不是仅用mock替代沙箱 |
| 实际权限探针 | 可写当前检出；合成外部哨兵、专用认证配置不可读；Git元数据不可写；命令网络不可用；子环境无GitHub/API密钥 |
| Issue→开发→测试→PR→反馈策略 | 明确fake Git/model/test worker/GitHub的单元模拟：成功产生draft PR反馈；失败占用尝试并阻止重复；测试期间文件变化禁止发布；首次启用只接收canary Issue #4 |
| Git与导出路径检查 | 真实Git临时检出：合法文件补丁通过，额外README修改拒绝；路径穿越、隐藏文件、自动化/依赖/安全文件修改拒绝 |
| 配额与停止 | 日上限3次、Issue终身2次、重复触发/冷却阻止；真实sleep子进程超时被终止；STOP阻止新子进程启动 |
| 实际登记脚本逻辑 | `node scripts/test_intake.cjs`执行workflow内原始JS，mock GitHub：LF/CRLF有效任务接收，陌生身份/缺字段/停止任务拒绝，反馈换行正确 |
| 语法 | Python compileall、4个.command的zsh语法、JSON格式workflow及node脚本、git diff --check通过 |
| 激活状态 | doctor确认enabled=false；项目ChatGPT登录文件和GitHub token均不存在；once在联网或模型调用前拒绝 |

独立 `simulate` 命令使用确定性样本文件替代模型，真实运行Git/补丁检查与源码快照中的固定测试，再模拟blob/tree/commit/branch/PR/comment API。其example.invalid链接明确不是已创建PR。此前基线快照20项通过；配置提交后再次实际运行simulate，源码快照中的33项测试通过，GitHub写操作均为显式模拟。结果保存在本机.automation/simulation.json，仍不能视为真实模型调用或真实远程PR。

发现并修复：Homebrew运行库需只读权限，未授权时探针安全失败；Actions脚本双重换行转义会误拒绝合法任务；测试前后文件变化必须阻止旧补丁发布；GitHub拒绝重定向防止令牌转发；Git/CLI检查限时；正常终止、挂断时清理本任务进程组；预校验拒绝反馈去重，避免重复评论。测试流程的Git边界单独用真实Git验证，策略流程用明确mock，避免在受限环境中重复启动大量Git进程。

证据仅本机：.automation/isolation-acceptance/、.automation/sandbox-suite/isolation.log、tests-final.log、simulation.json。专用状态/原始日志不上传GitHub。原有Starlette/httpx弃用警告仍存在，不影响测试。

未执行/未核实：专用ChatGPT网页登录、会员剩余额度、真实模型生成代码、实际本地PAT权限、官方Action付费探针、GitHub托管运行、账号账单硬上限、main分支保护设置、Grok实际身份权限、长期运行/休眠重启/强制断电。上一轮自动审批服务曾因使用额度不足拒绝一次进程检查，未执行该检查、没有绕过；本轮依据完整日志并重新完成最终测试。

首个真实canary为Issue #4，仍open且未标ready。必须用户完成专用登录、仅本仓库Token和配置PR审核，再由owner单任务验证真实模型/测试/草稿PR/Issue反馈；通过后才给Grok白名单。main、客户数据、业务后台运行方式均未由本自动化更改。

## CF-20261107-012 review revision

User authorized and confirmed adding Workflows read/write to the existing single-repository Token; GitHub displayed “Your personal access token has been updated”. Repository selection and 2026-11-14 expiry unchanged. The previous missing-permission blocker is superseded, but no workflow is installed until Grok reviews this revised candidate.

Candidate now adds push to main and per-PR/ref concurrency with cancel-in-progress. Push jobs both use the actual push SHA; PR jobs use head and merge revisions. Added 16 negative tests: missing/extra/renamed/duplicate names, duplicate manifest, removed baseline, same-count wrong names, run-count mismatch, skips/expected failures, failed parent process, missing/multiple/malformed/failed result. Pipeline negatives assert zero publication using only synthetic APIs and in-memory ledgers. Baseline test fixture accepts negative inputs without removing original assertions. Manifest now registers 57 tests including all original 38; original source hashes remain recorded. Local exact-manifest run: 57/57 in 1.763s. Actual CI remains NOT RUN pending candidate review and installation.

Follow-up executed evidence: native Mac isolation probe PASS; archived code 99cee00 exact runner 57/57 in 27.115s. Full unittest discovery 57/57 in 1.425s. Ledger hash unchanged (b31ac93a3d6850f6053ed16b913970f1f424981a9a4e52d9c0d2c1df2066d3ca). CI still not installed pending Grok candidate review.
