## FINAL-1 · 2026-11-05

候选版本1.0.0-rc1，干净Windows未验证，不发布正式1.0.0。迁移/相关回归及JASM实网验证通过；独立ZIP与远端状态以最终交付报告为准，未完成项不得视为通过。详见docs/FINAL_HANDOFF.md。

## MAINT-1-FIX（恢复分支，尚未发布）

2026-11-05：恢复检查点 a7e0e353c3a514ea75f19f179d9ff1de73dfd70c，分支 recovery/maint1-20261105。之后修复保留在工作区，未推送、未合并、未发布。

JASM仅对名称首尾执行strip；空项、内部控制字符、超长、冲突及无效格式仍拒绝，五游戏全部校验完成才预览，确认保存前备份与原子替换。外部/导入层保留有效的低优先级检索写法（Hutao、Chen Qianyu等），高层排在前；个人修正仍可完整替换/删除。顺序为个人修正 > 已验证导入 > 外部同步 > 内置。原始交换JSON仍format=1，持久状态format=2，兼容读取旧format=1而不静默改写。

JASM来源为 Moonholder/JASM-GameAssets；只请求manifest及五游戏Languages/zh-cn/characters.json，异环保留本地索引，不取图片、不打包第三方资源全集。版本号来自manifest，源16位hash不冒充SHA256；实际HTTP可用性及桌面点击仍待人工验收。

历史补全在更多设置可选择off/check/apply并确认保存；apply有明确确认。授权使用既有同步模式，也影响遗留CLI/已注册任务；不修改系统任务，当前启动一次/手动刷新规则不变。off/check不自动升级权限，历史引擎仍在提交前复核apply。

独立备份新增白名单data/character_library/library.json；SQLite Online Backup、JSON格式验证、SHA256、完整性校验、状态变化检测、临时恢复预演均复用原实现。只备份有效当前状态，不收集名称库旧备份全集、缓存或日志。所有写入需暂停后备份；不恢复覆盖生产库。

此恢复分支功能尚未包含在GitHub已发布rc3下载中；README保留原下载URL。打包脚本使用启动一次说明，下一次获准打包还需独立解压验收。

# Windows portable release candidate checklist

Target: 0.5.0-rc3. A local candidate is not a formal release.

## CLOSE-2 最终本地候选（2026-11-04，PARTIAL）

- [x] 第一轮修复显式收集角色JSON并纳入资源散列清单，资源9项/角色7项针对性测试通过；未重复518项完整回归。
- [x] 全新Windows x64 onedir ZIP，基线7d5cacb、dirty=true；包内BUILD_INFO与81文件SOURCE_INPUTS，准确路径/大小/散列见FINAL_HANDOFF.md。
- [x] 指定最终ZIP源码外解压实际运行；英文-only模拟记录的中文/英文/ID查询证明冻结JSON生效，六游戏API6项，已阅关注重启、SQLite及退出端口通过。
- [x] 包内隐私/凭据/资料包审计通过；reference原件只留本地并忽略；未暂存提交、推送、建tag或Release。
- [ ] GUI驱动超时，六游戏点击、正常MOD图/画廊及详情返回位置待人工；实际窗口截图只证明渲染状态。
- [ ] 干净Windows10/11、物理E/F跨设备及人工验收未完成；dirty源码未归档，不可宣布可复现正式发布。
- 功能冻结与最终说明：FINAL_HANDOFF.md、FINAL_RELEASE_NOTES.md。

## CLOSE-1 功能冻结（2026-11-04）

- [x] ModPage.search_info按后端结构补为可选字段，首次修复构建通过，无any/ts-ignore或绕过tsc。
- [x] 本轮前端17项及TypeScript/Vite构建通过，品牌开发资源实际HTTP200有效PNG。
- [x] 相关Python53项及临时库跨进程已阅/关注持久化通过；正式库仅只读查询且指纹不变。
- [ ] 六游戏导航点击、图片及品牌失败占位、详情返回/滚动实际界面验收：隔离浏览器导航超时，证据保留，不能标为通过。
- [ ] 下次打包显式收集角色JSON；本轮不打包、不新建Release。
- [x] 本轮完整回归只运行一次：Python518/518、0失败、0跳过，993.584秒，记录CLOSE1-python-full.txt。
- 当前可以整理CLOSE-2验收资料，但正式发布验收前须补齐上述实际界面确认，不能宣称已发布就绪。
- 词库维持269键，第三方快照非官方完整或统一授权；后3游戏覆盖有限。未补全的真实界面/干净系统验收继续保留。

