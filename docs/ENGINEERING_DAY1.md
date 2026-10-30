# 1.0 工程收敛：Day 1 审计

日期：2026-10-30。结论：**有条件可行，两周应收敛现有主链路，不应重写或扩展产品范围。** 估算为一名熟悉代码的开发者8–10个工作日，另需用户参与真实电脑验收；估算不是交付保证。若仍增加热门/分级/客户端需求，或缺少生产迁移和联网写入验收窗口，两周目标不可承诺。

## 实际状态和证据等级

| 项目 | 实际证据 | 状态 |
|---|---|---|
| 生产数据库 | schema 2；797 mods、797 user_states、798 mod_events、9 sync_runs、1 author_subscriptions；integrity=ok，FK=0 | 已只读核实 |
| 已阅代码 | schema 3，迁移新增first_viewed_at；详情available=false禁用，卡片与详情共用/api/read-state | 代码已完成；生产未部署迁移 |
| 正在运行的服务 | API 127.0.0.1:8766；Vite 127.0.0.1:5173；API命令行指向当前项目scripts/react_api.py，虚拟环境启动器转交给本机基础Python进程 | 已只读核实，未停止用户服务 |
| 实际数据库路径 | API ROOT来自脚本位置，连接当前项目data/eryoutoolbox.db；对真实本地MOD GET读状态返回200、available=false | 未发现第二份数据库路径；并非仅推测迁移问题 |
| 已阅副本E2E | 正式Backup API副本→迁移→真实HTTP POST/GET→退出API进程→新API进程GET | PASS，非Mock；仅写副本 |
| 浏览位置 | 当前代码已有history.state、联合身份锚点、保留列表DOM和ResizeObserver；上一轮隔离浏览器合成数据0px误差 | 代码存在；真实用户场景仍待验，不能把前一轮结果当本次现场验收 |
| 网页同步 | 普通同步仍为CLI；网页作者检查仅预览，导入报告需CLI；没有通用网页同步任务闭环 | 真实功能缺口 |
| Git | master，仅b85a809/V0.1提交，v0.1.0标签；未配remote，大量后续代码仍未追踪/未提交 | 源码冻结尚未完成 |

本次副本报告：data/diagnostics/read_state_20261030_034801_848915/report.json。API进程从14212重启为23460，端口由系统分配，未占用/关闭用户8766或5173。

副本执行：标记已阅→GET已阅→恢复未阅→GET未阅→再标记→重启API→GET仍已阅；重复已阅不产生新备份，本地列表read筛选也匹配。副本的MOD、作品事件、同步记录、关注表内容哈希不变，其他用户字段不变；生产DB和已有检查点SHA-256均不变。schema 2备份和schema 3工作副本保留在忽略的data/diagnostics内，含私人数据，不应上传。

相关临时库回归：41项通过（已阅、关注、迁移、数据库、备份）。生产库未执行POST、迁移或恢复。本次没有重新联网采集，也没有对生产UI进行点击写入验收。

## 当前数据流和依赖

```text
start_toolbox.cmd / stop_toolbox.cmd
  → toolbox_launcher.ps1（本机venv、pnpm、进程身份、端口和日志）
  → Python react_api.py 127.0.0.1:8766 + Vite 127.0.0.1:5173
  → React App/卡片/详情 → ui_queries → 项目data/eryoutoolbox.db
                          → read_states/subscriptions → 备份+事务 → user_states/关注表

scripts/sync.py（CLI）
  → gamebanana.collect_game（两路有界扫描）
  → models.normalize_record → importer.import_samples
  → 备份+事务 → mods + mod_events + sync_runs（保留人工状态）

网页作者检查 → author_updates.preview → Core作者ID列表/六游戏 + ProfilePage
  → logs/author_updates预览报告 → 用户手动CLI apply_report → 同一importer
  → sync_runs JSON保存作者基线

热门榜 → popular在线只读+内存缓存（不入库）
backup_project → SQLite Backup API + 指定检查点 + manifest/SHA256 → 临时恢复校验
```

主要运行依赖为Python/标准库SQLite/httpx，React/TypeScript/Vite/Tailwind、Node/pnpm。前端lockfile应冻结。旧Streamlit有独立requirements-ui.txt；不需要把它作为1.0启动依赖。移动盘路径由脚本位置解析；各电脑venv仍在LOCALAPPDATA。

## 保留与冻结

保留并收敛：React列表/详情/画廊、ui_queries、本机API安全校验、SQLite迁移和Backup API、gamebanana/models/importer、sync.py双扫描、已阅/关注、现有作者检查的有界查询与报告、现有启动器的PID身份验证。统一入口应包装这些函数，不复制采集/导入算法。

