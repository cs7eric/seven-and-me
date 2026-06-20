---
name: sql
description: PostgreSQL enterprise development database SQL design skill — generates uuid-PK, soft-delete, status-CHECK, no-physical-FK schema under the `app` schema. Use when designing Postgres tables, refactoring schemas, or writing migration SQL. Outputs directly executable SQL with partial unique indexes, jsonb GIN, CHECK constraints, and updated_at triggers.
---

# PostgreSQL Enterprise Development Database SQL Design Skill

## 1. Purpose

This skill guides an AI database designer to generate enterprise-ready PostgreSQL development database SQL.

The output must be directly usable in a development project and must follow strict rules for:

```text
schema design
table design
field naming
field types
primary keys
soft delete
status constraints
indexes
mapping tables
normalization
controlled denormalization
common business table patterns
migration-friendly SQL
PostgreSQL execution compatibility
```

This skill is not a general SQL tutorial. It is an execution specification for database-design agents.

---

## 2. Scope

Use this skill when the user requests:

```text
PostgreSQL SQL design
development database design
project database schema
enterprise SQL table structure
AI-generated PostgreSQL tables
mapping table design
normalization guidance
common business table modeling
```

Do not generate the following unless explicitly requested:

```text
user login tables
role tables
permission tables
authorization tables
authentication tables
audit log tables
order example tables
payment example tables
unrelated demo tables
production database user permissions
production deployment architecture
```

Only generate tables that are required by the user's actual business requirement.

Do not invent unrelated business modules.

---

## 3. Default Environment

Target database:

```text
PostgreSQL
```

Default environment:

```text
development database
```

Default schema:

```text
app
```

Required initialization SQL:

```sql
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE SCHEMA IF NOT EXISTS app;

CREATE OR REPLACE FUNCTION app.set_updated_at()
RETURNS trigger AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
```

Do not create additional schemas unless explicitly required.

---

## 4. Core Design Principles

Always follow:

```text
1. Prefer normalized structure by default.
2. Allow denormalization only with a clear reason.
3. Use PostgreSQL-native types correctly.
4. Use lowercase English names with underscores.
5. Use uuid primary keys.
6. Use deleted_at for soft delete.
7. Use timestamptz for all time fields.
8. Use numeric for money.
9. Use jsonb only for extension or snapshot data.
10. Add CHECK constraints for status fields.
11. Add partial unique indexes for soft-delete uniqueness.
12. Add indexes for relationship fields and common query paths.
13. Add updated_at trigger for mutable tables.
14. Do not use physical foreign keys by default.
15. Do not generate unrelated example tables.
16. SQL must be directly executable in PostgreSQL.
```

---

## 5. Required Generation Workflow

Before generating SQL, analyze:

```text
1. Independent entities
2. Detail or child entities
3. One-to-one relationships
4. One-to-many relationships
5. Many-to-many relationships
6. Mapping tables
7. Tree structures
8. Config tables
9. Dictionary tables
10. File or attachment tables
11. Record or process tables
12. Temporary draft tables
13. Required unique constraints
14. Required status values
15. Required indexes
16. Required denormalized fields
17. Required jsonb fields
18. Fields that should not be denormalized
```

If the requirement is incomplete, make reasonable assumptions and state them briefly.

Do not stop generation unless the missing information would make SQL unsafe or impossible.

---

## 6. Output Format

When generating database design, output in this order:

```text
1. Design assumptions
2. Table type summary
3. Relationship summary
4. Initialization SQL
5. CREATE TABLE statements
6. Index statements
7. Trigger statements
8. Comments for special or denormalized fields
9. Normalization explanation
10. Denormalization explanation if used
11. Migration file naming suggestion
12. Final self-check
```

SQL must be separated into executable blocks.

Do not mix unrelated explanations into SQL blocks.

---

## 7. Database Naming

Development database name should follow:

```text
project_name_dev
```

Valid:

```text
content_platform_dev
internal_tool_dev
asset_manager_dev
```

Invalid:

```text
test
demo
db
db1
new_database
```

---

## 8. Schema Rules

Use only:

```sql
app
```

All business tables must be created under:

