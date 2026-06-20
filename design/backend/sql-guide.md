# PostgreSQL 开发库 SQL 设计规范

## 1. 文档目标

本规范用于约束 PostgreSQL 开发库的数据库结构设计、SQL 生成、表关系建模、字段类型选择、索引设计与范式控制。

适用范围：

```text
开发环境
测试环境
AI 辅助数据库建模
项目早期数据结构设计
非生产环境 SQL 设计
```

不包含：

```text
用户登录
角色权限
鉴权体系
审计日志
订单示例
支付示例
具体业务表实例
生产级权限隔离
```

设计目标：

```text
结构清晰
命名统一
类型合理
关系明确
便于扩展
便于迁移
便于 AI 稳定生成 SQL
避免无关业务表污染设计
```

---

# 第一部分：开发库基础规范

## 2. 数据库命名

开发库统一使用：

```text
项目名_dev
```

示例：

```text
my_project_dev
content_platform_dev
internal_tool_dev
```

禁止使用：

```text
test
db
db1
demo
new_database
```

---

## 3. Schema 设计

开发库阶段统一使用一个业务 Schema：

```sql
CREATE SCHEMA IF NOT EXISTS app;
```

所有业务表统一放在：

```text
app
```

示例：

```text
app.xxx
app.xxx_yyy_mappings
```

开发库阶段不主动拆分多个 Schema，避免 AI 生成结构分散。

---

## 4. 开发库初始化 SQL

新建开发库后，优先执行：

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

说明：

```text
pgcrypto 用于生成 uuid。
app 用于统一存放业务表。
set_updated_at 用于自动维护 updated_at。
```

---

# 第二部分：命名规范

## 5. 表命名规范

表名统一使用：

```text
小写英文 + 下划线
```

推荐：

```text
app.article_categories
app.project_tasks
app.system_configs
app.xxx_yyy_mappings
```

禁止：

```text
UserInfo
userInfo
T_USER
tbl_user
用户表
data1
```

规则：

```text
1. 不使用中文
2. 不使用大写
3. 不使用驼峰命名
4. 不添加 t_、tbl_ 前缀
5. 名称必须能表达业务含义
6. 多对多关系表统一使用 xxx_yyy_mappings
```

---

## 6. 字段命名规范

字段名统一使用：

```text
小写英文 + 下划线
```

推荐：

```text
title
description
status
created_at
updated_at
deleted_at
sort_order
```

禁止：

```text
titleName
TitleName
createTime
isDelete
删除时间
```

---

# 第三部分：字段与类型规范

## 7. 主键规范

所有表必须有主键。

开发库统一使用 UUID：

```sql
id uuid PRIMARY KEY DEFAULT gen_random_uuid()
```

不使用：

```sql
id serial
id bigserial
id integer
```

---

## 8. 普通表基础字段

除纯记录表、临时表、特殊关系表外，普通业务表建议包含：

```sql
id uuid PRIMARY KEY DEFAULT gen_random_uuid(),

created_at timestamptz NOT NULL DEFAULT now(),
updated_at timestamptz NOT NULL DEFAULT now(),
deleted_at timestamptz,

sort_order integer NOT NULL DEFAULT 0,

status varchar(32) NOT NULL DEFAULT 'active',

remark text
```

字段说明：

| 字段         | 含义           |
| ---------- | ------------ |
| id         | 主键           |
| created_at | 创建时间         |
| updated_at | 更新时间         |
| deleted_at | 软删除时间，空表示未删除 |
| sort_order | 排序值，越小越靠前    |
| status     | 状态           |
| remark     | 备注           |

---

## 9. 软删除规范

统一使用：

```sql
deleted_at timestamptz
```

不使用：

```sql
is_deleted boolean NOT NULL DEFAULT false
delete_flag varchar(8)
```

判断未删除：

```sql
WHERE deleted_at IS NULL
```

软删除数据：

```sql
UPDATE app.table_name
SET deleted_at = now()
WHERE id = '这里填uuid'
  AND deleted_at IS NULL;
```

