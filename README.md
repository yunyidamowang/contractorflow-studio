# ContractorFlow Studio

面向美国和澳洲 Home Services 的本地后台演示。官网暂名 ContractorFlow Back Office，未完成名称/商标检索，不对外使用。当前版本 0.1.0-demo；所有数据、图片、套餐与收入均为演示，禁止导入真实客户资料。

## 立即运行

本目录已准备独立 `.venv`（约 58 MiB）。双击 `Start.command`，终端会显示仅本机工作区密钥；复制到后台 Unlock 字段。打开 http://127.0.0.1:8765/studio ，官网为 http://127.0.0.1:8765/ 。终端 Ctrl+C 停止。若端口已被占用，先关闭之前启动的本项目窗口，不要终止其他项目。

首次从远程检出时：Python 3.12 创建 `.venv`，再安装 `requirements.txt`。依赖固定版本，未安装系统服务、Docker 或本地模型。不需要每日执行复杂命令。

```sh
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt
./Start.command
```

## 已有能力

- 客户登记：服务、业务时区、套餐；工单/待办、咨询、跟进日期和交付记录。
- 项目文件：JPEG/PNG/PDF 格式验证、10 MiB 限制、SHA-256 精确去重、按指定项目命名、索引与 ZIP；不推断工程事实。
- 报价：客户给定价格/数量，Decimal 四舍五入至分；缺失字段阻止批准；审批后导出 CSV（Excel 可打开）、PDF 和英文摘要。未实现原生 XLSX 或自动 OCR。
- 英文跟进：规则分类、模板草稿、状态建议、提醒清单、内部日报；原文保留。不连接邮箱、不发送。
- 审批：Pending → Processing → Needs Review → Approved → Completed，失败可回到 Pending。新草稿直接进入 Needs Review；Completed 终态。模拟脚本的批准仅代表演示操作。
- 仪表盘：客户数、未完成任务、审批、交付、跟进和失败数；按月分币种记录 Demo 营业额；日志时间戳。HTTP 耗时在响应头中，业务处理耗时见交付记录时间差；仪表盘显示平均交付历时（非人工活跃时间）。

## 演示与测试

```sh
.venv/bin/python -m scripts.demo_delivery
.venv/bin/python -m unittest discover -s tests -v
```

三套交付位于 `artifacts/demo-delivery/`，不进入 Git。已生成 3 家客户、30 条咨询、10 条种子邮件和 20 个合成图片文件。脚本重复运行保持同一交付（追加模拟邮件一条是首轮演示流程）。测试使用独立临时库。

重要边界：这是单操作员内部系统，密钥持有人可管理全部 Demo 客户；客户 ID 范围校验阻止把一个客户的记录当作另一个客户处理，但没有多用户身份或客户登录。不得作为公网多租户 SaaS 部署。

协作入口：[HANDOFF.md](HANDOFF.md)。技术评估：[OPEN_SOURCE_EVALUATION.md](OPEN_SOURCE_EVALUATION.md)。待办：[TASKS.md](TASKS.md)。远程 GitHub 尚未建立，需用户授权。
