# 作者订阅 MVP

## 手动迁移与启动

本轮不执行真实库迁移。请先退出正在运行的同步、导入、回填任务。

```powershell
$python = Join-Path $env:LOCALAPPDATA 'ErYouToolbox\venv\Scripts\python.exe'
& $python scripts/migrate_subscriptions.py
& $python scripts/migrate_subscriptions.py --apply
```

第一条只说明操作，不写库。第二条仅对现有库执行 schema 1 → 2，先使用 SQLite Backup API 生成唯一备份并通过 integrity_check / foreign_key_check，再事务新增 author_subscriptions、更新 user_version；失败回滚。备份保存在 data/backups/subscriptions_时间戳.db，不删除历史文件。重复执行不重复备份或迁移。API 启动不会调用初始化；原 init_db.py 对未迁移旧库会要求使用本迁移入口。

新表：source、author_id、display_name、followed_at，联合主键 source + author_id；不绑定单条作品，跨游戏可共用作者。原四张表、检查点和内容分级不改变。

重启已有启动器后，在 MOD 详情作者区域关注或取消关注；关闭浏览器再打开，状态从 SQLite 读取。缺少作者 ID 或未迁移时按钮禁用并提示。游戏、搜索、分级和分页保留。详情画廊不因关注操作重置。

## 查询和安全

- GET /api/subscription 读取状态；POST /api/subscription 是唯一新增的关注写入入口。
- 服务保持只绑定 127.0.0.1。写入要求正确 Host、受信任的 5173/本机 API Origin、JSON、X-ErYouToolbox 请求头；不开放 CORS，拒绝无来源/跨站表单和分块请求。
- 只接受 source、author_id、followed；只允许关注本地已知作者。无任意 SQL，写入使用参数、事务和经校验备份；重复操作不写入、不备份。
- 订阅使用 SQL EXISTS 在分页前筛选，复用现有卡片与详情，不向 GameBanana 逐卡请求。
- 最近发布可显示关注前历史作品；新发布须同时满足关注后来源发布时间和本地 first_seen 事件。最近更新必须有 source_updated 事件；metadata_changed 不作为更新。历史事件仍是历史，不伪装实时动态。
- 本轮没有远程实时跟踪、定时任务或热门榜。

## 验收

```powershell
& $python -m unittest tests.test_subscriptions tests.test_react_api tests.test_ui_queries tests.test_database
```

1. 未关注时订阅页显示空状态。在详情点击作者名称能打开已有来源主页。
2. 关注作者，回订阅页，检查同作者跨游戏作品；切换游戏、分级、搜索及分页。
3. 查看历史作品标记；没有 source_updated 事件时“最近更新”应为空，即使 updated_at 非空。
4. 关闭重开浏览器验证关注仍在；取消关注后作品消失。
5. 关注/取消关注不会修改图片、MOD 元数据、用户备注、收藏、来源分级或作品事件。

## 后续远程同步所需字段

保留 source、author_id、已验证 author_url；后续独立迁移可增加每作者 last_attempt_at、last_success_at、同步状态、错误与 Retry-After、已验证来源更新时间/事件身份以及有界扫描进度。分页游标必须经过稳定性验证，不能直接把漂移页码当作无遗漏断点。远程结果继续走现有标准化/importer/source_updated 判定，订阅表不被普通同步覆盖。
