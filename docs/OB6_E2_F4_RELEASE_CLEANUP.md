# OB6-E2-F4 / 0.5.0-rc3 候选收敛

2026-11-03。起点为 master/fa6ba1c，开始时工作区干净。仅准备本地候选与源码归档，不发布 Release、不创建或移动标签。旧 OB 文档保留为历史，不改写原验收事实。

## F4-A：退出内容年龄分级

用户决定取消维护内容分级。移除 React 侧栏、评级批次入口、标签展示、评级图片遮挡。旧浏览快照中的 ratings 被归一为 null，allowUnknown 归一为 true；旧 localStorage 的隐藏偏好不再读取。API 忽略历史 ratings/show_* 参数，评级配置与评级任务 GET 返回 410，任务 POST 不允许执行。URL 安全、懒加载、失败重试、缩略图/原图分离不变。

不删除 SQLite 的 content_rating_status、raw_metadata_json 中历史评级证据或旧检查点，不做 schema 迁移。历史命令行工具和纯函数测试仅作兼容归档，不接入客户端。共享锁仍使用原 logs/content_ratings/instance.lock 文件名以协调旧入口；文件名不代表仍运行评级调度。桌面和构建不再依赖或包含 config/content_ratings.json，games.json、前端入口/资源散列仍是强制验证项。旧包不能混用新的内部资源。

## F4-B：刷新、授权和90天发现

主入口为“刷新 / 自动每N小时 / 继续向前搜索 / 更多设置 / 缓存管理”，详情移至原生设置对话框。所有原有检查、预览、确认、放弃、模式设置、统计和错误仍可访问；状态组件保持挂载，不因开关对话框重复运行任务。五列、1250px 最大网格和默认25件未改。

新用户默认 off，首次明确授权才保存推荐 apply/3小时；旧授权、间隔和其他配置不偷偷重置。check 只预览，apply 复用现有仅新增/可靠 source_updated 的 importer、备份、事务、用户状态保护和共享锁。客户端打开时按到期时间请求，关闭后不后台运行，不注册系统任务。停止按当前请求边界生效，写入前重新检查取消及授权，不打断事务。

官方 Core/List/New 文档确认 max_age 单位为秒、include_updated=1 包含新增和更新。实测原神单请求 max_age=7776000 得到20个 `[Mod, ID]`，没有来源时间戳。不能据此直接认定更新；逐ID详情放大会增加请求。本轮沿用既有 apiv11 Generic_NewAndUpdated 和 normalize_record，不另建采集器。

网页/自动默认候选规则：以本次采集 UTC 时间向前90天，created_at **或** updated_at 在窗口内才入候选。modified_at 和 first_seen_at 不参与。旧作品近期明确更新可入选；窗口外和缺日期记录分别统计，缺日期ID保存在待核实列表。旧库历史作品不会被删除。默认每游戏3页、全部游戏每页10条（单游戏手动20条），顺序执行；每页含重试最多2次HTTP请求，六游戏默认日常列表预算最多36次。既有作者轮转拥有自己的有界预算，另计实际请求。任何分页上限都不代表覆盖完整90天；coverage 始终明确 incomplete，不依赖单条旧作品提前终止。

真实只读验证共3次：Core1次、apiv11原神一页10条1次、MOD732438详情1次；无重试、无图片/MOD下载、无生产写入。10条均符合窗口；678931 于2026-05-21发布、2026-11-02来源更新，正确保留。没有证明整个来源90天全覆盖。

## 历史续扫

日常 AutoSync 不再自动派发更早 HistorySync，保留原历史正式检查点。用户主动继续每游戏最多2页，并复核边界；手动可不等待另一天，但仍遵守来源冷却、共享锁和完整性检查。apply 只有数据库提交后推进边界；off/check 仅预览，不推进正式位置，重复预览可能复查同一范围。分页漂移、未知空页、身份/顺序/元数据异常按原规则停止；暂停于请求结束后生效。主设置显示实际页数、重复、新收录/候选、失败和每游戏已提交边界日期。

## F4-C：时间和来源指标

created_at = _tsDateAdded；updated_at = _tsDateUpdated；modified_at = _tsDateModified。底层不写入回退更新时间。界面更新日期缺失/非法时回退可靠发布时间，并注明“暂无单独更新记录”；两者皆缺失显示“暂无来源数据”。最近更新浏览排序允许以发布时间回退，但订阅更新事件筛选仍必须有 source_updated，未伪造事件。

原列表 normalizer 未保存点赞/浏览/评论指标，历史快照因此缺失。现在只保存来源返回的非负整数 metrics 到既有 raw_metadata_json 的标准化记录，不加表或列，0与未知区分。旧库不批量回填；详情“刷新来源时间与指标”复用缓存的官方 ProfilePage，只展示，不改图片、作者、主库或事件。若来源仍缺失，继续暂无。

实测732438：发布时间2026-10-26 08:43:18 UTC，独立更新时间缺失；点赞26、浏览1351、下载113、评论3、1个文件、6张图片元数据（数值仅代表本次观察）。列表10条均有真实点赞和浏览，下载字段缺失，没有用浏览替代下载。自动来源更新判断继续要求既有 updated_at 非空且新值严格增加；第一次补到时间、日期回退、指标补齐不自动变成来源更新。

## F4-D：缓存分类和边界