```text
app
```

Example:

```text
app.table_name
app.xxx_yyy_mappings
```

Do not create multiple schemas unless explicitly requested.

---

## 9. Table Naming Rules

Use:

```text
lowercase English + underscore
```

Valid:

```text
app.content_categories
app.project_tasks
app.system_configs
app.xxx_yyy_mappings
```

Invalid:

```text
UserInfo
userInfo
T_USER
tbl_user
用户表
data1
```

Do not use vague names:

```text
data
info
record
list
temp
main
detail
```

unless combined with clear business meaning.

---

## 10. Column Naming Rules

Use:

```text
lowercase English + underscore
```

Valid:

```text
title
description
status
created_at
updated_at
deleted_at
sort_order
```

Invalid:

```text
titleName
TitleName
createTime
isDelete
删除时间
```

---

## 11. Primary Key Rules

Every table must have:

```sql
id uuid PRIMARY KEY DEFAULT gen_random_uuid()
```

Do not use:

```sql
serial
bigserial
integer primary key
varchar primary key
business code as primary key
```

Business codes may have unique indexes but must not replace the primary key.

---

## 12. Common Field Rules

Ordinary mutable business tables must include:

```sql
created_at timestamptz NOT NULL DEFAULT now(),
updated_at timestamptz NOT NULL DEFAULT now(),
deleted_at timestamptz,
remark text
```

Use when applicable:

```sql
status varchar(32) NOT NULL DEFAULT 'active',
sort_order integer NOT NULL DEFAULT 0,
extra jsonb NOT NULL DEFAULT '{}'::jsonb
```

Append-only record tables may omit:

```text
updated_at
updated_at trigger
```

if records are not expected to be modified.

---

## 13. Soft Delete Rules

Use:

```sql
deleted_at timestamptz
```

Do not use:

```sql
is_deleted boolean
delete_flag varchar
removed boolean
```

All normal queries must filter:

```sql
WHERE deleted_at IS NULL
```

Soft delete SQL:

```sql
UPDATE app.table_name
SET deleted_at = now()
WHERE id = 'uuid'
  AND deleted_at IS NULL;
```

Do not use hard delete unless explicitly requested.

---

## 14. Field Type Rules

Use these standard types:

```sql
id uuid
xxx_id uuid
parent_id uuid

code varchar(64)
name varchar(128)
title varchar(255)
description text
remark text

status varchar(32)
sort_order integer

amount numeric(18,2)
high_precision_amount numeric(24,6)
rate numeric(10,4)
quantity integer
count_value integer

url varchar(512)
email varchar(255)
phone varchar(32)
ip_address inet

file_name varchar(255)
file_ext varchar(32)
file_size bigint
mime_type varchar(128)

is_enabled boolean
is_visible boolean
is_default boolean

extra jsonb
snapshot_data jsonb
external_data jsonb

created_at timestamptz
updated_at timestamptz
deleted_at timestamptz
started_at timestamptz
ended_at timestamptz
expired_at timestamptz
published_at timestamptz
synced_at timestamptz
```

Money fields must use:

```sql
numeric(18,2)
```

High precision money-like fields may use:

```sql
numeric(24,6)
```

Do not use for money:

```sql
float
real
double precision
```

All time fields must use:

```sql
timestamptz
```

Do not store time as:

```sql
varchar
integer
bigint
timestamp without time zone
```

---

## 15. Field Length Rules

Recommended lengths:

```text
status: varchar(32)
code: varchar(64)
name: varchar(128)
title: varchar(255)
email: varchar(255)
url: varchar(512)
file_name: varchar(255)
file_ext: varchar(32)
mime_type: varchar(128)
```

Avoid:

```sql
varchar(9999)
```

Use `text` for long free-form content.

---

## 16. NOT NULL Rules

Use `NOT NULL` when a row is invalid without the field.

Usually required:

```text
id
created_at
updated_at
status
sort_order
required name/title/code fields
required relationship id fields
```

Usually nullable:

```text
description
remark
deleted_at
expired_at
published_at
optional extra fields
```

---

## 17. Default Value Rules

Recommended defaults:

