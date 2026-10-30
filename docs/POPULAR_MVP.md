# 热门 MOD MVP

## V0.4 Step 03B：近期发布

默认选择近期发布/30天，可选7、90天；保留历史累计的原来源排序接口。

近期候选使用 Generic_Newest，按真实 _tsDateAdded 对 UTC 窗口筛选，不用 modified_at 或 updated_at 代替。扫描每页最多50条，默认2页，最多5页，由页面“扫描上限”或 API max_pages 配置。不从历史热门第一页过滤日期。

窗口内去重后按实际累计喜欢/浏览数排序并分页，标注“近期候选集排名”，不称官方近期热度增长榜。缺失所选指标的作品不参与该指标排序，不用0或其他指标补齐；下载量尚无可靠字段时显示暂无数据。

没有观察到边界、时间缺失、来源时间顺序异常、重复或请求失败时 coverage=incomplete。只在已观察到边界且当前样本检查通过时标 boundary_observed，始终不保证完整无遗漏；达到扫描上限不会宣称完整。失败发生在后续页时保留已得候选并显式报告扫描中断。

30分钟缓存分两层：游戏/窗口/扫描上限/每页大小的候选集，及包含指标、展示页码、展示页大小的榜单结果。切换指标/展示页复用候选，手动刷新重新扫描有界页；来源请求沿用顺序锁、两秒间隔、超时及限流暂停。显示候选所用来源页中最早的真实获取时间，不把缓存读取时间当作新抓取时间。

离线测试覆盖窗口、边界、缺失指标、分页、去重、异常与缓存切换。2026-10-29真实验证仅原神一页5条，收到5条窗口内候选，喜欢数排序为21/20/16/8/5；没有观察到30天边界，coverage=incomplete，SQLite SHA-256未变。报告 logs/recent_popular_20261029_114933_459538.json。没有执行其他游戏扫描或全量采集。

```powershell
$python = Join-Path $env:LOCALAPPDATA 'ErYouToolbox\venv\Scripts\python.exe'
& $python -m unittest tests.test_recent_popular tests.test_popular tests.test_react_api tests.test_ui_queries
# 可选的一次原神单页5条只读在线验证
& $python scripts/probe_recent_popular.py
```

重启已有启动器后，检查默认30天、7/90天切换、指标切换、候选分页及覆盖提示；下载模式应暂无数据；切回历史累计仍显示来源排名。搜索与分级只筛当前展示页，不代表全候选集搜索。

## 原历史累计说明

在线读取 GameBanana Mod/Index，不写入 SQLite，不受本地收录数量限制。支持六个配置游戏及三种来源排序：likes → Generic_MostLiked、views → Generic_MostViewed、downloads → Generic_MostDownloaded。

真实验证（2026-10-29）：官方 ListFilterConfig 列出三种排序及 Generic_Game 过滤；本轮只实际执行原神、最多喜欢、第一页、3 条的小样本请求，HTTP 成功。三个游戏 ID 均为 8552，排名 1–3 的点赞分别为 7025、6600、5211；实际字段 _nLikeCount、_nViewCount。三个作品均未在本地，浏览不入库，SQLite 哈希不变。报告 logs/popular_probe_20261029_111546_766617.json。

最多浏览、最多下载的请求参数已离线测试，但尚未实际请求对应榜单；第二页真实响应尚未验证。下载数具体字段未确认，因此不显示猜测数值。来源指标按累计值展示，不称近 7 天热度；不提供本地模拟排行榜。

全部游戏分组显示，由用户逐组点击加载，不合成跨游戏排名，也不自动同时请求六个游戏。单游戏自动读取第一页。每页最多20条；来源分页元数据必须有效，游戏或作品身份异常即报错。排名由来源页位置计算，搜索与分级仅过滤已取回的当前来源页，不假装为全站搜索，也不重排排名。

进程内缓存30分钟，最多64个条件组合；所有来源请求共用顺序锁和两秒间隔，未增加后台任务。手动刷新绕过缓存，但无法绕过限流暂停；403/429停止并按 Retry-After 暂停，没有明确时间时保守暂停30分钟。超时或非 JSON 明确显示失败，不生成替代内容；不自动无限重试。

已收录作品通过 source=gamebanana + item_type=Mod + item_id 对照后进入现有详情。未收录作品点击卡片显示来源列表信息和原站入口，不触发详情 API、不自动入库。图片沿用现有标准化，不下载图片。缺少具体分级标签的远程记录显示 UNKNOWN，不把 _bHasContentRatings=false 当作详情分级证据；保留现有本机图片显示偏好。

验收：重启现有 API/React 启动器，进入热门分区，选原神，检查三种排序入口、分页、刷新和最后成功时间；切换全部游戏应为各游戏独立加载。开启搜索/分级后应明确只筛当前来源页。检查最新、订阅及本地详情仍可用。

```powershell
$python = Join-Path $env:LOCALAPPDATA 'ErYouToolbox\venv\Scripts\python.exe'
& $python -m unittest tests.test_popular tests.test_react_api tests.test_ui_queries
# 可选：仅一次原神最多喜欢第一页3条的真实探测
& $python scripts/probe_popular.py
```