冻结且不删除：Streamlit UI、早期probe/audit工具、全历史回溯、图片与分级批量回填调度、热门/近期热门的新增能力、额外平台、定时任务、桌面客户端、云同步。现有热门可继续读，不纳入本轮新增需求验收。

重复/分散：不是多套数据库，但有两套UI；不同脚本内重复网络超时/限速/429处理、备份文件命名和结果状态格式；迁移入口名称分散；author_updates还从scripts导入锁；read/subscriptions各自持有相似写事务。先统一调用入口、契约和诊断，不把这些全部重写。

## 必须处理的阻断和代码级风险

1. **P0部署门槛**：代码schema3、生产schema2，启动器只访问/api/games判断就绪。缺少只读启动健康报告和清晰的显式迁移流程，服务“已启动”不等于已阅可用。
2. **P0源码保护**：大量已验收功能尚在未提交工作区。先做数据备份，再由用户复核白名单本地提交；本轮不擅自commit、修改remote或push。
3. **P0网页同步缺口**：现有/api/author-updates只允许预览；普通sync.py未接入网页任务。要加入有限任务状态、确认写入、错误/取消和重启恢复，不是添加定时器。
4. **P1来源节流不统一**：普通sync.run_sync传collect_game delay=0.0，而作者/热门各自使用间隔和独立锁。多个入口可同时请求来源；网页同步前应统一总请求预算与互斥/节流。不要再引入第三个独立网络实现。
5. **P1作者公平性/基线**：固定LIMIT2总取前两位，超过两位可能饥饿；partial报告与checked_at、pending_ids的语义分散。需明确基线完成条件、待处理ID重试及跨批次新作判定，不能靠“最近预览成功”当作已同步。首次基线、真实更新、历史发现需有统一状态契约。
6. **P1任务生命周期**：ThreadingHTTPServer长请求可重复触发；各工具锁作用域不同。未来网页写任务需项目级单任务门闩、服务器保存报告/任务身份、原子导入；取消应在网络/批次边界执行，不能半提交MOD与事件。
7. **P1备份覆盖**：Backup API会复制整库，包括关注及用户字段；manifest快照目前重点校验原四表。作者检查未处理ID报告不在默认检查点备份名单，需在后续安全范围内扩展，而非误称已经完整支持所有任务恢复。
8. **P1导航验收不足**：保留DOM/锚点有合成测试，但真实未阅筛选可能令已打开作品移出列表、最后一页缩短、热门自有分页状态与顶层快照不同；用户主动滚动应停止定位。必须用真实图片/实际游戏状态验收，不能继续仅报告编译通过。
9. **P1备份成本**：首次已阅写入会做整库备份，安全但大量阅读会增加延迟和文件数；先量测实际成本，再定批次/会话备份策略，不在本轮取消安全机制或删除历史备份。
10. **P1可移植性/恢复**：E/F切换可解析同库，但venv和Node/pnpm来自当前电脑；启动器状态hash随项目绝对路径变化。换盘前退出服务，不能依据旧PID直接杀进程。两个Windows环境都需实测。
11. **P1运行版本不一致**：当前启动的是pnpm dev，前端可热更新，Python API则必须重启才载入代码；没有统一运行版本/schema标识。稳定交付前应冻结依赖与前后端版本，并验证重启流程，不能把浏览器刷新当作后端升级。

这些风险可以通过现有模块的窄接口调整收敛，尚无证据要求大面积重构。若后续验证显示现有导入事务无法承载任务确认，先报告影响，再调整计划。

## 两周最小范围、顺序和工作量

| 时间 | 范围 | 估算 | 必须验收 |
|---|---|---:|---|
| Day1（本轮） | 定向审计、真实备份副本HTTP已阅E2E、手动迁移及失败恢复说明 | 0.5–1天 | 本报告/副本证据 |
| Day2 | 用户手动迁移生产、只读健康诊断、冻结当前可复现源码 | 0.5–1天 | 生产797条和个人状态不变；实际浏览器已阅闭环 |
| Day3 | 只修真实导航问题，统一详情返回契约 | 0.5–1天 | 第二页/游戏/分级/未阅、后退前进；锚点移出结果也不跳错游戏 |
| Day4–5 | 包装现有sync为网页有界任务，预览→确认→应用；统一互斥及限速 | 1.5–2天 | 临时库失败/429/取消回滚；用户确认后单游戏真实小样本写入 |
| Day6 | 网页同步状态和API重启恢复，避免重复应用，操作入口收敛 | 1天 | 中途关闭API后状态明确，不假成功、不丢已提交数据 |
| Day7–8 | 作者公平轮转、基线/待处理ID/新作与source_updated语义修正 | 1–1.5天 | 1–2作者多游戏、第一次无假新作、失败不清空历史 |
| Day9 | 两电脑启动关闭、数据备份/临时恢复、长会话与故障验收 | 1天 | E/F、独立本机venv、无关进程不被停止、私人数据不进Git |
| Day10 | 只修阻断并冻结1.0；留出0.5–1天风险缓冲 | 0.5–1天 | 用户完整日常流程签收，本地版本可回退 |

