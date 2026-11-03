# ErYouToolbox 0.5.0-rc2 — Windows portable preview

**Pre-release draft only. Do not publish before user acceptance.**

ErYouToolbox is a personal GameBanana MOD discovery, tracking and local information-management tool. It does not download or install MOD files. Six configured games, local browsing, author subscriptions, read state, source rankings, bounded sync and rating enrichment use React + Python + SQLite. The desktop window uses pywebview and PyInstaller onedir.

## Windows use

Extract the entire ZIP to a writable folder. Keep `ErYouToolbox.exe` and `_internal` together. Microsoft Edge WebView2 Evergreen Runtime is required; missing-runtime errors explain the requirement. Python, Node, pnpm and Vite are not client prerequisites.

The first launch creates an **empty** `userdata` library alongside the EXE. No private MOD library or followed/read records are distributed. Explicitly select the first-use automation mode. Recommended settings are apply every three hours and bounded daily history, but nothing is enabled without consent. Existing settings are retained. Only an open client can schedule checks; closing it stops future scheduling. No Windows task is installed.

To update, close all instances and writers, back up userdata, and replace program files while retaining that directory. Do not overwrite userdata or copy a live SQLite main file. No automatic migration from a development/personal library is included. Roll back by restoring the previous program directory and its separately verified matching userdata backup, never by downgrading a database blindly.

## Limits and source semantics

- Counts/categories are locally collected, not GameBanana-wide completeness guarantees. Historical coverage remains incomplete.
- Source ranking numbers are cumulative; recent-published ranking is a bounded sample, not official recent growth.
- UNKNOWN and source Unrated are distinct and neither implies SFW. Concrete labels require evidence. Sensitive and unknown previews require independent user preferences. Human review is separate.
- Missing source statistics mean unknown, not zero. Remote source details do not create local records. File names are read-only and direct file downloads are absent.
- Historical rating gaps require small explicit save batches after preview. This work did not batch-apply production data.
- Comment preview/publication, login, MOD downloader/installer, XXMI, cloud, updater, and closed-client background tasks are not included.
- Unsigned candidate. Clean Windows, actual E/F hardware move, long-running three-hour scheduling, and user production small-batch acceptance remain required.

## Attribution and license review

GameBanana titles, authors, metadata and linked media belong to their respective owners and remain at the source. This software is not affiliated with GameBanana or Nahida Desktop. Nahida Desktop's GPL-3.0 project was studied for interaction/information architecture only; no component, CSS, icon, brand asset or other source was copied.

Runtime/build dependencies retain their own terms: React/Vite/Tailwind (MIT), TypeScript (Apache-2.0), Python (PSF), httpx/pywebview (BSD), pythonnet/clr_loader (MIT), PyInstaller (GPL with bootloader distribution exception). Verify included notices and current installed metadata before distribution. WebView2 is a Microsoft runtime installed separately. This document does not select a new license for the ErYouToolbox source; project-license acceptance remains with the owner.

## Artifact identification

Expected artifact: `ErYouToolbox-0.5.0-rc2-win-x64.zip`. Use adjacent `.zip.sha256` for the exact SHA-256 and `BUILD_INFO.json` for actual clean source commit, dependency versions and resource manifest. Publish neither an intermediate dirty artifact nor a different EXE with this checksum. No Release or tag is created automatically.