```sql
created_at timestamptz NOT NULL DEFAULT now()
updated_at timestamptz NOT NULL DEFAULT now()
status varchar(32) NOT NULL DEFAULT 'active'
sort_order integer NOT NULL DEFAULT 0
extra jsonb NOT NULL DEFAULT '{}'::jsonb
is_enabled boolean NOT NULL DEFAULT true
is_visible boolean NOT NULL DEFAULT true
is_default boolean NOT NULL DEFAULT false
amount numeric(18,2) NOT NULL DEFAULT 0
quantity integer NOT NULL DEFAULT 0
```

---

## 18. Status Rules

Any table with `status` must have a CHECK constraint.

Example:

```sql
CONSTRAINT ck_table_name_status CHECK (
    status IN ('active', 'disabled')
)
```

Common statuses:

```text
active
disabled
draft
archived
pending
running
success
failed
submitted
expired
```

Do not mix synonyms randomly:

```text
enable
enabled
open
normal
ok
valid
invalid
```

Each table must use one consistent status vocabulary.

---

## 19. Constraint Rules

Use database constraints for minimum data quality.

Use where applicable:

```text
PRIMARY KEY
NOT NULL
DEFAULT
CHECK
UNIQUE INDEX
```

Common CHECK constraints:

```sql
CONSTRAINT ck_table_name_amount CHECK (amount >= 0)
```

```sql
CONSTRAINT ck_table_name_quantity CHECK (quantity >= 0)
```

```sql
CONSTRAINT ck_table_name_rate CHECK (rate >= 0 AND rate <= 1)
```

```sql
CONSTRAINT ck_table_name_level CHECK (level >= 1)
```

```sql
CONSTRAINT ck_table_name_time_range CHECK (
    ended_at IS NULL OR started_at IS NULL OR ended_at >= started_at
)
```

---

## 20. Foreign Key Rules

Do not generate physical foreign keys by default.

Do not generate:

```sql
FOREIGN KEY
```

Use relation ID fields:

```sql
xxx_id uuid NOT NULL
```

Relationship fields must be indexed.

Generate physical foreign keys only when explicitly requested.

---

## 21. Index Rules

Create indexes for:

```text
frequent WHERE filters
relationship id fields
status filters
created_at sorting
soft-delete active data
unique business codes
mapping table relation fields
tree parent_id
file related_table + related_id
```

Ordinary list index:

```sql
CREATE INDEX idx_table_name_alive_created_at
ON app.table_name (created_at DESC)
WHERE deleted_at IS NULL;
```

Status list index:

```sql
CREATE INDEX idx_table_name_status_created_at
ON app.table_name (status, created_at DESC)
WHERE deleted_at IS NULL;
```

Relationship lookup index:

```sql
CREATE INDEX idx_table_name_xxx_id
ON app.table_name (xxx_id)
WHERE deleted_at IS NULL;
```

Unique business code index:

```sql
CREATE UNIQUE INDEX uk_table_name_code_alive
ON app.table_name (code)
WHERE code IS NOT NULL
  AND deleted_at IS NULL;
```

Mapping unique index:

```sql
CREATE UNIQUE INDEX uk_xxx_yyy_mappings_alive
ON app.xxx_yyy_mappings (xxx_id, yyy_id)
WHERE deleted_at IS NULL;
```

Index naming:

```text
idx_table_name_column_name
uk_table_name_column_name
```

Do not create excessive indexes without query purpose.

---

## 22. JSONB Rules

Use `jsonb` only for:

```text
extensible metadata
third-party raw data
snapshot data
temporary flexible structures
rarely queried optional attributes
```

Do not use `jsonb` for:

```text
core relational fields
frequently filtered fields
status
amount
time
relationship ids
names used in list queries
```

If jsonb is frequently queried, add only when needed:

```sql
CREATE INDEX idx_table_name_extra_gin
ON app.table_name USING gin (extra);
```

---

## 23. updated_at Trigger Rules

Use this function once:

```sql
CREATE OR REPLACE FUNCTION app.set_updated_at()
RETURNS trigger AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
```

Every mutable table with `updated_at` must have:

