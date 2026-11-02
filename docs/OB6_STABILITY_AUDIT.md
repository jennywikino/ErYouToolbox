# OB6 Web 稳定候选审计

审计日期：2026-11-02（Asia/Shanghai）。本轮仅审计，不修复业务，不安装/升级依赖，不执行生产 apply、迁移、Git 提交或推送，不修改计划任务。

结论：当前本地 Web 代码通过自动化与隔离浏览器验证，数据库完整性及临时恢复验证通过；**仍是未提交的稳定候选，不是已形成 Git 回退点的 OB6 稳定版本**。备份检查点覆盖存在 P1 缺口，需要后续独立处理，不能宣称完整灾难恢复能力已验收。

## 版本与源码

- 分支 master；HEAD `85558bec9334bb5a033ab8aec54203bc60d7f7bc`。
- annotated tag `v0.4.0-rc1` 解引用到同一提交；另有 v0.1.0，未修改任何标签。
- 审计文档写入前：19 个已跟踪文件修改、24 个未跟踪文件、暂存区为空。相对基线的已跟踪差异为 644 行增加、110 行删除；不包括未跟踪 OB5/OB6 源码。
- 保留全部本地改动，没有 reset/checkout/stash/add/commit/push。后续冻结必须审核并包含新增模块，不能仅提交已跟踪差异。
- .gitignore 已覆盖 data、logs、数据库及侧文件、node_modules、虚拟环境、dist、常见凭据。git ls-files 检查未发现 data/logs/node_modules、数据库/WAL/SHM、.env、pem/key 被跟踪；未进行全历史凭据审计，不对此作无泄漏保证。
- git status 对四个既有 tmp 目录提示无权访问，未删除或修改；不能将其视作已检查完毕。

## 环境

| 项目 | 实际结果 |
|---|---|
| 项目解释器 | `%LOCALAPPDATA%\ErYouToolbox\venv\Scripts\python.exe` |
| Python / SQLite | 3.15.1 / 3.53.4 |
| Python 依赖 | httpx 0.28.1；Streamlit 1.66.1；pip check 无冲突 |
| Node / pnpm | v24.22.1 / 12.15.0 |
| React / React DOM | 19.3.1 / 19.3.1 |
| Vite / TypeScript | 8.3.5 / 7.0.2 |
| Tailwind | 4.3.3 |
| 锁文件 | frontend/pnpm-lock.yaml，lockfileVersion 9.0 |
| Windows PowerShell | 5.1.26100.9711 |

没有重装或升级环境。Python requirements.txt 的 httpx 未锁定具体版本，是重现环境的次要风险；本轮仅记录当前实际版本。

只读核对的本机自动设置为 check、3 小时、每游戏最多5页；历史补全当前已启用、未暂停、每游戏最多5页。启用历史检查不等于允许生产入库，当前 check 模式只预览。本轮没有更改这些设置或触发任务。

## 测试与证据

- 项目虚拟环境全量 `unittest discover -s tests`：**412 项通过，173.298 秒，退出码 0**。日志 `logs/stability_audit/python_full.txt`。部分 usage/error 为预期拒绝非法参数的测试输出，最终没有失败。
- 前端单元测试：**15 项通过**；TypeScript 检查及 Vite 生产构建通过。
- profile 生命周期 Node 测试：**6 项通过**。
- Windows PowerShell 5.1 Parser.ParseFile：bootstrap、run_probe、run_ui、manage_auto_sync、auto_sync_bootstrap、toolbox_launcher 共 **6 个脚本均 0 语法错误**。
- CMD 入口静态核对：从 `%~dp0` 调用辅助 PowerShell；虚拟环境为当前电脑 LOCALAPPDATA 路径。启动器检查固定 localhost 端口、Vite strictPort 和进程身份，未在生产环境实际启停服务。
- 隔离 Edge 冒烟通过，使用 72 条模拟记录及被拦截的图片/API：标准桌面 3 列，紧凑 1920px 为 5 列、1366px 为 4 列，窄窗口不溢出；15/25/50 分页、偏好、订阅/作者页及详情返回正常，锚点误差 0px。同步 POST 为 0，没有来源 API 调用。
- 浏览器证据：`logs/ui_smoke/density_1793620416151_4NZp9f/`，报告、截图保留；profile_cleanup.json 为 removed，本次 profile 已删除。