| 类别 | 位置/口径 | 清理行为 |
|---|---|---|
| 热门/详情 | 当前API内存 | 显式确认后清空，保留429冷却 |
| 作者URL资料 | logs/author_profiles/数字ID.json | 仅格式、身份正确且已过期；不下载或删除头像图片 |
| WebView2 | userdata/cache/webview | 统计整个浏览器资料目录；仅微软官方 ClearBrowsingDataAsync(DiskCache)，不清除DOM偏好，不保证释放目录全部大小 |
| 测试profile和证据 | logs/ui_smoke | 只读统计，未验证进程归属/退出，不自动删除 |
| 运行日志/状态 | logs（总计含证据） | 只读统计；可能含恢复必需状态，不自动删 |
| 数据库/用户状态 | data/eryoutoolbox.db及WAL/SHM | 禁止缓存清理 |
| 检查点/设置/锁 | 既有logs、配置目录 | 保留 |
| 备份 | data/backups及外部备份 | 永久排除；不遍历外部独立备份位置 |

必须先预览类别和相对文件清单，再用户确认。预览有效5分钟，散列不匹配拒绝；路径白名单、真实路径、symlink/junction及根目录检查，拒绝任意路径。清理使用原共享锁，活动同步不可清理；被占用文件报告 partial，不强删、不递归删除目录。缓存清理状态位于 logs/cache_management/status.json，可再生，非业务恢复基线。

pywebview 官方支持 storage_path；本轮明确指定可移动 userdata/cache/webview，private_mode=False，避免库在退出时递归删除活动资料目录。清理通过底层官方 DiskCache API，在UI线程调度，不采用 filesystem rmtree。没有全局浏览器或其他应用目录的清理能力。设置偏好/SQLite不作为缓存删除。

只读实际审计：开发项目 logs 868文件/273452509字节（总计含证据），其中 ui_smoke 85文件/2193201字节；备份69文件/138452992字节。已知F1便携 userdata logs15文件/119660字节、备份7文件/20062208字节。均未清理；新WebView路径在旧版目录原先不存在。统计是本次观察，不是恒定值；空作者缓存没有可删项。

## F4-E：验收与已知限制

已通过关联测试：缓存/90天专项14项、桌面17项、历史评级兼容13项、历史扫描33项、查询/接口专项及前端16项/生产构建。统一冷却修复后最终全量Python484/484通过（170.239秒），前端16/16及生产构建通过；证据 F4-python-cooldown-final.txt、F4-frontend.txt、F4-build.txt。旧测试按退役功能及日期回退的新语义更新，未删除失败用例；失败日志保留。

预检ZIP源码外中文/空格目录真实EXE通过：缺games/前端资源拒绝启动；不需评级配置；官方DiskCache清理成功；旧评级任务不可启动；首次授权off/3小时持久化；已阅/关注、返回/前进、目录移动/重启、异常退出、重复实例、不可写userdata与端口释放。0次测试网络，写入仅临时fixture库。初次错误对话框取证过早只读到按钮，已等待Static文本就绪后复验，未放松产品校验。

最终候选须从白名单源码提交后重建，并针对最终ZIP再次源码外验收。SHA-256、构建SHA、完整测试和push结果写入本地构建清单及最终交付；不在尚未生成时编造值。包保留实际第三方许可证文本，不含个人库、日志、凭据、检查点或profile。

仍待人工：干净Windows/WebView2、真实E/F硬盘跨电脑、持续3小时到期、小批生产入库与手动历史继续、旧userdata升级/回滚。没有生产apply或schema迁移。90天来源完整覆盖未证明；历史资料不自动全库补齐。日志和测试profile自动清理因证据/归属不足暂不开放。Release和项目许可证确认仍需用户另行决定。

## 本机验收

完整解压新ZIP到独立可写目录，保留旧目录及备份，不混用_internal。新库先选手动，确认六游戏、空库刷新指引、无评级UI、图片默认允许、五列/25件与详情返回。更多设置仍能检查/确认/放弃预览；主动授权后才自动入库。需要旧数据时停写并通过既有备份/校验流程处理完整userdata，不只复制活动SQLite。

检查真实732438时间回退和来源指标，点击只读来源刷新；再检查有独立更新的历史作品。缓存管理先预览，确认只有允许类别；检查清理后已阅、关注、作品总数不变。继续向前搜索应显示边界与请求预算，不宣称全量完成。最后关闭重开，确认个人状态仍在。

```powershell
$python = Join-Path $env:LOCALAPPDATA 'ErYouToolbox\venv\Scripts\python.exe'
& $python -m unittest discover -s tests -p test_f4_cleanup.py -v
& $python -m unittest discover -s tests -p test_history_sync.py -v
& $python -m unittest discover -s tests -v
& $python tests/desktop_isolation_check.py --archive dist/desktop-0.5.0-rc3-final/ErYouToolbox-0.5.0-rc3-win-x64.zip --report logs/content_ratings/F4-user-isolation.json
```

官方依据：https://api.gamebanana.com/docs/endpoints/Core/List/New ，https://pywebview.flowrl.com/api/ ，https://learn.microsoft.com/en-us/dotnet/api/microsoft.web.webview2.core.corewebview2profile.clearbrowsingdataasync 。

最终入口审查补齐较长Retry-After：手动/自动共用既有历史cooldown.json安全状态；等待至少来源要求的时间（无明确时间保守3小时），立即刷新不能绕过。新增24小时Retry-After回归，484项全量通过；保留先前483项成功和失败日志，未删除用例。