```sql
CREATE TRIGGER trg_table_name_updated_at
BEFORE UPDATE ON app.table_name
FOR EACH ROW
EXECUTE FUNCTION app.set_updated_at();
```

Append-only tables may omit this.

---

## 24. Standard Ordinary Table Template

```sql
CREATE TABLE app.table_name (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),

    code varchar(64),
    name varchar(128) NOT NULL,
    description text,

    status varchar(32) NOT NULL DEFAULT 'active',
    sort_order integer NOT NULL DEFAULT 0,
    extra jsonb NOT NULL DEFAULT '{}'::jsonb,

    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    deleted_at timestamptz,

    remark text,

    CONSTRAINT ck_table_name_status CHECK (
        status IN ('active', 'disabled')
    )
);

CREATE UNIQUE INDEX uk_table_name_code_alive
ON app.table_name (code)
WHERE code IS NOT NULL
  AND deleted_at IS NULL;

CREATE INDEX idx_table_name_status_created_at
ON app.table_name (status, created_at DESC)
WHERE deleted_at IS NULL;

CREATE TRIGGER trg_table_name_updated_at
BEFORE UPDATE ON app.table_name
FOR EACH ROW
EXECUTE FUNCTION app.set_updated_at();
```

Remove unused template fields and indexes.

Do not keep unused fields blindly.

---

## 25. Relationship Modeling Rules

### 25.1 One-to-One

Definition:

```text
one A has one B
one B belongs to one A
```

Default design:

```text
merge into one table
```

Split only when:

```text
fields are large
fields are sensitive
fields are rarely used
lifecycle is different
structure changes frequently
```

Split table field:

```sql
a_id uuid NOT NULL
```

Unique index:

```sql
CREATE UNIQUE INDEX uk_b_table_a_id_alive
ON app.b_table (a_id)
WHERE deleted_at IS NULL;
```

---

### 25.2 One-to-Many

Definition:

```text
one A has many B
one B belongs to one A
```

Do not use mapping table.

Put parent ID on child table:

```sql
a_id uuid NOT NULL
```

Add index:

```sql
CREATE INDEX idx_b_table_a_id
ON app.b_table (a_id)
WHERE deleted_at IS NULL;
```

---

### 25.3 Many-to-Many

Definition:

```text
one A has many B
one B has many A
```

Must create mapping table:

```text
app.a_b_mappings
```

Mapping table template:

```sql
CREATE TABLE app.xxx_yyy_mappings (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),

    xxx_id uuid NOT NULL,
    yyy_id uuid NOT NULL,

    sort_order integer NOT NULL DEFAULT 0,

    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    deleted_at timestamptz,

    remark text
);

CREATE UNIQUE INDEX uk_xxx_yyy_mappings_alive
ON app.xxx_yyy_mappings (xxx_id, yyy_id)
WHERE deleted_at IS NULL;

CREATE INDEX idx_xxx_yyy_mappings_xxx_id
ON app.xxx_yyy_mappings (xxx_id)
WHERE deleted_at IS NULL;

CREATE INDEX idx_xxx_yyy_mappings_yyy_id
ON app.xxx_yyy_mappings (yyy_id)
WHERE deleted_at IS NULL;

CREATE TRIGGER trg_xxx_yyy_mappings_updated_at
BEFORE UPDATE ON app.xxx_yyy_mappings
FOR EACH ROW
EXECUTE FUNCTION app.set_updated_at();
```

---

## 26. Mapping Table Attribute Rules

Fields describing the relationship itself may be placed in the mapping table.

Allowed examples:

```sql
relation_status varchar(32) NOT NULL DEFAULT 'active',
is_default boolean NOT NULL DEFAULT false,
weight numeric(10,2) NOT NULL DEFAULT 0,
started_at timestamptz,
ended_at timestamptz
```

Decision rule:

```text
Describes A itself: put in A table.
Describes B itself: put in B table.
Describes relationship between A and B: put in mapping table.
```

Do not copy display fields into mapping table unless allowed by denormalization rules.

---

## 27. Normalization Rules

### First Normal Form

Each field must contain one atomic value.

Forbidden:

