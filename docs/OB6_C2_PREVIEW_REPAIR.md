# OB6-C2 定向图片补全

新增 `scripts/repair_previews.py`、`tests/test_preview_repairs.py` 和本文档。未修改现有回填脚本、React、数据库结构、采集器或同步系统。

## 只读审计

实际 1097 条 MOD：

| 游戏 | 无有效预览 | 仅缩略图/原图未验证 | 有原图元数据 |
|---|---:|---:|---:|
| 原神 | 278 | 4 | 48 |
| 崩铁 | 33 | 0 | 48 |
| 绝区零 | 198 | 0 | 248 |
| 鸣潮 | 20 | 0 | 60 |
| 终末地 | 20 | 0 | 60 |
| 异环 | 20 | 0 | 60 |
| 合计 | 569 | 4 | 524 |

全部对应 ID 保存于 `logs/preview_repairs/audit.json` 的各游戏 `ids` 中。无有效预览包括空、非法 JSON、无效 URL；不等同于来源确实无图。528 条有 URL 的记录均标记待网络验证；524 条仅表示有原图元数据，不保证图片可访问。

数据库本身不能确认来源无图，此类计数为 0 表示没有确认依据，而非所有作品来源均有图。今后的来源无图证据保存在专项状态与报告中，不修改作品原始资料。

## 流程

每批指定一个配置中的游戏，从 SQLite 选择缺图 ID，默认 10、最多 20 条。顺序请求官方 `Mod/{id}/ProfilePage`，无重试，间隔 2 秒；不扫描分页、不请求图片本体。先验证返回 ID、类型端点与游戏，再复用 `fetch_exact_item` / `extract_preview_images`，原图只能来自真实 `_sFile`。

只接受经过原有 URL 安全校验的 HTTPS `images.gamebanana.com/img/ss/mods/` 地址。新脚本复用 `run_backfill` / 原图片计划和事务函数；写入仅涉及 `preview_urls_json`。复用 `verified_backup` 进行整批一次 SQLite Backup API 备份与检查。共享现有 `logs/content_ratings/instance.lock`，不与同步同时写库。生产数据库不存在时不会初始化。

专项进度：`logs/preview_repairs/state.json`（绑定相对数据库路径），记录已处理状态及检查时间（UTC epoch 秒）。apply 事务成功后才更新；默认 dry-run 只写报告，不更新此状态。下批自动跳过已有原图和暂未到复查时间的 ID，新增历史作品下次会自然进入候选，不接入定时任务。

只有身份验证成功、HTTP 200 且明确 `_aImages=[]` 才确认来源无图，apply 后 7 天复查。缺字段、无可信原图、403、429、404、非法 JSON、网络错误都作为失败。失败 apply 记录一小时复查间隔；`--retry-failed` 优先失败记录但不绕过间隔。429/403 立即停止，冷却记录即使 dry-run 也保存，遵守 Retry-After（无可靠值时 24 小时），不阻塞长时间等待。

原实现对任一已有原图有保守保护，因此混合“原图＋低清”的旧记录可能被跳过；本轮不覆盖既有高清图，也不声称此类已全部修复。现有 URL 是否失效不在本轮自动检测范围，不将网络失败当无图，也不猜测高清地址。

## 实测

原神 10 个真实 ID：436225、475764、487517、502646、502722、502886、502891、506347、515521、539510。

实际详情请求 10 次，全部通过来源身份验证并取得可信原图元数据，待更新 10 条；失败 0，来源确认无图 0，实际更新 0、备份 0。报告：`logs/preview_repairs/preview_latest.json`。未请求图片文件，不能据此宣称图片本体加载成功。

离线新增测试 10 项、原回填回归 35 项通过，使用临时数据库与模拟 HTTP；涵盖六游戏审计、精确 ID、身份拒绝、可信域名、缩略图升级、已有高清不降级、重复幂等、来源空图证据、429 冷却、超时恢复、dry-run 无副作用、备份失败和事务回滚、人工状态与事件保护。Python 语法检查通过。

## Windows 验收

项目根目录执行：

```powershell
$python = Join-Path $env:LOCALAPPDATA 'ErYouToolbox\venv\Scripts\python.exe'
& $python scripts/repair_previews.py --audit
& $python -m unittest discover -s tests -p test_preview_repairs.py
& $python scripts/repair_previews.py --game 8552 --limit 10 --dry-run
```

用户审阅 dry-run 后手动写入（Codex 本轮未执行）：

```powershell
& $python scripts/repair_previews.py --game 8552 --limit 10 --apply
```

后续每批可选择 `--limit 20`，其他五游戏同样读取既有配置。成功 apply 后重复相同命令会选取下一批缺图记录，已补齐 ID 不重复写入。失败任务可在复查期限后加 `--retry-failed`。不要删除旧状态或备份来强行推进。

恢复时以 SQLite 当前图片数据及专项状态共同判断；状态保存失败发生在提交之后时，重复执行仍通过已有原图保护避免重复写入。审计不修改数据库或任何检查点。本轮没有生产 apply、自动任务变更、Git 提交或推送。
