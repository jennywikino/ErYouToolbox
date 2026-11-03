# 自己做着玩的（不要宣传和分发）

## 妙妙二玩箱（ErYouToolbox）

<img src="assets/branding/MiaomiaoEryouxiang_icon.png" alt="妙妙二玩箱图标" width="180">

点击这里[链接](https://github.com/jennywikino/ErYouToolbox/releases/download/v0.5.0-rc3/ErYouToolbox-0.5.0-rc3-win-x64.zip)下载

一款自用的二次元游戏 MOD 信息整理工具，聚合 GameBanana 公开数据，方便发现新作品、浏览图片和追踪作者。**不提供 MOD 文件下载。**

**版本：** `v0.5.0-rc3`（预发布候选）｜**平台：** Windows x64

**技术栈：** Python · SQLite · React / TypeScript · pywebview · PyInstaller

### 主要功能

- **MOD 发现：** 六款游戏信息采集，关注近 90 天发布或更新的作品，支持继续向前搜索历史。
- **浏览与筛选：** 最新 / 热门 MOD、游戏与分类索引、搜索、高清图片画廊。
- **个人管理：** 已阅标记、关注作者、本地状态保存。
- **自动更新：** 首次确认后可每 3 小时自动检查并入库；支持手动刷新。
- **数据维护：** SQLite 本地存储、备份与安全缓存清理。

### Windows 使用

1. 前往 [Releases](https://github.com/jennywikino/ErYouToolbox/releases) 下载 Windows x64 ZIP，并**完整解压**。
2. 双击 `妙妙二玩箱.exe`。无需单独安装 Python、Node.js 或 pnpm。
3. 首次启动会在程序旁创建 `userdata/` 空数据库；联网刷新后获取 MOD 信息。
4. 点击刷新，等待片刻即可

**系统要求：** Windows 10/11 x64、当前受支持的 Microsoft Edge WebView2 Evergreen Runtime，以及 .NET Framework（建议4.8/4.8.1）。包内已含Python解释器DLL与依赖；Node/pnpm不参与运行。.NET 6/8等现代运行时不等于.NET Framework。

**注意：** 关闭客户端后不会后台同步。更新软件时请保留 `userdata/`，不要用新包覆盖个人数据。

**验收状态（2026-11-03）：** 开发机Windows11已验证空库创建及一次GameBanana预览；缺少WebView2的模拟测试2项通过，提示含[官方安装链接](https://developer.microsoft.com/microsoft-edge/webview2/)，不自动安装。环境审计中的退出异常已保留原证据；F6修复通过最终候选ZIP独立解压联网20条预览后关闭、重启和锁/端口释放验收。**干净Windows10/11实机或虚拟机尚未验收，不能宣称全面兼容，Release仍待人工确认。** 详见[环境审计](docs/RELEASE_ENVIRONMENT_AUDIT.md)与[关闭修复报告](docs/OB6_E2_F6_SHUTDOWN_FIX.md)。

### 源码与文档

- 源码运行及开发约定：[AGENTS.md](AGENTS.md)
- 桌面打包说明：[OB6_E2_DESKTOP_PACKAGE.md](docs/OB6_E2_DESKTOP_PACKAGE.md)
- 发布验收：[RELEASE_CHECKLIST.md](docs/RELEASE_CHECKLIST.md)
- 项目开发进度：[PROJECT_STATUS.md](PROJECT_STATUS.md)

### 说明

这是个人学习与使用项目，当前仍在测试，不保证所有环境下完全稳定。作品信息和图片来自第三方公开来源，相关权利属于原作者；本项目不提供内容转载授权。

仓库公开可见，但当前未添加开源许可证，不代表允许任意复制、修改或再分发代码。
