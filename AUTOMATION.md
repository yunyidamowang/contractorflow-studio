# Grok → Codex 自动开发：首轮受控配置

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
- 可选启用登记器：仓库变量 `CF_INTAKE_ENABLED=true`、`CF_ALLOWED_ACTORS=["实际账号"]`；`CF_AUTOMATION_STOP=true`停止登记。登记器仅提示，本机关闭时不会开发。未启用不影响本机标签轮询。

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