---

## 10. 常用字段类型选择

### 10.1 名称、标题

```sql
name varchar(128) NOT NULL
title varchar(255) NOT NULL
```

### 10.2 简短编码

```sql
code varchar(64) NOT NULL
```

适用：

```text
分类编码
配置键
状态编码
外部编号
业务编码
```

### 10.3 描述

```sql
description text
```

### 10.4 状态

```sql
status varchar(32) NOT NULL DEFAULT 'active'
```

常用状态：

```text
active      启用
disabled    禁用
draft       草稿
archived    归档
pending     待处理
running     处理中
success     成功
failed      失败
```

### 10.5 数量

```sql
quantity integer NOT NULL DEFAULT 0
```

### 10.6 金额

金额字段必须使用：

```sql
amount numeric(18,2) NOT NULL DEFAULT 0
```

禁止使用：

```sql
float
double precision
real
```

### 10.7 时间

时间字段统一使用：

```sql
timestamptz
```

示例：

```sql
created_at timestamptz NOT NULL DEFAULT now()
published_at timestamptz
expired_at timestamptz
```

禁止使用：

```sql
varchar 存时间
integer 存时间
timestamp without time zone
```

### 10.8 布尔值

```sql
is_enabled boolean NOT NULL DEFAULT true
is_visible boolean NOT NULL DEFAULT true
is_default boolean NOT NULL DEFAULT false
```

### 10.9 JSON 扩展字段

```sql
extra jsonb NOT NULL DEFAULT '{}'::jsonb
```

规则：

```text
jsonb 仅用于扩展信息。
高频查询字段必须独立建字段。
不可将核心业务结构全部塞入 jsonb。
```

---

## 11. 字段长度建议

| 场景   | 类型            |
| ---- | ------------- |
| 状态   | varchar(32)   |
| 编码   | varchar(64)   |
| 名称   | varchar(128)  |
| 标题   | varchar(255)  |
| URL  | varchar(512)  |
| 长文本  | text          |
| 金额   | numeric(18,2) |
| 时间   | timestamptz   |
| JSON | jsonb         |

避免使用：

```sql
varchar(9999)
```

---

## 12. NOT NULL 规则

必须存在业务含义的字段应加：

```sql
NOT NULL
```

示例：

```sql
name varchar(128) NOT NULL
status varchar(32) NOT NULL DEFAULT 'active'
created_at timestamptz NOT NULL DEFAULT now()
```

可为空字段：

```sql
description text
remark text
deleted_at timestamptz
expired_at timestamptz
```

判断原则：

```text
数据没有该字段就无法成立时，使用 NOT NULL。
字段属于补充信息或可选信息时，允许为空。
```

---

## 13. 默认值规则

常见默认值：

```sql
status varchar(32) NOT NULL DEFAULT 'active'
sort_order integer NOT NULL DEFAULT 0
created_at timestamptz NOT NULL DEFAULT now()
updated_at timestamptz NOT NULL DEFAULT now()
deleted_at timestamptz
extra jsonb NOT NULL DEFAULT '{}'::jsonb
```

原则：

```text
基础默认值由数据库保证。
应用层不应承担所有默认值兜底。
```

---

## 14. 状态字段规范

含有 status 字段时，必须加 CHECK 约束。

示例：

```sql
status varchar(32) NOT NULL DEFAULT 'active',

CONSTRAINT ck_table_name_status CHECK (
    status IN ('active', 'disabled')
)
```

未知状态范围时，默认使用：

```text
active
disabled
```

禁止同项目内混用：

```text
enable
enabled
open
normal
ok
```

---

## 15. 排序字段规范

需要排序时统一使用：

```sql
sort_order integer NOT NULL DEFAULT 0
```

查询顺序：

```sql
ORDER BY sort_order ASC, created_at DESC
```

禁止使用：

```sql
sort
order
rank
index
```

---

# 第四部分：索引、约束与触发器