```text
tag_ids = '1,2,3'
contact_info = 'phone/email/wechat mixed'
multiple names in one field
jsonb array for relational IDs
```

Use separate fields or mapping tables.

### Second Normal Form

Each table must describe one entity or one relationship only.

Do not mix unrelated entity properties into one table.

### Third Normal Form

Do not store fields that can be obtained through relation.

Forbidden by default:

```sql
category_id uuid,
category_name varchar(128)
```

Allowed only when explicitly justified by denormalization rules.

---

## 28. Allowed Denormalization

Allow duplicated data only for:

```text
historical snapshot
high-frequency display
statistics
current status snapshot
external system sync
```

Recommended fields:

```sql
snapshot_name varchar(128),
snapshot_title varchar(255),
snapshot_data jsonb NOT NULL DEFAULT '{}'::jsonb,

view_count integer NOT NULL DEFAULT 0,
like_count integer NOT NULL DEFAULT 0,
comment_count integer NOT NULL DEFAULT 0,
usage_count integer NOT NULL DEFAULT 0,

current_status varchar(32),
latest_event_at timestamptz,

external_id varchar(128),
external_code varchar(128),
external_data jsonb NOT NULL DEFAULT '{}'::jsonb,
synced_at timestamptz
```

Every denormalized field should have a comment:

```sql
COMMENT ON COLUMN app.table_name.related_name IS
'Denormalized field for high-frequency display, source: related table name';
```

---

## 29. Common Table Type Templates

### 29.1 Master Data Table

Use for independent core objects.

```sql
CREATE TABLE app.table_name (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),

    code varchar(64),
    name varchar(128) NOT NULL,
    description text,

    status varchar(32) NOT NULL DEFAULT 'active',
    sort_order integer NOT NULL DEFAULT 0,
    extra jsonb NOT NULL DEFAULT '{}'::jsonb,

    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    deleted_at timestamptz,

    remark text,

    CONSTRAINT ck_table_name_status CHECK (
        status IN ('active', 'disabled')
    )
);
```

---

### 29.2 Detail Table

Use for child data under a parent object.

```sql
CREATE TABLE app.table_name (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),

    parent_id uuid NOT NULL,

    name varchar(128),
    description text,
    sort_order integer NOT NULL DEFAULT 0,
    extra jsonb NOT NULL DEFAULT '{}'::jsonb,

    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    deleted_at timestamptz,

    remark text
);

CREATE INDEX idx_table_name_parent_id
ON app.table_name (parent_id)
WHERE deleted_at IS NULL;
```

---

### 29.3 Mapping Table

Use for many-to-many relationships.

```sql
CREATE TABLE app.xxx_yyy_mappings (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),

    xxx_id uuid NOT NULL,
    yyy_id uuid NOT NULL,

    sort_order integer NOT NULL DEFAULT 0,

    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    deleted_at timestamptz,

    remark text
);
```

---

### 29.4 Config Table

Use for adjustable parameters.

```sql
CREATE TABLE app.configs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),

    config_key varchar(128) NOT NULL,
    config_value text,
    value_type varchar(32) NOT NULL DEFAULT 'string',

    description text,
    status varchar(32) NOT NULL DEFAULT 'active',

    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    deleted_at timestamptz,

    remark text,

    CONSTRAINT ck_configs_value_type CHECK (
        value_type IN ('string', 'number', 'boolean', 'json')
    ),

    CONSTRAINT ck_configs_status CHECK (
        status IN ('active', 'disabled')
    )
);
```

---

### 29.5 Dictionary Tables

Use for fixed options.

```sql
CREATE TABLE app.dict_types (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),

    code varchar(64) NOT NULL,
    name varchar(128) NOT NULL,

    status varchar(32) NOT NULL DEFAULT 'active',
    sort_order integer NOT NULL DEFAULT 0,

    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    deleted_at timestamptz,

    remark text,

    CONSTRAINT ck_dict_types_status CHECK (
        status IN ('active', 'disabled')
    )
);
```

