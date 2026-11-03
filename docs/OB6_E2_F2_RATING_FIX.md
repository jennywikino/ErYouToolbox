# OB6-E2-F2 来源分级修复

日期：2026-11-03。目标仍为0.5.0-rc1；本轮不提交、推送、创建标签或上传Release，不执行生产apply。

## 两个独立数据库

只读审计：开发库 `data/eryoutoolbox.db`；用户明确指定的便携目录为 `dist/desktop-0.5.0-rc1-F1-final/ErYouToolbox`，其数据库为该目录下 `userdata/data/eryoutoolbox.db`。不是从开发库推断桌面状态，也没有使用测试目录的Fixture代替生产数据。

| 游戏 | 开发总数 | 明确标签 | 来源Unrated | UNKNOWN | 桌面总数 | 明确标签 | 来源Unrated | UNKNOWN |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 原神8552 |330|20|248|62|154|0|119|35|
| 崩铁18366 |81|5|44|32|155|0|86|69|
| 绝区零19567 |446|63|243|140|159|0|83|76|
| 鸣潮20357 |80|4|30|46|161|0|61|100|
| 终末地21842 |80|10|18|52|163|0|53|110|
| 异环23012 |80|8|29|43|151|0|48|103|
| 合计 |1097|110|612|375|943|0|450|493|

有来源分类证据比例（包括列表明确false标志，不是SFW率）：开发六游戏依次81.21%、60.49%、68.61%、42.50%、35.00%、46.25%；桌面77.27%、55.48%、52.20%、37.89%、32.52%、31.79%。明确标签覆盖率分别为110/1097和0/943，不能将Unrated算作人工安全审核。

开发库代码计数：st42、sa78、lp17、pn52、nu38、cp2、sc30、ft4、rp4、Unrated612、UNKNOWN375。桌面只有Unrated450、UNKNOWN493。多标签计数不等于MOD数。完整逐类ID、每游戏计数及最近12条新增作品状态保存在 `logs/content_ratings/F2-chain-audit.json`，不进入Git。

## 真实来源与链路

预算实际12次、顺序请求、每次间隔至少2秒，无重试、无图片/MOD下载，之后不再联网。

| MOD ID | ProfilePage本次结果 |
|---|---|
|732765|st / sa / lp / pn / nu|
|732747|cp / sa|
|729979|st / sc / sa / pn / nu / ft|
|729808|sa|
|732552|st / sc / rp|
|732137|st / rp|
|735410、735384、734145、734116、732164、730877|HTTP200，但分级字段缺失，仅_sInitialVisibility=show，不能据此判定Unrated或安全|

来源明确标签实际为 `_aContentRatings` 的 code→label 字典。`fetch_batch` 校验ProfilePage `_idRow` 与请求ID严格一致，只保留评级字段，不保存说明或媒体。12条的详情/本地/API字段对照见 `F2-chain-verification.json`；本地API对照使用其复用的query_mod_detail只读查询，未另开生产写服务。`_sInitialVisibility`不是评级；`_bHasContentRatings=true`缺标签仍UNKNOWN；只有明确布尔false才归来源Unrated，且不改为SAFE。未从封面、标题或服装猜测。

只用这次已取得的6个可信样本，对真实库通过只读连接调用保存计划dry-run：开发匹配6、候选2、无变化4；桌面匹配6、候选6。两库updated均0，未备份、未推进生产检查点，文件指纹不变。其余6个无字段响应不进入保存候选。

根因区分：

- 来源接口：保存的普通列表快照常只有布尔标志，没有具体标签；ProfilePage有时能返回完整字典，也有只返回visibility的情况。不能承诺每个详情都有分级。
- 数据库存储：历史 `_source_rating_evidence` 有效；开发库4个已回填样本与当前来源一致，未发现本次样本被同步覆盖。原importer保留此证据，未改同步业务。
- 历史未补全：开发仍有375条UNKNOWN；桌面493条UNKNOWN尚未补详情。
- React筛选：原SQL参数化多标签OR筛选在分页之前执行，真实没有标签的数据不会因UI提供选项而自动匹配PN等类别；不是凭空补标签即可解决。
- 客户端新库：独立收录943条，未继承开发库110条标签，也没有可直接使用的补全入口；本轮新增受控入口。

## 客户端补全

右侧展开“内容分级”→“分级补全”。默认“预览补全”不写SQLite、不备份、不推进正式attempted进度。用户点击“补全并保存…”并确认后才允许写入；保存模式重新取得实时详情，不能把旧预览视为永久承诺。

每批最多20条，队列覆盖本地全部游戏，不随浏览筛选改变；优先既有UNKNOWN，跳过明确标签和有false来源证据的Unrated。复用 `run_rating_backfill.schedule`、`backfill_content_ratings.run/fetch_batch`、`save_verified_samples`、Online Backup和共享 `logs/content_ratings/instance.lock`。不建立第二套采集器，不接自动全库任务。包装后的EXE直接执行这些模块，不要求Python或Node。

路径相对于当前userdata：`logs/content_ratings/checkpoint_all.json`是既有正式检查点；source_pause.json是冷却；web_task.json及web_report_*.json是可再生任务报告。正常完成提交后才推进正式attempted列表。全来源失败仅在共享锁内保留失败队列，不推进attempted；用户勾选“重试失败队列”恢复。普通批次跳过失败队列，避免被同一失败ID永久阻塞。中止不强杀正在进行的事务，未提交样本之后可重查。

