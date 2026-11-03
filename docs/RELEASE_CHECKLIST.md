# Windows portable release candidate checklist

Target: 0.5.0-rc3. A local candidate is not a formal release.

## F6 退出修复门槛

- [x] 诊断：部分POST持有lifecycle_lock、GUI关闭同步等待锁的控制实验堆栈；源码/冻结60秒普通预览也有通过样本，不虚称旧事故唯一原因已确定。
- [x] GUI非阻塞取消/排空协调、HTTP读取超时、非daemon HTTP请求排空、事务完成后关闭、无os._exit及无生产数据清理。
- [x] 12项退出专用、35项历史回归、16项前端与构建；最终Python504/504通过，0失败。
- [x] 预验收包外部解压真实20条来源预览后关闭、重启、三轮启闭、异常恢复、端口重绑/文件锁重取/SQLite完整通过。
- 最终交付必须使用干净提交ZIP并重复独立实测；准确结果存于F6-final-native.json、F6-final-isolation.json及交付清单，发布前核对BUILD_INFO源码SHA与相邻ZIP散列，不能用预构建包替代。
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
