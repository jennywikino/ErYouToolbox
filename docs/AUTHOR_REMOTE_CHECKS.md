# 关注作者远程检查（有界 MVP）

默认预览，不自动写数据库。订阅页按钮同样仅预览，报告位于 logs/author_updates，原有订阅作品不因请求失败被清空。

本轮最多读取两位已关注 GameBanana 作者，每作者对六个配置游戏逐个顺序请求。默认每游戏一页、每作者最多五条详情；支持最多两页。间隔两秒，沿用 httpx 超时与请求头。403/429 停止全部作者，普通失败隔离到作者；不自动重试，不无限翻页。成功作者可从报告恢复而不重发请求；pending_ids 保存尚未取得详情的身份，恢复不使用漂移页码。超过两位作者的全面调度尚未实现，不宣称全部订阅覆盖。

官方 Core/List/New 文档确认 userid、gameid、itemtype、include_updated、秒制 max_age 与 page。实测当前作者 3945073：逗号分隔多 gameid 返回 HTTP200 空响应；单游戏 JSON 正常，因此实现逐游戏查询。

实测单页：六游戏共三条 ID，均出现在绝区零结果中；取得 732748 的一条 ProfilePage 详情，作者、作品与游戏身份均匹配。其来源更新时间缺失；没有误报来源更新。总计七请求，详情上限一导致 partial，两个 ID 保留待处理。报告 check_20261029_101316_268457.json。非空第二页行为尚未获得真实样本；模拟测试验证了有界分页/去重。max_age 窗口完整性仍未证明。

first_seen 是本地发现事件，不等同新发布通知。首次明确应用报告时，在 sync_runs.error_summary.author_check 内原子保存作者基线（无需新表迁移）；首次取得作品为历史，source_updated 仍由现有 importer 严格比较旧、新 updated_at。metadata_changed 不升级成版本更新。只有基线之后新发布、此前未收录的作品计为新发布候选。

真实写入必须由用户选择具体报告。每作者一个事务，MOD、事件和作者基线一并提交；事务前在写锁内使用已验证的 Backup API 备份。重复应用同一报告跳过。部分报告的已取得记录允许保存，未处理 ID 仍在报告，覆盖保持 incomplete。

```powershell
$python = Join-Path $env:LOCALAPPDATA 'ErYouToolbox\venv\Scripts\python.exe'
& $python -m unittest tests.test_author_updates tests.test_subscriptions tests.test_importer tests.test_react_api
& $python scripts/check_author_updates.py --dry-run --pages 1 --details 2
# 检查输出后，填写具体报告路径，手动确认写入：
& $python scripts/check_author_updates.py --apply-report logs/author_updates/实际报告.json
# 对同一报告剩余 ID 或失败作者进行下一轮预览；先确认前一批是否需导入：
& $python scripts/check_author_updates.py --resume-report logs/author_updates/实际报告.json --dry-run --details 2
```

报告含来源公开字段与图片 URL，不下载图片或 MOD。不要将日志上传 Git。页面显示最近预览状态，数据只有手动导入后才进入本地订阅流。恢复缓存记录保留原采样时间；同一次 Core 返回的已收录 ID 仍需有界详情比较，因为 ID 列表不携带版本变化证据。
