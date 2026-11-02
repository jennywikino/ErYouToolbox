# OB6-B 渐进历史补全

## 范围与默认值

复用 `collect_game` → `normalize_record` → `import_samples`，只查 `Mod/Index` 的 `Generic_Newest`。六游戏仍读取 `config/games.json`。

历史补全默认关闭。本轮只读核对的本机日常设置为 `check / 3 小时 / 每游戏最多 5 页`，没有更改。历史单独采用 24 小时间隔，默认每游戏 2 页，允许 1～5 页，请求串行，每页请求最多 50 条，实际页大小由返回元数据确认。

**HTTP 次数也受页预算约束**：默认六游戏整轮最多 12 次，最大设置最多 30 次，重试计入这个额度。超时/临时错误最多重试一次；重试消耗额度后可能少扫一页。429/403 停止后续游戏；保存冷却时间，不长时间阻塞等待。无有效 Retry-After 时保守冷却 24 小时。

每游戏一次失败尝试也占用当天额度。暂停/继续不跳过 24 小时间隔；暂停在当前 HTTP 请求结束后的安全点生效。1 页续扫只够复核边界，建议至少 2 页。

## 进度与事务

- 正式进度：现有 `sync_runs.error_summary.history_scan.checkpoint`，和该游戏 MOD/事件写入处于**同一 importer 事务**。不新增数据库结构。
- 移动盘镜像及运行状态：`logs/history_sync/state.json`。
- 启用、暂停和页数配置：`logs/history_sync/settings.json`，跟随项目移动。
- 日常预览仍在 `logs/web_sync/`，日常已提交检查点仍为 `error_summary.web_sync`，互不替代。
- 扫描报告：`logs/history_sync/latest.json` 和唯一命名的 `run_*.json`。
- 独立 dry-run：`preview_latest.json`、`preview_*.json`，不推进正式检查点、尝试时间或产生数据库备份。
- 429/403 冷却独立保存为 `cooldown.json`；即使 dry-run 也保留限流安全状态，区别于正式扫描进度。

历史检查点样例（临时测试数据，非生产提交）：

```json
{
  "game_id": 8552,
  "sort": "Generic_Newest",
  "per_page": 2,
  "page": 2,
  "boundary_ids": [6, 5],
  "last_committed_at": "2026-11-02T06:00:00Z",
  "last_scan_at": "2026-11-02T06:00:00Z",
  "oldest": "2020-09-13T12:35:00Z",
  "source_end_observed": false,
  "coverage": "incomplete"
}
```

恢复永远从数据库读取正式位置。项目 JSON 镜像保存失败时，已提交事务仍可恢复；不会仅因镜像损坏就跳过未提交页。每个实际写入的游戏批次先调用现有 `verified_backup`（SQLite Backup API + 完整性/外键检查），备份失败不写入。该封装沿用 `subscriptions_*.db` 命名。即使 MOD 无变化，提交历史进度仍是实际数据库写入，需要一次备份；check/dry-run 没有备份。

## 漂移与覆盖

首次从第 1 页开始；续扫重读已提交边界页，再向旧页推进。边界 ID 列表不一致时先记录漂移，不推进。下一轮按漂移方向有限复核相邻页，使用旧边界尾部多个 MOD ID 对齐，同时检查发布时间递减、页大小及记录总数的一致性。边界再次变化并不直接认定失败：只有在本轮有界重叠范围内重新找到足够锚点才允许重新对齐。

关键时间缺失、顺序异常、身份错误、不完整页、元数据异常均不提交不可信页。网络失败前已验证的连续前缀可以独立提交，失败页仍待下一轮重叠重试；数据库事务失败则该游戏作品、事件和进度一起回滚。其他游戏已提交的数据不受影响。

空页只有在 `_nRecordCount`、`_nPerpage` 和实际记录数一致时，才能记录来源末页观察值。仅“全是已有记录”、`_bIsComplete` 或达到预算均不代表完整覆盖。所有结果仍为 `coverage=incomplete`；即使观察末页也不声称无遗漏。

大幅增删、连续漂移或找不到足够锚点时会停留在旧检查点，需要人工检查报告或提高有限页预算，不能保证任意漂移都能自动恢复。固定页码 API 无游标/快照一致性，不能承诺一次扫描绝对完整。

## 与自动同步衔接

复用当前一次性自动任务与现有 Windows 计划任务，未注册第二个任务或后台服务。日常扫描、作者检查先执行，历史最后执行；日常尚未到期时也可独立判断历史是否到期，不修改日常检查时间。

共享 `logs/content_ratings/instance.lock`；自动任务已持锁时显式传递锁归属，不嵌套加锁。待确认手动预览保留，不被历史任务替换。

