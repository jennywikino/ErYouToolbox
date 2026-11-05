## MAINT-1-FIX（恢复分支，尚未发布）

2026-11-05：恢复检查点 a7e0e353c3a514ea75f19f179d9ff1de73dfd70c，分支 recovery/maint1-20261105。之后修复保留在工作区，未推送、未合并、未发布。

JASM仅对名称首尾执行strip；空项、内部控制字符、超长、冲突及无效格式仍拒绝，五游戏全部校验完成才预览，确认保存前备份与原子替换。外部/导入层保留有效的低优先级检索写法（Hutao、Chen Qianyu等），高层排在前；个人修正仍可完整替换/删除。顺序为个人修正 > 已验证导入 > 外部同步 > 内置。原始交换JSON仍format=1，持久状态format=2，兼容读取旧format=1而不静默改写。

JASM来源为 Moonholder/JASM-GameAssets；只请求manifest及五游戏Languages/zh-cn/characters.json，异环保留本地索引，不取图片、不打包第三方资源全集。版本号来自manifest，源16位hash不冒充SHA256；实际HTTP可用性及桌面点击仍待人工验收。

历史补全在更多设置可选择off/check/apply并确认保存；apply有明确确认。授权使用既有同步模式，也影响遗留CLI/已注册任务；不修改系统任务，当前启动一次/手动刷新规则不变。off/check不自动升级权限，历史引擎仍在提交前复核apply。

独立备份新增白名单data/character_library/library.json；SQLite Online Backup、JSON格式验证、SHA256、完整性校验、状态变化检测、临时恢复预演均复用原实现。只备份有效当前状态，不收集名称库旧备份全集、缓存或日志。所有写入需暂停后备份；不恢复覆盖生产库。

此恢复分支功能尚未包含在GitHub已发布rc3下载中；README保留原下载URL。打包脚本使用启动一次说明，下一次获准打包还需独立解压验收。

# OB6-E2 Windows x64 桌面候选

日期：2026-11-03。目标 0.5.0-rc1；不是正式 1.0 或 GitHub Release。

## OB6-E2-F1 启动修复与隔离验收（最新）

用户目录 `E:/codex/ErYouToolbox` 的 EXE SHA-256 为 `CE1B07B13067A3458667C502004E96467BD3195767DE3B151E70C3A747F80948`，与早期 `dist/desktop-0.5.0-rc1` 的失败EXE完全一致；其BUILD_INFO为0d4eaf8、dirty=true、EXE时间10:21，并非545c994最终产物。旧包的games/ratings实际已位于_internal/config，缺的不是资源本体，而是旧API从冻结后的react_api.__file__.parents[1]推算到了EXE外层config。此错误不由cwd决定。上一轮保留多个同版本构建且独立目录验收不足，造成错误产物容易被误取；旧产物保留作为失败证据，不再作为交付。

统一路径：`app_resources.resource_root()` 在冻结时仅使用sys._MEIPASS；开发时定位源码根。`executable_root()`独立定位EXE所在目录；userdata仍为EXE旁可写目录。API用独立resources_root读取不可缺失的games/ratings，不再以运行状态目录推断只读配置。userdata/config的现有镜像仅为原有同步模块兼容而保留，不是API配置fallback，也不代替包内校验。未改变内容分级默认策略、schema或同步业务。

构建前验证两份JSON、index.html及其引用的JS/CSS，生成带逐文件SHA-256的RESOURCE_MANIFEST.json。PyInstaller使用独立构建目录和--clean；收集后在_internal再次验证清单与输入完全一致，缺资源或散列变化禁止生成交付ZIP。启动前同样验证，缺资源时在创建userdata之前报完整路径，不返回空分级或放宽过滤。F1包名包含OB6-E2-F1，BUILD_INFO含build_revision，避免混淆同版本早期ZIP。

测试：新增资源回归8项、桌面17项、API14项通过；完整Python445/445（151.966秒），前端15/15及生产构建通过。证据 `logs/desktop-build/F1-python-tests.txt`。前期测试驱动的Unicode日志偏移、隐藏列表h1选择器、异常消息反斜杠比较问题均保留BLOCK报告，修正驱动后完整隔离验收PASS，不以失败报告替代成功证据。

真实隔离验收：`tests/desktop_isolation_check.py` 将ZIP解压至Windows TEMP下全新中文/空格目录（源码目录外C盘），从另一cwd启动，子进程PATH仅含Windows目录，清空PYTHONHOME/PYTHONPATH，无Vite。原生WebView通过临时回环CDP测试驱动实际点击MOD卡片、进入详情、点击关注；详情自动已阅。Node仅作为外部验收驱动，客户端不调用Node。使用明确标识的离线Fixture，不下载图片，不请求GameBanana，不导入私人数据。

已实测：6游戏、17分级、React资源、原生详情、已阅/关注保存、重启持久化、整个目录迁移、窗口关闭释放端口；移除ratings/games/index/JS时明确失败且不建userdata；测试目录ACL拒绝写入时报错，恢复ACL后正常启动；重复启动不替换现有锁；仅终止本测试直接启动的空闲EXE后，保留锁文件也能重启。完整证据 `logs/desktop-build/F1-isolation4.json`；最终源码提交重建后的复验以 `F1-final-isolation.json` 为准。没有修改用户已解压目录、生产库或系统任务。

最终目录：`dist/desktop-0.5.0-rc1-F1-final/`，ZIP为 `ErYouToolbox-0.5.0-rc1-OB6-E2-F1-win-x64.zip`。准确源码提交见包内BUILD_INFO，ZIP散列见同目录.sha256；只交付此F1包，不使用旧同版本产物。

```powershell
$python = Join-Path $env:LOCALAPPDATA 'ErYouToolbox\venv\Scripts\python.exe'
& $python -m unittest discover -s tests -p test_app_resources.py -v
& $python scripts/build_desktop.py --output dist/desktop-0.5.0-rc1-F1-new
& $python tests/desktop_isolation_check.py --archive dist/desktop-0.5.0-rc1-F1-new/ErYouToolbox-0.5.0-rc1-OB6-E2-F1-win-x64.zip --report logs/desktop-build/F1-manual-isolation.json
```

用户手动验收：完整解压F1 ZIP至新目录，核对BUILD_INFO的F1标识与源码SHA；双击，观察空库及六游戏/分级筛选；自行选择游戏检查预览后决定是否确认入库。关闭重开验证已阅关注。在另一台无Python/Node的Windows和真实F盘上仍需人工确认；本机受限PATH不等价于干净机器。本轮没有迁移1097条私人数据，首次空库正常；关闭后的后台计划任务仍未支持。不得现在创建Release或版本标签。

本轮用户明确批准Public源码提交/推送，旧Private记录不再作为阻断。审核白名单源码、测试、文档后正常推进master，不推送运行数据或EXE，不改旧标签/历史。以下OB6-E2原始记录中的Public阻断仅保留为历史。

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