这些测试不能代替生产网络、真实任务计划、跨电脑和生产写入验收。

## 生产数据库与恢复

实际文件由项目根定位：`data/eryoutoolbox.db`，审计时 4,153,344 字节。只读连接 mode=ro，未初始化数据库。

| 检查 | 结果 |
|---|---:|
| integrity_check | ok |
| foreign_key_check | 0 |
| user_version | 3 |
| journal_mode | delete |
| mods | 1097 |
| user_states | 1097 |
| author_subscriptions | 5 |
| mod_events | 1130 |
| sync_runs | 14 |

审计时 WAL/SHM/journal 侧文件均不存在，未删除或转换任何侧文件。结束时五张表数量仍相同。9 份专项检查点/配置的 SHA-256 在记录后到复核时均不变，清单为 `logs/stability_audit/checkpoint_inventory.json`。

执行现有 verify_backup.py：只读打开源库，SQLite Online Backup API 备份到临时目录，再恢复第二份临时库；完整性、外键、四张基础表数量、schema version 全部一致，原库文件哈希未变化。另行通过 SQLite Backup API 临时复制验证 author_subscriptions=5。未覆盖生产库，未直接复制活动主数据库文件。

data/backups 只读清单：69 个文件，共 138,452,992 字节，其中 subscriptions_*.db 34 份；未清理、压缩或修改。该前缀共用于已阅、关注、作者检查、历史进度及图片修复，不能仅按名称判为冗余。

现有 backup_project.py 支持 Online Backup API、SHA-256、清单及临时恢复预演，默认项目盘根 ErYouToolboxBackups，支持外部目标；同一物理设备不具备设备损坏恢复能力。本轮没有新建外部正式备份或实测独立设备恢复，相关实现由全量临时测试覆盖。

## 核心能力核对

| 能力 | 本轮证据 | 真实环境仍待验 |
|---|---|---|
| 六游戏、搜索、评级、分页 | API 临时库回归及隔离浏览器 | 每游戏真实记录抽查 |
| 已阅、作者关注 | schema 3、5 条关注，临时库写入/回滚及重启测试 | 真实按钮持久化，由用户操作 |
| 手动同步与确认 | 全量 web_sync/auto_sync 回归 | 真实预览→用户确认入库 |
| 自动检查、作者轮转 | 时钟、锁、恢复及模式回归 | 浏览器关闭后计划任务实跑 |
| 历史补全 | 历史分页/漂移/提交恢复测试 | 生产小批量验收 |
| 图片定向修复 | 相关模拟测试；OB6-C4 已有60次真实 dry-run报告 | 用户确认 apply 后图集检查 |
| 备份恢复 | 本轮真实源库只读临时恢复通过 | 独立设备整包及新增状态恢复 |
| 启动与退出 | PS5.1 语法、静态进程身份检查、浏览器退出清理 | 双击启动/重复启动/安全关闭 |

本轮未新增 GameBanana 请求。Windows 计划任务只读查询返回“拒绝访问”，因此注册状态、实际触发时间和上次运行结果未能确认；未自动调整权限、注册或触发任务。

## 风险分级

### P0

本轮检查范围内未发现 P0；不等于未测环境不存在故障。

### P1：正式冻结/完整恢复阻断

1. **OB5/OB6 尚未形成 Git 提交/标签**。本地功能不能仅靠旧 v0.4.0-rc1 标签恢复；需后续人工审核源码清单并授权本地提交。本轮遵令不提交。
2. **独立备份遗漏新运行状态**。backup_project.checkpoint_paths 默认只收集旧评级检查点、旧 preview_backfill 检查点和 source_pause；不包含 author_updates/rotation.json、history_sync 状态/配置、preview_repairs/state.json、web_sync 待确认任务等。其 checkpoint_bytes 也仅接受三种旧格式，不能简单用 --checkpoint 加入新状态。数据库中的已提交历史/同步进度可恢复，但轮转、待处理、专项复查时间和设置未完整覆盖。需后续单独修复并验收整包恢复，不能宣称当前整项目恢复已完整。

