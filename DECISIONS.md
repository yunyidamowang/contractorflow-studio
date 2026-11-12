# Decisions

- D022（2026-11-07）：公开仓库main保护已通过网页和实际PAT无变更请求验证；单仓库Token不授予管理/Actions权限。仅为Issue #4临时开启一次执行，结束恢复关闭，不解除canary锁、不启动watch。凭据重复粘贴已在本机检测并去除完全相同的重复部分，不向日志或Issue输出原值；旧暴露Token已从GitHub列表移除。

- 2026-11-06 / D001：在当前工作区 outputs/contractorflow-studio 建立独立仓库，避免影响其他项目。
- D002：Python 3.12 + FastAPI + SQLite + Pillow + pypdf；使用 ReportLab 生成 PDF（pypdf 负责读取验证，不适合排版生成），原生 HTML/CSS/JS，无 Node 构建依赖。
- D003：CSV 满足首版 Excel/CSV 输出；暂不增加 XLSX 依赖。报价输入为结构化表单，不用语言模型决定业务事实。按行 ROUND_HALF_UP 到 0.01 后求和；不假设税率、不混合 USD/AUD。
- D004：无 Docker、后台代理、自动邮件和外部 AI API。Ollama 已存在但不启动、不下载模型、不改设置。
- D005：单操作员密钥保护本地 API；所有记录按客户 ID 查询。此方案适合本地虚构资料，不提供客户访问隔离。未来多用户必须引入身份、角色和授权映射。
- D006：审批后才能导出，缺失金额输入不能批准；交付快照不随新增文件变化。原始文件不删除，去重只按相同客户/项目和相同字节。
- D007：GitHub 需用户先授权；Grok 连接能力只做文档层核验，暂不配置 MCP。保留文件交接。
- D008：官网草稿是技术占位文案，等 Grok 提供品牌与市场资料再调整。暂定名称未完成商标冲突检查，禁止公开发布。
- D009：备份仅离线进行；SQLite backup API + 文件哈希清单；恢复到新目录，原数据保留，密钥不备份、恢复后重新生成。

## 用户第二轮决定（覆盖旧对外品牌与价格假设）

- D010：ContractorFlow仅内部代号；CF_BRAND默认QuoteTrail Back Office，未清权候选，禁止正式发布。页面与新导出可替换；历史文件不覆盖。
- D011：$49一次样本试单优先；$299/$599月包仅假设，不采用Grok交接其他套餐价、时效和修订次数承诺。
- D012：SAMPLE MODE固定默认，不提供live切换或联系人CSV导入；原始附件保留字节，ZIP说明明确样本。模式不具备识别私人资料的能力，操作员仍必须只用虚构内容。
- D013：看板的sent是样本估价原状态，和邮件审批状态分离；没有已发送邮件接口。草稿修改撤销批准，重新Needs Review。审批者记录为本机操作员，生产分权待办。
- D014：照片PASS是人工文件关联；缺项例外及invoice_ready仅文档清单示意，不判断工程质量或批准开票。旧导入原名缺失时明确未知。
- D015：报价包手工结构化给定笔记、数量、价目和附件，不提供OCR/图纸算量或自动单价推断。附源记录和缺项，最终价格由承包商审核。

## 自动开发首轮（2026-11-07）

- D016：优先本机隔离Codex CLI + ChatGPT专用登录，复用现有额度；不复制全局认证、不改其他项目配置。GitHub Actions仅作关闭的登记入口；官方Action已评估，API探针模板不启用。
- D017：新自动任务只能经白名单作者和加标人、codex-ready结构化Issue；原文/评论/链接均不可信，不执行资料命令。仅纯源码固定SHA快照，无其他项目/客户资料。
- D018：并发1，每日UTC最多3次、每Issue最多2次、模型600秒、测试180秒、整任务20分钟截止；限制不是美元/token硬上限。没有API回退、购买、merge、删除或部署能力。
- D019：先提交配置草稿PR；真实Demo Issue #4须完成用户专用登录/仓库Token授权和验证，之后才允许Grok自动接单。默认关闭，不安装launchd或self-hosted Actions runner。

- D020：首次启用固定canary_issue=4，即使机器人和owner共用GitHub身份也不能执行其他Issue；用户真实验收后才手动改为null。

