# OB6-E2 Windows x64 桌面候选

日期：2026-11-03。目标 0.5.0-rc1；不是正式 1.0 或 GitHub Release。

## 架构与边界

pywebview 6.2.1 的 WinForms / EdgeChromium 独立窗口，PyInstaller 6.22.3 onedir；Python 3.15.1 x64、pythonnet 3.2.1、httpx 0.28.1。依赖仅装入本机 LOCALAPPDATA/ErYouToolbox/packaging-venv，不修改开发虚拟环境或全局 Python。依赖完整清单在构建证据 packaging-freeze.txt。

React/Vite 只在构建时使用。运行时同进程 ThreadingHTTPServer 绑定 127.0.0.1 的操作系统分配端口，提供现有 API 和 dist/index.html、dist/assets。不会将项目目录、userdata、数据库、配置或日志作为静态根目录。Host 必须匹配实际端口；写入要求相同 Origin、JSON 和原有 X-ErYouToolbox 头，拒绝开发服务器 Origin。

ReadOnlyAPI 增加可选 runtime_root，Web 默认行为保留；桌面传入 userdata。WebSync、AutoSync、normalizer、importer、Online Backup、事件、用户状态逻辑直接复用，没有第二套采集器或新 schema。

## 数据与关闭

布局：ErYouToolbox.exe、_internal、README.txt、BUILD_INFO.json；首次启动创建 userdata。数据库为 userdata/data/eryoutoolbox.db，配置为 userdata/config，运行检查点、报告、锁在 userdata/logs，专项数据库备份在 userdata/data/backups。

首次仅创建空 schema3，不打包1097条个人记录。已有 userdata 缺数据库、身份不符、schema不支持或目录不可写会报错，禁止静默新建替代库或自动迁移已有库。portable.json 用于区分本产品初始化的数据；中断初始化需要人工检查保留的数据，不自动删除重建。

同一便携目录的 OS 文件锁防重复实例。动态端口不占用8766/5173，不停止现有 Web 服务。窗口关闭时拒绝新写请求；同步活跃时提示等待/停止，同步完成后正常释放 HTTP 服务。异常收尾会请求停止网页扫描并等待已开始的操作，事务和断点沿用现有机制；不按进程名杀 Python/Node。

WebView2 缺失时报安装链接，不下载。图片和原帖沿用现有来源 URL；不下载或代理图片，外部链接由系统浏览器打开。禁止 file URL 和下载。首次自动模式为 off。

便携版仅客户端打开时可运行启动检查、立即检查/确认及已保存的自动模式；**关闭后自动计划任务未支持**，API与界面明确说明。没有注册或改动 Web 版 Windows 任务；不能将其 Python路径/项目身份直接用于EXE。

## 构建

在项目根目录使用项目解释器；沙箱内 LOCALAPPDATA 可能被重定向，实际执行已在正常 Windows 上下文核对。

```powershell
$python = Join-Path $env:LOCALAPPDATA 'ErYouToolbox\venv\Scripts\python.exe'
& $python -m venv (Join-Path $env:LOCALAPPDATA 'ErYouToolbox\packaging-venv')
$packPython = Join-Path $env:LOCALAPPDATA 'ErYouToolbox\packaging-venv\Scripts\python.exe'
& $packPython -m pip install -r requirements-desktop.txt
pnpm.cmd --dir frontend test
pnpm.cmd --dir frontend build
& $python -m unittest discover -s tests -p test_desktop.py -v
& $python scripts/build_desktop.py --output dist/desktop-0.5.0-rc1-new
```

不要在构建期间再改变 frontend/dist。输出目录存在即拒绝覆盖；输出只允许在项目 dist 下。白名单仅加入前端 dist 和两个公开 config；Python 模块由 PyInstaller 分析，绝不加入项目 data/logs、私有身份或整个源码目录。ZIP禁止包含 userdata、数据库、日志、依赖缓存、node_modules和Git历史。SHA-256单独输出。