## 16. 索引基础规范

需要索引的场景：

```text
经常用于 WHERE 的字段
经常用于 JOIN 或关联查询的字段
经常用于 ORDER BY 的字段
具有唯一性要求的字段
软删除表中的高频查询条件
```

### 16.1 普通索引

```sql
CREATE INDEX idx_table_name_status
ON app.table_name (status);
```

### 16.2 软删除常用索引

```sql
CREATE INDEX idx_table_name_alive_created_at
ON app.table_name (created_at DESC)
WHERE deleted_at IS NULL;
```

### 16.3 唯一索引

字段不能为空且不能重复：

```sql
CREATE UNIQUE INDEX uk_table_name_code_alive
ON app.table_name (code)
WHERE deleted_at IS NULL;
```

字段可为空但非空值不能重复：

```sql
CREATE UNIQUE INDEX uk_table_name_code_alive
ON app.table_name (code)
WHERE code IS NOT NULL
  AND deleted_at IS NULL;
```

规则：

```text
存在软删除时，唯一索引必须兼容 deleted_at。
```

---

## 17. 索引命名规范

普通索引：

```text
idx_表名_字段名
```

唯一索引：

```text
uk_表名_字段名
```

示例：

```text
idx_project_tasks_status
uk_project_tasks_code_alive
```

---

## 18. 外键规范

开发库阶段默认不使用数据库物理外键。

不生成：

```sql
FOREIGN KEY
```

仅保留关联字段：

```sql
xxx_id uuid NOT NULL
```

字段命名：

```text
被关联对象名_id
```

说明：

```text
字段关系必须清晰。
物理外键默认不生成，除非需求明确要求。
```

---

## 19. updated_at 自动更新

PostgreSQL 不会自动更新 updated_at，必须使用触发器。

初始化函数：

```sql
CREATE OR REPLACE FUNCTION app.set_updated_at()
RETURNS trigger AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
```

普通表创建后必须添加：

```sql
CREATE TRIGGER trg_table_name_updated_at
BEFORE UPDATE ON app.table_name
FOR EACH ROW
EXECUTE FUNCTION app.set_updated_at();
```

---

# 第五部分：标准建表模板

## 20. 普通业务表模板

```sql
CREATE TABLE app.table_name (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),

    -- 业务字段
    name varchar(128) NOT NULL,
    code varchar(64),

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

CREATE INDEX idx_table_name_alive_created_at
ON app.table_name (created_at DESC)
WHERE deleted_at IS NULL;

CREATE TRIGGER trg_table_name_updated_at
BEFORE UPDATE ON app.table_name
FOR EACH ROW
EXECUTE FUNCTION app.set_updated_at();
```

生成规则：

```text
table_name 必须替换为真实表名。
业务字段放在基础字段之前。
不需要 code 时，删除 code 字段及其唯一索引。
不需要 extra 时，删除 extra 字段。
CHECK 约束必须与实际 status 值保持一致。
```

---

# 第六部分：关系与 mapping 表

## 21. mapping 表定义

mapping 表用于表示两个实体之间的关系，通常对应：

```text
多对多关系
对象绑定关系
对象分配关系
对象关联关系
```

典型结构：

```text
一个 A 可以对应多个 B
一个 B 也可以对应多个 A
```

此时必须使用 mapping 表。

---

## 22. mapping 表命名规范

统一使用：

```text
app.xxx_yyy_mappings
```

示例：

```text
app.article_tag_mappings
app.project_member_mappings
app.product_category_mappings
```

规则：

```text
主对象名_关联对象名_mappings
```

禁止使用：

```text
relation
rel
map
middle_table
table1_table2
```

---

## 23. mapping 表字段规范

mapping 表默认只保存关系，不保存主表冗余字段。

标准模板：

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

## 24. mapping 表允许增加的关系属性

当字段描述的是“关系本身”时，可以放入 mapping 表。

可选字段：

