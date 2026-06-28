# Frontend API Migration Documentation Plan

## Goal

Create a complete migration document for the old frontend APIs in `F:\dev-repo\mp4-to-word-new\frontend`, covering current API usage, backend ownership, migration status, target service/module, and recommended steps.

## Phases

| Phase | Status | Scope |
|---|---|---|
| 1 | complete | Scan frontend API definitions and direct network calls |
| 2 | complete | Map API groups to pages and backend domains |
| 3 | complete | Compare current migrated services with remaining legacy Flask APIs |
| 4 | complete | Write migration document |
| 5 | complete | Validate references and summarize |

## Notes

- Trigger-style scheduler calls must remain on Python unless explicitly changed later.
- Existing Java-routed APIs already split under `src/services` should be recorded as migrated.

## Errors Encountered

| Error | Attempt | Resolution |
|---|---|---|
| `rg.exe` failed to start from WindowsApps path with access denied | Tried using `rg` for source scans | Switched to PowerShell `Get-ChildItem` + `Select-String` and continued scanning |
