# 自己做着玩的（不要宣传和分发）

# 妙妙二玩箱（ErYouToolbox）

![妙妙二玩箱品牌图标](assets/branding/MiaomiaoEryouxiang_icon.png)

中文产品名称为“妙妙二玩箱”，英文工程名、仓库及数据身份继续使用 ErYouToolbox。图标由用户提供并确认公开分发权限，详见 [品牌资源说明](assets/branding/README.md)。

面向 GameBanana 公开 MOD 信息的本地整理工具，使用 Python、SQLite 与 React / TypeScript。数据保存在本机；不登录来源站点，不下载 MOD 文件，不提供转载授权。目标代码仓库：`jennywikino/ErYouToolbox`。

当前候选版本为 **0.5.0-rc3**，尚未发布稳定版。首次使用需明确选择自动化模式；推荐每3小时检查并入库近90天发布或更新的作品，关闭后不后台运行。历史标签保持不变。

## Windows 桌面候选版

使用 pywebview + PyInstaller onedir，内嵌现有 React 生产资源与 Python 本地 API。完整解压后双击 `妙妙二玩箱.exe`，无需安装 Python、Node 或启动 Vite；需要 Windows x64 和 Microsoft Edge WebView2 Evergreen Runtime。

首次启动在 EXE 旁创建 `userdata/` 和**空作品库**，不会读取或迁移源码目录的个人数据库。更新时保留整个 userdata，不将其覆盖或上传。关闭客户端后不执行后台检查；Web 版计划任务与便携版数据独立，尚不支持便携版后台计划任务。

rc3已取消内容年龄分级筛选与图片遮挡，默认展示有效来源图片。浏览五列/25件、分类、已阅和关注不变。使用“刷新”获取近期候选；“继续向前搜索”逐批拓展较早历史，覆盖不完整时明确提示。缓存管理先预览确认，只清理白名单可再生缓存，不清空作品或个人状态。详见 [rc3收敛与验收](docs/OB6_E2_F4_RELEASE_CLEANUP.md)。

源码构建、隔离环境及人工验收见 [桌面打包说明](docs/OB6_E2_DESKTOP_PACKAGE.md) 和 [Release 检查清单](docs/RELEASE_CHECKLIST.md)。本轮仅本地候选，不自动建立 Release 或标签。

## 已实现

- 公开 API 信息采集与 SQLite 保存，多游戏配置、查询及有界增量同步。
- React 作品列表、搜索、详情与图片展示，已阅状态和作者关注。
- 同步预览、用户确认入库、默认关闭的自动检查与本机任务管理。
- 本机启动/停止脚本、数据库备份与临时恢复验证工具；保留可选 Streamlit 界面。

“已实现”指源码存在，不表示所有生产或跨电脑场景均已验收。图片通过来源 URL 展示，来源可用性和内容权利由来源决定。

## 开发中与已知限制

- 作者轮转、作者作品页、启动检查、渐进历史扫描和定向图片修复已有候选实现，仍需真实场景验收。
- 2026-11-02 已通过独立设备完整备份及临时恢复验收；备份前须暂停全部写入，失效预览通过正常界面处理，勿直接改写状态文件绕过检查。
- 跨电脑盘符变化、Windows 计划任务权限及完整恢复流程尚待实机确认。
- 仅提供待人工验收的桌面便携候选，不提供安装器、账号登录、MOD 下载或稳定版发布保证。
- Python 依赖尚未全部固定版本，安装结果不是严格可复现构建。

## Windows 本地运行

需要 Python 3、PowerShell 5.1+、Node.js 22.12+ 和 pnpm。以下命令均在项目根目录执行；项目可放在移动硬盘，勿在脚本中固定盘符。

```powershell
.\scripts\bootstrap.ps1
$python = Join-Path $env:LOCALAPPDATA 'ErYouToolbox\venv\Scripts\python.exe'
& $python scripts\init_db.py
pnpm.cmd --dir frontend install --frozen-lockfile
```

首次使用公开源码副本时，为该副本生成本地身份文件；不要覆盖已有项目身份：

```powershell
if (-not (Test-Path config\project_identity.json)) {
    @{ project_id = [guid]::NewGuid().ToString(); name = 'ErYouToolbox' } |
        ConvertTo-Json | Set-Content config\project_identity.json -Encoding UTF8
    # Windows PowerShell 5.1 的 UTF8 会写 BOM，转换为 Python 可读取的无 BOM UTF-8。
    $identityPath = Join-Path (Get-Location) 'config\project_identity.json'
    [IO.File]::WriteAllText($identityPath, (Get-Content $identityPath -Raw), (New-Object Text.UTF8Encoding($false)))
}
```

启动 API 与网页（分别在两个终端）：

```powershell
$python = Join-Path $env:LOCALAPPDATA 'ErYouToolbox\venv\Scripts\python.exe'
& $python scripts\react_api.py
```

```powershell
pnpm.cmd --dir frontend dev
```

浏览器访问 `http://127.0.0.1:5173`，API 监听 `127.0.0.1:8766`。初始化数据库为空，不附带个人数据。也可使用根目录 `start_toolbox.cmd` / `stop_toolbox.cmd` 管理本机服务。自动同步保持关闭，按需在本机配置；不要复制另一台电脑的任务授权、PID 或登录配置。

可选 Streamlit 界面需单独安装 `requirements-ui.txt` 中的依赖：

```powershell
& $python -m pip install -r requirements-ui.txt
.\scripts\run_ui.ps1
```

## 验证

```powershell
$python = Join-Path $env:LOCALAPPDATA 'ErYouToolbox\venv\Scripts\python.exe'
& $python -m unittest discover -s tests
pnpm.cmd --dir frontend test
pnpm.cmd --dir frontend build
```

测试应使用临时数据。生产网络采集、确认入库、任务注册及恢复需单独验收，勿将单元测试通过等同于生产验证。

## 数据、隐私与交接

公开源码不包含数据库、日志、原始响应、备份、凭据、个人项目身份、浏览器配置、缓存或内部验收记录。`.gitignore` 只是后续保护，不能移除已经进入历史的内容。发布候选采用独立源码快照，不携带原工作目录的 `.git` 历史。

`AGENTS.md` 是跨电脑交接说明，须随源码保留。新电脑创建本机 `%LOCALAPPDATA%\ErYouToolbox\venv`，不把虚拟环境放在移动硬盘内。源码副本不等于数据备份；恢复前先暂停所有写入，保留旧数据，使用临时目录验证。

当前未指定开源许可证；公开可见不等同于授权任意使用。发布前由维护者确定许可证及最终发布范围。