```sql
relation_status varchar(32) NOT NULL DEFAULT 'active',
is_default boolean NOT NULL DEFAULT false,
weight numeric(10,2) NOT NULL DEFAULT 0,
started_at timestamptz,
ended_at timestamptz
```

判断规则：

```text
字段描述 A 本身，放入 A 表。
字段描述 B 本身，放入 B 表。
字段描述 A 与 B 的关系，放入 mapping 表。
```

---

## 25. mapping 表禁止事项

不应将两个主表的普通展示字段复制到 mapping 表。

不推荐：

```sql
xxx_name varchar(128),
yyy_name varchar(128)
```

允许例外：

```text
历史快照
性能优化
外部系统同步
明确的业务冗余
```

---

## 26. 一对多关系规范

一对多关系定义：

```text
一个 A 有多个 B
一个 B 只属于一个 A
```

设计方式：

```text
不使用 mapping 表。
在 B 表中保存 a_id。
```

字段：

```sql
a_id uuid NOT NULL
```

---

## 27. 一对一关系规范

一对一关系定义：

```text
一个 A 只有一个 B
一个 B 也只属于一个 A
```

优先合并到同一张表。

允许拆表场景：

```text
字段很多
字段低频使用
字段敏感
字段生命周期不同
字段体积较大
```

拆表方式：

```sql
a_id uuid NOT NULL
```

并添加唯一索引：

```sql
CREATE UNIQUE INDEX uk_xxx_details_xxx_id_alive
ON app.xxx_details (xxx_id)
WHERE deleted_at IS NULL;
```

---

# 第七部分：数据库三范式

## 28. 第一范式：字段原子性

每个字段只存一个值，不存多个混合值。

推荐：

```sql
phone varchar(32)
email varchar(255)
```

不推荐：

```sql
contact_info text
```

不推荐：

```sql
tag_ids text
```

当一个对象拥有多个关联对象时，应使用 mapping 表。

---

## 29. 第二范式：字段依赖完整主键

一张表只描述一类对象。

字段必须描述该表对应的实体或关系，不得混入其他实体属性。

不推荐：

```sql
category_name varchar(128)
tag_names text
```

推荐：

```sql
category_id uuid
```

多标签关系使用：

```text
xxx_yyy_mappings
```

---

## 30. 第三范式：避免传递依赖

能从其他表通过关联查询得到的数据，默认不重复存储。

不推荐：

```sql
category_id uuid NOT NULL,
category_name varchar(128) NOT NULL
```

推荐：

```sql
category_id uuid NOT NULL
```

原则：

```text
除非属于明确的快照、统计、性能优化或外部系统同步，否则不冗余可关联查询字段。
```

---

# 第八部分：允许违反范式的情况

## 31. 反范式定义

反范式是指为了业务目标故意重复存储部分数据。

允许目标：

```text
保留历史快照
提升高频查询性能
降低复杂关联成本
降低统计成本
保存外部系统数据快照
```

---

## 32. 历史快照

适用：

```text
提交记录
审批记录
发布记录
合同记录
结算记录
导入记录
同步记录
状态流转记录
```

推荐字段：

```sql
snapshot_name varchar(128),
snapshot_title varchar(255),
snapshot_data jsonb NOT NULL DEFAULT '{}'::jsonb
```

原则：

```text
历史记录应保留发生当时的数据状态。
原始数据后续修改，不应影响历史快照。
```

---

## 33. 高频展示字段

当某个关联字段在列表或详情中高频展示，且关联查询成本较高时，可冗余。

示例：

```sql
related_name varchar(128)
```

要求：

```text
必须明确数据来源。
必须明确同步策略。
必须能接受或处理数据不一致风险。
```

---

## 34. 统计汇总字段

统计类字段允许冗余。

常见字段：

```sql
view_count integer NOT NULL DEFAULT 0,
like_count integer NOT NULL DEFAULT 0,
comment_count integer NOT NULL DEFAULT 0,
usage_count integer NOT NULL DEFAULT 0
```

用途：

