# Open source evaluation

核查日期：2026-11-06。仅研究官方仓库/许可/文档，不安装以下大型平台。许可证总结用于技术筛选，具体商业交付形式仍需逐条核对适用许可。本地未运行的项目，内存/磁盘为相对成本判断，**不是实测最低要求**；Apple Silicon 的未实测兼容性不视为保证。

## 逐项评估

| 项目与官方依据 | 许可与商业边界 | 维护观察 | 功能/Apple Silicon/自托管 | 成本、隐私、业务判断 |
|---|---|---|---|---|
| [github/github-mcp-server](https://github.com/github/github-mcp-server) | MIT；使用 GitHub 服务仍受账户、权限和服务条款约束 | 官方项目可访问；最近提交日期未核实 | 仓库/Issue 工具；官方远程服务不需 Mac 安装；也可本地自托管，未实测 | 远程本机占用低；学习中；令牌权限和 Issue 注入风险。待授权，仅研究 |
| [activepieces/activepieces](https://github.com/activepieces/activepieces) | 社区 MIT，企业功能商业许可，不混同 | GitHub 浏览器 API 快照 pushed_at 2026-11-06，archived=false；不是质量保证 | 可视化流程/MCP；可自托管；arm64 部署镜像/依赖需逐版本核验 | 多组件/运行时，内存磁盘中高；学习中；连接器可带出资料。需求重复且明确后再引入 |
| [n8n-io/n8n](https://github.com/n8n-io/n8n) | Sustainable Use/Enterprise；源码可见不等同 OSI 开源；不可默认允许向客户转售托管平台，需按业务模式核对 | 官方仓库可访问；未确认最近提交日期 | 工作流和大量集成、自托管；Node 路径可评估 arm64，未实测 | 中高占用与维护；凭据和日志风险。当前不安装，未来先审许可 |
| [baserow/baserow](https://github.com/baserow/baserow) / [LICENSE](https://raw.githubusercontent.com/baserow/baserow/develop/LICENSE) | OSE MIT，premium/enterprise 单独许可，文档 CC BY-SA | 仓库可访问；近期提交未知 | 数据表/应用/自动化，可自托管；多服务 arm64 未核验 | 中高磁盘与内存；学习中；权限/导出治理成本。简单 CRM 先用 SQLite |
| [espocrm/espocrm](https://github.com/espocrm/espocrm) / [LICENSE](https://raw.githubusercontent.com/espocrm/espocrm/master/LICENSE.txt) | AGPLv3；修改版本经网络提供服务涉及源码义务；扩展可能另许可 | 仓库可访问；近期提交未知 | 完整 CRM，PHP+数据库，可自托管；arm64 取决于运行环境，未实测 | 维护中高、业务配置复杂；适合完整销售流程，首版过重 |
| [py-pdf/pypdf](https://github.com/py-pdf/pypdf) / [LICENSE](https://raw.githubusercontent.com/py-pdf/pypdf/main/LICENSE) | BSD-3-Clause，商业可用，保留声明 | 本次安装 7.0.0，提交活跃度未核实 | 读写/合并/文本提取；纯 Python，本机 arm64 验证通过；本地处理 | 低占用，学习低；不可信 PDF 解析/资源耗尽风险；**采用作 PDF 验证，不负责 OCR** |
| [python-pillow/Pillow](https://github.com/python-pillow/Pillow) / [LICENSE](https://raw.githubusercontent.com/python-pillow/Pillow/main/LICENSE) | MIT-CMU，保留版权和声明 | 本次安装 13.0.0，近期提交未核实 | 图片读取/校验；arm64 wheel 安装和合成图导入测试通过；本地 | 低基础占用，解码时取决像素；需像素上限和补丁管理；**采用** |
| [paperless-ngx/paperless-ngx](https://github.com/paperless-ngx/paperless-ngx) | GPLv3，商业使用可行，分发衍生代码需履行义务 | 仓库可访问；近期提交未知 | 文档档案/OCR，自托管；arm64 依赖 Tesseract/镜像需核验 | 多服务/OCR，中高内存磁盘，维护中高；客户访问授权与全文索引风险。先不安装 |
| [docling-project/docling](https://github.com/docling-project/docling) / [LICENSE](https://raw.githubusercontent.com/docling-project/docling/main/LICENSE) | 代码 MIT，模型/权重与附属依赖另审 | 仓库可访问；近期提交未知 | 文档布局/结构解析，本地处理；Mac 路径待实测 | 模型下载和推理可占较多磁盘/内存；扫描件价值明确后试验，不作为首版依赖 |
| [openclaw/openclaw](https://github.com/openclaw/openclaw) | MIT，不代表其连接服务和模型免费 | 仓库可访问；API 直接读取限流，近期提交未核实 | 内部 Agent/工具连接，可本地/自托管；未在本机安装验证 | 宿主/工具权限和提示注入面大；成本依模型与工具。没有确定业务收益前不引入 |
| [ollama/ollama](https://github.com/ollama/ollama) / [LICENSE](https://raw.githubusercontent.com/ollama/ollama/main/LICENSE) | 引擎 MIT，模型各自许可，云模型另有服务条款 | 本机有可执行文件，近期项目提交未核实 | 本地模型运行/可自托管；支持 Mac 路径，本项目未启动 | 引擎成本较低，模型可占数 GB 以上磁盘与统一内存；本地模式也需审工具/网络。暂不用 |

## 维护状态核查限制

直接 GitHub REST API 的 11 项请求均返回 403 rate limit；结果原样记录 research_snapshot.json。浏览器能读取仓库主页和部分 API 快照，但不能把“页面可访问”当作“近期持续维护”。因此除明确标注者，不声称近期活跃。正式引入未安装组件前重新核查默认分支最近提交、安全公告、发布和镜像架构。不为绕过限流申请广泛账户权限。

## 首版选择和资源证据

采用 FastAPI / SQLite / Pillow / pypdf，补充 ReportLab 生成排版 PDF、python-multipart 处理表单、httpx 做本地集成测试。安装后的独立 .venv 约 58 MiB（含全部测试依赖），未下载 AI 模型。数据库与小图样例占用低；未做进程内存峰值测量。容量不能外推到真实工程照片或 5–10 客户并发。

替代平台的收益目前不足以抵消多服务和许可成本，不另引入新平台。SQLite/原生 UI 是首版最小方案；待真实流程证据决定是否切换 CRM 或工作流平台。

## Grok 连接结论

[GitHub 官方 MCP](https://github.com/github/github-mcp-server) 有远程入口和认证方式；[Grok 官方连接器文档](https://docs.x.ai/grok/connectors) 列出 GitHub 连接器及自定义 MCP；[Bot 安全说明](https://docs.x.ai/grok-bot/security) 解释权限和网络限制。属于产品文档支持，不是用户账户联通证据。本次没有登录、授权、创建远程仓库或配置 MCP；优先使用 HANDOFF.md 的文件流程，用户授权后才验证具体客户端。
