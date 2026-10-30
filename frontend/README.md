# ErYouToolbox V0.3 React 原型

独立 React + TypeScript + Vite + Tailwind CSS 原型。仅通过本机 Python API 读取现有 SQLite，旧 Streamlit 可同时运行。

## 启动

需要 Node.js 22.12+（推荐 Node 24）以及 npm 或 pnpm。Python 使用本机已有虚拟环境，无需新增 Python 依赖。

在项目根目录打开第一个 PowerShell：

~~~powershell
$python = Join-Path $env:LOCALAPPDATA 'ErYouToolbox\venv\Scripts\python.exe'
& $python scripts\react_api.py
~~~

第二个 PowerShell：

~~~powershell
Set-Location frontend
pnpm install --frozen-lockfile
pnpm dev
~~~

浏览器打开 http://127.0.0.1:5173 。也可使用 npm install 与 npm run dev；首次安装选定一种包管理器即可。

两个服务都只监听 127.0.0.1。Vite 将 /api 代理到本机 8766 端口。默认只看已有图片数据的记录，可切换“全部作品”；分页每页 18 条，API 上限 20 条。

UNKNOWN 预览默认隐藏，可主动在页面右侧开启，仅对当前页面会话生效。ADULT 等其他分级保持隐藏。列表使用缩略图，详情只加载当前原图和缩略图序列。图片直接由浏览器展示来源 URL，不下载到本地。

## 验证

~~~powershell
pnpm test
pnpm build
~~~

在项目根目录：

~~~powershell
& $python -m unittest discover -s tests -p test_react_api.py
~~~

浏览页选择游戏、搜索 ID/标题/作者，点击作品卡片进入独立详情视图。返回列表保留游戏、搜索及页码。分类区只列出当前页实际保存的分类，不代表来源完整分类树或作品总量统计。

参考 [Nahida Desktop 的 GameBanana 浏览目录](https://github.com/myparsleycat/nahida-desktop/tree/main/frontend/src/routes/gamebanana) 的界面组织思想。组件、样式和线性图标独立编写，未复制该项目代码、品牌或图片资产。

原型暂不提供分类筛选、用户状态写入、评论、下载或网络采集。