## F6 退出修复门槛

- [x] 诊断：部分POST持有lifecycle_lock、GUI关闭同步等待锁的控制实验堆栈；源码/冻结60秒普通预览也有通过样本，不虚称旧事故唯一原因已确定。
- [x] GUI非阻塞取消/排空协调、HTTP读取超时、非daemon HTTP请求排空、事务完成后关闭、无os._exit及无生产数据清理。
- [x] 12项退出专用、35项历史回归、16项前端与构建；最终Python504/504通过，0失败。
- [x] 预验收包外部解压真实20条来源预览后关闭、重启、三轮启闭、异常恢复、端口重绑/文件锁重取/SQLite完整通过。
- [x] 最终干净提交ZIP已重复通过独立10轮关闭矩阵与完整桌面隔离回归；记录F6-final-native.json/F6-final-isolation.json。构建源码ce6976047a96dd0541b503ff092685f82254096d；ZIP散列见F6报告。
- [ ] 无开发依赖的干净Windows10/11实机/虚拟机验收仍缺；不自动发布Release或创建tag。

## 2026-11-03 Release 依赖环境门槛

- [x] 最终 F5 delivery-final ZIP：Python315 DLL、PYZ模块、pywebview/pythonnet/clr_loader、HTTP/TLS/SQLite依赖及React静态文件已审计。
- [x] 外部系统依赖明确：WebView2 Evergreen Runtime、.NET Framework；非 Node/pnpm 或现代.NET SDK。
- [x] 缺少 WebView2 的模拟测试2项通过，安装URL明确，错误在创建用户库之前处理；未卸载本机Runtime。
- [x] 开发机 Windows11 x64：实际 EXE 首次空库0条，GameBanana原神1页/1次请求/20条预览，未确认入库，库仍0条。
- [ ] 干净 Windows10 x64（建议22H2）：未装Python/Node/pnpm，完整ZIP首次启动、网络预览、重启及退出实测。
- [ ] 干净 Windows11 x64：同上；记录Windows版本、.NET Release、WebView2版本、ZIP散列与截图。
- [ ] 干净快照缺少WebView2时验证真实原生安装提示；完成后从官方安装器安装并重试，不修改开发机Runtime。
- [ ] 环境兼容结论仍BLOCK，不能把开发机清空PATH的测试等同干净系统。结果见 RELEASE_ENVIRONMENT_AUDIT.md。
- [x] 原环境审计中的联网后退出超时证据保留；F6新增关闭协调并通过原预览场景预验收，不以旧F5结果代替新测试。最终包验收另列。

## F5 中文品牌

- [x] 用户确认 ICO/PNG 可公开分发；不生成替代图标。
- [x] 妙妙二玩箱：窗口、React、EXE 产品名/描述、Release 草稿显示名称。
- [x] 中文 EXE 文件名；工程身份与 userdata 路径不变。
- [x] 构建比较实际 PE 图标与原 ICO，资源完整性涵盖 ICO/PNG。
- [x] 相关 Python28项、前端16项及生产构建通过。
- [ ] 用户在目标电脑检查 Explorer、任务栏、Alt+Tab、快捷方式图标与 Windows 图标缓存。
- [ ] 新候选解压验收后，再另行授权创建标签及 Pre-release。

## Current rc3 gate

- [x] Rating UI/enrichment retired; legacy filters/preferences ignored; DB compatibility data retained.
- [x] No content_ratings.json startup/build dependency; required games and frontend assets still verified.
- [x] Compact refresh and settings dialog; explicit authorization before default3h apply; saved settings preserved.
- [x] Source-created/updated90-day candidate filtering, bounded requests, incomplete coverage, no old data deletion.
- [x] Earlier history is manual only, committed checkpoints/overlap preserved; no new system task.
- [x] Cache whitelist/preview/hash/path/locks and no business-data deletion; actual isolated WebView2 DiskCache call passed.
- [x] Source date fallback does not create update evidence; unknown metrics not zero; original licenses included by builder.
- [x] Python485/485, frontend16/16 and production build; long Retry-After blocks manual and automatic requests.
- [ ] Final clean-source artifact and external extraction: record exact results in F4 handoff and BUILD_INFO.
- [ ] User clean Windows, real E/F migration, three-hour automation, backed-up production small apply/history acceptance.
- [ ] Owner license/distribution review and explicit Release/tag approval.

