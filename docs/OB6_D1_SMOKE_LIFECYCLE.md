# OB6-D1 冒烟测试生命周期

改动：`tests/ui_navigation_smoke.cjs`、新增 `tests/smoke_profile.cjs`、`tests/test_smoke_profile.cjs`、本文档。

仅发现 `ui_navigation_smoke.cjs` 创建此类浏览器 profile。原实现未等待退出、未删除 profile。现在验证运行标签，使用唯一 mkdtemp 目录；正常完成、测试抛错、SIGINT/SIGTERM、未捕获异常及未处理 Promise 拒绝都走一次性收尾。先请求 Browser.close，再等待启动的浏览器退出；不强制终止未知浏览器。

删除前验证目标仅为本次运行目录直属 `profile`，拒绝重解析/符号链接和路径逃逸；Windows CIM 检查根进程、子孙进程及引用该专用 profile 的进程，逐文件检查独占可打开。检查失败、进程未退出或文件占用都保留目录，原因写入 `profile_cleanup.json`。删除不用 force、不重试强删；保留报告、截图、chrome.log、processes.json、error.log 和测量文件。没有 report.json 的旧分支现在也生成简短收尾报告。

无法捕获任务管理器强制结束、断电或 SIGKILL，因此这类中断可能留下 profile；不自动追删旧目录。错误日志和 profile_cleanup.json 是判断后续人工处理的依据。当前代码不提供历史缓存清理命令。

验证：生命周期六项单元测试通过（成功、失败、异常退出、活动进程、文件占用、越界路径），脚本语法检查通过。两次真实隔离 Edge 成功测试的 profile 均已清理；截图/测量/退出证据保留。最终运行目录 `logs/ui_smoke/visual_lifecycle_final_1793613056361_ToMkrE/` 包含 report.json、两种尺寸截图、measurements.json、chrome.log、processes.json、profile_cleanup.json。真实失败/强制中断浏览器场景未实测，不能以单元测试视为全部实机退出情形通过。

验收：`node --test tests/test_smoke_profile.cjs`；按原入口运行冒烟测试，检查输出目录中的 profile_cleanup.json，而非只看测试退出码。清理失败不会抹掉原测试结果。

## subscriptions 备份只读审计

审计时 32 份，合计 86,831,104 字节（约 82.81 MiB），文件名时间范围 2026-10-29 至 2026-11-02。没有读取或改写数据库内容，未删除、压缩任何备份。

`subscriptions_*.db` 是 `subscriptions.verified_backup` 的共享命名前缀，不能仅凭文件名判断为重复关注备份。调用来源包括：

- 关注/取消关注的实际变更与显式迁移。
- 已阅状态实际变更：每次符合条件的写入前生成完整数据库备份，日常浏览可能成为高频来源；幂等无变化分支跳过。
- 作者检查：提交作者基线/进度也会触发备份，即使作品无变化。
- 历史补全：提交历史进度也触发备份。
- 定向图片修复：实际存在图片变更时，每批备份一次。

实现为 SQLite Backup API + integrity_check/foreign_key_check，微秒时间戳文件名、存在时拒绝覆盖。所查实现没有自动限份、按日合并或删除策略，因此增长是设计结果；名称也不携带来源用途。本轮没有逐份对比内容，不能认定 32 份语义重复或可以安全删除。

建议后续单独审批保留策略：先明确来源/时间/恢复点并验证独立设备备份，再考虑近期详细、长期稀疏保留。不要直接按 subscriptions 前缀批量删除。本轮不改变任何备份策略。
