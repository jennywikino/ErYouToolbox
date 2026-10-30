# v0.4.0-rc1 本地基线提交准备

当前分支master，HEAD为b85a809（V0.1）；现有正式暂存区为空。本轮只生成候选清单和独立索引预览，未执行commit、tag、push或remote配置。

## 建议提交说明

`Prepare v0.4.0-rc1 - local browsing and reliable GameBanana sync`

范围：React作品浏览与高清画廊、已阅和作者关注、GameBanana同步预览/确认、六游戏有界增量恢复、默认关闭的自动检查/入库、移动盘启动器、任务管理与备份工具。包含测试、必要配置和pnpm-lock.yaml；保留旧Streamlit界面，不改变业务实现。

本地候选标签建议v0.4.0-rc1，尚未创建。它是当前源码基线，不表示真实重启、实际F盘切换及所有计划触发场景均已通过。

## 验证

核心Python回归156项通过；前端测试10项及生产构建通过。项目虚拟环境pip check无冲突，前端依赖清单与构建可用。requirements.txt保留httpx，requirements-ui.txt保留独立Streamlit依赖，pnpm-lock.yaml纳入候选。没有安装或更新依赖。

Python依赖未全部固定版本，跨电脑重建不是严格逐字节复现；Windows任务计划/PowerShell和本机虚拟环境仍需按现有文档配置。当前frontend/package.json的版本号0.3.0保留不变，候选Git标签是工程基线名称。

## 安全边界

检查范围为已追踪文件和本次可提交候选文件。常见令牌、私钥及硬编码凭据模式没有命中；不等同于所有秘密格式的绝对保证。没有大于1MiB的候选文件。.gitignore已覆盖SQLite及sidecar、data、logs、备份、node_modules、dist、venv、缓存、环境变量及常见私人配置，无需修改。

运行时数据库、检查点、自动任务本机设置及凭据不属于源码基线。回退源码不能代替恢复949条作品的独立数据备份。数据库schema兼容性应按迁移文档单独核对，不能因为Git回退而覆盖生产数据库。

完整文件清单、SHA-256、独立索引差异、排除目录清单及安全检查保存在本机忽略目录logs/rc1_review。独立索引不写真实.git/index；审批后应先复核文件散列及差异，再按明确清单暂存，不使用git add .或git add -A。

## 暂存预览结果与待确认事项

共100个候选文件。真实暂存区保持为空；预览使用logs/rc1_review/preview.index。相对V0.1的变更统计见change-stat.txt，完整差异见preview.txt，明确排除清单见excluded-files.txt，文件散列见audit.json。

git diff --check退出码为2：7处文件末尾多余空行，分别位于App.tsx、AutoSyncSettings.tsx、SyncCheck.tsx、react_api.py、importer.py、test_auto_sync.py、ui_navigation_smoke.cjs。仅格式警告，仍保留原文件，不将此检查宣称为通过。没有发现凭据模式命中或超大文件。

目前建议按清单保存源码，是否顺便处理这7处格式警告由用户决定。未经确认不执行正式暂存、commit或tag。源数据库未访问，全部Python测试使用项目解释器及隔离库。

## 待暂存文件

- .gitignore
- .streamlit/config.toml
- AGENTS.md
- config/content_ratings.json
- config/project_identity.json
- docs/AUTHOR_REMOTE_CHECKS.md
- docs/AUTHOR_SUBSCRIPTIONS.md
- docs/DISCOVERY_V04_PLAN.md
- docs/ENGINEERING_DAY1.md
- docs/OB2_A_NAVIGATION.md
- docs/OB2_B_IMAGE_PERFORMANCE.md
- docs/OB3_A_WEB_SYNC.md
- docs/OB3_B_SIX_GAME_SYNC.md
- docs/OB4_A_INCREMENTAL_SYNC.md
- docs/OB4_B_AUTO_SYNC.md
- docs/OB4_C_ACCEPTANCE.md
- docs/POPULAR_MVP.md
- docs/READ_NAVIGATION_IMAGE_FIX.md
- docs/READ_STATES.md
- docs/UI_STYLE_GUIDE.md
- docs/V0_4_0_RC1_BASELINE.md
- docs/VERSION_AND_BACKUP.md
- frontend/.gitignore
- frontend/README.md
- frontend/index.html
- frontend/package.json
- frontend/pnpm-lock.yaml
- frontend/src/App.tsx
- frontend/src/AuthorUpdateCheck.tsx
- frontend/src/AutoSyncSettings.tsx
- frontend/src/FollowAuthor.tsx
- frontend/src/Icons.tsx
- frontend/src/ModDetail.tsx
- frontend/src/PopularPanel.tsx
- frontend/src/PreviewCard.tsx
- frontend/src/ReadStateControl.tsx
- frontend/src/SyncCheck.tsx
- frontend/src/main.tsx
- frontend/src/policy.test.ts
- frontend/src/policy.ts
- frontend/src/styles.css
- frontend/src/types.ts
- frontend/tsconfig.json
- frontend/vite.config.ts
- requirements-ui.txt
- scripts/audit_discovery.py
- scripts/auto_sync.py
- scripts/auto_sync_bootstrap.ps1
- scripts/backfill_content_ratings.py
- scripts/backfill_previews.py
- scripts/backup_project.py
- scripts/check_author_updates.py
- scripts/import_content_ratings.py
- scripts/manage_auto_sync.ps1
- scripts/manage_auto_sync.py
- scripts/migrate_read_states.py
- scripts/migrate_subscriptions.py
- scripts/probe_content_ratings.py
- scripts/probe_popular.py
- scripts/probe_preview_quality.py
- scripts/probe_recent_popular.py
- scripts/react_api.py
- scripts/run_rating_backfill.py
- scripts/run_ui.ps1
- scripts/toolbox_launcher.ps1
- scripts/ui_app.py
- scripts/verify_read_state_e2e.py
- scripts/web_sync.py
- src/eryoutoolbox/author_updates.py
- src/eryoutoolbox/content_ratings.py
- src/eryoutoolbox/database.py
- src/eryoutoolbox/gamebanana.py
- src/eryoutoolbox/importer.py
- src/eryoutoolbox/models.py
- src/eryoutoolbox/popular.py
- src/eryoutoolbox/read_states.py
- src/eryoutoolbox/subscriptions.py
- src/eryoutoolbox/ui_queries.py
- start_toolbox.cmd
- stop_toolbox.cmd
- tests/test_author_updates.py
- tests/test_auto_sync.py
- tests/test_backfill_previews.py
- tests/test_backup_project.py
- tests/test_collector.py
- tests/test_content_ratings.py
- tests/test_database.py
- tests/test_importer.py
- tests/test_popular.py
- tests/test_preview_quality_probe.py
- tests/test_rating_backfill.py
- tests/test_rating_scheduler.py
- tests/test_react_api.py
- tests/test_read_states.py
- tests/test_recent_popular.py
- tests/test_subscriptions.py
- tests/test_ui_queries.py
- tests/test_web_sync.py
- tests/test_web_sync_recovery.py
- tests/ui_navigation_smoke.cjs
