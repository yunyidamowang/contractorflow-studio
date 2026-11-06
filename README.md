# ContractorFlow — internal project

对外候选名 **QuoteTrail Back Office** 尚未完成商标检查，仅用于本地草稿。默认 **SAMPLE MODE**，所有资料虚构，无真实客户模式开关。当前首要演示：$49 一次性样本试单；$299/$599仅为月包假设。

## 浏览器操作

双击 **Start.command**（准备20个合成文件与样本交付，不下载模型）。终端会显示本机工作区密钥。在 http://127.0.0.1:8765/studio 输入密钥点击 Unlock。官网本地草稿：http://127.0.0.1:8765/ 。结束时终端 Ctrl+C。

- **A 报价包**：填样本现场笔记、假设、排除项和已有备选；逐行录入给定数量/单价，从Files列表选同客户附件ID。Create review draft → Inspect → Approved → Download sample packet ZIP（PDF/CSV/说明/附件）。缺价格留空，补齐前不可批准。
- **B 估价跟进**：看板维护六种状态、上次联系日和下一步日期，筛无下一步项；选择三种语气生成草稿，Inspect编辑后Save，重新Approved后Export txt。系统不发送消息；“sent”仅是样本估价清单的导入状态。
- **C 照片例外**：导入样本PNG/JPEG，记录文件ID；在Photo checklist指定项目并分配照片ID到before/during/after/issue/completion/walkthrough。故意留竣工和交底项空，Prepare → Inspect → Approved → Export pdf/csv。报告阻止文档层面的开票就绪，实际开票权归承包商。

完整3分40秒点击讲解：[DEMO_WALKTHROUGH.md](DEMO_WALKTHROUGH.md)。试单范围：[TRIAL_SCOPE.md](TRIAL_SCOPE.md)。SAMPLE标识出现在页面、CSV、PDF每页、文本和ZIP说明；原始附件保留字节与元数据，不伪造施工信息。

品牌替换：启动服务前设置 `CF_BRAND` 环境变量，再启动；默认候选名仅本地使用。已有历史导出保留原样，新导出重新生成。

## 环境与验证

Python 3.12 独立 .venv。新检出运行：

```sh
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt
./Start.command
```

```sh
.venv/bin/python -m unittest discover -s tests -v
```

真实Chrome验收使用现有agent-browser工具（不属业务运行依赖）：启动本机服务后执行 `scripts/browser_qa.py` 、`scripts/browser_round2.py` 和 `scripts/browser_packet.py`。证据在artifacts目录，不提交Git。测试只添加虚构记录；不清空或覆盖原数据库。

独立环境约58MiB，无Docker、常驻Agent或新模型。技术边界：结构化输入和确定性模板，不自动理解图纸/施工照片；操作员手工确认信息与附件槽位；缺项不代表施工质量结论。单操作员持钥管理全部样本客户，不提供生产多租户身份隔离。

私有仓库：https://github.com/yunyidamowang/contractorflow-studio 。[HANDOFF](HANDOFF.md) 定义双AI交接；Grok已通过Issue提交研究，尚未验证的来源和商标状态见 [REQUIREMENTS_REVIEW.md](REQUIREMENTS_REVIEW.md)。生产安全项单列 [PRODUCTION_BACKLOG.md](PRODUCTION_BACKLOG.md)。禁止真实客户私人资料、上线门户或未经批准发布。
