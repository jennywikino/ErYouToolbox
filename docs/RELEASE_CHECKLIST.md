# Windows portable release candidate checklist

Target: 0.5.0-rc3. A local candidate is not a formal release.

## Current rc3 gate

- [x] Rating UI/enrichment retired; legacy filters/preferences ignored; DB compatibility data retained.
- [x] No content_ratings.json startup/build dependency; required games and frontend assets still verified.
- [x] Compact refresh and settings dialog; explicit authorization before default3h apply; saved settings preserved.
- [x] Source-created/updated90-day candidate filtering, bounded requests, incomplete coverage, no old data deletion.
- [x] Earlier history is manual only, committed checkpoints/overlap preserved; no new system task.
- [x] Cache whitelist/preview/hash/path/locks and no business-data deletion; actual isolated WebView2 DiskCache call passed.
- [x] Source date fallback does not create update evidence; unknown metrics not zero; original licenses included by builder.
- [x] Python484/484, frontend16/16 and production build; long Retry-After blocks manual and automatic requests.
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
