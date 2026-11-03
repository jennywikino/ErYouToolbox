# OB6-E2-F5：妙妙二玩箱品牌替换

目标版本仍为 0.5.0-rc3。中文产品名“妙妙二玩箱”，英文工程名 ErYouToolbox。

## 范围与兼容

- 用户提供 assets/branding/MiaomiaoEryouxiang_icon.ico 和 PNG，并明确确认具有公开源码及 Windows 包分发权限。原文件未修改。
- 原生窗口标题、React 文档标题/首页品牌/版本文案、README 与 Release 草稿使用中文品牌。
- EXE 为 `妙妙二玩箱.exe`。外层目录和 ZIP 继续使用 ErYouToolbox 工程名，避免改变数据目录和现有发行路径约定。
- Windows 产品名、文件说明为中文；InternalName、仓库、API、数据库结构、userdata、portable.json、project_identity、共享锁及检查点均不变。
- 旧 userdata 原位保留；更新程序时不要覆盖或复制活动数据库主文件。新解压目录不自动迁移个人库。先关闭所有写入并备份完整 userdata，再由用户明确决定迁移；本轮不操作生产库。

## 图标实现

PyInstaller 使用指定 ICO 和 windows_version.txt；ICO/PNG 显式收集至 `_internal/assets/branding`，纳入 SHA-256 资源清单。构建缺失品牌资源立即失败。构建后比较 PE 的 RT_ICON 图像与原 ICO 图像散列，8个全部一致。

pywebview WinForms 原生 `icon` 参数使用包内 ICO，显示在窗口标题栏、任务栏与 Alt+Tab。AppUserModelID 固定为 ErYouToolbox.Desktop，与可见名称及数据身份分离。React 标记通过 Vite 将用户 PNG 收集到静态资源；未改配色/网格。应用不自动创建快捷方式，用户创建的新快捷方式默认继承 EXE 图标。

## 验证与边界

相关 Python：品牌3项、资源8项、桌面17项，共28项通过；前端16项通过；TypeScript/Vite生产构建通过。

实际外部解压测试使用中文/空格临时目录、无项目 Python/Node PATH、无 Vite；验证原生标题、原生窗口图标像素与 ICO 一致、六游戏、只读资源缺失错误、已阅和关注持久化、自动同步设置保持、目录移动、重复启动锁、异常重启及端口释放。测试仅用隔离空库/模拟作品，不连接 GameBanana，不操作真实关注或 MOD。

实际运行结果记录于忽略的 `logs/content_ratings/F5-*-isolation.json`；最终交付目录为 `dist/desktop-0.5.0-rc3-F5-delivery`，ZIP 及相邻 SHA-256 文件以最终构建为准。BUILD_INFO 记录真实源码提交、构建环境与图标校验结果。

预构建外部独立解压已实际 PASS：窗口标题“妙妙二玩箱”，原生窗口图标与指定 ICO 像素一致；已阅/关注/自动化设置经重启和目录移动保持；异常退出恢复、资源缺失失败、端口释放通过。中文 EXE 的 Windows ProductName/FileDescription/OriginalFilename 已读取确认正确。最终干净提交包还需重复该测试，不以预构建结果替代。

Windows Explorer、任务栏、Alt+Tab 图标的人工视觉检查不能以自动化像素校验代替。若新 EXE 资源已正确但旧路径仍显示旧图标，先在全新解压目录查看、重新建立快捷方式；不强制清理系统缓存、不删除 userdata。物理 E/F 换盘和全新 Windows 环境仍需人工验收。

## 用户验收

1. 将最终 ZIP 完整解压到全新可写目录，双击妙妙二玩箱.exe；检查窗口名称和三个 Shell 入口图标。
2. 不授权自动入库时保持手动模式；确认六游戏、详情、图库、已阅和关注功能正常。
3. 关闭后确认端口释放，重启确认状态保持；关闭后移动整目录再次启动。
4. 对旧 userdata 先备份再用户手动验收，不删除旧目录。发布需另行人工确认，不自动创建 Release 或标签。
