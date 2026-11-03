# F6：联网预览后安全关闭（0.5.0-rc3）

## 已证实的问题与证据边界

开始时保留README、RELEASE_CHECKLIST、环境审计和启动依赖测试的未提交成果，未恢复旧tag或覆盖本地数据。

先只增加时间戳/线程名/阶段日志及faulthandler转储。源码短时、源码60秒和诊断冻结包60秒联网预览都有退出成功样本，说明旧故障不是每次必现。原环境审计旧EXE已终止且没有Python堆栈，不能事后断言它唯一卡在哪行。

离线控制实验明确复现：向本地API发送未完成POST，HTTP线程在`react_api.do_POST -> rfile.read`等待剩余请求体，同时持有`server.lifecycle_lock`；WinForms UI线程在`before_close`同步等待同一锁；冒烟线程在`winforms.destroy_window -> Invoke`等待UI。20秒转储记录三方具体栈，HTTP监听持续存活。旧请求socket无读取时限，关闭回调也未发出取消信号。证据：忽略的logs/content_ratings/F6-lock-repro.txt。

另一个确定风险：pywebview创建的非daemon冒烟线程先等loaded再不可取消sleep，提前正常关闭会留下仍在睡眠或执行JS的辅助线程；原finally还可能对已关闭GUI再次destroy。F6将该等待改为closing事件可中断，关闭协调同时等待该辅助线程真正结束。

这些是已复现/代码确认的缺陷；真实历史事故是否还含其他触发条件仍无旧堆栈佐证。修复有效性以新包重复原联网预览场景及控制实验为准，不以仅添加超时或空页面通过作为结论。

## 最小实现

- `scripts/desktop_lifecycle.py`：非daemon关闭协调器。GUI closing事件立即设closing并返回False，不获取HTTP/SQLite/共享锁或弹出同步阻塞对话框。重复点击复用同一协调线程。
- 后台发送web/auto/current_service/history内存取消信号，不调用会改写历史暂停设置的AutoSync.stop。历史在游戏/分页边界及写入前检查取消；已开始事务由原importer完成或回滚，不强杀。
- 保存web/auto/history工作Thread句柄，既检查状态/运行锁，也确认线程is_alive结束。关闭时45秒仍有任务或外部共享锁，保留窗口，标题明确提示等待后再次关闭；记录活跃状态和线程堆栈，不冒充成功或跳过事务。
- HTTP仅绑定原127.0.0.1动态端口。closing后拒绝新GET/POST，HTTP请求读取5秒超时；已进入POST的事务由原生命周期锁保护。
- serve_forever与请求处理线程使用非daemon；协调器在GUI及serve_forever之外调用shutdown，随后server_close排空请求并join HTTP线程，再destroy窗口。GUI再次触发closing时ready允许结束。
- 原无上限worker等待循环移除。启动中途异常同样注册清理回调。正常结束后ExitStack释放.desktop.lock，日志记录主线程返回；不删除锁文件或WAL/SHM，不用os._exit。
- 未改变UI布局、数据库schema、同步筛选与入库规则、作者/已阅业务或生产设置。

## 诊断日志

userdata/logs/desktop.log含时间戳、线程、阶段与耗时：GUI_close_requested、cancellation_sent、waiting_safe_boundary、workers_and_writes_drained、HTTP_shutdown_begin、HTTP_serve_forever_stopped、HTTP_closed_port_released、destroy_window_begin/returned、GUI loop returned、main_cleanup_complete、desktop_lock_released。

等待时每5秒记录状态和所有线程栈到userdata/logs/shutdown-threads.log；smoke诊断另外每20秒转储。SQLite事务不通过网络socket超时强制中断。遇真正无法结束的事务或请求会留下明确诊断，不能静默声称退出成功。

## 测试矩阵及当前结果

退出专用12项真实HTTP线程/临时SQLite：空闲/列表、未完整POST、检查中取消、保留待确认预览、事务中关闭后安全提交/已阅关注保持、新写请求503、超时保留活跃事务和窗口、自动任务取消、历史取消且设置不变、429/超时状态、重复关闭、非daemon冒烟等待取消、完整自动入库后关闭。12项内含组合断言；模拟来源不消耗真实预算。

历史35项通过，包括关闭前取消0请求、最后响应后取消不写入/不推进检查点；第一轮新增用例发现InterruptedError误记failed，修正为stopped，原失败日志保留。桌面17项原回归通过。前端16项、TypeScript/Vite构建通过，未改前端源码。初轮全量500项通过；补齐取消矩阵后的最终全量504/504通过，0失败、0跳过，耗时817.287秒，记录F6-python-accepted.txt，不删除/跳过用例。

预验收冻结ZIP在源码外中文/空格新目录解压，子进程PATH不含Python/Node，10次正常关闭全部退出码0；包含第一次空库、列表、真实原神一页20条预览后关闭（2.683秒）、重启预览关闭（3.169秒）、不完整POST、只在临时库设置已阅和关注、三次连续启动关闭、受控异常退出后恢复。每轮重新绑定相同端口、重新取得.desktop.lock，并检查integrity_check=ok/foreign_key_check无违规。不是干净OS验收。

预验收实际GameBanana请求1次，dry-run候选20条，未confirm；SQLite哈希不变。此前本轮诊断源码/冻结各一次真实单页请求，均只预览。最终交付包还需重复独立验证，所有联网次数分别记录，不批量扫描历史。

证据：F6-lock-fixed.txt、F6-lifecycle-accepted.txt、F6-history-final.txt、F6-native-validation.json、F6-python-accepted.txt、F6-frontend.txt与F6-frontend-build.txt，均位于忽略的logs/content_ratings。最终包BUILD_INFO和相邻sha256文件记录准确构建提交与散列，不使用旧预构建包作为交付。

## 人工验收与剩余门槛

完整解压本轮最终ZIP到新可写目录，保留旧版及完整userdata备份。先保持手动模式，选择原神刷新一页，预览20条后点击窗口X，确认进程与端口消失；重开再关闭三次，检查个人状态及自动化配置。若已有后台事务，标题应提示正在安全关闭，不能直接任务管理器强杀；超时则保留窗口、收集shutdown-threads.log后重试。

开发复验：

```powershell
$python = Join-Path $env:LOCALAPPDATA 'ErYouToolbox\venv\Scripts\python.exe'
& $python -m unittest discover -s tests -p test_desktop_shutdown.py
& $python -m unittest discover -s tests
```

干净Windows10/11、物理E/F迁移仍需人工实测；不因本轮关闭通过就宣称Release兼容完成。不修改Windows任务、不自动创建tag/Release，不执行生产apply。最终源码提交、推送状态与ZIP散列见本轮交付。

最终交付目录：`dist/desktop-0.5.0-rc3-F6-delivery`；干净提交的最终ZIP仍须执行tests/desktop_shutdown_check.py和原desktop_isolation_check.py，记录F6-final-native.json/F6-final-isolation.json。实际构建SHA、ZIP SHA-256、Git远端状态与生产指纹复验统一保存在本轮交付清单，不将预构建散列冒充最终包。
