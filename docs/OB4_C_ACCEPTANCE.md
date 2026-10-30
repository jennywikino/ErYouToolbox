# OB4-C 本机稳定性验收（2026-10-30）

## 实测通过

- 当前项目根目录为ErYouToolbox。实际计划任务ErYouToolbox-AutoSync-e459681a已注册、Ready，当前设置为自动检查、3小时间隔、每游戏最多5页，未修改设置。
- 实际动作启动系统Windows PowerShell，再执行本机LOCALAPPDATA下项目标识目录中的bootstrap.ps1；已安装bootstrap与项目源码SHA-256一致。
- Principal为Interactive、Limited：需当前Windows用户登录，不要求浏览器打开；不是注销状态下的后台账户任务。MultipleInstances为IgnoreNew，StartWhenAvailable=true，执行时间上限90分钟。
- 手动触发前确认模式check且任务Ready。北京时间18:13:00观察到新的LastRunTime，随后Ready、LastTaskResult=0；输出not_due、requests=0。没有修改任务配置，也没有关闭用户浏览器。此结果证明调度入口可执行，不证明实际联网扫描成功。
- 当前下一次Windows触发20:51:50（UTC12:51:50）；应用允许检查时间21:02:38左右（UTC13:02:38）。两者含义不同。
- 自动任务21项、网页同步/恢复32项、项目备份14项相关测试通过，共67项。使用临时库、隔离目录和模拟来源。锁、重复触发、失败恢复、预览保护、放弃/确认后的状态、缺盘安全退出和路径定位均有离线覆盖。
- 生产库只读integrity_check=ok、foreign_key_check=0。现有verify_backup.py实际备份/恢复演练PASS：mods949、user_states949、mod_events968、sync_runs12、schema3；恢复副本与原库一致，原库未变。
- 实际Python位于本机LOCALAPPDATA\ErYouToolbox\venv。定位器保存codex\Projects\ErYouToolbox这一盘根相对路径和项目标识，不保存E/F盘符。数据库按脚本根目录定位，缺盘或多份同标识项目会安全退出，不建空库。

## Git检查

当前分支master，仅有V0.1发布提交b85a809；未配置remote。工作区有大量修改/未追踪的后续源码，这是既有状态，本次未暂存或提交。

git ls-files未发现data、logs、数据库、凭据及Cookie匹配文件；已追踪文本未发现本次检查所覆盖的常见令牌/私钥模式。这是限定范围检查，不是所有秘密格式的绝对保证。

git check-ignore确认data/eryoutoolbox.db、logs、node_modules、dist、.env、本机配置及venv被忽略。现有SQLite及备份不进入Git。

建议在人工验收后，明确列出src、scripts、tests、frontend、必要config、docs、启动入口与AGENTS.md，检查git diff及暂存清单后创建本地稳定候选提交；仍未实测的跨电脑步骤完成前优先标记rc版本。不要git add .、不要上传数据。本轮未操作提交、标签或GitHub。

## 待注意／未完全通过

1. **触发相位与间隔门槛错位。** 手动立即检查会移动应用到期时间，但不移动Windows触发器。当前20:51触发早于21:02到期，可能再次not_due；若无其他触发，实际检查可能延至23:51。不会损坏数据，但不能把配置3小时解释成精确每3小时联网。本轮未擅自调整任务；建议后续单独确认如何对齐触发与应用到期规则。
2. 自动任务last_run保留上次自动检查waiting，而网页同步日志已显示随后确认成功。它们属于检查历史与提交状态两个口径，不能把旧waiting解释成仍有未提交预览。当前正式提交成功可在网页主同步结果查询；建议后续按task_id统一这两处状态口径。
3. 另一个电脑的任务、Python、依赖和个人设置均需独立初始化。只改变盘符且相对路径不变时定位器可适配；实际插拔、休眠、重启、注销以及F盘启动均未进行。
4. 同盘备份不是独立灾难恢复备份。backup_project.py可指定另外物理设备的目标；数据库内的正式检查点随数据库备份保存，额外网页预览日志可用--checkpoint显式包含。

## 不等3小时的人工验收

1. 在网页确认自动同步为“自动检查”，处理或放弃仍有效的手动预览。关闭浏览器即可，不必结束React API，也不要更改为自动入库。
2. 打开Windows任务计划程序，选中上述工具任务，右键“运行”。查看上次运行时间、上次结果、任务状态及本机scheduled.out.log、scheduled.err.log。也可在PowerShell手动触发：

```powershell
Start-ScheduledTask -TaskName 'ErYouToolbox-AutoSync-e459681a'
```

3. 若输出not_due，表示任务启动成功但应用按间隔跳过，**不算联网验收成功**。不修改计划配置时，要验证立即联网，可独立执行现有一次性入口的小样本检查：

```powershell
$python = Join-Path $env:LOCALAPPDATA 'ErYouToolbox\venv\Scripts\python.exe'
& $python scripts/auto_sync.py --dry-run --run-now --game 8552 --max-pages 1
& $python scripts/manage_auto_sync.py query
```

该命令不依赖浏览器，但不等同于通过Windows任务触发网络检查；它不绕过限流冷却。完整任务联网验收需在已到期时触发，并确认requests大于0及检查报告正常。

## 重启及换电脑待验步骤

- 自行正常重启（本轮没有执行关机）。登录后查询任务仍存在，网页模式/间隔仍保存；检查StartWhenAvailable和执行记录。错过触发不等于一定立即联网，仍受应用到期、缺盘及限流保护。
- 工具任务处于空闲、SQLite连接关闭后安全弹出移动盘。重新插入或在另一电脑使用时，先验证项目根路径、现有数据库数量、本机虚拟环境，再用项目Python查询任务。
- 另一电脑须单独注册本机任务。确认只有一份相同标识项目可被定位；不要复制数据库当作修复缺盘的方法。
- 缺盘时任务应失败退出并记录原因；恢复盘后下次执行可重查重叠页。不要在真实同步写入过程中拔盘制造故障。
- 备份测试、失败回滚及缺盘行为目前有隔离测试证据；真实断电/拔盘/两电脑切换仍待人工验收。

## 本轮修改与数据边界

仅新增本报告；未修改业务代码、React布局、任务配置或生产数据库内容。产生了忽略目录下的测试日志，以及现有计划任务本身的运行输出。未联网采集、未创建新任务、未提交或推送Git。