- D021（2026-11-07）：用户选择继续GitHub Free并公开原仓库，已在获知历史个人邮箱、Issue身份说明及内部商业材料后明确坚持原样公开；不另建仓库、不购买套餐。最终网页确认由用户操作，之后先验证main保护再配置认证和单次canary。调度器改为只接受原指定公开仓库，其余限制不变。

- D023（2026-11-12）：P0-D 的目标身份是两枚只安装在本仓库的 GitHub App。planner 与 publisher 各自使用安装令牌，不代表仓库所有者本人，也不把显示名当作身份。可选路线最多一个免费机器账号：由用户本人注册、接受当前条款、只用于跑机器。不用 classic personal access token 回避 fine-grained token 在协作者场景的限制。双身份尚未实现，试点保持 `enabled=false`、`canary_issue=4`。今后进入本公开仓库的提交使用 GitHub noreply 地址；不改写已有历史。安全配置只核验或开启免费告警，不购买、不自动合并、不自动打开依赖更新 PR。平台开关、App 和密钥由用户本人处理；文档不把未读到的开关写成已完成。

- D024（2026-11-12）：P1a 的队列只保证同一台机器上的互斥。本地 flock 加 SQLite `BEGIN IMMEDIATE` 不能当作多机分布式锁。租约默认 120 秒，心跳默认 30 秒；过期租约进入 `interrupted` 供人工复查，不自动再次启动模型，也不退回已预留的尝试。fencing token 只增不减；过期或失配的持有者不能发布。未知状态按 `blocked` 失败关闭。新表只用版本化迁移，显式 `migrate_up` / `migrate_down` 不改、不删、不重排已有 `runs` 行，且拒绝名为 `state.db` 的文件。调度器不自动迁移。`task_queue.enabled` 不是精确的 true 时，行为与现在的 `runs` 预留相同。`enabled` 仍为 false，`canary_issue` 仍为 4。POST 对账、launchd 样例和审计导出不在本决定里。

- D025（2026-11-12）：P1b 的发布对账默认关闭。只有 `publish_reconcile.enabled` 与 `task_queue.enabled` 都精确为 true 时才生效。示例配置不含这两个键。创建类 POST 不重试。只读 GET 的有限重试仍留在 `GitHub.api`，不拿来补发分支、PR 或评论。写结果不明进入 `publish_unknown`，之后只用已记录的分支名、commit、草稿 PR 和反馈标记做只读核对。核对为已存在才记入 `feedback_pending`；核对为不存在，或只有分支没有匹配的草稿 PR，保持 blocked 且不自动重发；无法判定也是 blocked。反馈补写只重发同一条脱敏评论，标记已存在则不发，最多 2 次且不重置次数，超过首次之后 24 小时也不再发，不重启模型。熔断是队列库旁边的 0600 文件，原因一经写入就保留。认证失败、main 保护或仓库策略漂移、账本损坏、重复领取、无法对账的写入、可信测试失败都会闩上它。代码里没有清除函数。清除是所有者停机后的手动删除，不是删库。P1a 已迁移的库不会被自动 ALTER。`enabled` 仍为 false，`canary_issue` 仍为 4。launchd 与审计哈希链不在本决定里。

- D026（2026-11-12）：P1c 的审计哈希链默认关闭。只有 `audit_chain.enabled` 精确为 true，并且队列或发布路径本身也精确启用时，状态变更才写入哈希链。示例配置不含 `audit_chain`、`task_queue`、`publish_reconcile`。链上的每条记录带上一条的哈希，版本号为 1。只读校验能指出第一处篡改、删除、错序或截断。校验失败则打开数据库失败关闭，不自动修复。记录只用允许的短标签，不写入令牌、邮箱或秘密。账本保留证明只在副本上做显式迁移，并要求旧 `runs` / `notices` 的值和尝试次数不变；不把整文件哈希当作保留证明。名为 `state.db` 的文件除非带夹具标志，否则拒绝；`.automation` 路径一律拒绝。launchd 样例不安装，`KeepAlive` 不为 true，不用 `caffeinate`，不把 `NetworkState` 当成连通性证明。安装样例仍须所有者另行批准。`enabled` 仍为 false，`canary_issue` 仍为 4。