- off：不自动联网。
- check：历史只生成比较报告；不写 SQLite，不推进正式历史位置。再次到期会从同一正式边界预览。
- apply：仅在历史已明确启用、未暂停且现有模式仍为 apply 时执行备份事务。写入前再次验证模式、元数据基线和历史检查点。

保留已阅、关注、首见时间、评级证据及已有高清图片。来源版本时间较旧或无法比较时仅补缺失信息；`modified_at` 不生成来源更新，只有已有明确 `updated_at` 严格增加才使用 importer 的 `source_updated`。新收录历史记录的 `first_seen` 表示本地首次发现，不表示来源刚发布。

## 真实只读验证

2026-11-02 UTC，仅绝区零 19567，两次 HTTP 请求，未重试：

| 指标 | 实际结果 |
| --- | --- |
| 页码 / 实际每页大小 | 1、2 / 各 50 |
| 来源返回总数 | 元数据为 5854，非本地全量覆盖声明 |
| 获取 / 去重后 / 重复 | 100 / 100 / 0 |
| 新收录候选 | 6 |
| 已有记录 | 94 |
| 可靠来源更新候选 | 1 |
| 资料变化候选 | 6 |
| 无变化 | 87 |
| 可写入变化候选总数 | 13（6 + 1 + 6） |
| 最新发布时间 | 2026-11-02T00:55:55Z |
| 最老发布时间 | 2026-10-23T10:52:14Z |
| 排序 | 本次两页发布时间递减，非长期保证 |
| 末页 / 覆盖 | 未到来源末页 / incomplete |

报告在 `logs/history_sync/preview_latest.json`。没有执行生产 apply，没有创建正式历史检查点、没有启用历史配置。后续保护规则进一步收紧为无可比来源版本时间时仅补缺失值，未再次发起来源请求；上述数字为此次真实 dry-run 的原始观察值。

## 测试与本机验收

新增 `tests/test_history_sync.py` 使用真实临时 SQLite 和 httpx MockTransport。覆盖初次/续扫、六游戏隔离、前后漂移及再漂移、重复 ID、实际页大小、时间/身份/分页异常、空页、请求预算、429/403、部分成功恢复、Ctrl+C、备份/事务回滚、共享锁、check 不写库、已阅/关注/图片/评级保护、真实来源更新、镜像恢复和受限 HTTP 入口。

本轮相关后端回归共 152 项通过：历史 31、采集器 30、自动同步 21、网页启动 10、网页同步 14、导入器 25、作者轮转 8、React API 13。前端 12 项测试及生产构建通过；Python 和浏览器测试脚本语法检查通过。未执行全仓测试或真实浏览器交互。

项目根目录 PowerShell：

```powershell
$python = Join-Path $env:LOCALAPPDATA 'ErYouToolbox\venv\Scripts\python.exe'
& $python -m unittest discover -s tests -p test_history_sync.py -v
& $python -m unittest discover -s tests -p test_auto_sync.py
& $python -m unittest discover -s tests -p test_startup_sync.py
& $python scripts/history_sync.py --game 19567 --max-pages 2 --dry-run
pnpm.cmd --dir frontend test
pnpm.cmd --dir frontend build
```

独立 `--dry-run` 是用户主动验证入口，可在历史未启用时预览；仍遵守共享锁、手动预览保护和限流冷却，不会改变保存的自动模式。不要反复执行在线命令。

浏览器需重启现有 API 后验收：在最新 MOD 的“展开详情”找到“历史补全”，先保持现有 check 模式，手动启用后执行一次；确认显示候选、各游戏进度，SQLite 和正式历史位置不变。暂停/继续应保存，不绕过当天额度。真实 apply 只能由用户明确选择现有自动入库模式后验收；本轮未执行。

`& $python scripts/history_sync.py --game 19567 --max-pages 2 --apply` 也必须满足已保存的 apply 模式及历史启用配置，不会替用户切换模式。

尚未实测浏览器交互、真实计划任务调度、跨物理 E/F 设备迁移或生产 apply；不能将临时库和构建通过视为这些验收已完成。

## 本轮文件

- 新增 `scripts/history_sync.py`、`frontend/src/HistorySyncSettings.tsx`、`tests/test_history_sync.py`、本文档。
- 局部修改 `gamebanana.py`（可选 HTTP 预算/限流等待上限；默认行为保留）、`importer.py`（历史进度载荷同事务、Ctrl+C 回滚）、`auto_sync.py`（低优先级调度）、`react_api.py`（受限历史入口）、`SyncCheck.tsx`（折叠区入口）、`tests/ui_navigation_smoke.cjs`（历史状态测试响应）。

未修改数据库 schema、Windows 任务、作者轮转算法、图片回填或卡片样式。未提交或推送 Git。