移动盘依赖连接可能仍指向旧盘符，本机已将90个确认目标存在的 node_modules 目录连接从F重连至E，不升级Node依赖。此问题只影响源码开发/构建，EXE不读取node_modules。

## 已执行与待验

- 前端15项通过，TypeScript/Vite构建通过。未改五列/25件布局、画廊、采集规则或 schema。
- 新增桌面17项临时库测试通过：6游戏/空库、静态隔离、Host/Origin、已阅关注重开、目录移动、锁、动态端口、拒绝错误schema/缺库/不可写、HTTP预览确认重复入库、无计划任务、默认off、冻结配置路径、锁释放前禁止确认。
- 源码pywebview实际窗口启动并加载React/API、关闭退出成功，首次发现计划任务说明被当错误已修正。该早期截图/文本仅作开发证据，以最终EXE结果为准。
- 最终完整Python437/437通过（173.644秒），证据 logs/desktop-build/python-final.txt。首轮434/435，新增桌面确认交界用例失败；保留 python-full-verbose.txt，未删失败用例。在桌面适配层保护工作线程结束前的预览状态，并限制其间重复POST后复验通过，未更改采集/导入业务规则。
- 首轮冻结EXE发现配置仍按开发路径查找，保留失败产物 verified 和日志；已使用 runtime_root 下的公开配置修复，并增加冻结路径回归。candidate2 ZIP解压后实际EXE正常显示独立React窗口和六游戏配置，退出码0；子进程PATH不包含Python或Node。这是本机受限PATH验证，不等于干净Windows验证。
- candidate2实际EXE的绝区零单页远程预览：HTTP200，1次请求、20条候选、0失败，coverage=incomplete；未确认入库，隔离库仍0条，退出码0、端口释放。证据 logs/desktop-build/exe-online-preview.json。未下载图片或MOD。
- 最终归档包构建目录为 dist/desktop-0.5.0-rc1-final；准确源码SHA、依赖版本和ZIP散列以该目录BUILD_INFO.json及.zip.sha256为准。此前 exploratory/verified/candidate2均为开发证据，不作为最终交付；不得发布dirty构建。
- 生产数据库前后文件SHA-256均为 D2D00D25BA64FF4A0F34B405583C5867AF64034A6E69977F8F4F8CF71E66F7DA，未迁移、恢复、同步或图片apply。
- 冷净Windows无Python/Node、WebView2缺失、实际E/F切换、不同分辨率、生产同步/个人库迁移仍需用户人工验收。

## 数据迁移、备份与回滚

本轮不自动迁移个人库。需要迁移时先关闭客户端、暂停全部写入，对开发库使用现有 backup_project.py --writers-paused 在独立设备生成完整包并验证。迁移计划必须同时包含SQLite和经校验的相对路径检查点，不直接复制活动SQLite主文件、不把机器计划任务授权一并移植。取得用户确认后再另行实施。

更新应用前关闭程序，完整保留旧便携目录作为回退；只更换EXE/_internal/README/BUILD_INFO，不覆盖userdata。回退使用旧程序加其匹配的数据备份，在新的演练目录验证后再决定恢复。不要将测试库覆盖生产库。需要独立灾难恢复备份时，关闭所有写入后备份整个userdata到另一物理设备，并校验；复制仅适用于已确认关闭的便携数据，运行中的SQLite必须使用Online Backup。

## Git / Release 阻断

起始 master 为0d4eaf88f2eddeaa74caea57f627569ad3454bc3。源码通过白名单本地提交后，最终包BUILD_INFO记录其准确SHA和dirty标志；不能把早期dirty包伪称来自干净tag。旧v0.1.0/v0.4.0-rc1不改。没有创建候选版本tag或Release。

2026-11-03 GitHub连接器实查 visibility=public。项目规则禁止直接推送原私有历史到公开仓库，因此本轮push BLOCK，不改可见性、不上传EXE、不创建Release/tag。须先确认私有归档目标或另行批准白名单公开快照与许可证。
