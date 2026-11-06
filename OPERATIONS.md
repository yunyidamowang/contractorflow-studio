# Operations

1. 双击 Start.command，使用终端显示的本机密钥解锁。只使用虚构资料，选定客户后操作。
2. 咨询通过客户工作区查看；工单/待办表单记录任务、说明和跟进日期。所有日期按 ISO 记录；客户时区仅元数据，暂不自动发送时区提醒。
3. 报价粘贴客户给定的结构化条目，检查缺失字段；Inspect 审查 → Approved → CSV/PDF/摘要导出 → Completed。缺失字段需创建完整的新草稿；不直接修改批准内容。
4. 英文邮件粘贴模拟原文，设定日期，检查模板语义；批准后下载文本。软件不发送邮件，不自动改变客户状态。
5. 文件导入前确认有权使用，指定项目 ID；上传 → Prepare file delivery → 审查文件清单 → 批准 → ZIP 下载。新增文件需重新生成交付快照。
6. Daily summary 展示当前客户内部状态统计；跟进详情在记录 payload 中；未实现操作系统通知或后台定时任务。
7. Demo 营业额仅手工记录；币种分开统计，金额以分输入。界面不可代替会计账簿，不把示例套餐当作收入。
8. 研究资料按 HANDOFF.md 投递，经核验转为任务。无自动消费 inbox 的进程。

## 备份恢复

先在启动窗口按 Ctrl+C 停止后台，再进入项目目录：

```sh
.venv/bin/python scripts/backup.py backup data backups/demo-20261106
.venv/bin/python scripts/backup.py restore backups/demo-20261106 backups/restore-check
```

目标目录必须不存在。备份 SQLite 一致性快照和文件，生成 SHA-256 清单；恢复校验摘要和数据库完整性，不覆盖原目录。恢复后用 CF_DATA 指向恢复目录并重新启动；生成新的密钥。先用虚构数据确认后再考虑真实业务恢复方案。

恢复演练和首单操作都需要明确负责人。自动化平台不作为日常启动依赖；结束演示时停止本项目进程。
