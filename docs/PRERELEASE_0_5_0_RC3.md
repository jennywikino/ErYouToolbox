# ErYouToolbox 0.5.0-rc3 — Windows portable candidate

Pre-release draft. Publication and tag creation require separate user acceptance.

ErYouToolbox discovers and organizes public GameBanana MOD metadata for six games. It does not download/install MOD files, provide accounts, or synchronize personal data to the cloud.

## Run and update

Fully extract `ErYouToolbox-0.5.0-rc3-win-x64.zip` into a writable directory and open `ErYouToolbox.exe`. Keep `_internal` beside the EXE. Windows x64 and Microsoft Edge WebView2 Evergreen Runtime are required. Client runtime does not require Python, Node, pnpm or Vite.

First run creates an empty SQLite library under EXE-adjacent `userdata`. Existing personal libraries are never embedded, automatically moved or overwritten. Close all writers and verify an independent backup before intentionally moving complete userdata or replacing program files. Do not copy a live SQLite main file alone. Keep an older program directory and its matching verified data backup for rollback; no schema migration is introduced here.

## rc3 behavior

- Content-age rating UI, filters, enrichment endpoint and image masking are retired by product decision. All valid source images may display. Old rating fields and original evidence remain in the database for compatibility; old browser preferences no longer hide records or media.
- Refresh prioritizes source release or independent source update within 90 days. `modified_at` and local first discovery are not evidence of a version update. Requests/pages are bounded, six games are serial, coverage remains incomplete. Older stored MODs are never deleted by the window.
- First-use automatic apply requires explicit consent. Recommended interval is three hours; saved choices are preserved. Off remains manual; check previews only; apply uses existing backups, transactions, locks and evidence rules. No new Windows task is registered. A closed client does not run scheduled work.
- Earlier history is expanded only by **Continue searching earlier**, with at most two pages per game including overlap verification. Confirmed database commits advance history; previews do not. Source drift, throttling and invalid boundaries stop progression.
- Missing independent update date displays the source publication date with an explicit fallback note. Source data is never fabricated. The read-only detail refresh can retrieve current metrics/time information; it does not modify stored MODs or events.
- Cache management requires preview and confirmation. It only clears memory rankings/details, validated expired author URL cache files, and official WebView2 DiskCache. Databases, read/follow state, checkpoints, settings, locks and backups are protected. Runtime logs/test evidence are measured but not automatically deleted.

## Limits and attribution

Local counts are not GameBanana-wide counts. New installs start empty: use Refresh and consent or the explicit preview confirmation. Rankings are cumulative/source sample rankings, not fabricated recent growth. Legacy records may lack dates or metrics until an explicit source refresh; missing values are not zero.

Images/media and MOD content belong to their source authors. The project is not affiliated with GameBanana or Nahida Desktop. Prior Nahida study concerned information architecture only; no GPL components, CSS, icons or assets were copied. No comments publishing/downloader/installer/login/automatic updater is included.

Dependency notices/installed versions must accompany distribution: React/Vite/Tailwind (MIT), TypeScript (Apache-2.0), Python (PSF), pywebview/httpx (BSD-3-Clause), pythonnet/clr_loader (MIT), PyInstaller (GPLv2+ with its bootloader exception). WebView2 is a separate Microsoft runtime. This draft does not choose a new license for the project owner's source.

## Before public release

Test the complete ZIP on a clean Windows machine, actual E/F drive migration, long-running three-hour automation, explicit small production sync and manual history continuation after backing up. Review distribution/license conditions. Check the adjacent SHA-256 file and clean source commit in `BUILD_INFO.json`. Unsigned binaries may trigger Windows warnings. No Release or tag has been created automatically.