```text
避免每次从明细表实时 COUNT。
提升列表页和统计页查询性能。
```

---

## 35. 状态快照

流程类、发布类、任务类数据可保存当前状态。

示例：

```sql
current_status varchar(32),
latest_event_at timestamptz
```

用途：

```text
避免每次从过程记录中计算当前状态。
```

---

## 36. 外部系统数据

第三方系统同步数据可以保存快照。

常见字段：

```sql
external_id varchar(128),
external_code varchar(128),
external_data jsonb NOT NULL DEFAULT '{}'::jsonb,
synced_at timestamptz
```

用途：

```text
保留外部系统原始数据。
支持后续排查、回放、比对、同步修复。
```

---

## 37. 反范式注释要求

所有冗余字段建议添加注释说明来源与用途。

```sql
COMMENT ON COLUMN app.table_name.related_name IS
'冗余字段，用于列表展示，来源于关联表 name';
```

原则：

```text
冗余字段必须有明确业务原因。
禁止无原因重复存储可关联查询字段。
```

---

# 第九部分：常见表类型设计

## 38. 主数据表

主数据表表示系统中的核心对象。

特征：

```text
有 name
有 code
有 status
有 sort_order
会被其他表引用
生命周期相对独立
```

字段模板：

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

CREATE INDEX idx_table_name_alive_created_at
ON app.table_name (created_at DESC)
WHERE deleted_at IS NULL;

CREATE TRIGGER trg_table_name_updated_at
BEFORE UPDATE ON app.table_name
FOR EACH ROW
EXECUTE FUNCTION app.set_updated_at();
```

适用：

```text
分类
标签
地区
配置项
项目
资源
渠道
类型
等级
模板
```

---

## 39. 明细表

明细表表示某个主表下的子数据。

特征：

```text
有 parent_id
依附于主表
通常不单独存在
生命周期通常跟随主表
```

字段模板：

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

CREATE TRIGGER trg_table_name_updated_at
BEFORE UPDATE ON app.table_name
FOR EACH ROW
EXECUTE FUNCTION app.set_updated_at();
```

适用：

```text
步骤
子项
附件记录
配置明细
表单字段
页面模块
清单项
```

---

## 40. mapping 关系表

适用：

```text
多对多关系
对象绑定关系
对象分配关系
对象关联关系
```

字段模板：

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

## 41. 配置表

适合保存可调整参数。

字段模板：

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

CREATE UNIQUE INDEX uk_configs_key_alive
ON app.configs (config_key)
WHERE deleted_at IS NULL;

CREATE TRIGGER trg_configs_updated_at
BEFORE UPDATE ON app.configs
FOR EACH ROW
EXECUTE FUNCTION app.set_updated_at();
```

---

## 42. 字典表

适合保存固定选项。

字段模板：

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

CREATE UNIQUE INDEX uk_dict_types_code_alive
ON app.dict_types (code)
WHERE deleted_at IS NULL;

CREATE TRIGGER trg_dict_types_updated_at
BEFORE UPDATE ON app.dict_types
FOR EACH ROW
EXECUTE FUNCTION app.set_updated_at();
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

CREATE UNIQUE INDEX uk_dict_items_type_code_alive
ON app.dict_items (dict_type_id, code)
WHERE deleted_at IS NULL;

CREATE INDEX idx_dict_items_type_id
ON app.dict_items (dict_type_id)
WHERE deleted_at IS NULL;

CREATE TRIGGER trg_dict_items_updated_at
BEFORE UPDATE ON app.dict_items
FOR EACH ROW
EXECUTE FUNCTION app.set_updated_at();
```

---

## 43. 树形表

适合上下级结构。

字段模板：

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
    )
);

CREATE INDEX idx_table_name_parent_id
ON app.table_name (parent_id)
WHERE deleted_at IS NULL;

CREATE INDEX idx_table_name_alive_created_at
ON app.table_name (created_at DESC)
WHERE deleted_at IS NULL;

