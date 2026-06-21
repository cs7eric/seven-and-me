# Feature Migration Design Doc Template

Use this template when migrating a feature from JSON persistence to PostgreSQL.

Copy the structure into:

- `design/backend/<feature-name>.md` for backend-led migrations
- `design/front/<feature-name>.md` for frontend-led migrations

Replace placeholder text with the real feature name, file paths, schema names, and migration choices.

## Title

`<Feature Name> Postgres Migration`

## 1. Background

Describe:

- what the feature does
- where it currently stores runtime data
- why JSON persistence is no longer sufficient
- what this migration is expected to unlock

## 2. Business Model

List the business entities and their responsibilities.

Recommended format:

- `<Entity A>`: what it represents in product behavior
- `<Entity B>`: what it represents in product behavior

Also describe the main user actions:

- create
- update
- delete
- view/list
- jump/link to adjacent modules

## 3. Persistence Redesign

Explain the redesign principles:

- tables are designed from business behavior, not copied from JSON
- JSON files are migration sources, not schema templates
- compatibility fields such as `legacy_key` exist only when needed

## 4. Table Design

For each table include:

- table name
- business meaning
- key columns
- soft-delete behavior
- status vocabulary
- indexing strategy

Suggested format:

### `app.<table_name>`

Purpose:

- `<what this table stores>`

Key fields:

- `id`
- `<field>`
- `<field>`

Indexes:

- `<index reason>`

Notes:

- `<denormalization or compatibility notes>`

## 5. Data Migration Strategy

Describe:

- source JSON files
- import timing
- idempotency strategy
- legacy ID mapping strategy
- ordering preservation strategy

If using deterministic UUID mapping, say exactly how it works.

## 6. Layer Responsibilities

Document the code layers and their ownership.

### ORM

File:

- `<absolute or repo-root path>`

Responsibilities:

- `<responsibility>`

### Repository

File:

- `<path>`

Responsibilities:

- `<responsibility>`

### Service

File:

- `<path>`

Responsibilities:

- `<responsibility>`

### API

File:

- `<path>`

Responsibilities:

- `<responsibility>`

### Frontend

Files:

- `<path>`
- `<path>`

Responsibilities:

- `<responsibility>`

## 7. File Entrypoints

List the first files a future maintainer should inspect.

Suggested order:

1. design doc
2. migration file
3. ORM
4. repository
5. service
6. API
7. frontend API client
8. feature page/components

## 8. Design-First Maintenance Rule

State the rule explicitly:

- read this design doc before structural changes
- update this design doc when changing schema, layering, contracts, or migration behavior

## 9. Validation

Record what was validated.

Suggested checklist:

- Python syntax or compile checks
- TypeScript typecheck
- Alembic migration execution
- table existence check
- row-count smoke test
- feature smoke test

For anything not run, say:

- not run
- blocked by environment
- pending manual verification

## 10. Future Change Checklist

Before modifying this feature, check:

- schema changes
- ORM field mapping
- repository filters and uniqueness checks
- service orchestration
- API payload compatibility
- frontend types and user-facing copy
- whether this design doc still matches reality