403/429立即停止；有Retry-After遵守其值，没有明确时间时保守暂停6小时，不忙等、不自动反复请求。404、超时、5xx、非法JSON和缺分级字段均保留失败原因，不改为Unrated。共享锁与普通同步协调，避免嵌套锁；网页关闭后API可继续，关闭桌面窗口时仍遵守活跃任务保护。

写入只改变mods.raw_metadata_json中来源评级证据，保存原始字段、验证UTC时间和详情endpoint。旧证据更晚时拒绝覆盖；相同字段重复保存幂等。一次事务前先成功备份至当前userdata/data/backups/ratings_web_*.db；失败回滚。标题、作者、图片、日期、已阅、关注、人工审核、mod_events和sync_runs不变。JSON检查点与SQLite不能跨文件原子提交，数据库已成功但后续检查点保存失败时不得声称事务一起回滚；恢复以库内已验证证据跳过已提交记录，避免重复写入。

## 图片与筛选

保留“显示作品图片”主开关。新增独立的UNKNOWN和敏感预览开关，默认关闭；后端及列表、详情、关联作品共用一致判定。本地保守集合为pn/nu/sc/ft/bg/iv，以及人工ADULT/NSFW状态；这是本地展示政策，不宣称来源官方统一风险等级。用户明确开启后可查看，仍不改变来源或人工审核。

来源Unrated可在主开关允许时预览，但仍显示Unrated，绝不标记SAFE；无证据UNKNOWN和rp待评级图片默认隐藏，需要明确未知/待评级偏好。API参数show_unknown_preview/show_sensitive分别控制；来源多标签OR过滤不随图片偏好改变。图片URL不被回填清空，高分辨率与缩略图逻辑不变。浏览器偏好存在localStorage，便携私密WebView会话可能在关闭后需要重新允许；评级及个人状态仍在SQLite持久保存。

## 测试、打包与验收

测试涵盖单/多标签、false、true无标签、完全缺字段、旧证据保护、新证据重启、403/404/429、超时/JSON、筛选、图片偏好、用户状态保护、dry-run、备份/SQL回滚、共享锁、取消、失败续跑及重复执行。最终完整Python458/458通过（454.227秒），证据 `logs/content_ratings/F2-python-final.txt`；追加rp保护后再次通过13项分级专项和前端15项，生产构建通过。首轮全量457/458的失败属于旧测试将403冷却带入随后的非法JSON场景，已增加冷却断言并隔离临时状态；两个用例都保留，原失败日志不删除。

最终本地包 `dist/desktop-0.5.0-rc1-F2-final/ErYouToolbox-0.5.0-rc1-OB6-E2-F2-win-x64.zip`，SHA-256为 `b878965e974670dc69c976a4c732cc86be0e91f2d2f9a40aa8b81fa378dd997e`。源码未提交，BUILD_INFO以d456b35为起点且明确dirty=true；仅用于本机验收，不可直接作为正式Release。最终源码外中文目录复验 `logs/content_ratings/F2-final-isolation.json` 为PASS，新增空队列评级dry-run检查，验证冻结模块和新接口不依赖开发环境；源请求数为0。真实非空来源保存通过临时库/模拟HTTP链路测试，未冒充便携生产库实际保存。正常详情/已阅/关注/迁移及异常恢复也通过。

修改清单：content_ratings.py；backfill_content_ratings.py、run_rating_backfill.py、react_api.py、desktop_app.py、build_desktop.py；新增rating_enrichment.py、audit_rating_chain.py；React的App、policy及其测试、PreviewCard、ModDetail、RelatedMods、PopularPanel，新增RatingEnrichment；测试rating_enrichment、react_api、rating_scheduler、desktop_isolation_check；本说明、PROJECT_STATUS、RELEASE_CHECKLIST和本说明的.gitignore例外。未修改models/importer/ui_queries、SQLite schema、五列CSS、普通同步或历史图片回填。

Windows人工步骤：

1. 不覆盖正在使用的F1目录；先保持自动同步关闭并退出旧客户端，独立备份整个旧userdata。
2. 完整解压F2至新可写目录，空库启动属正常。本轮不自动迁移943条或1097条数据；需要继续使用旧数据时由用户在停写并备份后手动迁移完整userdata，勿只复制活动SQLite主文件或混用_internal。
3. 展开右侧评级区，核对当前库统计；先预览最多20条，检查候选和失败原因。无字段的来源结果应保留UNKNOWN。
4. 仅在用户明确批准后点“补全并保存…”；核对备份、标签筛选和个人状态。重新运行应跳过已验证记录，失败用队列显式重试；冷却未结束不能绕过。
5. 验证UNKNOWN/敏感图片默认隐藏及手动允许，标题卡片和分级筛选仍可浏览全部；验证关闭重开后评级保留。

本轮生产updated=0，历史分级完整性没有宣称修复。仍需用户后续小批apply，且来源不提供证据的作品可能长期UNKNOWN。Release继续等待人工验收、源码归档和干净提交重建，不创建tag或上传。
