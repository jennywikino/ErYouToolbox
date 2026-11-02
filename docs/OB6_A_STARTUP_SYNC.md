# OB6-A 网页启动检查

## 执行规则

- 首屏本地查询独立执行，不等待自动同步状态或网络采集。
- 每份网页文档只执行一次启动检查（包括 React StrictMode、组件重挂载及分区切换）。刷新新文档仍由服务端重新判断到期条件。
- 新增受本地来源、Host、自定义请求头及空 JSON 请求体保护的 `POST /api/auto-sync/startup`。不接受模式、强制运行、任意脚本或 SQL 参数。
- 调用现有 `AutoSync.launch(startup=True)` → `AutoSync.run(force=False, preserve_preview=True)`，不建立新同步器。
- off 不采集；check 保留报告/预览、不写 MOD 数据；apply 沿用已保存的授权模式、来源校验、备份、事务和事件规则。
- 间隔、429 冷却、共享文件锁均由后端判定；网页不会修改用户设置。不覆盖仍在有效期内的手动或自动待确认预览（沿用原有十分钟预览期限）。
- 浏览器关闭不会取消 API 进程中的有界任务；关闭 API 或退出电脑仍不保证任务继续，沿用原有恢复机制。
- 控制条在导航和折叠后仍保持挂载；状态每三秒查询一次。任务结束后刷新本地列表，沿用当前筛选、页码，优先恢复可见作品锚点，像素位置作为备用。不会刷新整个网页。
- 网页启动检查不依赖 Windows 计划任务是否注册；关闭浏览器后的周期触发仍由现有计划任务负责。

## 本轮修改

- `scripts/auto_sync.py`：启动分支不强制跳过间隔，保护待确认预览，后台线程独立于网页请求生命周期。
- `scripts/react_api.py`：受限启动检查入口，沿用原请求保护。
- `frontend/src/autoStartup.ts`：每份网页文档一次请求。
- `frontend/src/App.tsx`：独立启动请求、持续保留控制组件、完成后保持筛选与位置刷新。
- `frontend/src/AutoSyncSettings.tsx`、`SyncCheck.tsx`：状态轮询、运行提示、完成通知。
- `frontend/src/policy.test.ts`、`tests/test_startup_sync.py`、`tests/ui_navigation_smoke.cjs`：离线回归和隔离浏览器场景。

## 已执行验证

- 项目虚拟环境 Python 语法检查通过。
- 临时数据库：启动检查 10 项、原自动同步 21 项、网页同步 14 项、React API 13 项，共 58 项通过。
- 前端 12 项测试通过；TypeScript 检查及 Vite 生产构建通过。
- 临时库真实 HTTP 测试验证非法 Origin 被拒绝、合法启动请求返回、断开连接后任务仍完成。
- 模拟网络覆盖到期/未到期、关闭、check/apply、重复打开、多实例锁、待确认预览、429 冷却和失败后恢复。原自动同步回归覆盖备份失败回滚、来源更新判断及人工状态/图片保护。
- 隔离 Chrome 尝试未通过：先遇到 GPU 缓存/启动问题，关闭 GPU 后仍出现 `CDP timeout: Page.navigate`。未完成页面交互、完成后位置和筛选保留的真实浏览器验收，不将单元测试视为浏览器验收。
- 本轮没有发起真实 GameBanana 请求，也没有对生产库执行测试入库、迁移或修改计划任务。未提交或推送 Git。

## 本机验收

先用现有关闭/启动入口重启 API 和前端，不要终止其他项目的服务。在网页中保留/选择“自动检查”模式进行首轮验收；不要为测试开启自动入库。

1. 打开最新 MOD，确认本地记录立即显示；展开控制条核对已保存模式、间隔和最近检查时间。
2. 若未到期，刷新及另开标签页均不增加来源采集请求。Network 中可有一次 `/api/auto-sync/startup`，它不等同于实际来源采集。
3. 到期后打开网页，确认后台开始检查，折叠管理面板、切换分区或关闭浏览器不取消任务。
4. 有待确认预览时再次打开网页，确认预览仍存在且未自动确认。需要新检查时使用原“放弃本次预览”。
5. 检查期间在第 3 页中部保留游戏、搜索、未阅、评级及图片条件；完成后核对筛选、页码、作品锚点与计数。对最新和订阅列表各验一次。
6. 关闭浏览器后重新打开，核对任务结果仍能查询；off 模式再次打开不产生来源请求。
7. 自动入库模式只在用户另行确认后使用；沿用已有备份和事务验收，不在此轮自动切换模式。

项目根目录 PowerShell：

```powershell
$python = Join-Path $env:LOCALAPPDATA 'ErYouToolbox\venv\Scripts\python.exe'
& $python -m unittest discover -s tests -p test_startup_sync.py -v
& $python -m unittest discover -s tests -p test_auto_sync.py -v
pnpm.cmd --dir frontend test
pnpm.cmd --dir frontend build
```

物理 E/F 盘切换未实测；新增代码不包含固定盘符，继续使用原项目根目录、运行配置和任务锁路径。