最小交付仅五项：已阅持久化；浏览位置恢复；网页手动一键有界同步；作者有界追踪；启动/同步失败恢复。所谓一键同步是用户触发并确认的流程，不承诺无人值守、全站完整性、实时推送或全历史回溯。

## 用户手动迁移与检查

在项目根目录，先关闭启动器及独立同步/回填任务。以下命令不会在本轮自动执行。

```powershell
$python = Join-Path $env:LOCALAPPDATA 'ErYouToolbox\venv\Scripts\python.exe'
# 迁移前只读检查；迁移后再执行同一条，预期schema由2变3，MOD仍797，完整性正常。
& $python -c "from pathlib import Path; import sqlite3; c=sqlite3.connect(Path('data/eryoutoolbox.db').resolve().as_uri()+'?mode=ro',uri=True); print('Schema:',c.execute('PRAGMA user_version').fetchone()[0]); print('Fields:',[r[1] for r in c.execute('PRAGMA table_info(user_states)')]); print('MODs:',c.execute('SELECT COUNT(*) FROM mods').fetchone()[0]); print('Integrity:',c.execute('PRAGMA integrity_check').fetchone()[0]); print('Foreign keys:',len(c.execute('PRAGMA foreign_key_check').fetchall())); c.close()"
$backupDir = Join-Path $env:USERPROFILE 'ErYouToolboxBackups'
& $python scripts/backup_project.py --destination $backupDir
# 把输出bundle路径填入；先校验备份及临时恢复，再迁移。
$bundle = Read-Host '粘贴本次备份输出的bundle目录'
& $python scripts/backup_project.py --verify $bundle
& $python scripts/migrate_read_states.py --apply
```

每条都需确认PASS/退出码0后再执行下一条，PowerShell不会因为上一个外部程序失败就自动停止整段。迁移本身还会生成并校验data/backups/subscriptions_时间戳.db，再在事务中新增列。备份目标应人工确认为不同物理设备；USERPROFILE只是便携示例，并不保证灾难恢复独立性。

重启启动器后，以实际浏览器完成标记→返回列表→未阅撤销→再次打开→关闭工具盒重开验收。生产未迁移之前按钮禁用是预期行为，不应绕过字段检查。

### 失败恢复方式

- 备份/校验失败：停止，不迁移；保留错误日志和已有备份。
- 迁移SQL失败：现有事务回滚，先重跑只读检查；应仍为schema2、797条，原关注/个人状态保留。修复具体错误后再重试，不运行删除重建。
- 出现完整性异常或意外结果：停止所有写入，保留当前生产文件及WAL/SHM状态，不单独删除日志文件；先对选定bundle执行`--verify`做临时恢复预演。不要在运行中覆盖database主文件。
- 真正生产恢复需要在停服后另行确认文件集合和目标路径，本轮不提供自动覆盖命令。已有before.db副本及bundle可用来复现问题；不可把诊断working.db误当生产库。

## 可重复证据命令

```powershell
& $python scripts/verify_read_state_e2e.py
& $python -m unittest tests.test_read_states tests.test_subscriptions tests.test_database tests.test_backup_project
```

第一条会通过Backup API从真实库产生新的隔离副本，只迁移并修改副本，再启动/关闭自己的临时API进程；不停止用户服务、不对生产POST。每次结果存data/diagnostics/read_state_时间戳/report.json。失败也保留报告和副本，不上传私人数据。

## 最终判定

**代码完成**：已有已阅、迁移、备份及导航修复；本轮新增可重复的副本E2E验证脚本，未重写前端或开发自动同步。

**测试通过**：真实数据副本上的HTTP写入/查询/API进程重启持久化、内容保护检查，以及41项临时库回归；生产只读检查和哈希保持不变。

**真实环境待验**：用户手动生产迁移及真实浏览器已阅操作；真实图片条件下导航验收；网页同步闭环、作者多批恢复、E/F双机与最终版本冻结。不能因为副本测试通过就宣称1.0已稳定可交付。
