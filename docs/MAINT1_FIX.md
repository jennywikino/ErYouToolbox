## MAINT-1-FIX（恢复分支，尚未发布）

2026-11-05：恢复检查点 a7e0e353c3a514ea75f19f179d9ff1de73dfd70c，分支 recovery/maint1-20261105。之后修复保留在工作区，未推送、未合并、未发布。

JASM仅对名称首尾执行strip；空项、内部控制字符、超长、冲突及无效格式仍拒绝，五游戏全部校验完成才预览，确认保存前备份与原子替换。外部/导入层保留有效的低优先级检索写法（Hutao、Chen Qianyu等），高层排在前；个人修正仍可完整替换/删除。顺序为个人修正 > 已验证导入 > 外部同步 > 内置。原始交换JSON仍format=1，持久状态format=2，兼容读取旧format=1而不静默改写。

JASM来源为 Moonholder/JASM-GameAssets；只请求manifest及五游戏Languages/zh-cn/characters.json，异环保留本地索引，不取图片、不打包第三方资源全集。版本号来自manifest，源16位hash不冒充SHA256；实际HTTP可用性及桌面点击仍待人工验收。

历史补全在更多设置可选择off/check/apply并确认保存；apply有明确确认。授权使用既有同步模式，也影响遗留CLI/已注册任务；不修改系统任务，当前启动一次/手动刷新规则不变。off/check不自动升级权限，历史引擎仍在提交前复核apply。

独立备份新增白名单data/character_library/library.json；SQLite Online Backup、JSON格式验证、SHA256、完整性校验、状态变化检测、临时恢复预演均复用原实现。只备份有效当前状态，不收集名称库旧备份全集、缓存或日志。所有写入需暂停后备份；不恢复覆盖生产库。

此恢复分支功能尚未包含在GitHub已发布rc3下载中；README保留原下载URL。打包脚本使用启动一次说明，下一次获准打包还需独立解压验收。

首轮：D盘关联Python121项通过，前端20项通过，TypeScript与生产构建通过。全部Python写入测试使用临时库/隔离目录，无生产userdata操作；未运行全量爬取、全量历史补全或打包。
新增回归 tests/test_maint1_fix.py 覆盖四个真实空格样本、严格拒绝、别名保留和个人覆盖、整包备份恢复预演、HTTP历史授权及off拒绝写入。原JASM测试按合并检索键语义调整，未删除失败用例。
待人工：JASM实际联网同步、历史授权UI、独立客户端与真实资料。恢复提交是修复前回退点；修复未二次提交。