## Historical rc2/rc1 checks (superseded where rc3 removes rating functionality)

- [x] F3 directed Nahida study; independent implementation, no GPL code/assets copied.
- [x] F3 first-use explicit consent, saved preferences preserved, periodic due hints while open; no new background service/task.
- [x] F3 source Unrated flag and stronger local labels retained in remote ranking; UNKNOWN never inferred SFW.
- [x] F3 local two-level categories and local counts; remote details do not create local read-state.
- [ ] F3 full regression, final clean-commit build, external extraction and archive safety checks: see F3 report for actual results.
- [ ] User manually accepts small rating save, real long-running automatic apply and three-hour scheduling before Pre-release.
- [ ] Clean Windows/WebView2 and actual E/F device acceptance; review project/dependency licenses before binary publication.

- [x] F2: separate development/portable rating audits; at most12 real requests, missing detail fields remain UNKNOWN.
- [x] F2: bounded client rating preview/explicit-save entry; backup/rollback, shared lock and retry queue covered by isolated tests.
- [x] F2: sensitive and UNKNOWN previews require separate explicit preferences; source tags and manual review remain independent.
- [ ] F2: user accepts a small production save batch and checks actual PN/NU/SC filters after restart; no production apply was run by Codex.
- [ ] F2: archive the uncommitted source and rebuild from a clean commit before any Release; do not publish the dirty local test package as final.

- [x] User confirmed Public source publication for OB6-E2-F1. Recheck sensitive files before every push; binary Release and dependency-license acceptance remain separately pending.
- [x] F1: distinguish bundle resources, executable directory, development root and userdata. Require both config JSON files and the complete production asset manifest.
- [x] F1: build/startup resource validation fails on missing config/index/JS or checksum mismatch; no empty-rating fallback.
- [x] F1: actual extracted EXE tested outside source in a Chinese/space path with a different cwd; native detail/read/follow, moved-directory persistence, duplicate lock and abnormal-exit recovery passed. Evidence in F1-isolation4.json; repeat against the final commit artifact.
- [ ] Record exact source commit and require BUILD_INFO working_tree_dirty=false for a releasable artifact.
- [ ] Pass Python regressions, frontend tests and production build; retain failed-test evidence.
- [ ] Build on Windows x64 in the isolated packaging environment; preserve dependency versions.
- [ ] Inspect ZIP entries: no personal DB, userdata, logs, credentials, node_modules or Git history.
- [ ] Extract ZIP to a fresh writable directory and double-click EXE with no Vite running.
- [ ] Validate on a clean Windows machine without Python/Node; check missing WebView2 guidance.
- [ ] Validate six game filters, local details, current full-resolution image, thumbnails and external links.
- [ ] Verify read/follow state after closing and reopening; use temporary library only.
- [ ] Check manual sync preview then explicit confirmation; verify backup, idempotency and rollback.
- [ ] Verify default automatic mode off; no production auto-apply during acceptance.
- [ ] Close idle/active/error scenarios, verify owned service termination and duplicate-instance protection.
- [ ] Move portable directory between drive letters; verify same userdata, no silent fallback DB.
- [ ] Replace program files while preserving userdata and verify rollback from retained old version.
- [ ] Explain portable background scheduling is not supported; do not register Web-version task against EXE.
- [ ] User explicitly accepts candidate; only then create a new tag from verified source.
- [ ] Recompute ZIP SHA-256, record source SHA, then separately authorize Release upload.

Never move existing tags, force-push, copy a running SQLite main file as a backup, or upload an unverified EXE.
# UX-SYNC-1B 补充（2026-11-04）

当前源码采用“本地服务启动一次同步 + 刷新MOD手动入库”，取代三小时周期与独立手动导入按钮；高级查询保留来源链接/ID预览确认。新执行关联Python65、前端19、TS/Vite及差异检查通过。未运行全量、真实GUI、生产同步或重新打包；旧CLOSE-2包仍旧逻辑。不得将旧包人工验收当作本轮通过，尚须验证新运行环境首次入库、游戏/页面切换不重触发、高级查询及列表返回。详见[UX-SYNC-1当前说明](UX_SYNC_1.md)。未操作Git提交/标签/发布。
