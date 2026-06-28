# Frontend API Migration Progress

## 2026-06-26

- Started full frontend API migration documentation.
- Read planning skill and initialized scoped planning files.
- Began scanning `src/lib/api.ts`, `src/services`, and direct page-level network calls.
- Extracted first-pass API helper list from `src/lib/api.ts`.
- Extracted direct network calls outside `src/lib/api.ts`.
- Scanned route definitions and page directories.
- Scanned old Python backend route ownership and current Java controller ownership.
- Created `design/front/infra/frontend-api-migration.md`.
- Updated `design/front/infra/index.md` to reference the migration document.
- Added source-file review list, current migration snapshot, frontend `@/lib/api` dependency summary, and backend endpoints that exist but are not primary frontend migration dependencies.
- Encountered `rg.exe` access denied in the Codex desktop WindowsApps path; switched to PowerShell `Select-String` for validation scans.
- Validated markdown heading structure and confirmed `design/front/infra/index.md` references `./frontend-api-migration.md`.
- Marked all plan phases complete.
