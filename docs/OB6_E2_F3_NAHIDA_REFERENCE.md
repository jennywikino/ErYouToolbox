# OB6-E2-F3 — 0.5.0-rc2 candidate

## F3-A: audit before implementation (2026-11-03)

Local master starts at d456b35; the working tree contains F2 rating fixes, which must be preserved. No checkout, reset or historical tag changes. Production data remains read-only.

Reference: https://github.com/myparsleycat/nahida-desktop/tree/main/frontend/src/routes/gamebanana (GPL-3.0). Directed reading only: index.tsx, toolbar, category-sidebar, game-home-panel, category-panel, mod-detail-panel, preview-card and mod-files-sidebar. Studied game/category/detail breadcrumbs, contextual category search, independent scrolling, cover/title/author hierarchy and separation of gallery from source statistics/files. No components, CSS, icons, assets or GPL source copied into this project. No Go/Wails/router/store migration.

Existing equivalents: App.tsx owns hash navigation and anchor restoration; PreviewCard and ModDetail own lazy thumbnails/current original; SyncCheck and AutoSyncSettings retain all manual operations. SQLite category/subcategory text supports only a local two-level index, not an official character taxonomy. Counts must be local, never GameBanana-wide.

Gaps: startup-only automatic checks; no explicit first-use desktop setup; author lists never fill missing avatar caches; page-local category badges instead of dataset navigation; remote popularity can lose stronger local rating evidence; source metrics/file information not surfaced in local detail. F2 already provides bounded rating enrichment, evidence preservation and conservative preview controls: reuse rather than rewrite.

Planned changes: existing automatic settings/startup helpers and tests; bounded author cache refresh; read-only category and saved-detail queries/API; existing App/cards/detail/sidebar plus small original components/styles; version/build/documentation. No schema change, production apply, downloader, installer, login, cloud, comment publication or new background task.

## Reference-to-implementation mapping

| Studied Nahida file | Interaction studied | Independent ErYouToolbox implementation |
|---|---|---|
| index.tsx | game/category/detail stages | existing App hash navigation + saved anchor state |
| gamebanana-toolbar.tsx | contextual path and return | App browse-path, existing game selector/return |
| category-sidebar.tsx | searchable, scrollable category context | CategorySidebar + parameterized local categories query |
| game-home-panel.tsx | feed hierarchy and clear state | existing latest/subscriptions/popular with skeleton/empty distinction |
| category-panel.tsx | category listing/pagination | existing server pagination with category/subcategory predicates |
| preview-card.tsx | cover/title/author hierarchy | existing PreviewCard with compact date/evidence summary |
| mod-detail-panel.tsx | current gallery, description/source metadata | existing ModDetail + safe text, DetailAuthor, source summary |
| mod-files-sidebar.tsx | auxiliary stats/files separate from gallery | read-only statistics/file metadata; no download controls |

The existing five-column/max1250px/25-item compact grid remains. Narrow windows reduce columns. No official category tree or character identity is inferred from title text. Local category counts include all collected records of the selected game, not the current search subset or source-wide totals.

## F3-B: automation, ratings and avatars

First-use desktop setup is visible only when no saved automatic settings exist. The user explicitly saves off/check/apply, three hours and optional daily history. Mode starts off until that action; existing settings are never rewritten. A minute timer only asks the existing startup endpoint after the reported due time; server mode, process lock, OS shared lock, pending preview, cooldown and final write guard remain authoritative. Off or not-due means no source request. Client closure ends future scheduling; an in-progress bounded worker still follows existing close protection. Automatic apply retains existing only-new/reliable-source-update selection, importer backups and rollback. No new Windows task/service.

Development library: 1097 total / 110 explicit / 612 source Unrated / 375 UNKNOWN. Actual user-specified F1 portable library: 943 / 0 / 450 / 493. Full IDs and per-game/code counts are local audit evidence, not bundled. No production writes: these totals intentionally do not improve from a dry-run.

Found and fixed remote ranking evidence loss: previous code passed only `_aContentRatings`; boolean false/true flags were discarded. Now the full source rating fields are interpreted. Known local detail labels also survive an incomplete remote list record. Unknown and source Unrated stay distinct; neither is converted to SFW. Existing F2 enrichment, older-evidence protection, OR filtering and independent conservative image preferences are reused.

