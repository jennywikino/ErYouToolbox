# Windows portable release candidate checklist

Target: 0.5.0-rc1. A local candidate is not a formal release.

- [ ] Confirm repository visibility, publication permissions and dependency licenses. Current public origin blocks pushing the original private history under project handoff rules.
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