CREATE TRIGGER trg_table_name_updated_at
BEFORE UPDATE ON app.table_name
FOR EACH ROW
EXECUTE FUNCTION app.set_updated_at();
```

适用：

```text
分类树
地区树
菜单树
组织树
目录树
```

字段说明：

```text
parent_id 表示上级节点。
level 表示层级。
path 保存完整路径，便于查询。
```

---

## 44. 附件表

适合记录上传文件。

字段模板：

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
    )
);

CREATE INDEX idx_files_related
ON app.files (related_table, related_id)
WHERE deleted_at IS NULL;

CREATE TRIGGER trg_files_updated_at
BEFORE UPDATE ON app.files
FOR EACH ROW
EXECUTE FUNCTION app.set_updated_at();
```

字段说明：

```text
related_table 表示文件关联的对象类型。
related_id 表示文件关联的数据 ID。
```

---

## 45. 普通业务记录表

该类型不是审计表，仅用于记录业务过程。

适用：

```text
流程记录
状态变更记录
处理记录
备注记录
导入记录
同步记录
```

字段模板：

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

说明：

```text
记录型数据通常创建后不修改。
如确实需要修改，再补充 updated_at 与触发器。
```

---

## 46. 导入任务表

适合 Excel、CSV、第三方数据导入。

字段模板：

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
    )
);

CREATE INDEX idx_import_tasks_status_created_at
ON app.import_tasks (status, created_at DESC)
WHERE deleted_at IS NULL;

CREATE TRIGGER trg_import_tasks_updated_at
BEFORE UPDATE ON app.import_tasks
FOR EACH ROW
EXECUTE FUNCTION app.set_updated_at();
```

---

## 47. 临时草稿表

适合保存未提交内容。

字段模板：

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

CREATE INDEX idx_drafts_type_created_at
ON app.drafts (draft_type, created_at DESC)
WHERE deleted_at IS NULL;

CREATE TRIGGER trg_drafts_updated_at
BEFORE UPDATE ON app.drafts
FOR EACH ROW
EXECUTE FUNCTION app.set_updated_at();
```

---

# 第十部分：SQL 编写规范

## 48. 禁止 SELECT *

禁止：

```sql
SELECT * FROM app.table_name;
```

推荐：

```sql
SELECT id, name, status, created_at
FROM app.table_name
WHERE deleted_at IS NULL;
```

---

## 49. 查询未删除数据

普通查询默认添加：

```sql
WHERE deleted_at IS NULL
```

示例：

```sql
SELECT id, name, status
FROM app.table_name
WHERE deleted_at IS NULL;
```

---

## 50. 分页查询

基础分页：

```sql
SELECT id, name, status, created_at
FROM app.table_name
WHERE deleted_at IS NULL
ORDER BY created_at DESC
LIMIT 20;
```

大数据量分页推荐使用游标式分页：

```sql
SELECT id, name, status, created_at
FROM app.table_name
WHERE deleted_at IS NULL
  AND created_at < '上一页最后一条的创建时间'
ORDER BY created_at DESC
LIMIT 20;
```

---

## 51. 更新数据

更新必须带明确条件。

推荐：

```sql
UPDATE app.table_name
SET name = 'new_name'
WHERE id = '这里填uuid'
  AND deleted_at IS NULL;
```

禁止：

```sql
UPDATE app.table_name
SET name = 'new_name';
```

---

## 52. 删除数据

默认使用软删除。

推荐：

```sql
UPDATE app.table_name
SET deleted_at = now()
WHERE id = '这里填uuid'
  AND deleted_at IS NULL;
```

不推荐：

```sql
DELETE FROM app.table_name;
```

---

# 第十一部分：AI 生成 SQL 指令模板

## 53. 可直接用于数据库设计 AI 的提示词