Real source budget used: **13 ProfilePage requests**, 2 Index pages (5 ranking rows and 10 latest-preview rows), 2 Member metadata requests, serial. Twelve rating samples yielded 6 explicit multi-label records and 6 HTTP200 records with only visibility and no sufficient rating evidence. The latter remain UNKNOWN. The additional detail confirmed `_nLikeCount`, `_nViewCount`, `_nDownloadCount`, `_nPostCount`, `_aFiles`, `_sText`, `_aCategory` and `_aSuperCategory`; `_sModelName` is absent on that ProfilePage, so the exact Mod endpoint, `_idRow`, canonical `_sProfileUrl` and configured `_aGame._idRow` establish read-only detail identity. No further details requested. No images or MOD files downloaded by diagnostic scripts.

Two followed authors returned validated official avatar URLs. Existing seven-day Member cache is reused; list expansion fills at most one missing entry, serialized and throttled, with global 403/429 cooldown. Detail author metadata shares the cache, failures keep initials, and follow relationships are untouched. Remaining uncached list authors fill on later opens; this is deliberately not an all-author scan.

## F3-C: browsing and details

Local two-level navigation filters before SQL LIMIT/OFFSET; games reset category context; saved browser history includes category/subcategory and preserves old history compatibility. Source details of non-local ranking records use an explicit cached read-only request, never auto-import/read-state. Local cards/details continue normal user state. Detail values are shown only if recorded/returned; unknown is not zero. Source HTML is parsed to plain text and escaped by React. File URLs are not exposed as download actions. Comments are count + original-site link; comment crawling/publication is deferred.

## F3-D: verification and artifact gate

- Full Python: **468/468 passed**, 193.871 seconds (`logs/content_ratings/F3-python-full.txt`). Frontend **16/16**, TypeScript/Vite production build passed. New F3 tests cover due/consent persistence, local category counts/filtering/read-only behavior, stronger remote labels, bounded avatars, detail identity/cache/cooldown/invalid JSON/timeout/safe text/unknown metrics.
- Preflight onedir build passed. ZIP extracted outside source into a fresh Chinese/space TEMP path; cwd and PATH exclude development Python/Node. Actual native WebView clicks verified first-use choice of off, persisted three-hour setting, local detail, read/follow, list return/browser forward, duplicate process lock, resource errors, read-only userdata ACL failure, move/restart and abnormal-exit recovery. Empty rating batch uses zero network requests and no committed checkpoint. Both emulated viewports 1920×1080 and 1366×768 have no horizontal overflow. Screenshots retained locally. Fixtures only, not production records or network performance claims.
- Final artifact must be rebuilt after the reviewed source commit and tested again. Exact commit, artifact checksum and push outcome are recorded by the build report/adjacent checksum and final handoff, not guessed in advance. No automatic tag or Release.

## Public safety and remaining acceptance

The existing tracked `config/project_identity.json` is a non-secret project UUID/name already in old history, not an API credential; it is unchanged and excluded from all portable builds. No new identity, production data, logs, caches, avatar media or checkpoints are staged. Do not rewrite already published history.

Still manual: clean Windows without developer tools, actual E/F hardware move, long-running three-hour check/apply and real user small-batch rating save. No production batch apply occurred. Missing source evidence can remain UNKNOWN indefinitely. Source ranking filters cover the fetched page; not a source-wide filtered ranking. The project owner must review distribution/license conditions before Release; see prerelease draft. These limits are not claimed passed by mock/unit tests.

## Windows acceptance

1. Retain the old client and back up its complete idle userdata. Fully extract rc2 to a new writable directory. Do not overwrite personal data with the package's empty initialization.
2. On a fresh directory choose off first; verify six games, empty state, category scope and 25-item compact default. Restart and confirm the saved mode persists without a new prompt.
3. For existing userdata, after an independently verified backup and all writers closed, move/copy the complete userdata intentionally; never copy a live main DB alone. No migration is performed by this build.
4. Browse game/category/subcategory, search/read/rating filters, page three, detail/back/forward. Inspect current original versus thumbnail strip. Missing images must differ from hidden/loading/failed.
5. Use rating preview first; only after human approval save a small batch. UNKNOWN/Unrated must not become SAFE and manual state/images must remain intact.
6. Explicitly enable automatic apply only after the small-batch acceptance. Observe actual inserted/update counts, backup and due interval; test off and pending-preview protection. Closed client is not a background service.
7. Compare ZIP SHA-256 with its adjacent checksum and BUILD_INFO clean source SHA. Do not publish the preflight dirty artifact. Release remains a separate user decision.

Latest preview used the existing WebSync on an Online Backup temporary copy: 1 request, 10 fetched/unique/classified, 7 new candidates, 3 unchanged, 0 source updates, 0 production writes. Normalization retained seven false/Unrated flags and three true-without-labels/UNKNOWN records. Production DB SHA-256 still matches the before audit; candidate counts are not actual imports.
