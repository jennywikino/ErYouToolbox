# OB5-A 作者自动检查

复用author_updates.check/apply_report、normalize_record、import_samples、verified_backup。普通同步和作者同步在同一次AutoSync任务内串行执行，共享logs/content_ratings/instance.lock；手动作者预览和报告导入也使用该锁。run_rotation本身不再获取锁，调用方必须持锁，避免嵌套死锁。没有新建Windows任务。

## 调度与数据安全

- 默认每轮最多两位当前仍关注的GameBanana作者。按上轮最后处理ID之后开始，末尾回绕；五作者测试顺序为7、8、9、10、11、7。无关注时正常结束。
- 每作者最多六游戏各一页Core/List/New及五个ProfilePage详情，默认作者阶段最多22次请求；每次请求间隔2秒，无并发。已有客户端不会在同一轮无限重试，网络失败交由下次轮转恢复。
- 详情必须确认作品、作者、支持游戏身份。仅MOD ID列表不是更新证据；来源updated_at增加仍由原importer判断。modified_at或metadata_changed不是版本更新。
- 默认自动关闭时不调用作者阶段。自动检查保存报告与公平轮转调度状态，不写MOD库或正式作者基线；自动入库提交已验证详情，保留已有图片、内容分级、已阅与关注。
- 首轮历史作品不创建first_seen提醒；后续新作品只有发布时间晚于基线才创建新作事件。独立dry-run不建立正式基线。初次获得缺失updated_at不产生source_updated。
- 正式基线在sync_runs.error_summary.author_check内，与每作者作品/事件同事务提交。部分成功记录pending_ids、done_ids，但不推进checked_at；最后一个ID处理完成后才推进检查时间。失败作者不会清空其他作者已提交结果。
- 每作者事务写入前备份。失败回滚该作者；写事务内复核关注关系及原基线，防止取消关注或陈旧报告竞态。

## 文件规则

移动盘项目的logs/author_updates/rotation.json保存轮转cursor、失败队列和冷却；latest.json及check_时间戳.json保存报告。普通自动检查可以推进调度cursor，但不能推进SQLite正式写入基线。独立check_author_updates.py --dry-run只生成报告，不移动cursor。

失败队列保留未处理ID；写入失败时也重新保留已验证但未提交的ID。普通错误最多连续尝试两轮，再冷却6小时，不阻塞其他作者。详情上限属于正常续扫，不累计失败。429/403停止后续作者，遵守Retry-After；缺少明确等待时间时保守冷却6小时。报告历史不删除。

E/F切换保持上述项目相对路径。每台电脑的自动模式和原Windows任务仍须按OB4独立配置。只有已经明确启用自动入库的配置才会写入；本轮没有对真实库执行apply，也没有变更本机任务/偏好。

## 验收证据与限制

完整离线回归343项通过；追加新作幂等测试后作者相关15项涵盖五作者公平轮转、取消关注、历史基线、部分提交后续扫、失败隔离、回滚保留队列、共享锁和限流冷却。前端10项通过，最终生产构建通过。测试数据位于临时库。

真实API调用0次，本轮未做真实关注作者联网验证，不能将模拟详情当成真实验证。生产数据库没有apply，未迁移schema，未修改v0.4.0-rc1标签或执行git push。真实浏览器、Windows定时触发和实盘E/F切换尚待用户验收。

```powershell
$python = Join-Path $env:LOCALAPPDATA 'ErYouToolbox\venv\Scripts\python.exe'
& $python -m unittest discover -s tests -p 'test_author*.py'
& $python scripts/check_author_updates.py --dry-run --pages 1 --details 1
```

第二条命令最多处理两位真实关注作者，每作者六次列表加一次详情，最多14次请求；仅预览，不推进正式基线和轮转。报告位于logs/author_updates。自动模式由现有auto_sync.py及已注册任务执行，不需要逐位手工导入报告。

测试自动检查可使用既有模式check及一次性auto_sync入口；注意该入口也会执行普通六游戏扫描，不属于单独作者小样本命令。启用apply前请先审阅报告并备份。订阅页自动轮询本地结果，不会为卡片逐项联网。
