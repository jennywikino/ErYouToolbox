# OB6-C4 六游戏定向补图预检

结论：通过本轮预检，具备用户手动分批 apply 的基础；本轮生产实际写入为 0。不是无人值守全库修复批准。

## 当前统计

|游戏|总数|无有效图|低清/未验证原图|原图元数据|URL待联网验证|已提交修复|待处理|
|---|---:|---:|---:|---:|---:|---:|---:|
|Genshin Impact|330|268|4|58|62|10|272|
|Honkai Star Rail|81|33|0|48|48|0|33|
|Zenless Zone Zero|446|198|0|248|248|0|198|
|Wuthering Waves|80|20|0|60|60|0|20|
|Arknights Endfield|80|20|0|60|60|0|20|
|Neverness To Everness|80|20|0|60|60|0|20|

总数 1097；无有效图 559，低清/未验证 4，原图元数据 534，含 URL 待验证 538，待处理 563。此前10条原神记录均有原图元数据，专项状态均为 verified。已提交失败与来源无图状态为0；这不是声明所有作品来源都有图。数据库统计和来源可用性是独立维度，不能相加。

## 真实网络结果

六游戏各 10 次精确详情请求，共 60 次，零自动重试，顺序执行；全部取得可信 _sFile 原图元数据并形成更新候选。每游戏来源验证成功率10/10，失败/来源无图/解析后跳过均0。未发起图片 HEAD/GET，不代表图片本体加载成功。四条低清记录并未保证进入此次网络样本，相关分支使用临时数据测试。

可修复 ID：

- Genshin Impact：541855, 545784, 552304, 557145, 557504, 566835, 581562, 584316, 586817, 596362
- Honkai Star Rail：487189, 487530, 511413, 542337, 608041, 614760, 635376, 652784, 652984, 653368
- Zenless Zone Zero：527935, 529789, 531649, 537466, 553291, 565870, 567291, 574763, 575473, 577779
- Wuthering Waves：592249, 595706, 596020, 619220, 658343, 714540, 720413, 722041, 722789, 725031
- Arknights Endfield：666289, 675342, 682611, 688983, 691126, 705812, 720894, 728076, 728623, 729174
- Neverness To Everness：712866, 719680, 725532, 726783, 727079, 728363, 729625, 729714, 729910, 730412

其余未请求记录受批次额度限制，不是失败。全部审计ID、来源结果与跳过数组见 `logs/preview_repairs/preflight_1793615456443167200.json`；空 failed/source_no_images/skipped_after_parsing 表示本次未出现该类记录。

## 安全审查与限制

- 复用 repair / fetch_exact_item / extract_preview_images / run_backfill / verified_backup，新增的 preflight 入口不支持 --apply。没有修改业务回填、UI、调度器或 schema。
- 固定官方 Mod/ProfilePage，核对ID、游戏、端点类型和官方图片URL。原图仅来自_sFile；thumbnail_url/switch_url按真实字段提取，不能猜文件名。已有高清以及高清低清混合采用原有保守跳过策略。
- 每条最多一次请求；5xx/超时记录失败，不自动重试。失败可稍后重跑；apply 后失败队列按原一小时复查，retry-failed不绕过该时间。403/429停止全轮后续游戏，冷却遵守Retry-After；本轮实际均未遇到。404或缺字段不得当来源无图。仅身份有效且明确空_aImages才支持来源无图证据，apply后七天复查。
- 正式写入沿用共享锁、一次批次备份、BEGIN IMMEDIATE及异常回滚，只改preview_urls_json。备份发生在事务之前，只能防范遵循同一锁的协作写入；需避免其他SQLite工具同时操作。
- SQLite提交与专项JSON状态保存不是原子事务。状态写入失败后仍以数据库原图保护保证幂等，但可能重复请求；恢复时数据库与状态需配套。没有硬编码磁盘盘符，状态绑定data/eryoutoolbox.db。
- 本轮业务表一致性指纹覆盖mods/user_states/author_subscriptions/mod_events/sync_runs，前后完全相同；专项state.json字节不变，备份文件清单及大小不变。没有生产apply、数据库迁移、后台任务触发或Git推送。

## 测试与后续建议

专项测试16项、原回填回归35项，共51项通过；Python语法检查通过。新增矩阵覆盖六游戏预算、403/404/5xx、混合高清保护、全部非图片字段及同步记录保持、共享锁、失败队列续跑。其余身份、空图、URL、429、超时、幂等、dry-run、备份与事务失败均使用临时SQLite及模拟HTTP验证。未运行UI冒烟。

建议先单游戏5条 apply，由用户执行并核对图片字段、用户状态、事件及同步游标；再单游戏10条，稳定后每批最多20条。每批先备份，保存运行前专项state.json以便配套恢复。不要直接自动六游戏全库apply，不删除旧备份。当前apply会重新请求来源，不是提交冻结的dry-run报告。

项目根目录 PowerShell：

```powershell
$python = Join-Path $env:LOCALAPPDATA 'ErYouToolbox\venv\Scripts\python.exe'
& $python -m unittest discover -s tests -p test_preview_repairs.py
& $python -m unittest discover -s tests -p test_backfill_previews.py
& $python scripts/preflight_previews.py
# 下条会重新消耗最多60次详情请求，勿反复执行
& $python scripts/preflight_previews.py --online
# 单游戏预览；本轮未自动执行对应apply
& $python scripts/repair_previews.py --game 8552 --limit 5 --dry-run
```

修改文件：新增scripts/preflight_previews.py、本文档；补充tests/test_preview_repairs.py。原生产回填函数不变。
