# 已阅 / 未阅 MVP

复用 user_states.is_read；schema 2 → 3 仅新增 nullable first_viewed_at。旧 is_read、收藏、忽略、备注和工作流不变；旧记录时间保留 NULL，不编造过去浏览时间。首次成功标记已阅时记录 UTC 时间，恢复未阅不删除该时间。UI 标注“首次记录浏览”。重复标记不重复写入或备份。

生产库不会自动迁移。暂停同步/导入/回填后手动执行：

```powershell
$python = Join-Path $env:LOCALAPPDATA 'ErYouToolbox\venv\Scripts\python.exe'
& $python -m unittest tests.test_read_states tests.test_subscriptions tests.test_react_api tests.test_ui_queries tests.test_database
& $python scripts/migrate_read_states.py
& $python scripts/migrate_read_states.py --apply
```

迁移入口先执行现有经验证的 SQLite Backup API 备份，再事务升级 user_version。失败回滚；重复运行安全。schema 1 的旧库会按顺序应用已存在的作者关注迁移和本次字段迁移。备份保存在 data/backups/，不移动已有备份，不修改检查点。E/F 盘变化依靠脚本位置定位同一数据库。

重启 API 和 React 后：

1. 最新 MOD、订阅动态默认“全部”；切换“未阅”“已阅”检查游戏、搜索与分页。
2. 仅滚动或点击外部原站链接，作品仍未阅；进入本地详情后自动标记，返回列表可见低调标识，图片清晰度不变。
3. 卡片及详情可手动标记/恢复未阅；详情恢复未阅后不会立即被本次打开的自动标记重新覆盖。
4. 关闭浏览器、重启并换游戏，状态从 SQLite 读取，不依赖 localStorage。
5. 普通同步及 source_updated 事件不重置已阅，当前不支持“更新后自动未阅”。

新增 GET/POST /api/read-state。POST 复用 Host/Origin/专用请求头/JSON/请求体大小限制，仅接受 source、item_id、is_read，限定本地 item_type=Mod。底层保留完整联合键以避免其他作品类型冲突，不提供任意字段写入；参数 SQL、备份和事务，UPsert 仅更新已阅及本地记录时间，不覆盖其他人工字段。缺少本地作品时拒绝写入。

范围：热门远程未收录作品不显示此控件，不会因热门卡片滚动而创建本地数据。本地热门作品进入已有本地详情后遵循同一已阅规则。筛选仅影响最新/订阅；状态本身持久保存，筛选选择当前保留在页面会话内，重新打开默认全部。浏览器交互需按上述步骤本机验收。
