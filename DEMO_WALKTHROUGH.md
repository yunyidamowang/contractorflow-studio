# 3 分 40 秒标准样本演示

仅本地、由操作员展示。候选品牌 QuoteTrail Back Office 尚未清权，禁止正式发布。所有输入虚构；默认 SAMPLE MODE，不存在真实客户模式切换。

启动：双击 Start.command（会准备合成样例），复制终端显示的工作区密钥。在 http://127.0.0.1:8765/studio 解锁。官网草稿 http://127.0.0.1:8765/ 。新下载放在浏览器下载目录，历史脚本交付在 artifacts/demo-delivery/。

| 时间 | 点击步骤 | 讲解与验收 |
|---|---|---|
| 0:00–0:20 | 指向 SAMPLE MODE 和候选品牌 | 新工作室、本地样本、非真实客户成果；不提供生产客户门户 |
| 0:20–1:20 / A | 选择第一家样本客户；Quote表单输入现场笔记、假设/排除项。保留示例12.5×8.40、2×25。可从文件列表复制同客户附件ID。Create review draft → Inspect → Approved → Download sample packet ZIP | 155.00来自给定数字；缺价格时留空且禁止批准，补齐后建新草稿；ZIP包含PDF、CSV、说明和选定附件。品牌及样本水印可见。最终价格由承包商审查 |
| 1:20–2:20 / B | 看板勾选无下一步筛选；选择状态、联系日和下一步日期，Save。邮件选择Friendly/Missing information/Final check-in，Prepare → Inspect展开 → 编辑 → Save draft → Approved → Export txt | 三种语气，所有草稿需人审。修改后重新进入Needs Review。“sent”仅指样本估价清单原状态；系统绝不发送邮件 |
| 2:20–3:20 / C | Files上传合成PNG并指定项目；文件列表显示ID。Photo checklist填相同项目和照片ID，故意留completion/walkthrough为空，勾选PM reports complete → Prepare exception report → Inspect → Approved → Export pdf/csv | 报告标缺项，invoice_ready=false；建议向PM索取资料，不向房主发指令。PASS仅表示人工关联文件，不代表视觉/安全核验。新导入文件可看原名→整理名对照；旧样例原名未知时明确标记未知 |
| 3:20–3:40 | 展示隐私说明及$49试单范围 | 一次试单、约定一件样本交付；月包只是待验证假设。不承诺成交率、工期或已具备真实客户处理资格 |

品牌替换：在启动前设置环境变量 CF_BRAND，重新启动本地服务；页面和新导出使用配置值。默认 QuoteTrail Back Office 只是候选名，不代表商标检查完成。历史导出是旧快照，需重新生成，原件保留。

演示恢复：刷新网页重新解锁；新的报价/草稿生成独立记录。请勿清空数据库或删除原件来重置演示。测试脚本只添加虚构记录。