```text
请为 PostgreSQL 生成开发库表结构 SQL。

硬性要求：
1. 只使用 app schema。
2. 所有表名和字段名使用小写英文加下划线。
3. 所有普通表必须有 id uuid PRIMARY KEY DEFAULT gen_random_uuid()。
4. 时间字段统一使用 timestamptz。
5. 金额字段统一使用 numeric(18,2)。
6. 所有普通表必须包含 created_at、updated_at、deleted_at。
7. 需要排序时使用 sort_order integer NOT NULL DEFAULT 0。
8. 需要状态时使用 status varchar(32) NOT NULL DEFAULT 'active'。
9. 有 status 字段时必须加 CHECK 约束。
10. 有软删除的唯一索引必须使用 WHERE deleted_at IS NULL。
11. 不要生成用户、角色、权限、鉴权、审计、订单、支付等无关示例表。
12. 不要使用物理外键。
13. 不要使用 SELECT *。
14. 不要生成具体业务示例，只根据输入的业务需求生成。
15. 多对多关系必须使用 xxx_yyy_mappings 表。
16. 一对多关系不要使用 mapping 表，只在子表中保存 xxx_id。
17. 不要把可以关联查询出来的名称、标题等字段重复存储，除非明确属于快照、统计、性能优化或外部系统同步。
18. 每张普通表都要给出 CREATE TABLE、必要索引、updated_at 触发器。
19. SQL 必须可以直接在 PostgreSQL 执行。
20. 生成完成后，必须说明每张表属于主数据表、明细表、mapping 表、配置表、字典表、树形表、附件表、记录表中的哪一种。
```

---

# 第十二部分：结构检查清单

## 54. SQL 生成后检查项

```text
1. 表是否全部位于 app schema 下？
2. 表名是否使用小写英文加下划线？
3. 字段名是否使用小写英文加下划线？
4. 是否存在 id uuid 主键？
5. 普通表是否包含 created_at？
6. 普通表是否包含 updated_at？
7. 普通表是否包含 deleted_at？
8. 时间字段是否使用 timestamptz？
9. 金额字段是否使用 numeric(18,2)？
10. 是否存在 SELECT *？
11. 是否生成了用户、权限、鉴权、审计、订单、支付等无关表？
12. 是否使用了物理外键？
13. 唯一索引是否兼容 deleted_at？
14. 普通表是否添加 updated_at 触发器？
15. 多对多关系是否使用 xxx_yyy_mappings？
16. 一对多关系是否错误设计成 mapping 表？
17. 是否重复存储了可关联查询字段？
18. 是否将多个值塞入单个字段？
19. SQL 是否可直接执行？
20. 表类型是否已明确？
```

---

# 第十三部分：设计判断规则

## 55. 表类型判断

```text
独立对象：建主数据表。
依附于主对象的子数据：建明细表，并添加 parent_id。
两个对象的多对多关系：建 mapping 表。
固定选项：建字典表。
可调整参数：建配置表。
上下级结构：建树形表。
文件资源：建附件表。
过程变化：建记录表。
```

---

## 56. 范式判断

```text
字段是否只存一个值？
表是否只描述一个对象或一种关系？
字段是否能从其他表关联查询得到？
```

原则：

```text
违反第一范式的结构禁止生成。
违反第二范式的结构禁止生成。
违反第三范式的结构默认禁止生成。
```

---

## 57. 允许反范式判断

仅以下情况允许重复存储字段：

```text
历史快照
高频展示
统计性能
状态快照
外部系统同步
```

若不属于以上情况，不允许重复存储可关联查询字段。

---

# 第十四部分：最终原则

```text
表放 app。
命名小写下划线。
主键用 uuid。
时间用 timestamptz。
金额用 numeric。
删除用 deleted_at。
更新用 updated_at 触发器。
默认不使用物理外键。
不生成用户权限鉴权审计示例。
不生成订单支付等无关业务表示例。
多对多才用 mapping。
一对多不用 mapping。
一个字段只存一个值。
一张表只描述一个对象或一种关系。
能关联查出来的字段默认不重复存。
只有快照、统计、性能、状态快照、外部同步才允许反范式。
```
