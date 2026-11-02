# OB6-S1 恢复覆盖与源码归档

日期：2026-11-02。最新家用电脑复验已解除备份 BLOCK，见文末。**以下为此前公司电脑的历史记录，当时交付为 BLOCK：修复代码与临时恢复验证已完成，但生产跨文件一致性检查未通过，未创建生产完整备份，未暂存、提交或推送。** 用户已明确选择保留 BLOCK，不擅自丢弃预览。

不是正式 1.0 发布；旧 v0.4.0-rc1 标签未改变。

## A/B：持久化恢复状态清单

下列“覆盖”指本轮代码已纳入验证清单，不表示当前生产整包已完成。

| 相对路径/位置 | 格式、生产者 | 恢复用途 | 类别/必要性 | 本轮覆盖 |
|---|---|---|---|---|
| data/eryoutoolbox.db：mods、user_states、author_subscriptions、mod_events | SQLite schema3；既有导入器、状态API | MOD、图片、评级、已阅、关注及事件 | A，必需 | Online Backup API；五表计数和全用户表指纹 |
| 同库 sync_runs.error_summary.web_sync | 日常同步事务 | 六游戏已提交同步位置 | A，必需 | 同一数据库快照 |
| 同库 sync_runs.error_summary.author_check/history_scan | 作者/历史导入事务 | 基线、未完成ID、正式历史进度 | A，必需 | 同一数据库快照 |
| config/project_identity.json | UUID对象；项目配置 | 移动盘身份、设备配置关联 | B，存在时必需 | 路径白名单、UUID检查 |
| logs/author_updates/rotation.json | eryoutoolbox-author-check-v1；run_rotation | 公平轮转、失败队列、待处理ID、冷却 | B，存在时必需 | 格式与字段验证 |
| logs/author_updates/latest.json | 同上；save_report | 手动作者入口读取的限流证据及最新预览；不只是显示报告 | B，存在时必需 | 格式、作者身份和待处理ID验证 |
| logs/history_sync/state.json | eryoutoolbox-history-v1；HistorySync | 最近尝试、漂移复核、镜像位置、失败 | B，存在时必需 | 相对数据库绑定；与正式历史镜像交叉核对 |
| logs/history_sync/settings.json | enabled/paused/max_pages，原生产者无format | 项目历史补全授权/暂停与预算 | B，存在时必需 | 精确字段集和类型检查 |
| logs/history_sync/cooldown.json | not_before等；HistorySync | 站点限流 | B，存在时必需 | 按固定路径验证有限数值 |
| logs/preview_repairs/state.json | preview-repairs-v1；repair | 已处理、失败、来源无图、复查时间 | B，存在时必需 | 相对数据库绑定，已验证项与本地记录核对 |
| logs/preview_repairs/cooldown.json | not_before等；repair | 403/429冷却 | B，存在时必需 | 按固定路径验证 |
| logs/content_ratings/checkpoint_*.json | eryoutoolbox-rating-backfill-v1；评级回填 | attempted_ids、失败、限流 | B，存在时必需 | 保留旧格式兼容 |
| logs/content_ratings/source_pause.json | eryoutoolbox-rating-pause-v1 | 来源暂停时间 | B，存在时必需 | 保留旧格式兼容 |
| logs/preview_backfill/*checkpoint*.json | eryoutoolbox-preview-backfill-v1；分页图片回填 | 页位置与未提交进度 | B，存在时必需 | 保留旧格式兼容 |
| logs/web_sync/task.json | eryoutoolbox-web-sync-v1；WebSync | 当前预览与用户确认状态 | B，存在时必需 | 校验状态、task_id、候选MOD基线和同步代次 |

未生成过的可选文件可以缺失，manifest 记录 absent_optional；已有必需路径损坏、未知格式、相对绑定错误或与数据库不一致会拒绝 complete。不通过复制整个 logs 覆盖状态。

## C/D/E：明确排除

- C 可再生：author_profiles 头像URL缓存、author_updates/check_*.json 历史报告、历史 run_/preview_ 报告、图片审计/预检统计、旧 web_sync 归档等。当前作者 latest 被代码读取作限流依据，因此特例纳入 B，不与其他报告混淆。
- D 本机配置：LOCALAPPDATA/ErYouToolbox/auto_sync/<项目UUID> 的 settings.json、last_run.json、registration.json、locator 与 Windows 计划任务；不能把旧电脑的自动 apply 授权、登录身份和路径直接移植。新电脑安装本机虚拟环境、定位同一项目UUID，先使用 off/check，小样本验收后手动配置并注册本机任务。备份不复制 LOCALAPPDATA 或凭据。
- E 临时状态：instance.lock、settings.lock、*.tmp、启动器 PID/services.json、运行中进程、浏览器 profile、控制台日志。禁止恢复旧PID或锁，全部不纳入数据备份。

项目JSON中的诊断错误文本可能包含旧绝对路径，仅作为诊断保留；恢复定位使用项目相对路径和相对数据库绑定，不依赖错误文本。

## 实现与安全边界

局部修改 scripts/backup_project.py、scripts/verify_backup.py，新增 scripts/recovery_state.py，扩充 tests/test_backup_project.py；未改采集、同步业务、UI、schema 或任务权限。

1. CLI 创建备份新增 `--writers-paused` 明确确认。必须先暂停全部数据库和 JSON 写入；共享任务锁只是额外防护，不能替代用户确认。程序调用也需 writers_paused=True。
2. 固定白名单及旧检查点模式，新增格式验证；额外文件也必须属于白名单。拒绝符号链接/重解析路径，manifest 不允许路径逃逸。
3. SQLite read-only snapshot + Online Backup API，不复制运行中的主文件，不改变WAL/SHM；全用户表/结构指纹及包含关注表的计数写入manifest。
4. 数据库与项目JSON分别捕获，做预览基线、历史镜像和专项图片已验证状态的跨文件核对。捕获与临时恢复完成后均重新检查文件集合、字节和数据库内容，发生变化不标记 complete。
5. SHA-256、manifest incomplete/failed/complete、唯一目录和不覆盖旧备份保留。恢复只在新临时目录，核对全表指纹、完整性、外键、计数、schema及检查点文件。
6. 旧 v1 manifest（无全表指纹、无关注表计数、无恢复清单）仍可验证；其旧备份覆盖范围不会被“升级”为已经包含新状态。JSON和SQLite仍无跨文件原子提交，不能检测两个观察时刻之间发生并完全回退的变化，因此暂停写入是硬前提。

## 当前生产验收：BLOCK

- 用户授权目标：`C:\Users\Admin\ErYouToolboxBackups`；已确认全部写入任务暂停。此路径不是本轮已成功创建的备份路径。
- 只读检查发现 `logs/web_sync/task.json` 状态 waiting、有 candidate，candidate.baseline 与当前 MOD 数据不符；sync_generation 一致。用户反馈当前无法处理，明确要求保留 BLOCK。
- 不自动改写/删除预览。未创建生产完整包，也未执行生产恢复或 apply。待用户通过现有网页正常放弃旧预览、确认写入仍暂停后，再重新验证；不得通过改JSON或跳过一致性检查来标记 complete。
- 生产表计数：MOD1097、用户状态1097、关注5、事件1130、同步14，schema3；完整生产用户表/结构指纹记录在 logs/ob6_s1/production_before.json。最终对比结果见下方执行结果补记。

## 测试与恢复预演

专项备份测试22项通过：旧格式、新增9类路径、可选缺失、无暂停确认、损坏/未知JSON、错误数据库绑定、SHA篡改、数据库与JSON不一致、备份期间数据库/检查点变化、中断、缺文件、恢复不覆盖生产数据、E/F默认目的地与无凭据/锁/缓存入包。

临时库新状态整包为数据库＋10个检查点（旧1、新9），临时恢复验证通过，备份未覆盖旧文件。真实生产跨文件整包未通过，不能用临时测试替代。

前端15项测试和生产构建通过，产物与之前冻结版本相同。全量 Python 测试结果在执行结果补记及 logs/ob6_s1/python_full.txt。本轮不重复 UI 冒烟。

## Git 归档状态

- master，HEAD 85558bec9334bb5a033ab8aec54203bc60d7f7bc；旧标签保持。
- origin 为 https://github.com/jennywikino/ErYouToolbox.git；连接器只读确认 visibility=private、具备push权限。
- 因生产恢复关键检查 BLOCK，按用户要求没有暂存、没有 commit、没有 push、没有新增或改动标签；没有刷新 origin/master 或判定远端无新提交。权限元数据不等于实际推送认证通过。
- 当前 Git 提交 SHA 不是新OB6基线，OB5/OB6及本轮修复仍在工作区。未执行最终暂存敏感审查，不声明“已安全上传”。

## 后续恢复执行条件与命令

先在网页正确放弃不匹配预览，再暂停全部写入。恢复包创建成功、全量测试和暂存安全审查全部通过后，才可恢复后续 Git 归档步骤。仍需人工验收计划任务权限及E/F跨电脑运行，不做1.0发布声明。

```powershell
$python = Join-Path $env:LOCALAPPDATA 'ErYouToolbox\venv\Scripts\python.exe'
& $python -m unittest discover -s tests
pnpm.cmd --dir frontend test
pnpm.cmd --dir frontend build
# 仅在预览一致且全部写入确已暂停后执行
& $python scripts/backup_project.py --writers-paused --destination 'C:\Users\Admin\ErYouToolboxBackups'
# 将下面路径替换为上条实际成功生成的bundle；仅临时恢复，不覆盖生产库
& $python scripts/backup_project.py --verify '<实际bundle路径>'
```

批准目标为本机C盘，物理设备独立性尚未实测；代码只核对卷并提示风险，不能把“不同卷”当成已证明“不同物理设备”。旧备份和专项状态一律保留。

## 最终执行结果

- 全量 Python：420 项通过、0失败，193.168秒；专项22项包含其中。前端15项通过、0失败，TypeScript/Vite构建通过。未改UI，未重复浏览器测试。
- 生产全用户表/结构指纹前后相同：`eae422e4d098509b7cd7bb8ef258d29d8d70ac4cfca62a6bf0bcc969ee7111c6`；五表计数不变。证据：logs/ob6_s1/production_before.json、production_after.json。
- 临时数据库完整恢复：PASS；当前生产跨文件完整备份与恢复：BLOCK/未执行。授权目标C目录未因此新建完整包。
- 本轮修改：scripts/backup_project.py、scripts/verify_backup.py、tests/test_backup_project.py、docs/OB6_STABILITY_AUDIT.md、PROJECT_STATUS.md；新增scripts/recovery_state.py及本文档。
- 剩余工作区：22个已跟踪修改、28个未跟踪文件，包含先前OB5/OB6成果。清单保存于logs/ob6_s1/tracked_changes.txt与untracked_files.txt；未暂存文件、未创建新commit，HEAD仍85558be，未push。修改过的备份源码差异检查通过，仅有Git行尾转换提示。
- 远端Private已确认，但由于BLOCK未执行fetch/整合审查/推送，远端分支SHA一致性未验；不得把旧HEAD当作新归档结果。


## 家用电脑跨设备复验（2026-11-02，最新）

本轮沿用同一移动硬盘原仓库，项目位置从 E: 改为 F:。起始 master / 85558bec9334bb5a033ab8aec54203bc60d7f7bc，origin 为指定仓库；连接器重新确认 Private、master、具备 push 权限。没有 init、clone、reset、clean、重写历史或移动标签。用户本轮明确授权在验收全部通过后正常 commit / push。

### 已解除的生产阻断

旧 waiting 预览仍与 MOD 基线不一致。本轮用户明确授权并亲自在既有页面点击“放弃本次预览”，服务记录对应 POST /api/sync 成功；只读复核为 discarded、candidate=null，一致性 PASS。未直接改写任务JSON、跳过检查或确认入库。因本机界面工具宿主启动失败，操作由用户完成。此操作通过既有逻辑保留旧预览归档。

用户确认全部写入保持暂停。只读进程核对没有项目后台写入进程，本机无 ErYouToolbox 计划任务，自动模式为 off；为页面操作临时启动的本地 API/Vite 已停止后再备份。历史设置即使 enabled，也在本机 off 下不运行。

### 独立完整备份与恢复

- Get-Partition / Get-Disk 实测 C: 为磁盘0（T253T2512G0C101，SATA），项目F:为磁盘3（TOSHIBA EXTERNAL_USB，USB），不同物理设备。
- 成功包：`%USERPROFILE%/ErYouToolboxBackups/eryoutoolbox_20261102_140234_205240_a00e260c`。公司电脑旧 C: 目录未访问、旧备份未删除。
- manifest complete，same_project_volume=false；数据库加11个白名单文件。作者轮转、作者最新更新检查、历史状态/设置、图片专项状态、评级/旧图片检查点、项目身份和已放弃同步任务全部入包。未产生的可选冷却文件在 manifest 标记 absent_optional。
- 创建过程临时恢复以及另行 --verify 均 PASS：integrity=ok、foreign_key_violations=0、schema3；mods1097 / user_states1097 / author_subscriptions5 / mod_events1130 / sync_runs14。
- 全用户表与结构指纹保持 `eae422e4d098509b7cd7bb8ef258d29d8d70ac4cfca62a6bf0bcc969ee7111c6`；状态文件与备份捕获前清单复核。没有覆盖生产库，不复制整个logs，不恢复本机任务授权或旧PID。

### 家用电脑测试

- 本机缺失项目虚拟环境；用已有运行时仅创建 `%LOCALAPPDATA%/ErYouToolbox/venv`，所有 Python 验收均使用该解释器。Python3.12.14、SQLite3.53.1、httpx0.28.1，pip check通过。系统可能把 LocalAppData 实体重定向至Codex包的 LocalCache，实际调用仍遵守规定路径。
- 全量 Python420项通过，95.049秒；专项22项通过，10.924秒，包含临时库完整新状态恢复和失败场景。前端15项通过，profile生命周期6项通过。
- 本机未安装pnpm；执行package.json同等命令：Node测试、tsc --noEmit、vite build。首次构建因node_modules目录连接残留旧E:而失败；验证90个目标包均在当前项目内后，仅重建连接，不改业务/锁文件、不升级前端依赖。复跑TypeScript、Vite构建通过。
- 构建产物：index-BAYyPHb3.css / index-ce8KsZlj.js。未因环境问题修改无关业务；仅清理git diff --check指出的六处行尾空白/文件末空行。

### 私有源码归档边界

.gitignore保留此前公开候选保护；本轮为已明确授权的私有历史归档，PROJECT_STATUS及OB5/OB6文档按逐文件白名单显式纳入。config/project_identity.json本来已在旧历史跟踪，本轮不修改或新暂存它；ignore不能抹掉旧历史，不宣称历史已匿名化。没有改变仓库可见性、上传生产数据、原始响应、备份、凭据或node_modules。

当前源码与已有历史执行常见凭据规则扫描，结果及范围见 source_security.json；逐文件暂存清单、暂存差异检查、远端整合核对和最终提交/推送核对均保存在本轮日志。提交SHA以包含本文的归档提交为准，避免文档自引用SHA；最终实际SHA及远端一致性在本轮交付与git_archive.json记录。旧标签保持，不创建v1.0正式标签。

证据目录：`logs/ob6_s1_home_20261102_215810/`。仍待人工：计划任务真实触发、E/F两机完整启动退出、每游戏真实内容及生产小批量写入/补图验收。这些不以本轮离线测试替代。本轮完成备份及Git归档后停止。