```sql
CREATE TABLE app.dict_items (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),

    dict_type_id uuid NOT NULL,

    code varchar(64) NOT NULL,
    name varchar(128) NOT NULL,
    value varchar(255),

    status varchar(32) NOT NULL DEFAULT 'active',
    sort_order integer NOT NULL DEFAULT 0,

    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    deleted_at timestamptz,

    remark text,

    CONSTRAINT ck_dict_items_status CHECK (
        status IN ('active', 'disabled')
    )
);
```

---

### 29.6 Tree Table

Use for hierarchical structures.

```sql
CREATE TABLE app.table_name (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),

    parent_id uuid,

    code varchar(64),
    name varchar(128) NOT NULL,

    level integer NOT NULL DEFAULT 1,
    path text,

    status varchar(32) NOT NULL DEFAULT 'active',
    sort_order integer NOT NULL DEFAULT 0,

    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    deleted_at timestamptz,

    remark text,

    CONSTRAINT ck_table_name_status CHECK (
        status IN ('active', 'disabled')
    ),

    CONSTRAINT ck_table_name_level CHECK (
        level >= 1
    )
);
```

---

### 29.7 File Table

Use for uploaded or linked files.

```sql
CREATE TABLE app.files (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),

    file_name varchar(255) NOT NULL,
    file_ext varchar(32),
    file_size bigint NOT NULL DEFAULT 0,
    file_url varchar(512) NOT NULL,
    mime_type varchar(128),

    related_table varchar(128),
    related_id uuid,

    status varchar(32) NOT NULL DEFAULT 'active',

    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    deleted_at timestamptz,

    remark text,

    CONSTRAINT ck_files_status CHECK (
        status IN ('active', 'disabled')
    ),

    CONSTRAINT ck_files_file_size CHECK (
        file_size >= 0
    )
);
```

---

### 29.8 Append-Only Record Table

Use for process records, state change records, import records, sync records, or business history.

```sql
CREATE TABLE app.operation_records (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),

    related_table varchar(128) NOT NULL,
    related_id uuid NOT NULL,

    operation_type varchar(64) NOT NULL,
    operation_content text,

    before_data jsonb,
    after_data jsonb,

    operated_at timestamptz NOT NULL DEFAULT now(),
    created_at timestamptz NOT NULL DEFAULT now(),

    deleted_at timestamptz,
    remark text
);

CREATE INDEX idx_operation_records_related
ON app.operation_records (related_table, related_id, operated_at DESC)
WHERE deleted_at IS NULL;
```

---

### 29.9 Import Task Table

Use for Excel, CSV, or third-party import tasks.

```sql
CREATE TABLE app.import_tasks (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),

    task_name varchar(128) NOT NULL,
    file_id uuid,

    status varchar(32) NOT NULL DEFAULT 'pending',

    total_count integer NOT NULL DEFAULT 0,
    success_count integer NOT NULL DEFAULT 0,
    failure_count integer NOT NULL DEFAULT 0,

    error_message text,

    started_at timestamptz,
    finished_at timestamptz,

    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    deleted_at timestamptz,

    remark text,

    CONSTRAINT ck_import_tasks_status CHECK (
        status IN ('pending', 'running', 'success', 'failed')
    ),

    CONSTRAINT ck_import_tasks_count CHECK (
        total_count >= 0
        AND success_count >= 0
        AND failure_count >= 0
    )
);
```

---

### 29.10 Draft Table

Use for temporary unsubmitted data.

```sql
CREATE TABLE app.drafts (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),

    draft_type varchar(64) NOT NULL,
    draft_data jsonb NOT NULL DEFAULT '{}'::jsonb,

    status varchar(32) NOT NULL DEFAULT 'draft',

    expired_at timestamptz,

    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    deleted_at timestamptz,

    remark text,

    CONSTRAINT ck_drafts_status CHECK (
        status IN ('draft', 'submitted', 'expired')
    )
);
```

---

## 30. Partitioning Guidance

Do not create partitions by default for development database.

Recommend partitioning only when the table is expected to become:

```text
large log table
large history table
large event table
large time-series table
large import/sync record table
```

Prefer monthly range partitioning on:

```text
created_at
operated_at
occurred_at
```

Partition template:

