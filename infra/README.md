# infra

后端 API 的工程化产物（OpenAPI 规范等）。

## 文件

| 文件 | 说明 |
|---|---|
| [`openapi.yaml`](./openapi.yaml) | OpenAPI 3.0 规范，覆盖全部 Blueprint 路由（`stock_chart` / `f10` / `self_selected` / `mp4_history` / `transcription` / `scheduler` / `public` / `system`） |

## 导入到 Apifox

### 方式 1：拖入（推荐）

1. 打开 Apifox → 「项目设置」→ 「数据导入」→ 「OpenAPI / Swagger」
2. 把 `openapi.yaml` 拖进去
3. 选择「覆盖 / 合并」即可

### 方式 2：URL 导入

1. 把 `openapi.yaml` 推到 git 远端（例如 `infra/openapi.yaml`）
2. Apifox → 「项目设置」→ 「数据导入」→ 「URL 导入」
3. 填 `https://raw.githubusercontent.com/<org>/<repo>/<branch>/infra/openapi.yaml`

## 环境变量

Apifox 导入后建议在「环境管理」里配两个环境：

| 环境 | baseUrl |
|---|---|
| `local` | `http://localhost:5000` |
| `dev`  | `https://<your-dev-host>` |

`openapi.yaml` 里的 `servers` 已声明这两个。

## 维护

- 改了 `backend/api/**/*.py` 里 Blueprint 路由后，**手动**同步更新 `openapi.yaml`
- 自动化（可选）：写一个脚本扫 Blueprint 路由自动生成 spec
  - Flask 的 `app.url_map` 能拿到全部路由（用过滤器筛 blueprint 名前缀）
  - 缺点：path param / query param / request body / response schema 都是动态的，没法自动推断；纯靠 inspect 拿不到完整的 type hints
  - 推荐：仍手写，spec 当作 living doc 维护

## 不在 spec 里的内容

- SSE 流（`/api/stream/<task_id>`）只声明了 `text/event-stream`，事件 schema 没写
- 所有 `additionalProperties: true` 的 schema（上游返回的非结构化数据，比如 eastmoney 的题材 / 板块行情）保留透传；具体字段看 F10 adapter

## 验证

```bash
# 用 swagger-cli 校验
npx @apidevtools/swagger-cli validate infra/openapi.yaml

# 或用 python
pip install openapi-spec-validator
python -m openapi_spec_validator infra/openapi.yaml
```

CI 里可以加这一步防止 spec drift。