### P2

- 计划任务真实状态查询受权限限制；跨电脑 E/F、断电和重启恢复未实测。应在本机授权环境完成验收。
- 备份在事务前、专项 JSON 在数据库提交后保存，存在非原子恢复边界；历史/作者/补图需结合各自机制恢复，不能只恢复主数据库就认定全部状态一致。
- 当前生产启动器未执行实机启停；移动盘拔出前需先停止服务。其本机进程状态按绝对项目路径哈希隔离，盘符变化后旧实例状态不能假设自动继承。
- Python 核心依赖版本未全部锁定；同盘备份非独立灾难恢复；完整备份无自动保留上限。

### P3

- 包版本仍为 frontend 0.3.0，部分页面仍显示 V0.4，与 OB6 阶段标识不同；不影响此次构建，不在本轮修改。
- 既有 EOF 空行/CRLF 提示及不可读临时目录未清理，不因此格式化业务代码。

## 下一阶段真实验收顺序

1. 先单独解决备份新状态覆盖，进行独立设备临时恢复预演；恢复只针对临时目录。
2. 用户审核未提交文件与隐私清单，再授权创建本地 OB6 候选提交/标签，不覆盖旧标签。
3. 当前电脑双击启动，验证只绑定127.0.0.1、端口冲突不误杀、重复启动不重复实例；关闭后检查端口释放。
4. 在 check 模式下验收打开网页到期检查、多标签页、待确认预览、关闭浏览器后任务完成；人工查询计划任务，不先启用自动入库。
5. 每游戏抽查搜索/分级/分页、详情返回；用户自行验收已阅和关注重启持久化。
6. 经独立备份后，用户手动批准单游戏小批量入库/补图，核对用户状态、事件、游标和回滚记录。审计本轮不代做。
7. 另一台电脑使用其本地虚拟环境，验证 F 盘识别及本机计划任务配置；不复制 C 盘虚拟环境，不带运行中进程直接拔盘。

复查命令（项目根目录）：

```powershell
$python = Join-Path $env:LOCALAPPDATA 'ErYouToolbox\venv\Scripts\python.exe'
& $python -m pip check
& $python -m unittest discover -s tests
& $python scripts/verify_backup.py
pnpm.cmd --dir frontend test
pnpm.cmd --dir frontend build
node --test tests/test_smoke_profile.cjs
```

本轮仅新增审计文档、状态索引和被忽略的验收证据。未改 UI、业务、备份策略、数据库内容或 Git 基线。

## OB6-S1 后续进展（不改写上述历史审计结果）

新增备份状态白名单与验证修复已通过临时恢复测试，详见 [OB6-S1](OB6_S1_RECOVERY_AND_GIT.md)。P1-B 在代码层面已补齐，但当前生产待确认预览的MOD基线与数据库不匹配，完整生产备份仍为 BLOCK。用户明确选择保留 BLOCK，因此 P1-A 仍未解决，未提交或推送；不能宣称稳定基线已归档。计划任务权限、跨E/F电脑仍待人工验收。


## 2026-11-02 家用电脑复验（最新）

原审计数字及限制保留为历史证据。OB6-S1生产备份阻断已解除：用户从现有界面放弃旧预览，独立C盘物理磁盘0与F盘物理磁盘3实测分离；SQLite+11状态文件整包及临时恢复两次PASS，生产全表指纹不变。家用本机项目虚拟环境新建并通过全量Python420项、备份专项22项、前端15项及profile6项；修复node_modules旧E盘连接后TypeScript/Vite生产构建PASS。归档目标为用户本轮授权的Private仓库，按白名单提交推送，不改可见性、不改旧历史/标签、不做1.0发布。具体备份路径、Git状态、证据与人工待验边界见[OB6-S1最新复验](OB6_S1_RECOVERY_AND_GIT.md)。