```sql
CREATE TABLE app.table_name (
    id uuid NOT NULL DEFAULT gen_random_uuid(),
    created_at timestamptz NOT NULL DEFAULT now()
) PARTITION BY RANGE (created_at);
```

Do not partition ordinary small master data tables.

---

## 31. Migration Script Rules

Generated SQL must be migration-friendly.

Recommended file naming:

```text
VYYYYMMDDHHMM__create_app_base.sql
VYYYYMMDDHHMM__create_app_tables.sql
VYYYYMMDDHHMM__add_app_indexes.sql
VYYYYMMDDHHMM__add_app_triggers.sql
```

Rules:

```text
Do not modify already executed migrations.
Create a new migration for every change.
CREATE EXTENSION and CREATE SCHEMA belong in base migration.
Create tables before indexes.
Create indexes before triggers.
Add comments after tables and indexes.
```

---

## 32. SQL Writing Rules

Never use:

```sql
SELECT *
```

Use explicit columns:

```sql
SELECT id, name, status, created_at
FROM app.table_name
WHERE deleted_at IS NULL;
```

Use cursor-style pagination for large data:

```sql
SELECT id, name, status, created_at
FROM app.table_name
WHERE deleted_at IS NULL
  AND created_at < 'previous_page_last_created_at'
ORDER BY created_at DESC
LIMIT 20;
```

Update must have clear conditions:

```sql
UPDATE app.table_name
SET name = 'new_name'
WHERE id = 'uuid'
  AND deleted_at IS NULL;
```

Soft delete:

```sql
UPDATE app.table_name
SET deleted_at = now()
WHERE id = 'uuid'
  AND deleted_at IS NULL;
```

Do not generate destructive statements unless explicitly requested:

```sql
DROP TABLE
TRUNCATE TABLE
DELETE FROM
```

---

## 33. Comments Rule

Use comments for:

```text
denormalized fields
snapshot fields
external sync fields
non-obvious jsonb fields
important table purpose
```

Examples:

```sql
COMMENT ON TABLE app.table_name IS 'Stores configurable project-level records';

COMMENT ON COLUMN app.table_name.snapshot_data IS
'Snapshot data captured at the time of operation';
```

---

## 34. Enterprise Safety Rules

Do not generate:

```text
unbounded varchar without reason
money as float
time as varchar
comma-separated IDs
multiple values in one field
business code as primary key
physical foreign key by default
unnecessary denormalized names
unclear table names
irrelevant example tables
auth/audit/order/payment tables unless requested
```

Always generate:

```text
uuid primary key
soft delete field
created_at
updated_at where mutable
status CHECK constraint where status exists
necessary indexes
mapping table for many-to-many
partial unique indexes for soft-delete uniqueness
comments for denormalization
```

---

## 35. Final Self-Check

Before returning SQL, verify:

```text
1. All tables are under app schema.
2. All names use lowercase English and underscores.
3. Every table has uuid primary key.
4. Ordinary tables have created_at, updated_at, deleted_at.
5. Time fields use timestamptz.
6. Money fields use numeric(18,2) or numeric(24,6).
7. Soft delete uses deleted_at.
8. Unique indexes support soft delete.
9. No physical foreign keys unless explicitly requested.
10. No SELECT *.
11. Many-to-many uses xxx_yyy_mappings.
12. One-to-many does not use mapping table.
13. Fields are atomic.
14. Tables describe one entity or one relationship.
15. No unnecessary denormalized fields.
16. Denormalized fields have comments.
17. All status fields have CHECK constraints.
18. Mutable tables have updated_at trigger.
19. Relationship ID fields have indexes.
20. SQL can run directly in PostgreSQL.
21. No unrelated user/auth/audit/order/payment tables are generated.
22. Output includes table type and relationship explanation.
23. Output includes assumptions when information is incomplete.
24. Output includes migration file naming suggestion.
```

---

## 36. Response Style

When responding:

```text
Be precise.
Be implementation-oriented.
Do not over-explain basic database theory.
Do not add unrelated examples.
Do not generate tables outside the requested business scope.
If assumptions are made, list them briefly.
Return SQL in executable blocks.
Explain table types and relationships after SQL.
```

Final response must be structured, reviewable, and ready for direct development use.