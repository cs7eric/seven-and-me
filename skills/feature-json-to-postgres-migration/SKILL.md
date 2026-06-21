---
name: feature-json-to-postgres-migration
description: Migrate a project feature from JSON-based persistence to PostgreSQL across schema design, data migration, ORM, repository/service/API layers, UI adaptation, and synchronized design documentation. Use when a feature currently reads or writes JSON files and needs to be rebuilt on Postgres while preserving behavior, adding maintainable layering, and forcing future maintainers to consult design docs first.
---

# Feature JSON To Postgres Migration

Use this skill when a feature still persists runtime data in JSON and needs a full migration to PostgreSQL without stopping at table design.

Always read `F:\dev-repo\mp4-to-word-new\skills\sql.md` first and follow its PostgreSQL rules unless the user explicitly asks for a different database standard.

## Workflow

### 1. Map the feature before editing

Inspect the current implementation end to end:

- locate JSON read/write files
- locate backend entrypoints, repositories, services, schedulers, and APIs
- locate frontend pages, dialogs, state, and API clients
- locate all user-visible assumptions about persistence

Capture the current feature behavior before redesigning tables. Treat the JSON format as migration input, not as the target schema.

### 2. Redesign tables from business behavior

Design tables from the feature's real business entities and interactions, not by mechanically mirroring JSON fields.

Always produce:

- business entity summary
- relationship summary
- new PostgreSQL tables under `app`
- soft-delete strategy
- status/check constraints where applicable
- indexes for actual query paths
- migration naming plan

Default design rules:

- prefer `uuid` primary keys
- use `deleted_at` for soft delete
- avoid physical foreign keys unless explicitly required
- keep JSON only for true extension fields or snapshots
- use stable compatibility fields only when needed for legacy import, such as `legacy_key`

### 3. Plan JSON -> Postgres migration

Define how historical JSON data enters the new schema:

- identify the JSON source files
- decide whether import runs in Alembic, bootstrap code, or a one-time service path
- make import idempotent
- preserve ordering and business identity
- use deterministic ID mapping when old IDs are not valid UUIDs

Do not let old JSON shape constrain the new business schema.

### 4. Implement layered backend changes

Implement the full stack, not only the table:

1. Alembic migration
2. ORM models
3. repository/data-access layer
4. service layer or equivalent upward capability layer
5. API/controller layer

Use this direction:

- API owns transaction boundary
- service owns use-case orchestration
- repository owns Postgres CRUD and import helpers
- ORM mirrors the new schema

Keep response payloads backward compatible when that reduces frontend churn, but do not preserve bad internal structure just for symmetry with the old JSON format.

### 5. Adapt the UI

Update the frontend so it reflects the new persistence model:

- update API types and request payloads
- update feature copy that still says data lives in JSON files
- update interactions that rely on old implicit defaults
- preserve user behavior unless the redesign intentionally changes it

If the feature links into adjacent pages, verify those jumps and query params still work.

### 6. Write design docs as part of the migration

Create or update a design document in:

- `F:\dev-repo\mp4-to-word-new\design\backend` for backend-heavy work
- `F:\dev-repo\mp4-to-word-new\design\front` for frontend-heavy work

Use `references/design-doc-template.md` as the default starting template. Copy its structure, then tailor section names and examples to the feature being migrated.

The design doc must include:

- migration background
- business model
- table design
- layer responsibilities
- file entrypoints
- migration strategy
- future modification checklist

Treat this doc as the maintenance entrypoint, not as optional aftercare.

### 7. Add code entry comments that point to design docs

In the key files you touch, add short header comments telling future maintainers to read the relevant design doc first.

Typical files:

- ORM models
- repositories
- services
- API files
- complex frontend feature entry files

The comment should make two expectations explicit:

- read the design doc before structural changes
- sync code changes back into the design doc

### 8. Validate the migrated feature

Validate at the appropriate layers:

- syntax/compile checks
- migration execution
- table existence checks
- smoke test for imported row counts when applicable
- frontend typecheck if UI changed

If you cannot run a step, say exactly what remains unverified.

## Output checklist

Before finishing, verify that all of the following are true:

- JSON runtime persistence has been replaced by Postgres runtime persistence
- tables are redesigned from business behavior
- ORM exists for the new schema
- repository/service/API layers are wired through
- UI is adapted if needed
- design docs exist in `design/backend` or `design/front`
- key files contain design-doc entry comments
- the design doc says future edits must sync back into design

## Default deliverables

Unless the user asks otherwise, leave behind:

- Alembic migration file
- ORM model file updates
- repository/service/API updates
- frontend API and feature page updates when needed
- one design doc for the migrated feature
- one design doc based on `references/design-doc-template.md`

## Example trigger

Use this skill for requests like:

- "migrate this feature from json persistence to postgres"
- "use the sql skill to redesign this feature's tables and orm"
- "replace local JSON runtime storage with Postgres and update API, UI, and design docs"
