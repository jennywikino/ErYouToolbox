# 自己做着玩的（不要宣传和分发）

## 妙妙二玩箱（ErYouToolbox）

<img src="assets/branding/MiaomiaoEryouxiang_icon.png" alt="妙妙二玩箱图标" width="180">

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

**系统要求：** Windows x64、Microsoft Edge WebView2 Runtime（部分电脑需要另行安装）。

**注意：** 关闭客户端后不会后台同步。更新软件时请保留 `userdata/`，不要用新包覆盖个人数据。

### 源码与文档

- 源码运行及开发约定：[AGENTS.md](AGENTS.md)
- 桌面打包说明：[OB6_E2_DESKTOP_PACKAGE.md](docs/OB6_E2_DESKTOP_PACKAGE.md)
- 发布验收：[RELEASE_CHECKLIST.md](docs/RELEASE_CHECKLIST.md)
- 项目开发进度：[PROJECT_STATUS.md](PROJECT_STATUS.md)

### 说明

这是个人学习与使用项目，当前仍在测试，不保证所有环境下完全稳定。作品信息和图片来自第三方公开来源，相关权利属于原作者；本项目不提供内容转载授权。

仓库公开可见，但当前未添加开源许可证，不代表允许任意复制、修改或再分发代码。
