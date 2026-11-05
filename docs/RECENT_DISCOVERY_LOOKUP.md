# OB7-B补充：近期活动发现与精确ID查询

2026-11-03，只修改源码，不重打客户端、不发布、不自动提交或推送、不执行生产入库。

## 541855实际诊断

只请求一次官方`/apiv11/Mod/541855/ProfilePage`，HTTP200，作品541855、游戏8552、Mod原帖身份匹配。来源发布时间2024-09-13T09:36:42Z，明确更新时间2026-10-26T14:23:49Z，修改时间2026-10-26T14:23:33Z。

开发`data/eryoutoolbox.db`已有该作品，Skins/Zhongli；使用现有query_mods无筛选精确ID搜索命中1条。已知旧F1便携目录userdata库没有该作品，无筛选也0条。因此开发库不是未入库；两份数据库不能混用结论。UI的游戏、分类、已阅、图片等条件仍与ID检索一起生效，错误分类能使已入库作品不可见。

该来源有90天内明确更新时间，原有created/updated窗口已会接纳它，不能归因于本次修正的modified遗漏。没有足够逐记录扫描证据确认旧便携库是否曾扫到该记录，也没有确认用户现在打开的是该旧库；有限分页并不保证扫描到所有近期更新。不能虚称已确定“曾被窗口排除”。当前代码不提供来源全量覆盖保证。

## 变更

- web_sync.recent_window接受来源created_at、updated_at或modified_at任一处于窗口内；缺失/非法/未来日期不编造。采集器本已保留三种字段及within_days_candidate，不另写采集器。
- importer未改：source_updated仍依据独立updated_at证据，modified不能替代文件更新证据。现有自动入库仍不把仅元数据变化当来源更新。
- 最新列表同步工具栏增加主动MOD ID查找，必须选择六游戏之一。POST /api/sync 的lookup操作复用共享锁、SourceDetail官方详情身份校验、缓存与403/429冷却；一次详情请求，不扫描历史列表或下载文件。已有本地作品直接提示清除筛选，不重复请求。
- 查找成功只生成标题/作者/身份预览，沿用现有待确认弹窗和confirm流程。保存复用import_samples、备份、事务、过期与数据库指纹校验。失败不写库、不吞掉来源错误。旧待确认预览必须先确认或放弃，不覆盖。
- ID查找不套90天限制，可主动寻找旧作品；其候选games为空，不生成分页检查点。确认入库的同步记录只包含空checkpoints，不覆盖既有正式游标。普通扫描仍有页数上限、coverage=incomplete。
- ui_queries不改过滤语义；不自动清空分类或个人筛选，不修改已阅、关注、内容评级或旧图片。

## 验证

临时SQLite与模拟来源：远程查找7项、rc3安全/窗口15项、原WebSync14项、既有来源详情及分类浏览test_f3_browsing.py 10项，合计46项通过；前端16项及TypeScript/Vite构建通过。用例包含旧发布近期更新、仅修改、日期缺失、有限覆盖、分类排除、重复入库、身份错误、超时/404/429、备份失败、异步预览确认和检查点不推进。模拟失败不等于本次真实请求遇到限流；未存在的test_source_detail.py曾发现0项，不计入通过数量。

## 本机验收

重启源码Web API和前端，选择原神，清空分类/已阅/图片等筛选后搜索541855。开发库应直接找到。若在独立测试空库中，输入541855并点击“查询来源”，查看预览，再手动确认导入；不确认时数据库不变。再次查询应提示已保存，不制造重复。已有待确认预览先主动处理，不可绕过。

```powershell
$python = Join-Path $env:LOCALAPPDATA 'ErYouToolbox\venv\Scripts\python.exe'
& $python -m unittest discover -s tests -p test_remote_lookup.py
& $python scripts/react_api.py
```

前端另运行`pnpm.cmd --dir frontend dev`。本轮没有重打EXE，现有便携客户端不会自动获得这些源码改动。正式库、现有检查点没有执行写入；用户确认单条保存属于后续手动验收。
