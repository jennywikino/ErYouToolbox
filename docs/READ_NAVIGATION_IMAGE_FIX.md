# V0.5 已阅、返回位置与图片加载修复验收

## A：已阅功能

2026-10-30 只读检查：生产 schema=2，797条MOD，user_states有is_read但缺first_viewed_at。详情提示迁移并禁用按钮符合代码逻辑，不是另一份浏览器状态库。卡片和详情都使用 /api/read-state，按source + item_id定位item_type=Mod。

临时库验证旧结构迁移、重复标记、撤销、重新连接持久化、失败回滚和本机HTTP写入，共10项通过；未迁移真实库。迁移脚本已存在，无需重建数据库。

先停止同步、导入和回填，手动执行：

```powershell
$python = Join-Path $env:LOCALAPPDATA 'ErYouToolbox\venv\Scripts\python.exe'
& $python scripts/backup_project.py
& $python scripts/migrate_read_states.py --apply
& $python -c "from pathlib import Path; import sqlite3; c=sqlite3.connect(Path('data/eryoutoolbox.db').resolve().as_uri()+'?mode=ro',uri=True); print('Schema:',c.execute('PRAGMA user_version').fetchone()[0]); print('Fields:',[r[1] for r in c.execute('PRAGMA table_info(user_states)')]); print('MODs:',c.execute('SELECT COUNT(*) FROM mods').fetchone()[0]); print('Integrity:',c.execute('PRAGMA integrity_check').fetchone()[0]); print('Foreign keys:',len(c.execute('PRAGMA foreign_key_check').fetchall())); c.close()"
```

预期 schema=3，含 first_viewed_at，MODs=797，Integrity=ok，Foreign keys=0。默认备份在项目盘根目录 ErYouToolboxBackups，同物理设备不是灾难恢复备份；可加 --destination 指向另一物理磁盘。迁移本身还会先生成并校验data/backups备份。失败停止，不删除或重建数据库。

随后重启现有启动器，打开详情自动标记，返回检查卡片状态并恢复未阅，关闭重开验证持久化。

## B：返回位置

原先打开详情后卸载列表，并强制滚动到顶部；返回没有锚点恢复。

现在保留隐藏列表DOM，在现有hash路由/history.state中保存分区、游戏、搜索草稿及提交关键词、排序、分级、已阅过滤、分页、图片偏好、滚动位置及联合MOD身份。内部返回和浏览器后退/前进恢复快照，以作品身份及原视口偏移定位；短时ResizeObserver校正布局，用户滚动/点击/按键立即停止校正。若未阅筛选导致作品移出结果，降级恢复原滚动位置，不跳转到其他游戏。

直接切换游戏/主分区清除旧恢复目标并回顶部。首次直接打开详情没有列表快照时返回默认库。列表返回会重新读取一次本地JSON反映已阅变化，但不会主动清空并重建所有卡片。

## C：图片诊断与实际比较

- 列表已有正确缩略图读取；详情使用image_url原图，切换条使用switch_url/thumbnail_url。没有改写来源文件名或降低高清图质量。
- 只读抽查20条有图记录，共155张图，133张有独立缩略图及切换图；22张安全退回原图，可能因来源没有单独规格，未猜测地址。
- 原列表全部设置native lazy，但Chrome仍会提前请求较远图片。现对接近视口的卡片才赋src，首三张eager/high，其余lazy/low并异步解码。
- 保留16:10卡片占位；详情大图仅加载当前原图，限制稳定容器高度，保持object-contain。区分无图、未加载、加载中和加载失败。
- 返回保持列表DOM及原src，避免依靠重建图片来恢复；未加缓存破坏参数、代理或图片服务。缓存命中时检查complete/naturalWidth，避免加载提示卡住。

使用同一36条模拟MOD、18条/页、延迟SVG，在隔离Chrome和临时Vite端口比较；所有API和图片均拦截，不访问生产API或下载真实图片：

| 项目 | 修改前 | 修改后 |
|---|---:|---:|
| 首屏图片请求尝试 | 12 | 6 |
| 返回后的作品锚点误差 | 1758px | 0px |
| 返回时额外图片请求 | 0 | 0 |
| 返回时本地列表JSON请求 | 0 | 1 |

修改前返回图片虽重新创建，浏览器未产生额外图片请求，因此不能把原问题全部归因于缓存失效。模拟测试没有证明真实CDN缓存命中或下载加速，未声称真实网络耗时改善。真实CDN速度与缓存需用户在浏览器Network面板（关闭Disable cache）复核；保留已有referrer策略和原URL。

内部返回、浏览器后退/前进均恢复0px误差；游戏切换回0px；附加游戏8552、Fixture搜索、first_seen排序及第二页恢复通过。测试日志保存在忽略的logs/ui_smoke/，不进入Git。

```powershell
& $python -m unittest tests.test_read_states tests.test_subscriptions.SubscriptionTests.test_http_post_guard_and_follow_round_trip
```

前端目录运行 pnpm.cmd test 和 pnpm.cmd build。可选从项目根目录运行 node tests/ui_navigation_smoke.cjs verify，需已有Chrome（不安装依赖），仅使用合成数据；报告及隔离浏览器profile保留在logs/ui_smoke。

真实已阅端到端仍需用户先手动迁移，然后在实际UI验收。历史累计/近期热门算法、采集器、数据库内容和已有分级图片均未改动。
