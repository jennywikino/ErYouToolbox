# OB4-B 自动同步与自动入库

## 默认行为

默认关闭。网页保存设置不会注册 Windows 任务，也不会因刷新网页而执行同步。

- 手动：继续使用现有检查、预览、确认流程。
- 自动检查：一次性任务检查后退出，保留候选报告，不写数据库、正式检查点或数据库备份。
- 自动入库：用户明确启用后，一次性任务检查并自动提交新作品及具有可靠来源更新时间证据的记录。仅标题、图片、标签、modified_at 变化及首次取得 updated_at 不作为自动来源更新；这些资料补齐仍可通过手动预览确认。

复用 WebSync、collect_game、import_samples、Backup API、事务、正式检查点及 OS 文件锁。不启动另一套常驻服务、不执行图片请求、不增加数据库结构。

默认六游戏串行，每游戏最多3页、每页10条；每游戏页数可设1至10。沿用有界重试、429 Retry-After 和停止规则；限流后即使手动立即运行也不绕过本机冷却。Coverage保持incomplete。

自动确认持锁完成检查与写入；写事务内再次校验数据库基线和自动入库开关。作品、事件和检查点同事务提交，备份失败或SQL失败回滚；无作品变化不创建数据库备份。已经开始的事务不会因切换关闭而被强制中断。

## 本机设置与移动盘

本机文件位于 `%LOCALAPPDATA%\ErYouToolbox\auto_sync\<project_id>\`：settings.json、last_run.json、历史运行报告、locator.json、bootstrap.ps1 及任务输出日志。不将自动入库偏好从另一台电脑自动继承。各电脑分别注册和启用。

config/project_identity.json 是项目标识，不包含秘密。注册时只保存相对盘根目录的位置；任务由本机 bootstrap 启动，逐个盘根检查这个**确切路径**与项目标识，不做递归搜索。换盘符不需要修改代码。如果相同标识出现多份、移动盘缺失、数据库缺失或本机虚拟环境缺失，直接报错退出，不创建数据库、不改其他目录、不反复重试。

注册的计划任务以当前用户、有限权限、交互登录方式执行，不保存密码；浏览器和React API均不必打开，但Windows用户必须已登录。电脑休眠或关机时不能同步，StartWhenAvailable允许系统恢复后补触发。安全策略可能禁止普通用户注册任务，遇到该错误应报告，不自动提权。

任务间隔使用注册时设置。修改网页间隔后，请再次执行register更新Windows触发器；网页会显示间隔不一致提示。设置“关闭”立即阻止后续任务访问来源；也可禁用或删除本机计划任务。任务查询状态最多缓存30秒。

## 首次验收（项目根目录 PowerShell）

所有Python命令使用项目解释器：

```powershell
$python = Join-Path $env:LOCALAPPDATA 'ErYouToolbox\venv\Scripts\python.exe'
& $python -m unittest discover -s tests -p test_auto_sync.py
```

先使用已有项目备份机制；推荐另外一块物理设备的目标目录：

```powershell
& $python scripts/backup_project.py
```

默认目标与项目同盘，不能代替独立灾难恢复备份。需要时给以上命令增加 `--destination` 和明确的私人备份目录。

先执行一次单游戏小样本，只检查：

```powershell
& $python scripts/auto_sync.py --dry-run --run-now --game 8552 --max-pages 1
```

该显式dry-run即使自动模式关闭也可执行，但不绕过429冷却，也不会覆盖仍有效的手动待确认预览。确认报告及保留数据正确后，可选择自动检查：

```powershell
& $python scripts/auto_sync.py --mode check --interval-hours 6 --max-pages 3
& $python scripts/manage_auto_sync.py register
& $python scripts/manage_auto_sync.py query
```

注册后首次触发约一分钟后，后续按间隔触发。运行完自动退出；默认不自动重试失败任务到成功，而是保留报告、等待下次计划或手动恢复。

网页关闭时手动执行一次已保存模式，验证与浏览器无关：

```powershell
& $python scripts/auto_sync.py --run-now
```

只有用户完成小样本验收并决定允许真实写入后，才执行：

```powershell
& $python scripts/auto_sync.py --mode apply
```

也可在网页选择自动入库并确认保存。该操作不立即执行入库，但已注册的任务下一次触发会按此模式运行。自动入库后的报告分别显示扫描统计和实际新增/来源更新数；其他资料变化不属于自动入库范围。

关闭、禁用、删除：

```powershell
& $python scripts/auto_sync.py --mode off
& $python scripts/manage_auto_sync.py disable
& $python scripts/manage_auto_sync.py query
& $python scripts/manage_auto_sync.py delete
```

这些入口只操作身份匹配的本工具任务，不删除数据库、备份、检查点或历史报告。移动盘不在时，也可通过Windows任务计划程序禁用 `ErYouToolbox-AutoSync-e459681a`。

## 网页及恢复

重启现有工具盒后，在最新MOD顶部保存模式、间隔及页数。主同步区继续显示外部一次性任务的进度和结果，允许手动检查。自动任务不会抢占十分钟内仍等待确认的手动预览；提示manual_preview_pending时先处理该预览或等待过期。

设置页显示上次检查、下次允许检查、Windows下次计划触发、最近任务状态、实际新增、来源更新、请求/失败及覆盖状态。关闭网页不影响已运行的计划任务。API重启可读取外部任务日志；正式进度仍从SQLite同步日志恢复。恢复时复查首页和重叠页，不跳过未提交数据，不能保证分页漂移时绝对无遗漏。

## 本轮验证边界

- 先运行OB4-A相关32项回归通过。
- 最终完整Python回归335项通过，其中自动任务测试20项。前端10项及生产构建通过。Windows PowerShell 5.1 Parser.ParseFile检查两个PS脚本通过。
- 测试使用临时SQLite和模拟来源，覆盖默认关闭、检查不写库、自动入库、幂等、共享锁、超时恢复、429冷却、备份/事务失败、禁用开关、身份定位、状态刷新，以及已阅/关注/高清图片保护。任务注册/查询/禁用/删除用模拟subprocess测试，未创建真实任务。
- 真实来源只调用原神一页：1次请求、10条、全部无变化。比较目标为从只读生产连接用SQLite Backup API生成的临时库，没有生产apply或生产偏好写入；生产库读取时856条。
- 未实际注册Windows任务、未验证真实定时触发、真实E/F硬盘切换或浏览器交互。这些由用户按上述步骤验收。
