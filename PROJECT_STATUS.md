# ErYouToolbox 项目状态索引

更新日期：2026-11-03。Web 业务功能冻结；当前进入 OB6-E2 Windows 桌面候选验收，未发布正式版。

## OB6-E2 桌面候选（当前）

- 版本 0.5.0-rc1；复用 React 生产构建与现有 Python API、采集/导入/备份逻辑，pywebview + PyInstaller onedir，不启动 Vite。
- EXE 旁 userdata 为独立空库及状态根目录，不迁移开发数据库；首次自动同步关闭，关闭客户端后不运行计划任务。
- 桌面专项临时库17项、完整Python437项、前端15项及生产构建通过。解压EXE独立窗口实测成功；绝区零单页真实预览1请求20候选，未入库，退出后端口释放。结果及未验项见 docs/OB6_E2_DESKTOP_PACKAGE.md。
- GitHub 实查当前仓库为 Public，与此前私有归档记录不同；依据交接规则不推送现有历史，不修改可见性。Git push BLOCK，旧标签不变。
- 本轮未执行生产 apply、迁移、计划任务注册或私人数据迁移。详细交付及人工阻断见桌面打包说明。

## 此前记录（历史，最新结果见下节）

- Git：master / 85558be；已有 v0.4.0-rc1 仍是旧回退点，OB5/OB6 尚未提交。
- 当前审计：Python 412 项、前端15项、profile生命周期6项通过，前端构建及 PS5.1 语法通过。
- 数据库：1097 MOD、1097 用户状态、5 作者关注、1130 事件、14 同步记录，schema3，完整性正常；只读临时恢复通过。
- OB6-S1：备份覆盖修复代码及临时恢复已验证；生产预览与数据库不一致，用户选择保留 BLOCK。未创建生产完整包、未暂存/提交/推送；仍未形成新 Git 基线。历史审计数字保留，最新执行结果见 S1 文档。
- S1最新回归：Python420项、前端15项通过，生产构建通过；生产数据指纹不变。工作区仍保留全部未归档源码。

## 家用电脑跨设备复验（最新，2026-11-02）

- 同一移动盘当前定位 F:；未初始化/克隆仓库，原 master 历史与旧标签保留。归档目标仍为 Private `jennywikino/ErYouToolbox`，本次授权正常提交和推送；不公开、不创建正式发布标签。
- 用户通过现有页面放弃失效预览，确认写入保持暂停；服务随后关闭。生产跨文件一致性已 PASS，SQLite 全表指纹未改变。
- 独立备份：`%USERPROFILE%/ErYouToolboxBackups/eryoutoolbox_20261102_140234_205240_a00e260c`，SQLite + 11 个状态文件；创建内置临时恢复和独立 --verify 均 PASS。C: 为 SATA 磁盘0，F: 为 USB 磁盘3。未删除历史备份，未复制整个 logs。
- 家用本机项目虚拟环境新建成功：Python 3.12.14 / SQLite 3.53.1 / httpx 0.28.1，pip check PASS；未安装全局依赖。
- 本轮全量 Python 420 项（95.049秒）、专项备份22项、前端15项、profile生命周期6项均通过；TypeScript 与 Vite 生产构建 PASS。移动后90个 node_modules 目录连接从旧盘路径重连到当前项目已有包，未升级依赖或改锁文件。
- 原先 BLOCK 及旧测试数字属于历史记录；本轮备份阻断已解除。Git归档使用明确文件白名单，排除运行数据、凭据、依赖、个人身份配置；提交SHA以包含本次文档的提交为准，最终推送及本地/远端核对记录于本轮证据目录与交付。
- 证据：`logs/ob6_s1_home_20261102_215810/`（不入Git）。仍待人工验收：真实计划任务、跨电脑启动/退出、生产小批量入库/图片修复。完成归档后停止，不进入客户端开发。

## 文档入口

- [OB6-S1 恢复覆盖与 Git 状态](docs/OB6_S1_RECOVERY_AND_GIT.md)：当前阻断、恢复状态清单、授权备份目标及继续条件。

- [OB6 稳定性与环境审计](docs/OB6_STABILITY_AUDIT.md)：当前权威审计、P1阻断与真实验收顺序。
- [作者轮转](docs/OB5_A_AUTHOR_ROTATION.md)
- [作者列表与作品页](docs/OB5_B_AUTHORS.md)
- [紧凑同步控制区](docs/OB5_C_UI.md)
- [网页启动检查](docs/OB6_A_STARTUP_SYNC.md)
- [渐进历史扫描](docs/OB6_B_HISTORY_SYNC.md)
- [紧凑列表](docs/OB6_C1_COMPACT_VIEW.md)：布局以最新代码为准，最终最大1250px、宽桌面5列。
- [定向图片回填](docs/OB6_C2_PREVIEW_REPAIR.md)
- [六游戏图片预检](docs/OB6_C4_PREVIEW_PREFLIGHT.md)
- [冒烟缓存生命周期与备份增长](docs/OB6_D1_SMOKE_LIFECYCLE.md)

## 范围冻结

保留 Python + SQLite + React 现有能力。禁止本阶段顺手改 UI、采集器、同步策略或 schema；生产写入只能经用户明确的小样本验收。未完成项必须区分代码测试通过与生产/跨设备未验，不能以单元测试代替真实环境结论。
